"""The one entry point every event source (doc_events, scheduler jobs, a
future webhook receiver) calls: `handle_event(event_code, user, variables)`.

Everything downstream of "an event happened" lives here: does a template
exist and is it enabled, does this user even want this category, are we
inside their quiet hours, have they already hit today's cap, have we
already sent this exact event today — only after all of that does it
render the template and hand off to `delivery.send_push` (this app's own,
fully independent FCM sender — see delivery.py's module docstring for why
it doesn't call the framework-patched `frappe.api.fcm_api.send_fcm`) and
record the send.

Deliberately NOT a generic data-driven rules engine — each check below is
a short, readable Python function, matching this codebase's existing
style (plain service functions, e.g. `games/bible_battle/*.py`) rather
than an interpreter for rule rows nobody but this file will ever read.
"""

import frappe
from frappe.utils import get_datetime, now_datetime, nowdate

from truth_of_bible.notifications import delivery, timeutils
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


def handle_event(event_code: str, user: str, variables: dict | None = None, force: bool = False) -> bool:
	"""Never raises — a bad template or a transient failure here must never
	break whatever save/scan/webhook triggered it. Returns True only if a
	notification was actually created and (attempted to be) pushed."""
	try:
		return _handle_event(event_code, user, variables or {}, force)
	except Exception:
		frappe.log_error(title=f"Notification engine: {event_code}", message=frappe.get_traceback())
		return False


def _handle_event(event_code: str, user: str, variables: dict, force: bool) -> bool:
	if not user or user in ("Guest", "Administrator"):
		return False

	template = frappe.db.get_value(
		"TOB Notification Template",
		event_code,
		["name", "audience", "enabled", "category", "priority", "title", "body", "deeplink_route", "deeplink_id_field"],
		as_dict=True,
	)
	if not template or not template.enabled:
		return False

	if template.audience == "User" and not _passes_user_checks(event_code, user, template, force):
		return False
	# Admin-audience resolution (role lookup, per-admin-category prefs) is
	# intentionally not implemented in this slice — see
	# NOTIFICATION_ENGINE_PLAN.md's sequencing. An Admin-audience template
	# with no resolver yet is simply not actionable, so it's skipped rather
	# than guessed at.
	if template.audience != "User":
		return False

	title = frappe.render_template(template.title or "", variables).strip()
	if not title:
		return False
	body = frappe.render_template(template.body or "", variables).strip() if template.body else ""

	route_id = variables.get(template.deeplink_id_field) if template.deeplink_id_field else None

	_write_notification_log(user, title, body)

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


def _passes_user_checks(event_code: str, user: str, template: dict, force: bool) -> bool:
	pref = get_or_create_preference(user)

	field = _CATEGORY_PREFERENCE_FIELD.get(template.category)
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
