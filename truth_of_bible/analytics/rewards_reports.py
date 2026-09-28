"""Admin reports for the app-wide rewards system (`truth_of_bible.rewards`)
— `require_admin()`-gated, read-only. This system had zero admin
visibility before this module; it reads the existing `TOB Reward *`
doctypes without any new tracking, same reasoning as
`analytics/reading_reports.py`. Fully separate from
`analytics/sunday_school_reports.py` — nothing here touches a
`TOB Sunday School *` doctype.
"""

import frappe

from truth_of_bible.communication.auth import require_admin


@frappe.whitelist(methods=["GET"])
def get_overview_stats(days=30):
	require_admin()
	days = max(1, min(int(days), 180))
	since = frappe.utils.add_days(frappe.utils.nowdate(), -days)

	return {
		"points_awarded": int(
			frappe.db.sql(
				"select sum(points) from `tabTOB Reward Ledger` where points > 0 and creation >= %s", (since,)
			)[0][0] or 0
		),
		"active_earners": frappe.db.sql(
			"select count(distinct user) from `tabTOB Reward Ledger` where creation >= %s", (since,)
		)[0][0] or 0,
		"coupons_redeemed": frappe.db.count("TOB Reward Coupon", {"creation": [">=", since]}),
		"wallet_converted": float(
			frappe.db.sql(
				"select sum(amount) from `tabTOB Reward Wallet Ledger` where kind='CONVERT' and creation >= %s", (since,)
			)[0][0] or 0
		),
		"referrals_rewarded": frappe.db.count("TOB Reward Referral", {"status": "REWARDED", "rewarded_at": [">=", since]}),
	}


@frappe.whitelist(methods=["GET"])
def get_top_earners(days=30, limit=20):
	require_admin()
	days = max(1, min(int(days), 180))
	limit = max(1, min(int(limit), 100))
	since = frappe.utils.add_days(frappe.utils.nowdate(), -days)

	rows = frappe.db.sql(
		"""select user, sum(points) as total from `tabTOB Reward Ledger`
		where points > 0 and creation >= %s group by user order by total desc limit %s""",
		(since, limit), as_dict=True,
	)
	if rows:
		brief = {
			u.name: u.full_name
			for u in frappe.get_all("User", filters={"name": ["in", [r.user for r in rows]]}, fields=["name", "full_name"])
		}
		for r in rows:
			r["full_name"] = brief.get(r.user, r.user)
	return {"days": days, "rows": rows}


@frappe.whitelist(methods=["GET"])
def get_redemption_stats(days=30):
	require_admin()
	days = max(1, min(int(days), 180))
	since = frappe.utils.add_days(frappe.utils.nowdate(), -days)

	by_tier = frappe.db.sql(
		"""select tier, count(*) as count, sum(points_spent) as points from `tabTOB Reward Coupon`
		where creation >= %s group by tier order by count desc""",
		(since,), as_dict=True,
	)
	return {"days": days, "by_tier": by_tier}


@frappe.whitelist(methods=["GET"])
def get_ledger(user=None, reason=None, limit=50, offset=0):
	require_admin()
	filters = {}
	if user:
		filters["user"] = user
	if reason:
		filters["reason"] = reason
	limit = max(1, min(int(limit), 100))
	offset = max(0, int(offset))

	rows = frappe.get_all(
		"TOB Reward Ledger", filters=filters,
		fields=["name", "user", "reason", "title", "points", "creation"],
		order_by="creation desc", limit_page_length=limit, limit_start=offset,
	)
	total = frappe.db.count("TOB Reward Ledger", filters)
	return {"rows": rows, "total": total}
