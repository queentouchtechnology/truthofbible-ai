import frappe
from frappe import _
from frappe.model.document import Document


class TOBAIPrompt(Document):
	def validate(self):
		if not self.active:
			return
		# Two active rows for the same task are only a conflict if they'd
		# both resolve for the same call — i.e. same language_override
		# (including both blank, the default-prompt case). SQL NULL never
		# equals '' or NULL via "=", so the blank case needs "is not set".
		filters = [["task", "=", self.task], ["active", "=", 1], ["name", "!=", self.name]]
		if self.language_override:
			filters.append(["language_override", "=", self.language_override])
		else:
			filters.append(["language_override", "is", "not set"])
		existing = frappe.db.get_value("TOB AI Prompt", filters, "name")
		if existing:
			scope = (
				f"language_override '{self.language_override}'"
				if self.language_override
				else "the default (no language override)"
			)
			frappe.throw(
				_("{0} is already the active prompt for task '{1}' at {2}.").format(existing, self.task, scope)
			)
