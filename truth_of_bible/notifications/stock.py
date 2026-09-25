"""LOW_STOCK / OUT_OF_STOCK — NOTIFICATION_ENGINE_PLAN.md "What's still
open" item 3 ("WooCommerce doesn't push stock changes via order webhooks;
needs a new scheduled poll against /wc/v3/products, a different mechanism
than everything built so far").

**Needs one new site_config.json key before this does anything**:
`woocommerce_api_auth` — the same WooCommerce REST Basic-Auth header value
the Flutter app already embeds as `shopToken` in `lib/src/core/constants.dart`
(a `Basic <base64 of ck_...:cs_...>` string). That credential already exists
and already works (the whole Shop module runs on it client-side) — this
just needs the SAME value added server-side too, under this new key,
copy-pasted from the Flutter source rather than generating a fresh
WooCommerce API key. Never hardcoded here, matching every other credential
in this app.

Reports as ONE summary admin notification per run (not one push per
product) — a store with 12 out-of-stock items should not page an admin 12
times in a row; the summary names a few and gives a total count.
"""

import frappe
import requests

from truth_of_bible.notifications.engine import handle_event

_BASE_URL = "https://www.edenza.org/wp-json/wc/v3"
_TIMEOUT = 30
_PER_PAGE = 100
_MAX_PAGES = 10  # hard ceiling — this is a periodic health poll, not a full catalogue export
_NAMES_IN_SUMMARY = 5

# A product with `manage_stock` on and no per-product `low_stock_amount`
# falls back to this — WooCommerce itself has no single global default
# exposed over the REST API, so this is a deliberate, documented choice,
# not a discovered value.
_DEFAULT_LOW_STOCK_THRESHOLD = 5


def _auth_header():
	value = frappe.get_site_config().get("woocommerce_api_auth")
	if not value:
		frappe.log_error(
			title="Notification engine: woocommerce_api_auth missing",
			message=(
				"site_config.json has no 'woocommerce_api_auth' key — the stock poll is skipped "
				"until this is set to the same value as the Flutter app's own 'shopToken' constant "
				"(lib/src/core/constants.dart)."
			),
		)
		return None
	return value


def _fetch_products(stock_status: str) -> list[dict]:
	auth = _auth_header()
	if not auth:
		return []
	products, page = [], 1
	while page <= _MAX_PAGES:
		try:
			response = requests.get(
				f"{_BASE_URL}/products",
				headers={"Authorization": auth},
				params={"stock_status": stock_status, "per_page": _PER_PAGE, "page": page, "status": "publish"},
				timeout=_TIMEOUT,
			)
		except requests.RequestException as e:
			frappe.log_error(
				title="Notification engine: WooCommerce stock poll failed",
				message=f"stock_status={stock_status} page={page}: {type(e).__name__}: {e}",
			)
			return products
		if response.status_code != 200:
			frappe.log_error(
				title="Notification engine: WooCommerce stock poll rejected",
				message=f"stock_status={stock_status} page={page}: HTTP {response.status_code}: {response.text[:1000]}",
			)
			return products
		batch = response.json() or []
		if not isinstance(batch, list) or not batch:
			break
		products.extend(batch)
		if len(batch) < _PER_PAGE:
			break
		page += 1
	return products


def _is_low_stock(product: dict) -> bool:
	if not product.get("manage_stock"):
		return False
	qty = product.get("stock_quantity")
	if qty is None:
		return False
	threshold = product.get("low_stock_amount") or _DEFAULT_LOW_STOCK_THRESHOLD
	return 0 < qty <= threshold


def _summary(products: list[dict]) -> str:
	names = [p.get("name") or p.get("sku") or p.get("id") for p in products[:_NAMES_IN_SUMMARY]]
	text = ", ".join(str(n) for n in names)
	extra = len(products) - len(names)
	if extra > 0:
		text += f" and {extra} more"
	return text


def daily_check() -> None:
	"""Scheduled daily (see hooks.py) — stock levels don't need finer
	granularity than the order-webhook events, which already cover the
	minute-to-minute picture; this is the slow-moving "check the shelf"
	signal."""
	try:
		_run()
	except Exception:
		frappe.log_error(title="Notification engine: stock check failed", message=frappe.get_traceback())


def _run() -> None:
	out_of_stock = _fetch_products("outofstock")
	if out_of_stock:
		handle_event(
			"OUT_OF_STOCK",
			None,
			{"count": len(out_of_stock), "products": _summary(out_of_stock)},
		)

	in_stock = _fetch_products("instock")
	low = [p for p in in_stock if _is_low_stock(p)]
	if low:
		handle_event(
			"LOW_STOCK",
			None,
			{"count": len(low), "products": _summary(low)},
		)
