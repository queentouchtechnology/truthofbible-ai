"""Replaces the first newsletter series (a 9-issue "7 daily activities" course, issue 1 listing every topic)
with one standalone message per topic (newsletter_issues.ISSUES), and renames the template's "Try this week"
box to "Your step today" for the daily schedule. Only while nothing has been sent yet, so desk edits made
after the newsletter went live are never overwritten."""

import frappe

from truth_of_bible.communication import newsletter
from truth_of_bible.communication.newsletter_issues import ISSUES

_ISSUE = "TOB Newsletter Issue"


def execute():
	if not frappe.db.table_exists(_ISSUE):
		return
	if frappe.db.count(_ISSUE, {"times_sent": [">", 0]}):
		return
	frappe.db.delete(_ISSUE)
	for no, data in enumerate(ISSUES, start=1):
		frappe.get_doc({"doctype": _ISSUE, "issue_no": no, "enabled": 1, **data}).insert(ignore_permissions=True)
	frappe.db.set_single_value("TOB Newsletter Settings", "last_issue_no", 0)

	if frappe.db.exists("Email Template", newsletter.TEMPLATE):
		html = frappe.db.get_value("Email Template", newsletter.TEMPLATE, "response_html") or ""
		if "Try this week" in html:
			frappe.db.set_value("Email Template", newsletter.TEMPLATE, "response_html", html.replace("Try this week", "Your step today"))
