"""Who counts as "an admin" for Admin-audience notifications.

This app has no "System Manager"-gated admin concept — admin status is
purely these three Frappe roles, matching EXACTLY the check the Flutter
client itself uses to reveal the Admin Panel menu item (see
`lib/src/core/theme/global/main_drawer.dart`'s `hasAdminAccess`, and the
roles `erpUserSignupService.dart` actually grants a new admin account).
Confirmed live before use — there is no separate admin portal; admin
users log into the same app/account as everyone else, so they already go
through the same `User FCM Token` registration path.
"""

import frappe

ADMIN_ROLES = ("Batch Evaluator", "Moderator", "Course Creator")


def admin_users() -> list[str]:
	"""Every enabled User holding at least one admin role, de-duplicated —
	a user with more than one admin role must still be notified once."""
	rows = frappe.get_all(
		"Has Role",
		filters={"role": ["in", ADMIN_ROLES], "parenttype": "User"},
		pluck="parent",
	)
	users = list(dict.fromkeys(rows))
	if not users:
		return []
	enabled = set(frappe.get_all("User", filters={"name": ["in", users], "enabled": 1}, pluck="name"))
	return [u for u in users if u in enabled]
