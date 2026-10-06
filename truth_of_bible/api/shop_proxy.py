"""WooCommerce (edenza.org) calls for the mobile app, made server-side.

The app used to call the WooCommerce REST API directly with the store's
consumer key/secret baked into the build — enough to read and change every
order, customer and product. The key now lives only in site_config.json —
the existing `woocommerce_api_auth` (the full `Basic ...` header, also used
by marketplace/engine.py and notifications/stock.py) — and the app talks to
these methods instead: the catalog is public, orders
are always the signed-in member's own, and the admin pass-through is
role-checked.
"""

import requests

import frappe
from frappe import _

# Roles allowed to use the Shopping admin screens' pass-through.
SHOP_ADMIN_ROLES = {"System Manager", "Sales Manager"}

_CATALOG_PARAMS = {
	"page", "per_page", "search", "category", "orderby", "order", "status", "featured", "on_sale",
	"min_price", "max_price", "stock_status", "include", "exclude", "tag", "slug", "parent", "hide_empty",
	"type", "sku",
}
_ORDER_LIST_PARAMS = {"page", "per_page", "status", "orderby", "order"}
_ADDRESS_FIELDS = (
	"first_name", "last_name", "company", "address_1", "address_2", "city", "state", "postcode",
	"country", "email", "phone",
)


_STORE_URL = "https://www.edenza.org/wp-json"  # same store as marketplace/engine.py


def _auth() -> str:
	value = frappe.get_site_config().get("woocommerce_api_auth")
	if not value:
		frappe.log_error(title="Shop proxy: woocommerce_api_auth missing",
			message="site_config.json has no 'woocommerce_api_auth' — the app's shop can't load.")
		frappe.throw(_("The shop is not available right now"))
	return value


def _wc(method: str, path: str, params: dict | None = None, data=None):
	auth = _auth()
	if not path.startswith("/wc/v3/") or ".." in path:
		frappe.throw(_("Invalid shop request"))
	try:
		r = requests.request(
			method,
			_STORE_URL + path,
			params=params or None,
			json=data,
			headers={"Authorization": auth},
			timeout=30,
		)
	except requests.RequestException:
		frappe.log_error(title="Shop proxy: WooCommerce unreachable", message=frappe.get_traceback())
		frappe.throw(_("The shop is not available right now"))
	try:
		body = r.json()
	except ValueError:
		body = None
	if r.status_code >= 400:
		message = body.get("message") if isinstance(body, dict) else None
		frappe.throw(message or _("Shop request failed ({0})").format(r.status_code))
	return body


def _pick(params, allowed) -> dict:
	params = frappe.parse_json(params) if isinstance(params, str) else (params or {})
	return {k: v for k, v in params.items() if k in allowed and v not in (None, "")}


def _signed_in() -> str:
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please sign in"), frappe.PermissionError)
	return user


# ------------------------------------------------------------------ catalog


@frappe.whitelist(allow_guest=True)
def products(params=None):
	return _wc("GET", "/wc/v3/products", _pick(params, _CATALOG_PARAMS))


@frappe.whitelist(allow_guest=True)
def product(product_id):
	return _wc("GET", f"/wc/v3/products/{int(product_id)}")


@frappe.whitelist(allow_guest=True)
def categories(params=None):
	return _wc("GET", "/wc/v3/products/categories", _pick(params, _CATALOG_PARAMS))


# ------------------------------------------------------------------- orders


def _address(src) -> dict:
	src = src or {}
	return {k: str(src.get(k) or "")[:200] for k in _ADDRESS_FIELDS if k in src}


@frappe.whitelist(methods=["POST"])
def create_order(order):
	"""Cash-on-delivery order for the signed-in member. Payment state,
	status and the billing email are set here, never taken from the app."""
	user = _signed_in()
	order = frappe.parse_json(order) if isinstance(order, str) else (order or {})
	line_items = [
		{"product_id": int(i["product_id"]), "quantity": max(1, int(i.get("quantity") or 1)),
		 **({"variation_id": int(i["variation_id"])} if i.get("variation_id") else {})}
		for i in (order.get("line_items") or [])
		if i.get("product_id")
	]
	if not line_items:
		frappe.throw(_("Your cart is empty"))
	billing = _address(order.get("billing"))
	billing["email"] = user
	payload = {
		"payment_method": "cod",
		"payment_method_title": "Cash on Delivery",
		"set_paid": False,
		"status": "processing",
		"billing": billing,
		"shipping": _address(order.get("shipping")),
		"line_items": line_items,
		"shipping_lines": [
			{"method_id": str(s.get("method_id") or "")[:100], "method_title": str(s.get("method_title") or "")[:200],
			 "total": str(s.get("total") or "0")}
			for s in (order.get("shipping_lines") or [])
		],
	}
	coupons = [str(c.get("code") or "")[:100] for c in (order.get("coupon_lines") or []) if c.get("code")]
	if coupons:
		payload["coupon_lines"] = [{"code": c} for c in coupons]
	return _wc("POST", "/wc/v3/orders", data=payload)


@frappe.whitelist()
def my_orders(params=None):
	"""Only the signed-in member's orders (matched by billing email)."""
	user = _signed_in()
	query = _pick(params, _ORDER_LIST_PARAMS)
	query["search"] = user
	orders = _wc("GET", "/wc/v3/orders", query) or []
	return [o for o in orders if ((o.get("billing") or {}).get("email") or "").lower() == user.lower()]


# -------------------------------------------------------------------- admin


@frappe.whitelist()
def admin_request(path: str, method: str = "GET", params=None, data=None):
	"""Shopping admin screens: any /wc/v3 call, for shop admins only."""
	if not (set(frappe.get_roles()) & SHOP_ADMIN_ROLES):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	method = (method or "GET").upper()
	if method not in ("GET", "POST", "PUT", "DELETE"):
		frappe.throw(_("Invalid shop request"))
	params = frappe.parse_json(params) if isinstance(params, str) else params
	data = frappe.parse_json(data) if isinstance(data, str) else data
	return _wc(method, path, params, data)
