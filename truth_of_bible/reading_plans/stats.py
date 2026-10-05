"""Reading-plan habit numbers: plan streak, reading calendar, totals.

Built from each enrollment's `completion_log` ({day_number: 'YYYY-MM-DD'},
the date a day was ticked). A "plan day" is a date on which the user ticked
at least one day of any plan."""

import json
from datetime import date, timedelta

import frappe
from frappe.utils import getdate, nowdate


def _log(raw) -> dict:
	try:
		data = json.loads(raw or "{}")
		return data if isinstance(data, dict) else {}
	except ValueError:
		return {}


def plan_dates(user: str) -> dict:
	"""date -> number of plan days ticked that date."""
	counts: dict = {}
	for raw in frappe.get_all("TOB User Reading Plan", filters={"user": user}, pluck="completion_log"):
		for value in _log(raw).values():
			try:
				d = getdate(value)
			except Exception:
				continue
			counts[d] = counts.get(d, 0) + 1
	return counts


def streaks(dates) -> tuple[int, int]:
	"""(current, best). The current streak survives until the end of today
	— yesterday's reading still counts as "on a streak" this morning."""
	days = set(dates)
	if not days:
		return 0, 0
	today = getdate(nowdate())
	cursor = today if today in days else today - timedelta(days=1)
	current = 0
	while cursor in days:
		current += 1
		cursor -= timedelta(days=1)
	best = run = 0
	prev: date | None = None
	for d in sorted(days):
		run = run + 1 if prev and d - prev == timedelta(days=1) else 1
		best = max(best, run)
		prev = d
	return current, max(best, current)


def stats(user: str, weeks: int = 12) -> dict:
	counts = plan_dates(user)
	current, best = streaks(counts)
	today = getdate(nowdate())
	# Calendar: `weeks` full weeks ending this week (Mon–Sun columns).
	start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
	calendar = []
	d = start
	while d <= today:
		calendar.append({"date": str(d), "count": counts.get(d, 0)})
		d += timedelta(days=1)
	week_start = today - timedelta(days=today.weekday())
	return {
		"streak": current,
		"best_streak": best,
		"days_read": sum(counts.values()),
		"active_days": len(counts),
		"this_week": sum(c for dd, c in counts.items() if dd >= week_start),
		"plans_completed": frappe.db.count("TOB User Reading Plan", {"user": user, "status": "Completed"}),
		"plans_active": frappe.db.count("TOB User Reading Plan", {"user": user, "status": "Active"}),
		"calendar_start": str(start),
		"calendar": calendar,
	}
