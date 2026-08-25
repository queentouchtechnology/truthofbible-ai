import frappe
from frappe import _
from frappe.model.document import Document


class TOBAIPrompt(Document):
	def validate(self):
		if not self.active:
			return
		# Two active rows for the same task are only a conflict if they'd
		# both resolve for the same call — i.e. same language (including
		# both blank, the default-prompt case).
		existing = frappe.db.get_value(
			"TOB AI Prompt",
			[["task", "=", self.task], ["active", "=", 1], ["name", "!=", self.name],
			 ["language", "=", self.language or ""]],
			"name",
		)
		if existing:
			scope = f"language '{self.language}'" if self.language else "the default (no language override)"
			frappe.throw(
				_("{0} is already the active prompt for task '{1}' at {2}.").format(existing, self.task, scope)
			)
