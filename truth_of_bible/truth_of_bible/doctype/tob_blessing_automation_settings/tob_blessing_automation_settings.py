import frappe
from frappe import _
from frappe.model.document import Document


class TOBBlessingAutomationSettings(Document):
	def validate(self):
		if self.post_to_instagram and not self.post_to_facebook:
			frappe.throw(_("Instagram posts reuse the image hosted by the Facebook post, so turn Facebook on too."))
		if (self.preview_minutes_before or 0) < 0:
			frappe.throw(_("Preview minutes can't be negative."))
		self.slack_channel_id = (self.slack_channel_id or "").strip()
		if self.enabled and self.preview_channel == "Slack" and not self.slack_channel_id:
			frappe.throw(_("Set the Slack Channel ID, or change 'Send Previews To' to None."))
