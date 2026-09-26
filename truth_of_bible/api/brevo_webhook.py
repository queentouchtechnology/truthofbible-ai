"""Receives Brevo's transactional email delivery-event webhook, updating
the matching `TOB Communication Campaign Recipient.email_status`.

**Auth — a real, deliberate difference from every other webhook in this
codebase**: Brevo does not HMAC-sign its webhook payloads the way
WooCommerce/Discourse/Chatwoot do (see
COMMUNICATION_CENTER_API_CONTRACT.md SS4.2). Verified instead by a shared
token appended to the webhook URL as a query parameter when the webhook is
registered in Brevo's dashboard:
`.../api/method/truth_of_bible.api.brevo_webhook.receive?token=<brevo_webhook_secret>`
— checked by constant-time string comparison against `brevo_webhook_secret`
in site_config.json. If that key is missing, every delivery is rejected
(fails closed) — silently, since Brevo doesn't need (and doesn't
meaningfully act on) an error response here.
"""

import hmac
import json

import frappe

_EVENT_STATUS = {
	"request": "SENT",
	"delivered": "DELIVERED",
	"opened": "OPENED",
	"click": "CLICKED",
	"hardBounce": "BOUNCED",
	"softBounce": "BOUNCED",
	"blocked": "FAILED",
	"invalid": "FAILED",
	"error": "FAILED",
}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive():
	if not _verify_request():
		return {"status": "ok"}

	try:
		payload = json.loads(frappe.request.data or b"{}")
	except Exception:
		return {"status": "ok"}

	try:
		_handle_event(payload)
	except Exception:
		frappe.log_error(title="Communication Center: brevo_webhook", message=frappe.get_traceback())

	return {"status": "ok"}


def _verify_request() -> bool:
	secret = frappe.get_site_config().get("brevo_webhook_secret")
	if not secret:
		frappe.log_error(
			title="Communication Center: brevo_webhook_secret missing",
			message="site_config.json has no 'brevo_webhook_secret' key — every Brevo webhook delivery is being rejected until this is set.",
		)
		return False
	provided = frappe.form_dict.get("token") or frappe.get_request_header("X-Brevo-Webhook-Token") or ""
	if not hmac.compare_digest(provided, secret):
		# Unlike the other three webhooks, `receive()` above swallows a
		# failed verification into a plain {"status": "ok"} rather than
		# `frappe.throw` — so a mismatch was previously not just unlogged
		# but literally indistinguishable from success. Logged here for
		# the same reason as chatwoot_webhook.py's `_verify_request`.
		frappe.log_error(
			title="Communication Center: brevo_webhook token mismatch",
			message=f"Provided token present={bool(provided)}. Check brevo_webhook_secret in site_config.json matches the token set when this webhook was registered in Brevo.",
		)
		return False
	return True


def _handle_event(payload: dict) -> None:
	event = payload.get("event")
	message_id = payload.get("message-id") or payload.get("messageId")

	if event == "unsubscribed":
		_handle_unsubscribed(message_id)
		return

	status = _EVENT_STATUS.get(event)
	if not status or not message_id:
		return

	recipient_name = frappe.db.get_value(
		"TOB Communication Campaign Recipient", {"email_message_id": message_id}, "name"
	)
	if not recipient_name:
		return

	frappe.db.set_value("TOB Communication Campaign Recipient", recipient_name, "email_status", status)
	frappe.db.commit()


def _handle_unsubscribed(message_id) -> None:
	"""An unsubscribe must actually stop future sends, not just be logged
	(Decision 13) — flips this user's own communication_center_email_opt_out."""
	if not message_id:
		return
	recipient_name = frappe.db.get_value(
		"TOB Communication Campaign Recipient", {"email_message_id": message_id}, "name"
	)
	if not recipient_name:
		return
	user = frappe.db.get_value("TOB Communication Campaign Recipient", recipient_name, "user")
	if not user:
		return

	from truth_of_bible.notifications.preferences import update_preference

	update_preference(user, {"communication_center_email_opt_out": 1})
	frappe.db.commit()
