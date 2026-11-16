"""The Website Popup fields were added to TOB Website Settings after the single already existed, so their
defaults never filled in: the app section showed as off and the delay as empty (the popup then appeared after
3 seconds). Fill them once, only where the delay was never set -- a sign the section was never configured."""

import frappe


def execute():
	doctype = "TOB Website Settings"
	if frappe.db.get_single_value(doctype, "popup_delay_seconds"):
		return
	frappe.db.set_single_value(doctype, "popup_delay_seconds", 12)
	frappe.db.set_single_value(doctype, "popup_show_app", 1)
	if not frappe.db.get_single_value(doctype, "popup_every_days"):
		frappe.db.set_single_value(doctype, "popup_every_days", 1)
	if not frappe.db.get_single_value(doctype, "popup_title"):
		frappe.db.set_single_value(doctype, "popup_title", "A blessing for you today")
