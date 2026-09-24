import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

# Everything that ends up in the published post.
POST_FIELDS = ("content_type", "title", "image_text", "image_footer", "caption", "how_to_find")


class TOBSocialContent(Document):
	def validate(self):
		for field in POST_FIELDS:
			self.set(field, (self.get(field) or "").strip())

		# Same rule as TOB Blessing Verse: approval certifies exact wording, so
		# editing approved wording voids it — unless approval is ticked in the
		# same save (that person has just checked the new wording).
		edited = not self.is_new() and any(self.has_value_changed(f) for f in POST_FIELDS)
		if self.social_approved and edited and not self.has_value_changed("social_approved"):
			self.social_approved = 0
			frappe.msgprint(_("Post wording changed, so social approval was cleared. Check it and approve again."))

		if self.social_approved and not (self.image_text and self.caption):
			frappe.throw(_("Add the image text and post text before approving."))

		if self.social_approved and (self.is_new() or self.has_value_changed("social_approved")):
			self.approved_by = frappe.session.user
			self.approved_on = now_datetime()
		elif not self.social_approved:
			self.approved_by = None
			self.approved_on = None
