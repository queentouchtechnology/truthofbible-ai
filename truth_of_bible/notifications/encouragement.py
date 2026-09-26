"""Daily spiritual/emotional encouragement push — a large, admin-growable
pool of short evangelistic/comfort messages (`TOB Encouragement Message`),
one picked at random per user per day so the same message never blankets
everyone at once. Deliberately separate from `prayer.py`'s own smaller,
code-fixed rotation: this pool is meant to grow indefinitely from the
admin app's Encouragement Messages screen, with no code deploy needed to
add a new message.

Every user with at least one registered device is a candidate — same
"no reading-state gate" reasoning as prayer.py, since this is meant to
reach a brand-new user from day one, not only someone who's already
engaged with Bible reading.

Reuses `daily_reminder_time` (the same slot BIBLE_READING_CONTINUE fires
in) rather than adding yet another per-user time preference. A user CAN
get both a reading nudge and an encouragement push in the same hour —
each is deduped/capped independently by the engine (one shared
`DAILY_ENCOURAGEMENT` event_code, so `engine.py`'s own "already sent
today" check already prevents more than one of THESE per day), and the
shared `max_daily_notifications` cap still applies across everything.
"""

import random

import frappe
from frappe.utils import now_datetime

from truth_of_bible.notifications import timeutils
from truth_of_bible.notifications.engine import handle_event
from truth_of_bible.notifications.preferences import get_or_create_preference

_EVENT = "DAILY_ENCOURAGEMENT"


def daily_scan() -> None:
	"""Hourly scheduler job (see hooks.py), same cadence as reading.py/
	prayer.py/bible_study.py."""
	users = frappe.get_all("User FCM Token", pluck="user", distinct=True)
	for user in users:
		try:
			_scan_one(user)
		except Exception:
			frappe.log_error(
				title=f"Notification engine: encouragement scan ({user})", message=frappe.get_traceback()
			)


def _scan_one(user: str) -> None:
	pref = get_or_create_preference(user)
	if not pref.get("encouragement"):
		return

	now_local = timeutils.local_now(pref.timezone)
	if now_local.hour != timeutils.time_to_seconds(pref.daily_reminder_time) // 3600:
		return

	message = _pick_message(exclude=pref.get("last_encouragement_message"))
	if not message:
		return

	sent = handle_event(
		_EVENT,
		user,
		{
			"enc_title": message.title,
			"enc_body": message.body or "",
			"deeplink_route_override": message.deeplink_route or "",
		},
	)
	if not sent:
		return

	# Best-effort bookkeeping only — a failure here must never turn a
	# successfully delivered push into a logged error, so it's deliberately
	# outside handle_event's own try/except-everything contract.
	try:
		frappe.db.set_value(
			"TOB Notification Preference", pref.name, "last_encouragement_message", message.name
		)
		frappe.db.set_value(
			"TOB Encouragement Message",
			message.name,
			{"times_sent": (message.times_sent or 0) + 1, "last_sent_at": now_datetime()},
		)
		frappe.db.commit()
	except Exception:
		frappe.log_error(
			title="Notification engine: encouragement bookkeeping failed", message=frappe.get_traceback()
		)


def _pick_message(exclude=None):
	"""Weighted random pick among enabled messages, excluding whichever one
	this user got last (so the same message never repeats two days running)
	— unless that's the ONLY enabled message, in which case a repeat is the
	only option and is allowed rather than sending nothing."""
	rows = frappe.get_all(
		"TOB Encouragement Message",
		filters={"enabled": 1},
		fields=["name", "title", "body", "deeplink_route", "weight", "times_sent"],
	)
	if not rows:
		return None
	candidates = [r for r in rows if r.name != exclude] or rows
	weights = [max(1, r.weight or 1) for r in candidates]
	return random.choices(candidates, weights=weights, k=1)[0]
