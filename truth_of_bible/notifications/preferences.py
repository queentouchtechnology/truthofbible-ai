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
