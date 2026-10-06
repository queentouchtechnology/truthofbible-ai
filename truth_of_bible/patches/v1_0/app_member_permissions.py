"""Per-user API keys (api/app_auth.py) replace the Administrator key the app
used to ship. Requests now run with the member's own roles, so grant exactly
what the member screens read — nothing broader.

- LMS Course / Course Chapter / Course Lesson: members read courses; guests
  only the course catalog.
- Issue: members read/write/create THEIR OWN tickets (if_owner).
- Issue Type / Issue Priority: lookup lists, readable by everyone signed in.
- Website Slideshow: dashboard banners, public.
- Comment: members create blog comments/replies/likes themselves (this
  used to need the Blogger role, which members no longer get).

Old tickets were created as Administrator (shared key), so their owner is
set to the member who raised them — otherwise if_owner hides their history.
"""

import frappe
from frappe.permissions import add_permission, update_permission_property

# Every app member has LMS Student (the Customer portal role is no longer
# given or relied on).
MEMBER_ROLES = ("LMS Student",)

# App members who got Blogger from the old signup (it also made them System
# Users with desk access). Staff Bloggers are left alone.
MEMBERS_WITH_BLOGGER = (
	"allannkandu87@gmail.com",
	"andondelfia@gmail.com",
	"bieony24@gmail.com",
	"danielahiable673@gmail.com",
)


def _grant(doctype, role, ptypes=("read",), if_owner=False):
	if not frappe.db.exists("DocType", doctype) or not frappe.db.exists("Role", role):
		return
	add_permission(doctype, role, 0)  # copies standard perms to Custom DocPerm first
	for ptype in ptypes:
		update_permission_property(doctype, role, 0, ptype, 1)
	if if_owner:
		update_permission_property(doctype, role, 0, "if_owner", 1)


def execute():
	for role in MEMBER_ROLES:
		for doctype in ("LMS Course", "Course Chapter", "Course Lesson"):
			_grant(doctype, role)
		_grant("Issue", role, ("read", "write", "create"), if_owner=True)
	_grant("LMS Course", "Guest")
	for doctype in ("Issue Type", "Issue Priority"):
		_grant(doctype, "All")
	for role in ("All", "Guest"):
		_grant("Website Slideshow", role)
	for role in MEMBER_ROLES:
		_grant("Comment", role, ("read", "write", "create"))

	# Members who only ever got Customer: give them LMS Student so they keep
	# their tickets/courses now that permissions hang off LMS Student.
	customer_only = frappe.db.sql_list(
		"""
		SELECT DISTINCT c.parent FROM `tabHas Role` c
		JOIN `tabUser` u ON u.name = c.parent AND u.enabled = 1
		WHERE c.role = 'Customer' AND c.parenttype = 'User'
		  AND c.parent NOT IN ('Administrator', 'Guest')
		  AND NOT EXISTS (SELECT 1 FROM `tabHas Role` s
		      WHERE s.parent = c.parent AND s.parenttype = 'User' AND s.role = 'LMS Student')
		"""
	)
	for user in customer_only:
		frappe.get_doc("User", user).add_roles("LMS Student")

	for user in MEMBERS_WITH_BLOGGER:
		if frappe.db.exists("User", user) and "Blogger" in frappe.get_roles(user):
			# Saves the user; user_type drops back to Website User when no
			# desk role is left.
			frappe.get_doc("User", user).remove_roles("Blogger")

	# Give members their existing tickets back (created as Administrator).
	frappe.db.sql(
		"""
		UPDATE `tabIssue` i JOIN `tabUser` u ON u.name = i.raised_by
		SET i.owner = u.name
		WHERE i.owner = 'Administrator' AND i.raised_by IS NOT NULL AND i.raised_by != ''
		"""
	)
	frappe.clear_cache()
