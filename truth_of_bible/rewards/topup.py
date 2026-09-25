"""Razorpay top-ups for the rewards wallet.

Server-authoritative, unlike the older client-driven wallet flow: the server
creates the Razorpay order (so the amount can't be tampered with on the
phone), and the wallet is credited only after the payment is proven —
either the app's signed callback (`verify_topup`) or Razorpay's own webhook
(`handle_webhook`, which covers "paid, then the app was killed"). Both credit
through the same idempotency key (`topup:<payment_id>`), so whichever arrives
first wins and the other is a harmless no-op.

Needs in site_config.json (never sent to the client except the public key id):
  razorpay_key_id, razorpay_key_secret      — API keys (a dedicated pair is fine)
  razorpay_webhook_secret                   — optional; enables the webhook
Currency is the wallet's base currency (`rewards_wallet_currency`, INR by
default). Charging in other currencies needs international payments enabled
on the Razorpay account.

Credits are 1:1 (no bonus) and non-refundable in-app; refunds are handled in
the Razorpay dashboard and reversed with an ADJUST row.
"""

import hashlib
import hmac
import json

import frappe
import requests

from truth_of_bible.rewards import engine

_API = "https://api.razorpay.com/v1"
_TIMEOUT = 20
MIN_AMOUNT = 10
MAX_AMOUNT = 10000
PRESETS = (50, 100, 250, 500)


def _keys():
	conf = frappe.get_site_config()
	return conf.get("razorpay_key_id"), conf.get("razorpay_key_secret")


def options() -> dict:
	key_id, secret = _keys()
	return {"enabled": bool(key_id and secret), "min": MIN_AMOUNT, "max": MAX_AMOUNT, "presets": list(PRESETS)}


def _call(method: str, path: str, **kwargs):
	key_id, secret = _keys()
	try:
		response = requests.request(method, f"{_API}{path}", auth=(key_id, secret), timeout=_TIMEOUT, **kwargs)
	except requests.RequestException:
		frappe.log_error(title="Rewards top-up: Razorpay unreachable", message=frappe.get_traceback())
		frappe.throw(frappe._("Couldn't reach the payment service. Please try again."), frappe.ValidationError)
	if response.status_code not in (200, 201):
		frappe.log_error(
			title="Rewards top-up: Razorpay rejected the request",
			message=f"{method} {path} -> HTTP {response.status_code}: {response.text[:1500]}",
		)
		frappe.throw(frappe._("The payment service couldn't process that. Please try again."), frappe.ValidationError)
	return response.json()


def create_topup(user: str, amount) -> dict:
	if not options()["enabled"]:
		frappe.throw(frappe._("Adding money isn't available yet."), frappe.ValidationError)
	try:
		amount = int(float(amount))
	except (TypeError, ValueError):
		frappe.throw(frappe._("Enter a valid amount."), frappe.ValidationError)
	if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
		frappe.throw(
			frappe._("Enter an amount between {0} and {1}.").format(MIN_AMOUNT, MAX_AMOUNT), frappe.ValidationError
		)
	currency = engine._wallet_config()["currency"]
	order = _call(
		"POST",
		"/orders",
		json={
			"amount": amount * 100,
			"currency": currency,
			"receipt": f"tobw-{frappe.generate_hash(length=10)}",
			"notes": {"purpose": "rewards_wallet", "user": user},
		},
	)
	return {"order_id": order["id"], "amount": amount, "currency": currency, "key_id": _keys()[0]}


def _credit(user: str, amount: float, payment_id: str) -> bool:
	"""Credits the wallet once per payment. True if newly credited."""
	key = f"topup:{payment_id}"
	if frappe.db.exists("TOB Reward Wallet Ledger", {"user": user, "dedupe_key": key}):
		return False
	frappe.get_doc(
		{
			"doctype": "TOB Reward Wallet Ledger",
			"user": user,
			"kind": "TOPUP",
			"title": f"Added money ({payment_id})",
			"amount": amount,
			"dedupe_key": key,
		}
	).insert(ignore_permissions=True)
	return True


def _settle(order_id: str, payment_id: str, expected_user: str | None) -> dict:
	"""Confirms with Razorpay itself (never trusting the client) that the
	payment is captured and belongs to this rewards-wallet order, then
	credits the wallet."""
	order = _call("GET", f"/orders/{order_id}")
	notes = order.get("notes") or {}
	if notes.get("purpose") != "rewards_wallet" or not notes.get("user"):
		frappe.throw(frappe._("That payment isn't a wallet top-up."), frappe.ValidationError)
	user = notes["user"]
	if expected_user and user != expected_user:
		frappe.throw(frappe._("That payment belongs to a different account."), frappe.PermissionError)

	payment = _call("GET", f"/payments/{payment_id}")
	if payment.get("order_id") != order_id:
		frappe.throw(frappe._("That payment doesn't match the order."), frappe.ValidationError)
	if payment.get("status") == "authorized":
		payment = _call("POST", f"/payments/{payment_id}/capture", json={"amount": payment["amount"], "currency": payment["currency"]})
	if payment.get("status") != "captured":
		frappe.throw(frappe._("The payment hasn't completed yet."), frappe.ValidationError)

	amount = round(int(payment["amount"]) / 100, 2)
	credited = _credit(user, amount, payment_id)
	return {"user": user, "amount": amount, "currency": payment.get("currency"), "credited": credited}


def verify_topup(user: str, order_id: str, payment_id: str, signature: str) -> dict:
	key_secret = _keys()[1]
	if not key_secret:
		frappe.throw(frappe._("Adding money isn't available yet."), frappe.ValidationError)
	expected = hmac.new(key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
	if not hmac.compare_digest(expected, signature or ""):
		frappe.log_error(title="Rewards top-up: bad signature", message=f"user={user} order={order_id} payment={payment_id}")
		frappe.throw(frappe._("We couldn't verify that payment."), frappe.ValidationError)
	return _settle(order_id, payment_id, expected_user=user)


def handle_webhook(raw_body: bytes, signature: str) -> dict:
	secret = frappe.get_site_config().get("razorpay_webhook_secret")
	if not secret:
		frappe.throw(frappe._("Webhook not configured."), frappe.PermissionError)
	expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
	if not hmac.compare_digest(expected, signature or ""):
		frappe.throw(frappe._("Invalid signature."), frappe.PermissionError)

	event = json.loads(raw_body or b"{}")
	if event.get("event") not in ("payment.captured", "order.paid"):
		return {"ignored": True}
	payload = event.get("payload") or {}
	payment = (payload.get("payment") or {}).get("entity") or {}
	order_id, payment_id = payment.get("order_id"), payment.get("id")
	if not (order_id and payment_id):
		return {"ignored": True}
	notes = payment.get("notes") or {}
	if notes.get("purpose") != "rewards_wallet":
		return {"ignored": True}  # a payment for something else on this account
	return _settle(order_id, payment_id, expected_user=None)
