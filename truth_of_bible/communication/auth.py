"""Shared admin-authorization check for every Communication Center
whitelisted method (Decision 12 — reuse existing admin authorization,
never trust client-side UI visibility as the real boundary).

Deliberately checks `System Manager`, matching the exact role every other
admin-managed doctype in this app already restricts itself to (see e.g.
TOB Notification Template's own `permissions` list) — NOT the separate
`admin_audience.ADMIN_ROLES` set (Batch Evaluator / Moderator / Course
Creator), which decides who *receives* an Admin-audience push, an
unrelated concept from who may *manage* the Communication Center itself.
"""

import frappe
from frappe import _


def require_admin() -> None:
	if "System Manager" not in frappe.get_roles(frappe.session.user):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
