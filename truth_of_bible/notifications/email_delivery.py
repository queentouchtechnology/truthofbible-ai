"""Email delivery for the truth_of_bible notification engine — an opt-in
second channel alongside the push each event already sends.

Every event's title/body is already rendered once in engine.py; this module
wraps that same rendered content in one shared, Frappe-editable shell (the
"TOB Notification Email" Email Template, seeded by install.seed_
notification_email_template — same pattern api/app_auth.py's OTP email
already uses) rather than needing a bespoke Email Template per event. An
admin opts an event in with its "Send Email" switch (TOB Notification
Template.send_email, editable from the app's Notification Templates
screen); nothing in this module decides which events matter.
"""

import urllib.parse

import frappe

_WRAPPER_TEMPLATE = "TOB Notification Email"

# Mirrors the Flutter app's `appOpenLinkBase`
# (lib/src/config/route_id_sources.dart) — the admin Communication Center's
# campaign composer builds this exact same link by hand for its own "Insert
# app link" button. Keep both in sync if this ever changes.
#
# NOT `/app/...` — that prefix is Frappe's own reserved Desk route, so a
# guest tap used to 301 to `/login?redirect-to=%2Fapp%2Fopen` instead of
# ever reaching the app (confirmed live 2026-10-08).
_APP_OPEN_LINK_BASE = "https://learn.truthofbible.org/open"


def send_notification_email(user: str, title: str, body: str, route: str | None, route_id, event_code: str) -> None:
	"""Never raises — called from engine.py's `_send_one` right after the
	push, and a broken email must never be mistaken for a broken
	notification (the push/in-app log already happened by this point)."""
	try:
		_send(user, title, body, route, route_id)
	except Exception:
		frappe.log_error(
			title=f"Notification engine: email failed ({event_code})",
			message=frappe.get_traceback(),
		)


def _send(user: str, title: str, body: str, route: str | None, route_id) -> None:
	# `user` is this codebase's User.name, which is the email address itself
	# (see app_auth.py's own note on this) — falls back to a lookup rather
	# than assuming it, same defensive style as the rest of notifications/*.
	recipient = frappe.db.get_value("User", user, "email") or user
	if not recipient or "@" not in recipient:
		return

	context = {
		"title": title,
		"body": body,
		"cta_url": _app_link(route, route_id) if route else None,
		"cta_label": "Open in App",
	}
	try:
		wrapper = frappe.get_cached_doc("Email Template", _WRAPPER_TEMPLATE)
		subject = frappe.render_template(wrapper.subject, context) or title
		message = frappe.render_template(wrapper.response, context)
	except frappe.DoesNotExistError:
		subject, message = title, body

	frappe.sendmail(recipients=[recipient], subject=subject, message=message)


def _app_link(route: str, route_id) -> str:
	params = {"route": route}
	if route_id is not None:
		params["id"] = str(route_id)
	return f"{_APP_OPEN_LINK_BASE}?{urllib.parse.urlencode(params)}"
