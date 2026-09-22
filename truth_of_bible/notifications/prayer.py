"""The prayer-nudge engine — a single gentle "take a moment to pray"
reminder per user per day, fired at their own `preferred_prayer_time`
(hourly scheduler, same mechanism as `reading.daily_scan`).

Rather than one fixed message, the wording rotates across the 9 variants
below, weighted to roughly match the cadence given when this feature was
specced (2026-09-22): most days pick a daily-eligible, time-of-day-flavored
variant; some days pick one of the "variety" variants (Reflection ~2-3x/
week, Thanksgiving/Others ~1-2x/week each) instead — purely for wording
variety, never more than one prayer nudge in a day. The rotation is
deterministic per (user, local date) via a seeded RNG, so re-running the
same hour's scan twice never flips the choice.

Tone rules (same as reading.py): never implies the user has been
neglecting prayer, never claims to know what they should pray for — every
variant is an invitation, not a nudge about a gap.
"""

import random

import frappe
from frappe.utils import get_datetime, nowdate

from truth_of_bible.notifications import timeutils
from truth_of_bible.notifications.engine import handle_event
from truth_of_bible.notifications.preferences import get_or_create_preference

_ALL_PRAYER_EVENTS = (
	"PRAYER_DAILY",
	"PRAYER_MORNING",
	"PRAYER_EVENING",
	"PRAYER_SCRIPTURE",
	"PRAYER_REFLECTION",
	"PRAYER_PEACE",
	"PRAYER_THANKSGIVING",
	"PRAYER_OTHERS",
	"PRAYER_ROUTINE",
)

# Chosen when it's not a "variety" day (see _pick_variant) and the user's
# preferred hour doesn't fall in the morning/evening bands below.
_DAILY_POOL = ("PRAYER_DAILY", "PRAYER_SCRIPTURE", "PRAYER_ROUTINE", "PRAYER_PEACE")


def daily_scan() -> None:
	"""Hourly scheduler job (see hooks.py `scheduler_events`). Scans every
	user with at least one registered device — there's no reading-state-like
	activity table for prayer, so device registration is the closest proxy
	for "an active app user", same as how delivery.py already only ever
	pushes to users with a `User FCM Token` row anyway.
	"""
	users = frappe.get_all("User FCM Token", pluck="user", distinct=True)
	for user in users:
		try:
			_scan_one(user)
		except Exception:
			frappe.log_error(
				title=f"Notification engine: prayer scan ({user})", message=frappe.get_traceback()
			)


def _scan_one(user: str) -> None:
	pref = get_or_create_preference(user)
	if not pref.prayer:
		return

	now_local = timeutils.local_now(pref.timezone)
	preferred_hour = int(timeutils.time_to_seconds(pref.preferred_prayer_time) // 3600)
	if now_local.hour != preferred_hour:
		return

	if _already_sent_prayer_today(user):
		return

	handle_event(_pick_variant(user, now_local), user, {})


def _pick_variant(user: str, now_local) -> str:
	# Seeded by (user, local date) — same pick if this hour's scan is ever
	# re-run, varied day to day and user to user.
	rng = random.Random(f"{user}|{now_local.date().isoformat()}")
	roll = rng.random()

	# ~2-3x/week
	if roll < 0.35:
		return "PRAYER_REFLECTION"
	# ~1-2x/week each
	if roll < 0.55:
		return rng.choice(["PRAYER_THANKSGIVING", "PRAYER_OTHERS"])

	if now_local.hour < 11:
		return "PRAYER_MORNING"
	if now_local.hour >= 18:
		return "PRAYER_EVENING"
	return rng.choice(_DAILY_POOL)


def _already_sent_prayer_today(user: str) -> bool:
	"""Cross-event dedup: handle_event's own dedup only guards against the
	SAME event_code firing twice today, but a different hour's scan could
	otherwise pick a different variant and send a second prayer nudge the
	same day. Uses the site's own "today" (matching engine.py's own
	_already_sent_today), not the user's local day — same simplification
	already accepted elsewhere in this engine.
	"""
	return bool(
		frappe.db.exists(
			"TOB Notification Send Log",
			{
				"user": user,
				"event_code": ["in", list(_ALL_PRAYER_EVENTS)],
				"sent_at": [">=", get_datetime(nowdate())],
			},
		)
	)
