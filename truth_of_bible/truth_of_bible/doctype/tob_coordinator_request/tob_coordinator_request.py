import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

# What the old app-side coordinator signup granted immediately.
COORDINATOR_ROLES = ("Batch Evaluator", "Moderator", "Course Creator")


class TOBCoordinatorRequest(Document):
	def validate(self):
		before = self.get_doc_before_save()
		was = before.status if before else "Pending"
		if was != "Pending" and self.status != was:
			frappe.throw(_("This request was already {0}").format(was))

	def on_update(self):
		before = self.get_doc_before_save()
		if self.status == "Pending" or (before and before.status == self.status):
			return
		self.db_set({"reviewed_by": frappe.session.user, "reviewed_on": now_datetime()})
		if self.status == "Approved":
			self._grant()

	def _grant(self):
		user = frappe.get_doc("User", self.user)
		have = {r.role for r in user.roles}
		for role in COORDINATOR_ROLES:
			if role not in have:
				user.append("roles", {"role": role})
		if user.user_type != "System User":
			user.user_type = "System User"
		user.save(ignore_permissions=True)

		if self.company_name:
			if not frappe.db.exists("Company", self.company_name):
				frappe.get_doc(
					{
						"doctype": "Company",
						"company_name": self.company_name,
						"abbr": (self.company_abbr or self.company_name[:5]).upper(),
						"default_currency": "INR",
						"country": "India",
					}
				).insert(ignore_permissions=True)
			if not frappe.db.exists(
				"User Permission", {"user": self.user, "allow": "Company", "for_value": self.company_name}
			):
				frappe.get_doc(
					{"doctype": "User Permission", "user": self.user, "allow": "Company", "for_value": self.company_name}
				).insert(ignore_permissions=True)
