"""Audience resolution and per-channel eligibility for the Communication
Center — Decision 3 (v1 audience types: SINGLE_USER / SELECTED_USERS /
ALL_ELIGIBLE_USERS only) and contract SS2's eligibility rules.

Only real app accounts count as an audience, matching
`notifications/triggers.py`'s own `on_user_created` exclusion: a
Desk-created System User is never "a user" in the Communication Center's
sense, only a `Website User` is. `Administrator`/`Guest` are excluded the
same way `admin_audience.py` already excludes them elsewhere in this app.
"""

import re

import frappe

from truth_of_bible.notifications.preferences import get_or_create_preference

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# E.164-compatible: a leading + and 8-15 digits — matches what the
# Flutter client's own intl_phone_field-based screens already enforce
# (see get_whatsapp_number_screen.dart), re-checked here rather than
# trusted blindly (contract SS2's explicit instruction).
_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")

CHANNELS = ("push", "email", "whatsapp")


def resolve_audience(audience_type: str, audience_user_ids: list) -> list[str]:
	if audience_type == "ALL_ELIGIBLE_USERS":
		return frappe.get_all(
			"User",
			filters={"user_type": "Website User", "enabled": 1},
			pluck="name",
		)

	ids = [u for u in (audience_user_ids or []) if u]
	if not ids:
		return []
	users = frappe.get_all(
		"User",
		filters={"name": ["in", ids], "user_type": "Website User", "enabled": 1},
		pluck="name",
	)
	return list(dict.fromkeys(users))


def channel_eligible(user: str, channel: str, pref=None) -> bool:
	pref = pref or get_or_create_preference(user)

	if channel == "push":
		if pref.get("communication_center_push_opt_out"):
			return False
		return bool(frappe.db.exists("User FCM Token", {"user": user}))

	if channel == "email":
		if pref.get("communication_center_email_opt_out"):
			return False
		email = (frappe.db.get_value("User", user, "email") or "").strip()
		return bool(_EMAIL_RE.match(email))

	if channel == "whatsapp":
		if pref.get("communication_center_whatsapp_opt_out"):
			return False
		phone = (frappe.db.get_value("User", user, "mobile_no") or "").strip()
		return bool(_PHONE_RE.match(phone))

	return False


def estimate(audience_type: str, audience_user_ids: list) -> dict:
	users = resolve_audience(audience_type, audience_user_ids)
	counts = {"push": 0, "email": 0, "whatsapp": 0}
	for user in users:
		pref = get_or_create_preference(user)
		for channel in CHANNELS:
			if channel_eligible(user, channel, pref):
				counts[channel] += 1
	return {"total_users": len(users), "channel_eligible_counts": counts}
