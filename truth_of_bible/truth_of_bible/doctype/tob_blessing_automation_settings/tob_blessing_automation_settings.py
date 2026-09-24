import frappe
from frappe import _
from frappe.model.document import Document

# Column names on TOB Automation Schedule; index = Python's date.weekday() (Monday = 0).
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class TOBBlessingAutomationSettings(Document):
	def validate(self):
		if self.post_to_instagram and not self.post_to_facebook:
			frappe.throw(_("Instagram posts reuse the image hosted by the Facebook post, so turn Facebook on too."))
		if (self.preview_minutes_before or 0) < 0:
			frappe.throw(_("Preview minutes can't be negative."))
		self.slack_channel_id = (self.slack_channel_id or "").strip()
		if self.enabled and self.preview_channel == "Slack" and not self.slack_channel_id:
			frappe.throw(_("Set the Slack Channel ID, or change 'Send Previews To' to None."))

		seen = set()
		for row in self.content_schedules or []:
			if row.content_type in seen:
				frappe.throw(_("{0} has more than one schedule row; keep one.").format(row.content_type))
			seen.add(row.content_type)
			if row.enabled and not any(row.get(d) for d in WEEKDAYS):
				frappe.throw(_("Tick at least one weekday for {0}, or turn it off.").format(row.content_type))
