"""Festival themes go live for everyone (asked 2026-11-17): TOB Website Settings → Festival Themes = Everyone.
Runs once; after this the switch is changed only in the desk."""

import frappe


def execute():
	frappe.db.set_single_value("TOB Website Settings", "festival_themes", "Everyone")
	frappe.clear_document_cache("TOB Website Settings", "TOB Website Settings")
