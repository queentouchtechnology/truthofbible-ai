import frappe

from frappe.utils import cint

from truth_of_bible.notifications import delivery
from truth_of_bible.notifications.engine import _write_notification_log


@frappe.whitelist()
def send_test_route(event_code: str, user: str | None = None, id: str | None = None, log: int = 1):
	"""Admin-only routing test: pushes one notification template to one user
	with its real route and id, skipping preferences, quiet hours, caps and
	dedup. Used to verify cold-start / background tap routing per type.

	Like a real send it also writes the in-app Notification Log row (unread),
	so the app's bell badge, "New Updates" count and Live Updates move too.
	Pass log=0 for a push only.
	"""
	frappe.only_for("System Manager")

	template = frappe.get_doc("TOB Notification Template", event_code)
	target = user or frappe.session.user
	ref_id = (id or "").strip() or None

	variables = {}
	if template.deeplink_id_field:
		variables[template.deeplink_id_field] = ref_id or "test"

	title = frappe.render_template(template.title or event_code, variables).strip() or event_code
	body = frappe.render_template(template.body or "", variables).strip() if template.body else ""

	if cint(log):
		_write_notification_log(target, title, body, template.deeplink_route, variables.get(template.deeplink_id_field) if template.deeplink_id_field else None)

	sent = delivery.send_push(
		user=target,
		title=title,
		body=body,
		route=template.deeplink_route,
		ref_id=variables.get(template.deeplink_id_field) if template.deeplink_id_field else None,
		notif_type=event_code,
	)
	return {
		"sent": sent,
		"logged": bool(cint(log)),
		"user": target,
		"title": title,
		"route": template.deeplink_route,
		"id": variables.get(template.deeplink_id_field) if template.deeplink_id_field else None,
	}
