import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class TOBBlessingVerse(Document):
	def validate(self):
		self.kjv_text = (self.kjv_text or "").strip()
		# Approval certifies one exact text. Any edit to that text voids it, so
		# the automation can never post wording nobody has checked.
		if self.social_approved and not self.is_new() and self.has_value_changed("kjv_text"):
			self.social_approved = 0
			frappe.msgprint(_("KJV text changed, so social approval was cleared. Check the new text and approve again."))

		if self.social_approved and not self.kjv_text:
			frappe.throw(_("Add the KJV text before approving this verse for social posts."))

		if self.social_approved and (self.is_new() or self.has_value_changed("social_approved")):
			self.approved_by = frappe.session.user
			self.approved_on = now_datetime()
		elif not self.social_approved:
			self.approved_by = None
			self.approved_on = None
