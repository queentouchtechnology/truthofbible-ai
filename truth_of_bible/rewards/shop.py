"""Pays an Edenza shop order from the rewards wallet.

The app creates the WooCommerce order (with any rewards coupon applied),
then calls `pay_order`. The amount is never taken from the phone: it's
read back from WooCommerce — the order total minus shipping (shipping
isn't charged to the wallet, same as the checkout screen shows) — and the
order must belong to the signed-in member. One wallet debit per order
(`shop:<order_id>`), so a retry or double tap can't charge twice. If the
wallet can't cover it the order is cancelled in the shop, so nothing ships
unpaid.
"""

import frappe
import requests
from frappe.utils import cint, flt

from truth_of_bible.rewards import engine

_CLOSED = ("cancelled", "refunded", "failed", "trash")


def _wc(method: str, path: str, **kwargs) -> dict:
	auth = engine._wc_auth()
	if not auth:
		frappe.throw(frappe._("The shop isn't available right now. Please try again later."), frappe.ValidationError)
	try:
		response = requests.request(
			method, f"{engine._WC_BASE}{path}", headers={"Authorization": auth}, timeout=engine._TIMEOUT, **kwargs
		)
	except requests.RequestException:
		frappe.log_error(title="Rewards shop: WooCommerce unreachable", message=frappe.get_traceback())
		frappe.throw(frappe._("Couldn't reach the shop. Please try again."), frappe.ValidationError)
	if response.status_code not in (200, 201):
		frappe.log_error(
			title="Rewards shop: WooCommerce rejected the request",
			message=f"{method} {path} -> HTTP {response.status_code}: {response.text[:1500]}",
		)
		frappe.throw(frappe._("The shop couldn't process that. Please try again."), frappe.ValidationError)
	return response.json() or {}


def _cancel(order_id: int) -> None:
	try:
		_wc("PUT", f"/orders/{order_id}", json={"status": "cancelled"})
	except Exception:
		frappe.log_error(title="Rewards shop: couldn't cancel unpaid order", message=f"order {order_id}")


def pay_order(user: str, order_id) -> dict:
	order_id = cint(order_id)
	if not order_id:
		frappe.throw(frappe._("Invalid order."), frappe.ValidationError)
	order = _wc("GET", f"/orders/{order_id}")
	email = ((order.get("billing") or {}).get("email") or "").strip().lower()
	if email != user.lower():
		frappe.throw(frappe._("That order belongs to a different account."), frappe.PermissionError)

	amount = round(
		max(0.0, flt(order.get("total")) - flt(order.get("shipping_total")) - flt(order.get("shipping_tax"))), 2
	)
	key = f"shop:{order_id}"
	engine._lock_user(user)
	if engine._ledger_has("TOB Reward Wallet Ledger", user, key):
		return {"paid": True, "amount": amount, "balance": engine.wallet_balance(user)}
	if order.get("status") in _CLOSED:
		frappe.throw(frappe._("That order is no longer open."), frappe.ValidationError)
	if engine.wallet_balance(user) < amount:
		_cancel(order_id)
		frappe.throw(
			frappe._("Not enough wallet balance — the order was cancelled. Add money and try again."),
			frappe.ValidationError,
		)
	engine._insert_once(
		{
			"doctype": "TOB Reward Wallet Ledger",
			"user": user,
			"kind": "SHOP",
			"title": f"Edenza order #{order_id}",
			"amount": -amount,
			"dedupe_key": key,
		}
	)
	return {"paid": True, "amount": amount, "balance": engine.wallet_balance(user)}
