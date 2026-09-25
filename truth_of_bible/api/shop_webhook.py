"""Receives WooCommerce's `order.updated` webhook (edenza.org) and turns an
order status transition into both a User-audience Shopping notification
(to the order's own customer) and, for the statuses that matter to an
admin, an Admin-audience Orders notification.

**Not yet connected**: this endpoint exists and works, but nothing on the
WooCommerce side is currently configured to call it. Registering the
webhook (Settings → Advanced → Webhooks in the edenza.org wp-admin, or
programmatically via `POST /wc/v3/webhooks` using the same `shopToken`
the Flutter app already has) is a deliberate, separate step — see
NOTIFICATION_ENGINE_PLAN.md's Progress log for why that's not done here
unasked.

**Verification**: this is `allow_guest=True` (WooCommerce has no Frappe
session) — the ONLY thing standing between this endpoint and anyone on
the internet POSTing fake order data is the webhook signature.
WooCommerce signs every delivery with `X-WC-Webhook-Signature`: a
base64-encoded HMAC-SHA256 of the raw request body, keyed with the
webhook's own secret (set when the webhook is created, and mirrored here
via `frappe.get_site_config()["woocommerce_webhook_secret"]`). A request
with a missing/wrong signature is rejected outright — no site_config key
means every delivery is rejected (fails closed, not open).

**Customer identity**: no Frappe-side ID mapping between a WooCommerce
customer and a Frappe User exists anywhere in this app (confirmed by a
full repo audit before writing this file) — the Flutter client itself
only ever matches "my own orders" by billing email (see
`order_history.dart`). This receiver does the same:
`frappe.db.get_value("User", {"email": billing_email}, "name")`. An order
whose billing email doesn't match any Frappe User is a real, expected
case (guest checkout, or an email that differs from the app account) —
it silently gets no user-side push, but the admin-side one (if any)
still fires.

**Payload shape**: WooCommerce's REST webhook payload for the `order`
resource is well-documented and stable (the same shape as a GET
`/wc/v3/orders/{id}` response) — `status`, `id`, `billing.email` are used
below and have not changed across WooCommerce major versions in years, so
this is written with real confidence, unlike the Discourse receiver
(`community_webhook.py`), which is explicitly flagged as needing a live
test.
"""

import base64
import hashlib
import hmac
import json

import frappe

from truth_of_bible.notifications.engine import handle_event

# WooCommerce order status -> (User-audience event, Admin-audience event).
# Either side of the tuple may be None. Statuses not listed here
# (pending, on-hold, trash, or any custom status a plugin adds) are
# silently ignored — no seeded template, no code path, nothing sent.
_STATUS_EVENTS = {
	"processing": ("ORDER_PLACED", "NEW_ORDER"),
	"completed": ("ORDER_DELIVERED", None),
	"cancelled": ("ORDER_CANCELLED", None),
	"refunded": ("REFUND_PROCESSED", None),
	"failed": ("PAYMENT_FAILED", "PAYMENT_FAILED_ADMIN"),
}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def order_updated():
	if not _verify_signature():
		frappe.throw("Invalid signature", frappe.PermissionError)

	try:
		payload = json.loads(frappe.request.data or b"{}")
	except Exception:
		frappe.throw("Invalid payload", frappe.ValidationError)

	_handle_order_updated(payload)
	return {"ok": True}


def _handle_order_updated(payload: dict) -> None:
	status = (payload.get("status") or "").lower()
	order_id = payload.get("id")
	billing_email = ((payload.get("billing") or {}) or {}).get("email", "").strip()

	user_event, admin_event = _STATUS_EVENTS.get(status, (None, None))
	variables = {"order_id": order_id, "status": status}

	if user_event and billing_email:
		user = frappe.db.get_value("User", {"email": billing_email}, "name")
		if user:
			handle_event(user_event, user, variables)
			if status == "completed":
				try:
					from truth_of_bible.rewards import engine as rewards_engine

					rewards_engine.on_order_completed(user, order_id)
				except Exception:
					frappe.log_error(title="Rewards: order points failed", message=frappe.get_traceback())

	if admin_event:
		handle_event(admin_event, None, variables)


def _verify_signature() -> bool:
	secret = frappe.get_site_config().get("woocommerce_webhook_secret")
	if not secret:
		frappe.log_error(
			title="Notification engine: woocommerce_webhook_secret missing",
			message="site_config.json has no 'woocommerce_webhook_secret' key — every WooCommerce webhook delivery is being rejected until this is set.",
		)
		return False

	signature = frappe.get_request_header("X-WC-Webhook-Signature") or ""
	body = frappe.request.data or b""
	computed = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
	return hmac.compare_digest(signature, computed)
