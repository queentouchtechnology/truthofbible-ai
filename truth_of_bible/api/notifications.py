"""Whitelisted, session-cookie-authenticated endpoints for the Flutter
client's side of the notification engine: syncing reading activity and
reading/writing the caller's own notification preferences. Every method
here acts as `frappe.session.user` only — never a token-selectable user —
matching this app's existing per-user-ownership convention (see
`api/bible.py`'s `qa_followup`).
"""

import frappe

from truth_of_bible.notifications import preferences
from truth_of_bible.notifications import reading


@frappe.whitelist(methods=["POST"])
def record_reading_activity(book: str | None = None, chapter=None, verse=None) -> dict:
	"""Fire-and-forget from the Flutter client right after it logs a Bible
	reading activity locally. Never returns an error the client needs to
	handle specially — reading must never be blocked by this call.
	"""
	try:
		reading.record_reading(frappe.session.user, book, chapter, verse)
		return {"ok": True}
	except Exception:
		frappe.log_error(title="record_reading_activity", message=frappe.get_traceback())
		return {"ok": False}


@frappe.whitelist(methods=["POST"])
def get_notification_preferences() -> dict:
	doc = preferences.get_or_create_preference(frappe.session.user)
	return preferences.as_dict(doc)


@frappe.whitelist(methods=["POST"])
def update_notification_preferences(
	bible_reading=None, spiritual_growth=None, bible_study=None, prayer=None,
	quiz=None, courses=None, community=None, shopping=None, account=None,
	announcements=None, marketing_opt_in=None, daily_reminder_time=None,
	quiet_hours_start=None, quiet_hours_end=None, max_daily_notifications=None,
	timezone=None, preferred_prayer_time=None, admin_new_user=None,
	admin_support=None, admin_orders=None, admin_moderation=None,
	admin_lms=None, admin_system=None, communication_center_push_opt_out=None,
	communication_center_email_opt_out=None, communication_center_whatsapp_opt_out=None,
) -> dict:
	values = {
		"bible_reading": bible_reading, "spiritual_growth": spiritual_growth,
		"bible_study": bible_study, "prayer": prayer, "quiz": quiz, "courses": courses,
		"community": community, "shopping": shopping, "account": account,
		"announcements": announcements, "marketing_opt_in": marketing_opt_in,
		"daily_reminder_time": daily_reminder_time, "quiet_hours_start": quiet_hours_start,
		"quiet_hours_end": quiet_hours_end, "max_daily_notifications": max_daily_notifications,
		"timezone": timezone, "preferred_prayer_time": preferred_prayer_time,
		"admin_new_user": admin_new_user, "admin_support": admin_support,
		"admin_orders": admin_orders, "admin_moderation": admin_moderation,
		"admin_lms": admin_lms, "admin_system": admin_system,
		"communication_center_push_opt_out": communication_center_push_opt_out,
		"communication_center_email_opt_out": communication_center_email_opt_out,
		"communication_center_whatsapp_opt_out": communication_center_whatsapp_opt_out,
	}
	values = {k: v for k, v in values.items() if v is not None}
	doc = preferences.update_preference(frappe.session.user, values)
	return preferences.as_dict(doc)


@frappe.whitelist(methods=["POST"])
def mark_notification_opened(name: str) -> dict:
	"""Marks one of the CALLER'S OWN Notification Log rows as read/opened —
	ownership is enforced here, not left to doctype permissions, since
	Notification Log's own REST permissions are broader (erpToken-scoped)
	than "only your own row" (see NOTIFICATION_ENGINE_PLAN.md Phase 38).
	"""
	owner = frappe.db.get_value("Notification Log", name, "for_user")
	if owner != frappe.session.user:
		frappe.throw("Not permitted", frappe.PermissionError)
	frappe.db.set_value("Notification Log", name, "read", 1)
	return {"ok": True}
