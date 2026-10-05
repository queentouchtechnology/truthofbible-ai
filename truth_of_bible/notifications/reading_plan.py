"""Reading-plan reminders — the plan-aware side of the reading engine
(notifications/reading.py), same tone rules: never shame a missed day,
never turn a plan into a score.

Three notifications, all in the "Bible Reading" category (so the user's
Bible Reading toggle, quiet hours and daily cap all apply):

- READING_PLAN_DAY — once a day, in the user's own Daily Reminder hour:
  "Day N of <plan> is ready". Only when the plan hasn't been touched yet
  today. For a user with an active plan this REPLACES the generic
  "continue reading" nudge (reading._try_continue_nudge skips them), so
  they get one reminder, not two.
- READING_PLAN_NUDGE — once per gap, after 3 days with no plan progress:
  a gentle "pick up where you left off". Reset by any progress.
- READING_PLAN_COMPLETED — right when the last day is ticked.

All three open the plan (`/readingPlan` route, id = plan name); the plan
screen offers the day's reading from there.
"""

import frappe
from frappe.utils import get_datetime, getdate

from truth_of_bible.notifications import timeutils
from truth_of_bible.notifications.engine import handle_event
from truth_of_bible.notifications.preferences import get_or_create_preference

STALE_DAYS = 3


def user_has_active_plan(user: str) -> bool:
	return bool(frappe.db.exists("TOB User Reading Plan", {"user": user, "status": "Active"}))


def _variables(enrollment, plan_title: str) -> dict:
	day = frappe.db.get_value(
		"TOB Reading Plan Day",
		{"plan": enrollment.plan, "day_number": enrollment.current_day or 1},
		["title", "reference_label"],
		as_dict=True,
	) or {}
	return {
		"plan": enrollment.plan,
		"plan_title": plan_title,
		"day_number": enrollment.current_day or 1,
		"day_title": day.get("title") or "",
		"reference": day.get("reference_label") or "",
	}


def daily_scan() -> None:
	"""Hourly (hooks.py). One reminder per user per pass: their most
	recently active plan only, even when they follow several."""
	rows = frappe.get_all(
		"TOB User Reading Plan",
		filters={"status": "Active"},
		fields=[
			"name", "user", "plan", "current_day", "last_activity_at", "last_reminded_date", "stale_nudged",
			"reminder_time",
		],
		order_by="last_activity_at desc",
	)
	seen = set()
	titles = {}
	for row in rows:
		if row.user in seen:
			continue
		seen.add(row.user)
		try:
			if row.plan not in titles:
				titles[row.plan] = frappe.db.get_value("TOB Reading Plan", row.plan, "title") or ""
			_scan_one(row, titles[row.plan])
		except Exception:
			frappe.log_error(
				title=f"Notification engine: reading plan scan ({row.user})", message=frappe.get_traceback()
			)


def _scan_one(row, plan_title: str) -> None:
	pref = get_or_create_preference(row.user)
	if not pref.bible_reading:
		return
	# The plan's own reminder time if the user set one, else their general one.
	reminder_hour = timeutils.time_to_seconds(row.reminder_time or pref.daily_reminder_time) // 3600
	now_local = timeutils.local_now(pref.timezone)
	today_local = now_local.date()
	last = get_datetime(row.last_activity_at) if row.last_activity_at else None
	# Activity is stored in server time; close enough to the user's own day
	# for "did they already do today's reading".
	touched_today = bool(last and last.date() == getdate(now_local.replace(tzinfo=None)))

	if touched_today:
		return

	if (
		last
		and not row.stale_nudged
		and (get_datetime(now_local.replace(tzinfo=None)) - last).days >= STALE_DAYS
		and now_local.hour == reminder_hour
	):
		if handle_event("READING_PLAN_NUDGE", row.user, _variables(row, plan_title)):
			frappe.db.set_value(
				"TOB User Reading Plan", row.name, {"stale_nudged": 1, "last_reminded_date": today_local},
				update_modified=False,
			)
		return

	if row.last_reminded_date and getdate(row.last_reminded_date) == today_local:
		return
	if now_local.hour != reminder_hour:
		return
	if handle_event("READING_PLAN_DAY", row.user, _variables(row, plan_title)):
		frappe.db.set_value(
			"TOB User Reading Plan", row.name, "last_reminded_date", today_local, update_modified=False
		)


def on_plan_completed(user: str, plan: str) -> None:
	"""Called by api.reading_plan.mark_day_complete when the last day is
	ticked. Never raises into that request."""
	try:
		title = frappe.db.get_value("TOB Reading Plan", plan, "title") or ""
		handle_event("READING_PLAN_COMPLETED", user, {"plan": plan, "plan_title": title})
	except Exception:
		frappe.log_error(title="Notification engine: reading plan completed", message=frappe.get_traceback())
