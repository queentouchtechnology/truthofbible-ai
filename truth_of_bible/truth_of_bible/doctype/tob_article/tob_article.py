import re

import frappe
from frappe import _
from frappe.model.document import Document

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class TOBArticle(Document):
	def validate(self):
		self.slug = (self.slug or "").strip().lower()
		if not SLUG.match(self.slug):
			frappe.throw(_("Slug: use lowercase letters, numbers and single hyphens, e.g. hope-that-holds."))
		before = self.get_doc_before_save()
		if before and before.status == "Published" and before.slug != self.slug:
			frappe.throw(_("The slug can't change after publishing — the address is already live."))
		self.words = len(re.sub(r"<[^>]+>", " ", self.html or "").split())
