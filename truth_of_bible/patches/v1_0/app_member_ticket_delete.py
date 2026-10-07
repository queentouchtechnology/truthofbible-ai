"""Members can delete their OWN support tickets from the app (the Help Desk
screen has a delete action). app_member_permissions gave read/write/create
on own Issues but not delete, so the app got "User not allowed to delete
Issue". Same scope: LMS Student, if_owner."""

import frappe
from frappe.permissions import add_permission, update_permission_property


def execute():
	if not frappe.db.exists("Role", "LMS Student"):
		return
	add_permission("Issue", "LMS Student", 0)
	update_permission_property("Issue", "LMS Student", 0, "delete", 1)
	update_permission_property("Issue", "LMS Student", 0, "if_owner", 1)
	frappe.clear_cache(doctype="Issue")
