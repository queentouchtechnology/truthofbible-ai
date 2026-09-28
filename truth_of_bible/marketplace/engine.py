"""Student-seller marketplace on edenza.org (WCFM Marketplace on top of
WooCommerce) — a Sunday School Student can apply to sell, and once an
admin approves them, list/create/edit/delete their own products (always
starting Pending, never self-published) and see their own orders.

**Why a per-seller WooCommerce key, not the app's one shared key**: the
Flutter app already embeds one full read/write WooCommerce key
(`shopToken` in lib/src/core/constants.dart, mirrored server-side as
`site_config.json["woocommerce_api_auth"]` — see notifications/stock.py's
module docstring). Handing that same key to a student-facing screen would
let any student (or anyone who extracts the app) edit or delete ANY
product or order in the whole store, not just their own. Instead, when an
admin approves a seller application they must first create a real WCFM
vendor WordPress user + a personal WooCommerce REST API key for that
student (WP-Admin → WooCommerce → Advanced → REST API — a manual,
external step, same category as registering the order webhook below),
then paste that key/secret into `provision_seller()` below. WooCommerce
attributes anything created with that key to that WP user automatically
(no custom WordPress code needed), which is exactly how WCFM already
knows which vendor owns which product. That per-seller key is used ONLY
for the initial product-create call, so attribution is set correctly at
birth; every other call (list/update/delete/approve/reject/stock/order
sync) uses the shared admin key, which is safe because ownership is
already checked here, against `TOB Seller Product`, before any write.

**Why a local ledger, not WCFM's own vendor scoping**: WooCommerce's core
REST API has no concept of "list only products I authored" — that's a
WCFM-side restriction on its own vendor dashboard/shortcodes, not
something the REST API enforces, and the product schema doesn't even
expose `post_author`. `TOB Seller Product` is this app's own source of
truth for "which product ids belong to which seller," built the moment
this app creates a product, so ownership checks and "my products"
listing/pagination never depend on WCFM internals we can't verify from
here.

**Orders — real-time and a safety net**: `sync_order_line_items()` is
called from two places: `api/shop_webhook.py`'s `order.updated` receiver
(real-time, but only once that webhook is actually registered in
edenza.org's WP-Admin — see that file's own docstring for why it isn't
yet) and `poll_recent_orders()`, scheduled hourly, which re-scans the last
few hours of orders regardless. The dedupe_key on `TOB Seller Order Line`
makes seeing the same order from both paths harmless — this is what makes
"notified when a student's product sells" actually work today, before
anyone flips the webhook switch.
"""

import base64
from datetime import timedelta

import frappe
import requests
from frappe.utils import get_datetime, now_datetime
from frappe.utils.password import get_decrypted_password

from truth_of_bible.notifications.engine import handle_event

_BASE_URL = "https://www.edenza.org/wp-json/wc/v3"
_TIMEOUT = 30
_DEFAULT_LOW_STOCK_THRESHOLD = 5

_ALLOWED_PRODUCT_FIELDS = {
	"name", "description", "short_description", "regular_price", "sale_price",
	"sku", "manage_stock", "stock_quantity", "low_stock_amount", "images",
	"categories", "weight", "dimensions",
}

_WC_STATUS_TO_CACHE = {"pending": "Pending", "publish": "Publish", "draft": "Draft", "private": "Draft", "trash": "Trash"}


def _admin_auth() -> str | None:
	value = frappe.get_site_config().get("woocommerce_api_auth")
	if not value:
		frappe.log_error(
			title="Marketplace: woocommerce_api_auth missing",
			message=(
				"site_config.json has no 'woocommerce_api_auth' key — marketplace admin-scope calls "
				"(approve/reject, stock/order sync) are skipped until this is set to the same value as "
				"the Flutter app's own 'shopToken' constant (lib/src/core/constants.dart)."
			),
		)
		return None
	return value


def _seller_auth(account: dict) -> str:
	key = get_decrypted_password("TOB Seller Account", account.name, "consumer_key", raise_exception=False)
	secret = get_decrypted_password("TOB Seller Account", account.name, "consumer_secret", raise_exception=False)
	if not key or not secret:
		frappe.throw("This seller's store isn't fully set up yet. Contact an admin.")
	return f"Basic {base64.b64encode(f'{key}:{secret}'.encode()).decode()}"


def _wc_request(method: str, path: str, auth: str | None, **kwargs):
	if not auth:
		frappe.throw("The shop isn't reachable right now. Please try again later.")
	try:
		response = requests.request(method, f"{_BASE_URL}{path}", headers={"Authorization": auth}, timeout=_TIMEOUT, **kwargs)
	except requests.RequestException as e:
		frappe.log_error(title="Marketplace: WooCommerce request failed", message=f"{method} {path}: {type(e).__name__}: {e}")
		frappe.throw("Could not reach the shop right now. Please try again.")
	if response.status_code >= 400:
		frappe.log_error(title="Marketplace: WooCommerce request rejected", message=f"{method} {path}: HTTP {response.status_code}: {response.text[:1000]}")
		frappe.throw("The shop rejected that request. Please check the details and try again.")
	return response.json() if response.content else {}


def _sanitize_product_payload(payload) -> dict:
	if not isinstance(payload, dict):
		frappe.throw("Invalid product data.")
	clean = {k: v for k, v in payload.items() if k in _ALLOWED_PRODUCT_FIELDS}
	if "images" in clean:
		images = []
		for img in clean["images"] or []:
			if isinstance(img, dict):
				if img.get("id"):
					images.append({"id": img["id"]})
				elif img.get("src"):
					images.append({"src": img["src"]})
		clean["images"] = images
	if "categories" in clean:
		cats = []
		for c in clean["categories"] or []:
			if isinstance(c, dict) and c.get("id"):
				cats.append({"id": c["id"]})
			elif isinstance(c, int):
				cats.append({"id": c})
		clean["categories"] = cats
	return clean


# ---------------------------------------------------------------- account ---

def _account(user: str):
	return frappe.db.get_value(
		"TOB Seller Account", {"user": user},
		["name", "user", "status", "store_name"], as_dict=True,
	)


def get_seller_status(user: str) -> dict:
	account = _account(user)
	if not account:
		return {"status": "None"}
	return {"status": account.status, "store_name": account.store_name or ""}


def apply_to_sell(user: str, store_name: str | None) -> dict:
	existing = _account(user)
	if existing:
		return {"status": existing.status, "store_name": existing.store_name or ""}
	doc = frappe.get_doc({
		"doctype": "TOB Seller Account",
		"user": user,
		"status": "Pending Approval",
		"store_name": store_name or "",
		"applied_at": now_datetime(),
	}).insert(ignore_permissions=True)
	handle_event(
		"SELLER_APPLICATION_RECEIVED", None,
		{"student_name": frappe.db.get_value("User", user, "full_name") or user, "store_name": store_name or ""},
	)
	return {"status": doc.status, "store_name": doc.store_name or ""}


def require_active_seller(user: str) -> dict:
	account = _account(user)
	if not account or account.status != "Active":
		frappe.throw("You don't have an active seller account yet.")
	return account


# ---------------------------------------------------------------- products ---

def _ledger_row(user: str, product_id: int):
	name = frappe.db.get_value("TOB Seller Product", {"seller": user, "product_id": product_id}, "name")
	return frappe.get_doc("TOB Seller Product", name) if name else None


def _upsert_ledger(user: str, product_json: dict) -> None:
	product_id = product_json.get("id")
	fields = {
		"title_cache": product_json.get("name") or "",
		"sku_cache": product_json.get("sku") or "",
		"status_cache": _WC_STATUS_TO_CACHE.get(product_json.get("status"), "Pending"),
		"price_cache": product_json.get("price") or product_json.get("regular_price") or "",
		"stock_cache": product_json.get("stock_quantity") if product_json.get("stock_quantity") is not None else 0,
	}
	row = _ledger_row(user, product_id)
	if row:
		row.update(fields)
		row.save(ignore_permissions=True)
	else:
		frappe.get_doc({
			"doctype": "TOB Seller Product", "seller": user, "product_id": product_id,
			"created_at": now_datetime(), **fields,
		}).insert(ignore_permissions=True)


def create_product(user: str, payload: dict) -> dict:
	account = require_active_seller(user)
	clean = _sanitize_product_payload(payload)
	if not clean.get("name") or not clean.get("regular_price"):
		frappe.throw("Product name and price are required.")
	clean["status"] = "pending"
	response = _wc_request("POST", "/products", auth=_seller_auth(account), json=clean)
	_upsert_ledger(user, response)
	handle_event(
		"SELLER_PRODUCT_SUBMITTED", None,
		{"student_name": frappe.db.get_value("User", user, "full_name") or user, "product_name": clean.get("name")},
	)
	return response


def update_product(user: str, product_id: int, payload: dict) -> dict:
	require_active_seller(user)
	row = _ledger_row(user, product_id)
	if not row:
		frappe.throw("You don't own this product.")
	clean = _sanitize_product_payload(payload)
	clean.pop("status", None)
	response = _wc_request("PUT", f"/products/{product_id}", auth=_admin_auth(), json=clean)
	_upsert_ledger(user, response)
	return response


def delete_product(user: str, product_id: int) -> dict:
	require_active_seller(user)
	row = _ledger_row(user, product_id)
	if not row:
		frappe.throw("You don't own this product.")
	_wc_request("DELETE", f"/products/{product_id}", auth=_admin_auth())
	row.status_cache = "Trash"
	row.save(ignore_permissions=True)
	return {"ok": True}


def list_products(user: str, page: int = 1, per_page: int = 20, search: str | None = None, status: str | None = None) -> dict:
	filters = {"seller": user}
	if status:
		filters["status_cache"] = status
	if search:
		filters["title_cache"] = ["like", f"%{search}%"]
	total = frappe.db.count("TOB Seller Product", filters)
	rows = frappe.get_all(
		"TOB Seller Product", filters=filters,
		fields=["name", "product_id", "title_cache", "sku_cache", "status_cache", "price_cache", "stock_cache", "review_note", "created_at"],
		order_by="created_at desc",
		limit_start=(int(page) - 1) * int(per_page), limit_page_length=int(per_page),
	)
	return {"rows": rows, "total": total, "page": int(page), "per_page": int(per_page)}


def list_orders(user: str, page: int = 1, per_page: int = 20) -> dict:
	filters = {"seller": user}
	total = frappe.db.count("TOB Seller Order Line", filters)
	rows = frappe.get_all(
		"TOB Seller Order Line", filters=filters,
		fields=["order_id", "order_number", "product_id", "product_title", "quantity", "line_total", "order_status", "order_date"],
		order_by="order_date desc",
		limit_start=(int(page) - 1) * int(per_page), limit_page_length=int(per_page),
	)
	return {"rows": rows, "total": total, "page": int(page), "per_page": int(per_page)}


def get_low_stock_products(user: str) -> list:
	return frappe.get_all(
		"TOB Seller Product", filters={"seller": user, "status_cache": "Publish", "low_stock_notified_at": ["is", "set"]},
		fields=["product_id", "title_cache", "stock_cache"],
	)


# --------------------------------------------------------------- orders ----

def sync_order_line_items(order: dict) -> None:
	order_id = order.get("id")
	if not order_id:
		return
	order_number = str(order.get("number") or order_id)
	status = order.get("status") or ""
	date_created = order.get("date_created")
	order_date = get_datetime(date_created) if date_created else now_datetime()

	for line in order.get("line_items") or []:
		product_id = line.get("product_id")
		if not product_id:
			continue
		seller = frappe.db.get_value("TOB Seller Product", {"product_id": product_id}, "seller")
		if not seller:
			continue

		dedupe_key = f"{order_id}:{product_id}"
		product_title = line.get("name") or ""
		quantity = line.get("quantity") or 1
		line_total = float(line.get("total") or 0)

		existing = frappe.db.get_value("TOB Seller Order Line", {"dedupe_key": dedupe_key}, "name")
		if existing:
			frappe.db.set_value("TOB Seller Order Line", existing, {"order_status": status, "quantity": quantity, "line_total": line_total})
			continue

		frappe.get_doc({
			"doctype": "TOB Seller Order Line",
			"seller": seller, "order_id": order_id, "order_number": order_number,
			"product_id": product_id, "product_title": product_title,
			"quantity": quantity, "line_total": line_total, "order_status": status,
			"order_date": order_date, "dedupe_key": dedupe_key,
		}).insert(ignore_permissions=True)

		handle_event("SELLER_NEW_ORDER", seller, {"product_title": product_title, "quantity": quantity, "order_number": order_number})


def poll_recent_orders() -> None:
	"""Hourly (see hooks.py) — the safety net that makes seller order
	notifications work even before the WooCommerce order webhook is
	registered on edenza.org (see api/shop_webhook.py)."""
	try:
		_poll_recent_orders()
	except Exception:
		frappe.log_error(title="Marketplace: poll_recent_orders failed", message=frappe.get_traceback())


def _poll_recent_orders() -> None:
	if not frappe.db.exists("TOB Seller Product", {}):
		return
	auth = _admin_auth()
	if not auth:
		return
	after = (now_datetime() - timedelta(hours=3)).isoformat()
	page = 1
	while page <= 5:
		try:
			response = requests.get(
				f"{_BASE_URL}/orders", headers={"Authorization": auth},
				params={"after": after, "per_page": 100, "page": page, "status": "any"}, timeout=_TIMEOUT,
			)
		except requests.RequestException as e:
			frappe.log_error(title="Marketplace: order poll failed", message=f"page={page}: {type(e).__name__}: {e}")
			return
		if response.status_code != 200:
			frappe.log_error(title="Marketplace: order poll rejected", message=f"page={page}: HTTP {response.status_code}: {response.text[:1000]}")
			return
		batch = response.json() or []
		if not isinstance(batch, list) or not batch:
			break
		for order in batch:
			sync_order_line_items(order)
		if len(batch) < 100:
			break
		page += 1


# ------------------------------------------------------------ low stock ----

def check_low_stock() -> None:
	"""Daily (see hooks.py) — per-seller low-stock notification, distinct
	from notifications/stock.py's global admin summary (that one doesn't
	know which product belongs to which student)."""
	try:
		_check_low_stock()
	except Exception:
		frappe.log_error(title="Marketplace: check_low_stock failed", message=frappe.get_traceback())


def _check_low_stock() -> None:
	auth = _admin_auth()
	if not auth:
		return
	rows = frappe.get_all(
		"TOB Seller Product", filters={"status_cache": "Publish"},
		fields=["name", "seller", "product_id", "title_cache", "low_stock_notified_at"],
	)
	if not rows:
		return
	by_id = {r.product_id: r for r in rows}
	ids = list(by_id.keys())
	for i in range(0, len(ids), 100):
		chunk = ids[i:i + 100]
		try:
			response = requests.get(
				f"{_BASE_URL}/products", headers={"Authorization": auth},
				params={"include": ",".join(str(x) for x in chunk), "per_page": 100}, timeout=_TIMEOUT,
			)
		except requests.RequestException as e:
			frappe.log_error(title="Marketplace: low-stock fetch failed", message=f"{type(e).__name__}: {e}")
			continue
		if response.status_code != 200:
			frappe.log_error(title="Marketplace: low-stock fetch rejected", message=f"HTTP {response.status_code}: {response.text[:1000]}")
			continue
		for product in response.json() or []:
			ledger = by_id.get(product.get("id"))
			if not ledger:
				continue
			qty = product.get("stock_quantity")
			frappe.db.set_value("TOB Seller Product", ledger.name, "stock_cache", qty if qty is not None else 0)
			if not product.get("manage_stock") or qty is None:
				continue
			threshold = product.get("low_stock_amount") or _DEFAULT_LOW_STOCK_THRESHOLD
			if 0 < qty <= threshold:
				if not ledger.low_stock_notified_at:
					handle_event("SELLER_LOW_STOCK", ledger.seller, {"product_title": ledger.title_cache, "stock_quantity": qty})
					frappe.db.set_value("TOB Seller Product", ledger.name, "low_stock_notified_at", now_datetime())
			elif ledger.low_stock_notified_at:
				frappe.db.set_value("TOB Seller Product", ledger.name, "low_stock_notified_at", None)


# ---------------------------------------------------------------- admin ----

def list_seller_applications(status: str | None = None) -> list:
	filters = {"status": status} if status else {}
	rows = frappe.get_all(
		"TOB Seller Account", filters=filters,
		fields=["name", "user", "status", "store_name", "applied_at", "approved_at", "admin_note"],
		order_by="applied_at desc",
	)
	if not rows:
		return rows
	brief = {
		u.name: u for u in frappe.get_all("User", filters={"name": ["in", [r.user for r in rows]]}, fields=["name", "full_name", "user_image"])
	}
	for r in rows:
		u = brief.get(r.user)
		r["full_name"] = u.full_name if u else r.user
		r["user_image"] = u.user_image if u else None
	return rows


def provision_seller(user: str, store_name: str | None, consumer_key: str, consumer_secret: str, admin_note: str | None = None) -> dict:
	if not consumer_key or not consumer_secret:
		frappe.throw("Consumer key and secret are required.")
	existing = frappe.db.get_value("TOB Seller Account", {"user": user}, "name")
	doc = frappe.get_doc("TOB Seller Account", existing) if existing else frappe.new_doc("TOB Seller Account")
	doc.user = user
	if store_name:
		doc.store_name = store_name
	doc.consumer_key = consumer_key
	doc.consumer_secret = consumer_secret
	doc.status = "Active"
	doc.approved_at = now_datetime()
	if admin_note:
		doc.admin_note = admin_note
	if not doc.get("applied_at"):
		doc.applied_at = now_datetime()
	doc.save(ignore_permissions=True)
	handle_event("SELLER_ACCOUNT_APPROVED", user, {"store_name": doc.store_name or ""})
	return {"status": doc.status}


def suspend_seller(user: str, note: str | None = None) -> dict:
	existing = frappe.db.get_value("TOB Seller Account", {"user": user}, "name")
	if not existing:
		frappe.throw("No seller account for this user.")
	doc = frappe.get_doc("TOB Seller Account", existing)
	doc.status = "Suspended"
	if note:
		doc.admin_note = note
	doc.save(ignore_permissions=True)
	return {"status": doc.status}


def reactivate_seller(user: str) -> dict:
	existing = frappe.db.get_value("TOB Seller Account", {"user": user}, "name")
	if not existing:
		frappe.throw("No seller account for this user.")
	doc = frappe.get_doc("TOB Seller Account", existing)
	doc.status = "Active"
	doc.save(ignore_permissions=True)
	return {"status": doc.status}


def list_pending_products() -> list:
	rows = frappe.get_all(
		"TOB Seller Product", filters={"status_cache": "Pending"},
		fields=["name", "seller", "product_id", "title_cache", "sku_cache", "price_cache", "created_at"],
		order_by="created_at asc",
	)
	if not rows:
		return rows
	brief = {
		u.name: u for u in frappe.get_all("User", filters={"name": ["in", [r.seller for r in rows]]}, fields=["name", "full_name", "user_image"])
	}
	for r in rows:
		u = brief.get(r.seller)
		r["seller_name"] = u.full_name if u else r.seller
		r["seller_image"] = u.user_image if u else None
	return rows


def approve_product(ledger_name: str, note: str | None = None) -> dict:
	row = frappe.get_doc("TOB Seller Product", ledger_name)
	_wc_request("PUT", f"/products/{row.product_id}", auth=_admin_auth(), json={"status": "publish"})
	row.status_cache = "Publish"
	if note:
		row.review_note = note
	row.save(ignore_permissions=True)
	handle_event("SELLER_PRODUCT_APPROVED", row.seller, {"product_title": row.title_cache})
	return {"status": row.status_cache}


def reject_product(ledger_name: str, note: str | None = None) -> dict:
	row = frappe.get_doc("TOB Seller Product", ledger_name)
	_wc_request("PUT", f"/products/{row.product_id}", auth=_admin_auth(), json={"status": "draft"})
	row.status_cache = "Rejected"
	if note:
		row.review_note = note
	row.save(ignore_permissions=True)
	handle_event("SELLER_PRODUCT_REJECTED", row.seller, {"product_title": row.title_cache, "note": note or ""})
	return {"status": row.status_cache}
