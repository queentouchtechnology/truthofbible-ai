"""Bible Study suggestion nudge — NOTIFICATION_ENGINE_PLAN.md "What's still
open" item 6 (the "Bible Study" preference toggle existed in the UI with no
matching event before this slice).

The plan's own Phase 4 spec describes this as "keyed off recentBooks" — a
list of recently-read books this app doesn't actually track anywhere
(`TOB User Reading State`, reading.py's own state doctype, only ever stores
a single `last_book`, not a history). Rather than inventing new tracking
the plan never confirmed, this reuses that one real field: a gentle
suggestion to go deeper into whatever book the person was last reading,
not a synthesized "recent books" list. Same tone rules as reading.py
(never shame, never imply failure) — this only ever fires for someone
who's actively reading, never an inactive one (that's reading.py's own,
separate inactivity tiers).

"Max 2/week" (the plan's own cap for this event) needs no new state field:
`TOB Notification Send Log` already has one row per event actually sent,
so a plain count over the last 7 days is enough — the same table
`engine.py`'s own daily-cap check already reads.
"""

import frappe
from frappe.utils import add_days, now_datetime

from truth_of_bible.notifications import timeutils
from truth_of_bible.notifications.engine import handle_event
from truth_of_bible.notifications.preferences import get_or_create_preference

_MAX_PER_WEEK = 2
_EVENT = "BIBLE_STUDY_SUGGESTION"


def daily_scan() -> None:
	"""Hourly scheduler job (see hooks.py), same cadence as reading.py's own
	scan — a per-user "hour" granularity is all this product promises
	anywhere else, no reason for this to be finer."""
	rows = frappe.get_all(
		"TOB User Reading State",
		filters={"last_book": ["is", "set"]},
		fields=["name", "user", "last_book", "last_read_date"],
	)
	for row in rows:
		try:
			_scan_one(row)
		except Exception:
			frappe.log_error(
				title=f"Notification engine: bible study scan ({row.user})", message=frappe.get_traceback()
			)


def _scan_one(row) -> None:
	pref = get_or_create_preference(row.user)
	if not pref.bible_study:
		return

	now_local = timeutils.local_now(pref.timezone)
	today_local = now_local.date()

	# Only for someone actively reading — an inactive user gets reading.py's
	# own gentler inactivity-tier copy instead, never this one too.
	if row.last_read_date != today_local:
		return

	if now_local.hour != timeutils.time_to_seconds(pref.daily_reminder_time) // 3600:
		return

	if _sent_this_week(row.user) >= _MAX_PER_WEEK:
		return

	handle_event(_EVENT, row.user, {"book": row.last_book})


def _sent_this_week(user: str) -> int:
	since = add_days(now_datetime(), -7)
	return frappe.db.count("TOB Notification Send Log", {"user": user, "event_code": _EVENT, "sent_at": [">=", since]})
