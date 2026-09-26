"""Get-or-create access to a user's TOB Notification Preference, with
gentle, non-spammy, opt-out-by-default values (marketing is the one
opt-in-by-default-off field — see Phase 20) so a user who has never opened
a settings screen still behaves reasonably.
"""

import frappe

DEFAULTS = {
	"bible_reading": 1,
	"spiritual_growth": 1,
	"bible_study": 1,
	"prayer": 1,
	"encouragement": 1,
	"quiz": 1,
	"courses": 1,
	"community": 1,
	"shopping": 1,
	"account": 1,
	"announcements": 1,
	"marketing_opt_in": 0,
	"daily_reminder_time": "07:00:00",
	"quiet_hours_start": "21:00:00",
	"quiet_hours_end": "07:00:00",
	"max_daily_notifications": 6,
	"timezone": "Asia/Kolkata",
	"preferred_prayer_time": "12:00:00",
	# Admin-audience category toggles — only meaningful for a user holding
	# an admin role (admin_audience.ADMIN_ROLES), but harmless to default
	# on for everyone: a non-admin's row having these set to 1 has no
	# effect, since engine.py only ever fans an Admin-audience event out to
	# admin_users() in the first place.
	"admin_new_user": 1,
	"admin_support": 1,
	"admin_orders": 1,
	"admin_moderation": 1,
	"admin_lms": 1,
	"admin_system": 1,
	# Communication Center (Decision 13/15) — deliberately separate from the
	# per-category toggles above; see COMMUNICATION_CENTER_API_CONTRACT.md
	# SS5. Opt-out semantics, so 0 (not opted out) is the gentle default.
	"communication_center_push_opt_out": 0,
	"communication_center_email_opt_out": 0,
	"communication_center_whatsapp_opt_out": 0,
}

EDITABLE_FIELDS = set(DEFAULTS.keys())


def get_or_create_preference(user: str):
	name = frappe.db.exists("TOB Notification Preference", {"user": user})
	if name:
		return frappe.get_doc("TOB Notification Preference", name)
	doc = frappe.get_doc({"doctype": "TOB Notification Preference", "user": user, **DEFAULTS})
	doc.insert(ignore_permissions=True)
	return doc


def update_preference(user: str, values: dict):
	doc = get_or_create_preference(user)
	for key, value in values.items():
		if key in EDITABLE_FIELDS:
			doc.set(key, value)
	doc.save(ignore_permissions=True)
	return doc


def as_dict(doc) -> dict:
	return {field: doc.get(field) for field in DEFAULTS}
