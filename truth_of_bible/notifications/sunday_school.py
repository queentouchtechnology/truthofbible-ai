"""Scheduled jobs for the Sunday School rewards system.

`weekly_reset_scan` — Monday-midnight cron (`scheduler_events["cron"]`).
Finalizes any quiz still `Published` for the week that just ended (a
safety net — an admin should normally have already closed it), computes
the Winner Group Bonus, and notifies every student who scored that week of
their result.

`daily_scan` — runs once a day (`scheduler_events["daily"]`), driving the
Redemption & Expiry clock described in `sunday_school/engine.py`'s module
docstring: warns students approaching their points-expiry deadline, then
expires anyone past it. Both paths go through `handle_event`, the one
notification entry point every event in this app uses (preferences/quiet-
hours/caps/dedup already handled there).
"""

import frappe
from frappe.utils import add_days

from truth_of_bible.notifications.engine import handle_event
from truth_of_bible.sunday_school import engine


def daily_scan():
	"""Registered under `scheduler_events["daily"]`."""
	try:
		engine.check_expiry_warnings()
	except Exception:
		frappe.log_error(title="Sunday School daily scan: expiry warnings failed", message=frappe.get_traceback())
	try:
		engine.expire_stale_points()
	except Exception:
		frappe.log_error(title="Sunday School daily scan: expire_stale_points failed", message=frappe.get_traceback())

import frappe
from frappe.utils import add_days

from truth_of_bible.notifications.engine import handle_event
from truth_of_bible.sunday_school import engine


def weekly_reset_scan():
	"""Registered under `scheduler_events["cron"]["0 0 * * 1"]` — fires at
	Monday 00:00, closing out the week that just ended."""
	last_week = add_days(engine.week_start_of(), -7)
	run_reset_for_week(last_week)


def run_reset_for_week(week_start) -> dict:
	"""Also callable directly from `api/sunday_school_admin.py::run_weekly_reset`
	for a manual/testing trigger — same computation either way. Quizzes
	need no finalize step here anymore: an LMS Quiz Submission scores
	itself the moment it's created (see sunday_school/engine.py::
	on_lms_quiz_submission), so by the time this runs every quiz score
	for the week is already in the Points Ledger."""
	from truth_of_bible.api import sunday_school as student_api

	bonus_result = engine.compute_weekly_group_bonus(week_start)

	overall = student_api.get_leaderboard("overall", str(week_start))
	notified = []
	for entry in overall["leaderboard"]:
		user = entry["id"]
		if handle_event(
			"SS_WEEKLY_RESULTS", user,
			{"rank": entry["rank"], "points": entry["points"], "week_start": str(week_start)},
		):
			notified.append(user)

	return {
		"week_start": str(week_start),
		"group_bonus": bonus_result,
		"notified": notified,
	}
