"""Receives Discourse's `notification` and `flag_created` webhooks
(community.truthofbible.org) and turns them into User-audience Community
notifications (a reply to your post, being mentioned) and an Admin-
audience moderation alert (a post was flagged) — the latter is
NOTIFICATION_ENGINE_PLAN.md "What's still open" item 2, added once the
`notification` receiver below was already live and proven (same HMAC
verification, same webhook secret, same "log unmapped, never guess"
caution — `flag_created`'s payload shape is exactly as unverified as
`notification`'s `notification_type` values were before those were
confirmed live).

**UNVERIFIED — needs a live test delivery before this can be trusted.**
Unlike `shop_webhook.py`'s WooCommerce receiver (whose payload shape is
long-stable and well-documented), this one depends on two things that
can't be confirmed without either checking this instance's live Discourse
admin panel or a real test delivery: (1) that the "Notification Event"
webhook group is even available/enabled for this Discourse version, and
(2) the exact integer `notification_type` values this instance uses for
"replied" and "mentioned". The values below (2 and 1 respectively) are
Discourse's oldest, most stable core notification types — very unlikely
to have changed — but "very unlikely" is not "confirmed", so every
notification_type this receiver doesn't recognize gets logged
(`_log_unmapped_notification`) rather than silently dropped: check
Frappe's Error Log after the webhook is registered and a real reply/
mention happens, and correct `_NOTIFICATION_TYPE_EVENTS` below if needed.

**Not yet connected** — same status as `shop_webhook.py`: this endpoint
exists and works, but nothing on the Discourse side currently calls it.
Registering the webhook (Discourse Admin → API → Webhooks, with the
"Notification Event" checkbox, or programmatically via
`POST /admin/api/web_hooks.json`) is a deliberate, separate step.

**Verification**: `allow_guest=True` (Discourse has no Frappe session) —
`X-Discourse-Event-Signature` (format `sha256=<hex hmac>` of the raw
request body, keyed with `discourse_webhook_secret` from
`frappe.get_site_config()`) is the only thing standing between this
endpoint and anyone on the internet POSTing forged notification data. No
site_config key means every delivery is rejected (fails closed).

**User identity**: the Flutter client creates each user's Discourse
account with the SAME username as their Frappe user, auto-created on
first opening Community if one doesn't already exist (confirmed by a
full repo audit — see `community.dart`'s `getCommunityProfile`/
`createCommunityProfile` flow — before writing this file). This receiver
maps a notification's `username` back to a Frappe User the same way:
`frappe.db.get_value("User", {"username": username}, "name")`.
"""

import hashlib
import hmac
import json

import frappe

from truth_of_bible.notifications.engine import handle_event

# Same integer values the in-app "My Activity" list already trusts and
# renders correctly today (`CommunityNotification.verb`/`_icon` in the
# Flutter app, `community_extras_models.dart`/`community_notifications_
# screen.dart`) — that list is populated by Discourse's own
# `/notifications.json`, using these exact type numbers, so they're
# considerably better-confirmed for THIS instance than the two originally
# shipped here (which were Discourse's stable defaults, not instance-
# verified). 5/15 both mean "liked" (15 = several posts liked at once,
# consolidated); 12 is "granted_badge".
_NOTIFICATION_TYPE_EVENTS = {
	2: "COMMUNITY_REPLY",  # "replied"
	1: "COMMUNITY_MENTION",  # "mentioned"
	5: "COMMUNITY_LIKE",  # "liked"
	15: "COMMUNITY_LIKE",  # "liked_consolidated" (several at once)
	12: "COMMUNITY_BADGE",  # "granted_badge"
}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def notification_created():
	if not _verify_signature():
		frappe.throw("Invalid signature", frappe.PermissionError)

	try:
		payload = json.loads(frappe.request.data or b"{}")
	except Exception:
		frappe.throw("Invalid payload", frappe.ValidationError)

	_handle_notification(payload.get("notification") or {})
	return {"ok": True}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def flag_created():
	"""**More uncertain than `notification_created` above** — Discourse's
	standard webhook groups are documented for "Post"/"Topic"/"Notification"
	events; whether a distinct "flag" event group/payload exists on this
	Discourse version (vs. flags only surfacing as a `post` event with
	`hidden`/`flag_count` changed, or needing a plugin) is genuinely
	unconfirmed — the plan doc flags this explicitly rather than guessing
	further. The full raw payload is always logged (not just on an
	unrecognized shape, unlike `notification_created`) so the real shape
	Discourse actually sends can be read from Error Log after this webhook
	is registered, and this parser corrected to match if needed."""
	if not _verify_signature():
		frappe.throw("Invalid signature", frappe.PermissionError)

	try:
		payload = json.loads(frappe.request.data or b"{}")
	except Exception:
		frappe.throw("Invalid payload", frappe.ValidationError)

	frappe.log_error(
		title="Notification engine: flag_created payload (shape discovery)",
		message=f"Raw payload: {payload}",
	)
	_handle_flag(payload)
	return {"ok": True}


def _handle_flag(payload: dict) -> None:
	post = payload.get("post") or payload
	post_id = post.get("id")
	topic_title = post.get("topic_title") or post.get("topic_slug") or ""
	if not post_id:
		return
	handle_event("COMMUNITY_REPORT", None, {"post_id": post_id, "topic_title": topic_title})


def _handle_notification(notification: dict) -> None:
	notif_type = notification.get("notification_type")
	username = (notification.get("username") or "").strip()
	if not notif_type or not username:
		return

	event = _NOTIFICATION_TYPE_EVENTS.get(notif_type)
	if not event:
		_log_unmapped_notification(notif_type, notification)
		return

	user = frappe.db.get_value("User", {"username": username}, "name")
	if not user:
		return

	data = _parse_data(notification.get("data"))
	# A badge notification carries no `topic_title` at all — its own
	# payload shape is `badge_name`/`badge_title` instead (same field the
	# in-app list already falls back to — see `CommunityNotification.
	# fromJson`'s `data['badge_name']`).
	if event == "COMMUNITY_BADGE":
		variables = {"badge_name": data.get("badge_title") or data.get("badge_name", "")}
	else:
		variables = {"topic_title": data.get("topic_title", "")}
	handle_event(event, user, variables)


def _parse_data(raw) -> dict:
	if isinstance(raw, dict):
		return raw
	try:
		return json.loads(raw or "{}")
	except Exception:
		return {}


def _log_unmapped_notification(notif_type, notification) -> None:
	frappe.log_error(
		title=f"Notification engine: unmapped Discourse notification_type {notif_type}",
		message=(
			f"Raw payload: {notification}\n\n"
			"If this is actually 'replied' or 'mentioned', update "
			"_NOTIFICATION_TYPE_EVENTS in community_webhook.py."
		),
	)


def _verify_signature() -> bool:
	secret = frappe.get_site_config().get("discourse_webhook_secret")
	if not secret:
		frappe.log_error(
			title="Notification engine: discourse_webhook_secret missing",
			message="site_config.json has no 'discourse_webhook_secret' key — every Discourse webhook delivery is being rejected until this is set.",
		)
		return False

	signature = frappe.get_request_header("X-Discourse-Event-Signature") or ""
	body = frappe.request.data or b""
	computed = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
	return hmac.compare_digest(signature, computed)
