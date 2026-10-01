"""Spending the rewards wallet on things other than the shop: donations to
Truth of Bible and sending money to another member.

Both replace the old app flows that wrote ERPNext Journal Entries against
the old `User Wallet - TOB` account straight from the phone (with the admin
token). Everything here runs on the server, under the per-member lock, and
is idempotent per client `request_id` — a double tap or a retry can't
donate or send twice.

A Razorpay donation is a normal verified top-up (rewards/topup.py) followed
by `donate` from the wallet, so card payments keep going through the one
server-verified Razorpay path.
"""

import frappe
from frappe.utils import flt

from truth_of_bible.rewards import engine

_MAX_AMOUNT = 100000


def _amount(value) -> float:
	amount = round(flt(value), 2)
	if amount <= 0 or amount > _MAX_AMOUNT:
		frappe.throw(frappe._("Enter a valid amount."), frappe.ValidationError)
	return amount


def _request_key(request_id) -> str:
	request_id = (request_id or "").strip()
	if not request_id or len(request_id) > 64:
		frappe.throw(frappe._("Missing request id."), frappe.ValidationError)
	return request_id


def donate(user: str, amount, request_id) -> dict:
	amount = _amount(amount)
	key = f"donate:{_request_key(request_id)}"
	engine._lock_user(user)
	if engine._ledger_has("TOB Reward Wallet Ledger", user, key):
		return {"donated": True, "amount": amount, "balance": engine.wallet_balance(user)}
	if engine.wallet_balance(user) < amount:
		frappe.throw(frappe._("Not enough wallet balance for this donation."), frappe.ValidationError)
	engine._insert_once(
		{
			"doctype": "TOB Reward Wallet Ledger",
			"user": user,
			"kind": "DONATE",
			"title": "Donation to Truth of Bible",
			"amount": -amount,
			"dedupe_key": key,
		}
	)
	return {"donated": True, "amount": amount, "balance": engine.wallet_balance(user)}


def send(user: str, to_user, amount, request_id) -> dict:
	amount = _amount(amount)
	to_user = (to_user or "").strip().lower()
	if not to_user or not frappe.db.exists("User", {"name": to_user, "enabled": 1}):
		frappe.throw(frappe._("That member wasn't found."), frappe.ValidationError)
	to_user = frappe.db.get_value("User", {"name": to_user}, "name")
	if to_user == user:
		frappe.throw(frappe._("You can't send money to yourself."), frappe.ValidationError)
	request = _request_key(request_id)
	out_key, in_key = f"send:{request}", f"receive:{request}"

	# Lock both members in a fixed order so two opposite transfers can't deadlock.
	for u in sorted((user, to_user)):
		engine._lock_user(u)
	if engine._ledger_has("TOB Reward Wallet Ledger", user, out_key):
		return {"sent": True, "amount": amount, "balance": engine.wallet_balance(user)}
	if engine.wallet_balance(user) < amount:
		frappe.throw(frappe._("Not enough wallet balance."), frappe.ValidationError)
	sender_name = frappe.utils.get_fullname(user) or user
	receiver_name = frappe.utils.get_fullname(to_user) or to_user
	engine._insert_once(
		{
			"doctype": "TOB Reward Wallet Ledger",
			"user": user,
			"kind": "TRANSFER",
			"title": f"Sent to {receiver_name}",
			"amount": -amount,
			"dedupe_key": out_key,
		}
	)
	engine._insert_once(
		{
			"doctype": "TOB Reward Wallet Ledger",
			"user": to_user,
			"kind": "TRANSFER",
			"title": f"Received from {sender_name}",
			"amount": amount,
			"dedupe_key": in_key,
		}
	)
	return {"sent": True, "amount": amount, "balance": engine.wallet_balance(user)}
