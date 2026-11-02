"""Send Every was added to TOB Newsletter Settings after the single already existed, so its Daily default never
filled in and the desk showed it blank."""

import frappe


def execute():
	if not frappe.db.get_single_value("TOB Newsletter Settings", "frequency"):
		frappe.db.set_single_value("TOB Newsletter Settings", "frequency", "Daily")
