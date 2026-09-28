"""Admin-facing user search for the Flutter Users screen.

Plain `/api/resource/User` REST filters can express a name search and a
plain field equality, but not "holds this role" (Has Role is a separate
child table) or "has no push token registered" (an anti-join against
`User FCM Token`) — so this gets one dedicated whitelisted method rather
than forcing those through the generic list API like the rest of
admin/users/ does.
"""

import frappe

from truth_of_bible.communication.auth import require_admin

_SORT_FIELDS = {"creation", "full_name", "modified", "last_active"}


def _bool_flag(value):
	"""None (param omitted) = no filter; 'true'/'1' = require; 'false'/'0' =
	exclude. Mirrors how every other optional bool query param in this app
	is read off `frappe.form_dict`, which always hands strings."""
	s = str(value).lower()
	if s in ("true", "1"):
		return True
	if s in ("false", "0"):
		return False
	return None


@frappe.whitelist(methods=["GET"])
def search_users(
	query=None, status=None, role=None, has_mobile=None, has_fcm_token=None,
	sort_field="creation", sort_dir="desc", limit_start=0, limit_page_length=20,
):
	require_admin()
	limit_start = int(limit_start or 0)
	limit_page_length = int(limit_page_length or 20)
	sort_field = sort_field if sort_field in _SORT_FIELDS else "creation"
	sort_dir = "asc" if str(sort_dir).lower() == "asc" else "desc"

	# Excludes Frappe's two synthetic system accounts, matching
	# UsersRepositoryImpl._scoped()'s own reasoning: never real users an
	# admin manages here.
	conditions = ["u.name not in ('Administrator', 'Guest')"]
	values = {}

	if query:
		conditions.append("(u.full_name like %(query)s or u.name like %(query)s)")
		values["query"] = f"%{query}%"

	if status == "active":
		conditions.append("u.enabled = 1")
	elif status == "disabled":
		conditions.append("u.enabled = 0")

	if role:
		conditions.append(
			"exists (select 1 from `tabHas Role` hr where hr.parent = u.name "
			"and hr.parenttype = 'User' and hr.role = %(role)s)"
		)
		values["role"] = role

	has_mobile = _bool_flag(has_mobile)
	if has_mobile is False:
		conditions.append("(u.mobile_no is null or u.mobile_no = '')")
	elif has_mobile is True:
		conditions.append("(u.mobile_no is not null and u.mobile_no != '')")

	has_fcm_token = _bool_flag(has_fcm_token)
	if has_fcm_token is False:
		conditions.append("not exists (select 1 from `tabUser FCM Token` ft where ft.user = u.name)")
	elif has_fcm_token is True:
		conditions.append("exists (select 1 from `tabUser FCM Token` ft where ft.user = u.name)")

	where = " and ".join(conditions)
	return frappe.db.sql(
		f"""select u.name, u.full_name, u.email, u.mobile_no, u.enabled, u.user_type, u.user_image
		from `tabUser` u
		where {where}
		order by u.{sort_field} {sort_dir}
		limit %(limit_page_length)s offset %(limit_start)s""",
		{**values, "limit_page_length": limit_page_length, "limit_start": limit_start},
		as_dict=True,
	)
