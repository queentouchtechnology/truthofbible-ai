"""Read-only history for the Rewards screens: points, wallet (new ledger
merged with the member's older ERPNext wallet entries, so nothing they had
before disappears) and the friends they've invited."""

import frappe
from frappe.utils import cint, get_fullname

from truth_of_bible.rewards import engine

_MAX_WINDOW = 1000


def _window(page, page_size):
	page = max(cint(page) or 1, 1)
	size = min(max(cint(page_size) or 20, 1), 50)
	return (page - 1) * size, size


def points_history(user: str, page=1, page_size=20) -> dict:
	start, size = _window(page, page_size)
	rows = frappe.get_all(
		"TOB Reward Ledger",
		filters={"user": user},
		fields=["title", "points", "reason", "creation"],
		order_by="creation desc",
		limit_start=start,
		limit_page_length=size + 1,
	)
	return {
		"items": [
			{"title": r.title or r.reason or "Points", "points": r.points, "when": str(r.creation), "reason": r.reason}
			for r in rows[:size]
		],
		"has_more": len(rows) > size,
	}


_KIND_LABEL = {"TOPUP": "Money added", "CONVERT": "Points converted", "SPEND": "Spent", "ADJUST": "Adjustment"}


def _legacy_label(account: str, party: str) -> str:
	account = account or ""
	if "Bank" in account:
		return "Wallet top-up"
	if "Donations" in account:
		return "Donation"
	if party and party in account:
		return "Withdrawal"
	return "Reward"


def _legacy_wallet_rows(user: str, limit: int) -> list:
	"""The member's older wallet entries (ERPNext GL Entry against their
	Customer), same query the previous wallet screen made."""
	party = user.split("@")[0]
	try:
		rows = frappe.get_all(
			"GL Entry",
			filters={"party_type": "Customer", "party": party, "is_cancelled": 0},
			fields=["creation", "account", "debit", "credit", "remarks", "voucher_no"],
			order_by="creation desc",
			limit_page_length=limit,
		)
	except Exception:
		frappe.log_error(title="Rewards wallet history (legacy)", message=frappe.get_traceback())
		return []
	return [
		{
			"title": _legacy_label(r.account, party),
			"amount": float(r.credit or 0) - float(r.debit or 0),
			"when": str(r.creation),
			"note": (r.remarks or "")[:140],
			"source": "legacy",
			"currency": "INR",
		}
		for r in rows
	]


def wallet_history(user: str, page=1, page_size=20) -> dict:
	start, size = _window(page, page_size)
	need = min(start + size + 1, _MAX_WINDOW)
	new = frappe.get_all(
		"TOB Reward Wallet Ledger",
		filters={"user": user},
		fields=["kind", "title", "amount", "creation"],
		order_by="creation desc",
		limit_page_length=need,
	)
	items = [
		{
			"title": r.title or _KIND_LABEL.get(r.kind, "Wallet"),
			"amount": float(r.amount or 0),
			"when": str(r.creation),
			"note": _KIND_LABEL.get(r.kind, ""),
			"source": "wallet",
			"currency": None,
		}
		for r in new
	] + _legacy_wallet_rows(user, need)
	items.sort(key=lambda i: i["when"], reverse=True)
	page_items = items[start : start + size]
	return {
		"items": page_items,
		"has_more": len(items) > start + size,
		"balance": engine.wallet_balance(user),
	}


_STATUS_LABEL = {"PENDING": "Waiting to start reading", "REWARDED": "Rewarded", "CAPPED": "Monthly limit reached"}


def _mask(user: str) -> str:
	name = (get_fullname(user) or user.split("@")[0]).strip()
	parts = name.split()
	return parts[0] + (f" {parts[-1][0]}." if len(parts) > 1 else "")


def invite_summary(user: str) -> dict:
	rows = frappe.get_all(
		"TOB Reward Referral",
		filters={"referrer": user},
		fields=["referee", "status", "creation", "rewarded_at"],
		order_by="creation desc",
		limit_page_length=100,
	)
	return {
		**engine.referral_overview(user),
		"friends": [
			{"name": _mask(r.referee), "status": r.status, "status_label": _STATUS_LABEL.get(r.status, r.status.title()), "joined": str(r.creation), "rewarded_at": str(r.rewarded_at or "")}
			for r in rows
		],
	}
