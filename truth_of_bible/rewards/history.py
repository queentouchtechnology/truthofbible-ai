"""Read-only history for the Rewards screens: points, wallet (new ledger
merged with the member's older ERPNext wallet entries, so nothing they had
before disappears) and the friends they've invited. Every row carries a
`category` (donation, AI usage, points conversion, ...) and both lists
support search, category filter and sort — all decided here, not in the app.
"""

import frappe
from frappe.utils import cint, get_fullname

from truth_of_bible.rewards import engine

_MAX_WINDOW = 1000
_SORTS = ("newest", "oldest", "high", "low")


def _window(page, page_size):
	page = max(cint(page) or 1, 1)
	size = min(max(cint(page_size) or 20, 1), 50)
	return (page - 1) * size, size


def _sort(sort):
	return sort if sort in _SORTS else "newest"


# --- points ------------------------------------------------------------

_POINT_LABELS = {
	"daily_checkin": "Check-in",
	"read_chapter": "Bible reading",
	"complete_quiz": "Quiz",
	"devotional": "Devotional",
	"share_app": "Sharing",
	"complete_profile": "Profile",
	"referral": "Referral",
	"wallet": "Points conversion",
	"redeem": "Coupon",
	"order": "Shop order",
}


def _point_category(reason: str) -> str:
	reason = reason or ""
	if reason.startswith("referral"):
		return "referral"
	if reason.startswith("streak"):
		return "streak"
	return reason or "other"


def _point_label(category: str) -> str:
	if category == "streak":
		return "Streak bonus"
	return _POINT_LABELS.get(category, category.replace("_", " ").title())


def points_history(user: str, page=1, page_size=20, q=None, category=None, sort="newest") -> dict:
	start, size = _window(page, page_size)
	sort = _sort(sort)
	where, args = ["user=%s"], [user]
	q = (q or "").strip()
	if q:
		where.append("title like %s")
		args.append(f"%{q}%")
	if category:
		if category == "referral":
			where.append("reason like 'referral%%'")
		elif category == "streak":
			where.append("reason like 'streak%%'")
		else:
			where.append("reason=%s")
			args.append(category)
	order = {
		"newest": "creation desc",
		"oldest": "creation asc",
		"high": "points desc, creation desc",
		"low": "points asc, creation desc",
	}[sort]
	rows = frappe.db.sql(
		f"""select title, points, reason, creation from `tabTOB Reward Ledger`
		where {' and '.join(where)} order by {order} limit %s, %s""",
		(*args, start, size + 1),
		as_dict=True,
	)
	reasons = frappe.db.sql_list("select distinct reason from `tabTOB Reward Ledger` where user=%s", user)
	cats = sorted({_point_category(r) for r in reasons})
	return {
		"items": [
			{
				"title": r.title or _point_label(_point_category(r.reason)),
				"points": r.points,
				"when": str(r.creation),
				"category": _point_category(r.reason),
				"category_label": _point_label(_point_category(r.reason)),
			}
			for r in rows[:size]
		],
		"has_more": len(rows) > size,
		"categories": [{"key": c, "label": _point_label(c)} for c in cats],
	}


# --- wallet ------------------------------------------------------------

_WALLET_LABELS = {
	"topup": "Top-up",
	"conversion": "Points conversion",
	"ai_usage": "AI usage",
	"donation": "Donation",
	"withdrawal": "Withdrawal",
	"reward": "Reward",
	"adjustment": "Adjustment",
}
_KIND_CATEGORY = {"TOPUP": "topup", "CONVERT": "conversion", "SPEND": "ai_usage", "ADJUST": "adjustment"}


def _legacy_category(account: str, party: str) -> str:
	account = account or ""
	if "Bank" in account:
		return "topup"
	if "Donations" in account:
		return "donation"
	if party and party in account:
		return "withdrawal"
	return "reward"


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
	out = []
	for r in rows:
		cat = _legacy_category(r.account, party)
		out.append(
			{
				"title": _WALLET_LABELS[cat],
				"amount": float(r.credit or 0) - float(r.debit or 0),
				"when": str(r.creation),
				"note": (r.remarks or "")[:140],
				"source": "legacy",
				"currency": "INR",
				"category": cat,
				"category_label": _WALLET_LABELS[cat],
			}
		)
	return out


def wallet_history(user: str, page=1, page_size=20, q=None, category=None, sort="newest") -> dict:
	start, size = _window(page, page_size)
	sort = _sort(sort)
	new = frappe.get_all(
		"TOB Reward Wallet Ledger",
		filters={"user": user},
		fields=["kind", "title", "amount", "creation"],
		order_by="creation desc",
		limit_page_length=_MAX_WINDOW,
	)
	items = []
	for r in new:
		cat = _KIND_CATEGORY.get(r.kind, "adjustment")
		items.append(
			{
				"title": r.title or _WALLET_LABELS[cat],
				"amount": float(r.amount or 0),
				"when": str(r.creation),
				"note": "",
				"source": "wallet",
				"currency": None,
				"category": cat,
				"category_label": _WALLET_LABELS[cat],
			}
		)
	items += _legacy_wallet_rows(user, _MAX_WINDOW)

	present = sorted({i["category"] for i in items})
	needle = (q or "").strip().lower()
	if needle:
		items = [i for i in items if needle in f"{i['title']} {i['note']} {i['category_label']}".lower()]
	if category:
		items = [i for i in items if i["category"] == category]
	if sort == "oldest":
		items.sort(key=lambda i: i["when"])
	elif sort == "high":
		items.sort(key=lambda i: (i["amount"], i["when"]), reverse=True)
	elif sort == "low":
		items.sort(key=lambda i: (i["amount"], i["when"]))
	else:
		items.sort(key=lambda i: i["when"], reverse=True)
	return {
		"items": items[start : start + size],
		"has_more": len(items) > start + size,
		"balance": engine.wallet_balance(user),
		"categories": [{"key": c, "label": _WALLET_LABELS[c]} for c in present],
	}


# --- invites -----------------------------------------------------------

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
			{
				"name": _mask(r.referee),
				"status": r.status,
				"status_label": _STATUS_LABEL.get(r.status, r.status.title()),
				"joined": str(r.creation),
				"rewarded_at": str(r.rewarded_at or ""),
			}
			for r in rows
		],
	}
