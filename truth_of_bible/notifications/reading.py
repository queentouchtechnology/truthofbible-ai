"""The spiritual/Bible-reading engine (Phase 5 of NOTIFICATION_ENGINE_PLAN.md,
option A — approved 2026-09-22): a small server-side mirror of each user's
last reading activity, synced from the Flutter client, so the daily
continue-reading nudge and the gentle inactivity tiers are correct across
a user's multiple devices instead of only knowing about the one device
that happens to run a local scheduler.

Tone rules (do not violate when editing the seeded templates in
install.py): never imply spiritual failure, never claim to know God's
will for the person, never shame inactivity, never turn reading into a
competitive score. `reading_days` exists only to let a template author
write different, still-gentle copy for a first-time vs. an established
reader later — it is never shown to the user as a number.
"""

import frappe
from frappe.utils import get_datetime, now_datetime

from truth_of_bible.notifications import timeutils
from truth_of_bible.notifications.engine import handle_event
from truth_of_bible.notifications.preferences import get_or_create_preference

# Largest first: a user inactive 40 days must land on the 30-day tier, not
# be caught by the 3-day check and stop there.
_INACTIVE_TIERS = (30, 14, 7, 3)


def record_reading(user: str, book: str | None, chapter, verse=None, book_id=None) -> None:
	"""Called from `truth_of_bible.api.notifications.record_reading_activity`
	right after the Flutter client logs the same activity locally. Only
	ever updates state — it never itself sends a notification, so opening
	the app and reading normally can never, by itself, trigger a push;
	only the scheduled scan below decides that, and only after the fact.

	`book_id` is the app's numeric book id (kept alongside `book`, the
	localized display name used in notification copy) — it's the only
	form of "book" a deep link can actually navigate to, see
	`_try_continue_nudge`'s `deeplink_ref`.
	"""
	pref = get_or_create_preference(user)
	today_local = timeutils.local_now(pref.timezone).date()

	existing = frappe.db.exists("TOB User Reading State", {"user": user})
	doc = frappe.get_doc("TOB User Reading State", existing) if existing else frappe.new_doc("TOB User Reading State")
	doc.user = user
	is_new_day = doc.get("last_read_date") != today_local
	doc.last_book = book
	if book_id is not None:
		doc.last_book_id = book_id
	doc.last_chapter = chapter
	doc.last_verse = str(verse) if verse is not None else None
	doc.last_read_at = now_datetime()
	doc.last_read_date = today_local
	if is_new_day:
		doc.reading_days = (doc.reading_days or 0) + 1
	# They're reading again right now — whatever inactivity tier they were
	# previously flagged at is over. This is what makes Phase 12's rule
	# ("never notify inactivity if they already returned") actually hold.
	doc.inactive_tier_notified = "None"
	if existing:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)


def daily_scan() -> None:
	"""Hourly scheduler job (see hooks.py `scheduler_events`). For every
	user with a reading-state row: send at most one gentle nudge per pass —
	either today's continue/start reminder (if it's their configured hour
	and they haven't read today) or the next inactivity tier they've
	crossed, never both in the same pass.
	"""
	rows = frappe.get_all(
		"TOB User Reading State",
		fields=[
			"name", "user", "last_book", "last_book_id", "last_chapter", "last_read_at",
			"last_read_date", "inactive_tier_notified", "last_notified_continue_date",
		],
	)
	for row in rows:
		try:
			_scan_one(row)
		except Exception:
			frappe.log_error(
				title=f"Notification engine: reading scan ({row.user})",
				message=frappe.get_traceback(),
			)


def _scan_one(row) -> None:
	pref = get_or_create_preference(row.user)
	if not pref.bible_reading and not pref.spiritual_growth:
		return
	if not row.last_read_at:
		return

	now_local = timeutils.local_now(pref.timezone)
	today_local = now_local.date()

	if row.last_read_date == today_local:
		return  # already read today on some device — never nudge a returning user

	if _try_continue_nudge(row, pref, now_local, today_local):
		return  # one nudge per pass is enough

	_try_inactivity_nudge(row, now_local)


def _try_continue_nudge(row, pref, now_local, today_local) -> bool:
	if row.last_notified_continue_date == today_local:
		return False
	if now_local.hour != timeutils.time_to_seconds(pref.daily_reminder_time) // 3600:
		return False

	if row.last_book:
		# `deeplink_ref` is "<book_id>|<chapter>|1" for the app's
		# `/continueReading` route (see deepLink_routes.dart) to open the
		# reader at this exact chapter — empty when this row predates
		# `last_book_id` (e.g. not read again yet on the updated app), in
		# which case that route falls back to the generic verse screen.
		deeplink_ref = f"{row.last_book_id}|{row.last_chapter or 1}|1" if row.last_book_id else ""
		event, variables = "BIBLE_READING_CONTINUE", {
			"book": row.last_book,
			"chapter": row.last_chapter,
			"deeplink_ref": deeplink_ref,
		}
	else:
		event, variables = "BIBLE_READING_CONTINUE_GENERIC", {}

	if handle_event(event, row.user, variables):
		frappe.db.set_value("TOB User Reading State", row.name, "last_notified_continue_date", today_local)
	return True


def _try_inactivity_nudge(row, now_local) -> None:
	days_inactive = (get_datetime(now_local.replace(tzinfo=None)) - get_datetime(row.last_read_at)).days
	for tier in _INACTIVE_TIERS:
		if days_inactive >= tier and row.inactive_tier_notified != str(tier):
			if handle_event(f"BIBLE_READING_INACTIVE_{tier}", row.user, {}):
				frappe.db.set_value("TOB User Reading State", row.name, "inactive_tier_notified", str(tier))
			return
