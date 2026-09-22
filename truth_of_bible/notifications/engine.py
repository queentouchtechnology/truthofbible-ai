"""The one entry point every event source (doc_events, scheduler jobs, a
webhook receiver) calls: `handle_event(event_code, user, variables)`.

Everything downstream of "an event happened" lives here: does a template
exist and is it enabled, does this recipient even want this category, are
we inside their quiet hours, have they already hit today's cap, have we
already sent this exact event today — only after all of that does it
render the template and hand off to `delivery.send_push` (this app's own,
fully independent FCM sender — see delivery.py's module docstring for why
it doesn't call the framework-patched `frappe.api.fcm_api.send_fcm`) and
record the send.

Two audiences, one pipeline: `template.audience == "User"` sends to the
single `user` the caller passed in; `template.audience == "Admin"` fans
out internally to every admin (`admin_audience.admin_users()`) and applies
the same per-recipient checks to each — callers of an Admin-audience event
pass `user=None` (see `triggers.py`'s admin-event functions). Both paths
share the same preference-row shape (`TOB Notification Preference`, one
row per user) and the same quiet-hours/daily-cap/dedup logic — only the
category → preference-field map differs.

Deliberately NOT a generic data-driven rules engine — each check below is
a short, readable Python function, matching this codebase's existing
style (plain service functions, e.g. `games/bible_battle/*.py`) rather
than an interpreter for rule rows nobody but this file will ever read.
"""

import frappe
from frappe.utils import get_datetime, now_datetime, nowdate

from truth_of_bible.notifications import delivery, timeutils
from truth_of_bible.notifications.admin_audience import admin_users
from truth_of_bible.notifications.preferences import get_or_create_preference

_CATEGORY_PREFERENCE_FIELD = {
	"Bible Reading": "bible_reading",
	"Spiritual Growth": "spiritual_growth",
	"Bible Study": "bible_study",
	"Prayer": "prayer",
	"Quiz": "quiz",
	"Courses": "courses",
	"Community": "community",
	"Shopping": "shopping",
	"Account": "account",
	"Announcements": "announcements",
}

# Admin-audience categories → the admin-side preference toggle. A separate
# map (not merged with the one above) because "Orders" means something
# different for an admin (a new order came in) than for a user (my order
# shipped) — they'd share a category *label* in TOB Notification Template
# but must not share a preference field. "Moderation" (not "Community") is
# the admin-side category for community-report events, deliberately
# distinct from the User-audience "Community" category above.
_ADMIN_CATEGORY_PREFERENCE_FIELD = {
	"Users": "admin_new_user",
	"Support": "admin_support",
	"Orders": "admin_orders",
	# Shares the Orders toggle rather than getting its own preference field
	# — a failed payment is, for an admin, an order-desk concern, not a
	# separate thing to individually opt in/out of.
	"Payments": "admin_orders",
	"Moderation": "admin_moderation",
	"LMS": "admin_lms",
	"System": "admin_system",
}


def handle_event(event_code: str, user: str | None = None, variables: dict | None = None, force: bool = False) -> bool:
	"""Never raises — a bad template or a transient failure here must never
	break whatever save/scan/webhook triggered it. Returns True only if at
	least one notification was actually created and (attempted to be)
	pushed. `user` is required for a User-audience event and ignored (pass
	`None`) for an Admin-audience one, which resolves its own recipients."""
	try:
		return _handle_event(event_code, user, variables or {}, force)
	except Exception:
		frappe.log_error(title=f"Notification engine: {event_code}", message=frappe.get_traceback())
		return False


def _handle_event(event_code: str, user: str | None, variables: dict, force: bool) -> bool:
	template = frappe.db.get_value(
		"TOB Notification Template",
		event_code,
		["name", "audience", "enabled", "category", "priority", "title", "body", "deeplink_route", "deeplink_id_field"],
		as_dict=True,
	)
	if not template or not template.enabled:
		return False

	if template.audience == "User":
		if not user or user in ("Guest", "Administrator"):
			return False
		if not _passes_checks(event_code, user, template, force, _CATEGORY_PREFERENCE_FIELD):
			return False
		return _send_one(template, user, variables, event_code)

	if template.audience == "Admin":
		sent_any = False
		for admin in admin_users():
			if not _passes_checks(event_code, admin, template, force, _ADMIN_CATEGORY_PREFERENCE_FIELD):
				continue
			# One admin's send must never abort the rest of the fan-out — a
			# failure here (see _send_one's own try/except note) would
			# otherwise propagate out of this loop and silently skip every
			# admin after the one that failed.
			try:
				if _send_one(template, admin, variables, event_code):
					sent_any = True
			except Exception:
				frappe.log_error(
					title=f"Notification engine: admin fan-out ({event_code}, {admin})",
					message=frappe.get_traceback(),
				)
		return sent_any

	return False


def _send_one(template: dict, user: str, variables: dict, event_code: str) -> bool:
	title = frappe.render_template(template.title or "", variables).strip()
	if not title:
		return False
	body = frappe.render_template(template.body or "", variables).strip() if template.body else ""

	route_id = variables.get(template.deeplink_id_field) if template.deeplink_id_field else None

	# Writing the in-app Notification Log row can trigger OTHER doc_events/
	# Server Scripts on that core doctype that this app doesn't own or
	# control (e.g. a legacy, framework-patched "FCM on insert" Server
	# Script found live on 2026-09-22, independently calling
	# frappe.api.fcm_api.send_fcm — see this module's own docstring for why
	# that function isn't depended on here). A failure in someone else's
	# hook must never block the actual push below, which is this app's own,
	# independent, already-proven-working delivery path.
	try:
		_write_notification_log(user, title, body)
	except Exception:
		frappe.log_error(
			title=f"Notification engine: writing Notification Log failed ({event_code})",
			message=frappe.get_traceback(),
		)

	delivery.send_push(
		user=user,
		title=title,
		body=body,
		route=template.deeplink_route,
		ref_id=str(route_id) if route_id is not None else None,
		notif_type=event_code,
	)
	_record_send(user, event_code)
	return True


def _passes_checks(event_code: str, user: str, template: dict, force: bool, field_map: dict) -> bool:
	pref = get_or_create_preference(user)

	field = field_map.get(template.category)
	if field and not pref.get(field):
		return False

	if force:
		return True

	now_local = timeutils.local_now(pref.timezone)
	if timeutils.in_quiet_hours(now_local, pref.quiet_hours_start, pref.quiet_hours_end):
		return False

	if _sent_today_count(user) >= (pref.max_daily_notifications or 6):
		return False

	if _already_sent_today(user, event_code):
		return False

	return True


def _write_notification_log(user: str, title: str, body: str) -> None:
	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"subject": title,
			"email_content": body,
			"type": "Alert",
			"for_user": user,
		}
	).insert(ignore_permissions=True)


def _today_start():
	return get_datetime(nowdate())


def _sent_today_count(user: str) -> int:
	return frappe.db.count(
		"TOB Notification Send Log", {"user": user, "sent_at": [">=", _today_start()]}
	)


def _already_sent_today(user: str, event_code: str) -> bool:
	return bool(
		frappe.db.exists(
			"TOB Notification Send Log",
			{"user": user, "event_code": event_code, "sent_at": [">=", _today_start()]},
		)
	)


def _record_send(user: str, event_code: str) -> None:
	frappe.get_doc(
		{
			"doctype": "TOB Notification Send Log",
			"user": user,
			"event_code": event_code,
			"sent_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
