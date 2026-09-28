"""Admin reports for the Sunday School weekly rewards system —
`require_admin()`-gated, read-only, mirroring `analytics/reading_reports.py`'s
shape. Leaderboard ranking itself is delegated to
`api.sunday_school.get_leaderboard` rather than re-implemented here, so
there's exactly one ranking query in the codebase.
"""

import frappe

from truth_of_bible.communication.auth import require_admin
from truth_of_bible.sunday_school import engine
from truth_of_bible.api import sunday_school as student_api


@frappe.whitelist(methods=["GET"])
def get_overview_stats():
	require_admin()
	week = engine.week_start_of()
	return {
		"week_start": str(week),
		"total_students": frappe.db.count("TOB Sunday School Profile", {"status": "Active"}),
		"total_groups": frappe.db.count("TOB Sunday School Group", {"status": "Active"}),
		"points_awarded_this_week": int(
			frappe.db.sql(
				"select sum(points) from `tabTOB Sunday School Points Ledger` where week_start=%s", (week,)
			)[0][0] or 0
		),
		"points_awarded_all_time": int(
			frappe.db.sql("select sum(points) from `tabTOB Sunday School Points Ledger`")[0][0] or 0
		),
		"open_quizzes": frappe.db.count("TOB Sunday School Weekly Quiz", {"status": "Published"}),
		"pending_verse_verifications": frappe.db.count("TOB Sunday School Verse Completion", {"status": "Pending"}),
	}


@frappe.whitelist(methods=["GET"])
def get_weekly_leaderboard_report(kind="overall", week_start=None):
	require_admin()
	return student_api.get_leaderboard(kind=kind, week_start=week_start)


@frappe.whitelist(methods=["GET"])
def get_group_standings():
	require_admin()
	week = engine.week_start_of()
	this_week = student_api.get_leaderboard("group", str(week))["leaderboard"]

	all_time_rows = frappe.db.sql(
		"""select `group`, sum(points) as total from `tabTOB Sunday School Points Ledger`
		where `group` is not null and `group` != '' group by `group` order by total desc""",
		as_dict=True,
	)
	names = {}
	if all_time_rows:
		names = {
			g.name: g.group_name
			for g in frappe.get_all(
				"TOB Sunday School Group", filters={"name": ["in", [r["group"] for r in all_time_rows]]},
				fields=["name", "group_name"],
			)
		}
	all_time = [
		{"rank": i + 1, "group": r["group"], "group_name": names.get(r["group"], r["group"]), "points": int(r.total)}
		for i, r in enumerate(all_time_rows)
	]
	return {"week_start": str(week), "this_week": this_week, "all_time": all_time}


@frappe.whitelist(methods=["GET"])
def get_attendance_report(week_start=None):
	require_admin()
	week = engine.week_start_of(week_start) if week_start else engine.week_start_of()
	rows = frappe.get_all(
		"TOB Sunday School Attendance", filters={"week_start": week},
		fields=["name", "user", "attended_class", "attended_quiz", "completed_memory_verse", "goal_bonus_awarded"],
	)
	if rows:
		brief = {
			u.name: u.full_name
			for u in frappe.get_all("User", filters={"name": ["in", [r.user for r in rows]]}, fields=["name", "full_name"])
		}
		for r in rows:
			r["full_name"] = brief.get(r.user, r.user)
	return {"week_start": str(week), "rows": rows}


@frappe.whitelist(methods=["GET"])
def get_student_history(user):
	require_admin()
	profile = frappe.db.get_value(
		"TOB Sunday School Profile", user, ["group", "status"], as_dict=True
	)
	ledger = frappe.get_all(
		"TOB Sunday School Points Ledger", filters={"user": user},
		fields=["title", "points", "source", "week_start", "creation"], order_by="creation desc", limit_page_length=100,
	)
	quiz_attempts = frappe.get_all(
		"TOB Sunday School Quiz Attempt", filters={"user": user},
		fields=["quiz", "score", "total_marks", "rank", "submitted_at"], order_by="submitted_at desc",
	)
	verse_completions = frappe.get_all(
		"TOB Sunday School Verse Completion", filters={"user": user},
		fields=["memory_verse", "status", "rank", "completed_at"], order_by="completed_at desc",
	)
	return {
		"user": user,
		"profile": profile,
		"points_history": ledger,
		"quiz_attempts": quiz_attempts,
		"verse_completions": verse_completions,
	}
