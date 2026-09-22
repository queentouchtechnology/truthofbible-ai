"""Receives Chatwoot's outbound webhook (Settings -> Integrations ->
Webhooks on the Chatwoot side) for `message_created` and
`conversation_status_changed` events, keeping the local TOB WhatsApp
Conversation/Message mirror in sync and notifying admins of new inbound
messages via the existing notification engine (Decision 4/5 — reused, not
duplicated).

**Auth — UNVERIFIED against this specific instance, same honest-assumption
precedent as `community_webhook.py`'s own docstring.** Unlike WooCommerce/
Discourse, Chatwoot's plain "Webhooks" integration does not compute an
HMAC signature over its payload in most self-hosted versions — there is no
standard signature header to verify. The practical, commonly-used
workaround (and what this implementation uses) is a shared secret appended
to the webhook URL itself as a query parameter when the webhook is
registered in Chatwoot:
`.../api/method/truth_of_bible.api.chatwoot_webhook.receive?secret=<chatwoot_webhook_secret>`
— checked below by constant-time string comparison against
`chatwoot_webhook_secret` in site_config.json. **Before registering the
real webhook**, check this Chatwoot instance's Settings -> Integrations
page for a genuine HMAC option; if one exists, switch `_verify_request` to
the same `hmac.compare_digest` pattern already used in
`shop_webhook.py`/`community_webhook.py` and update
COMMUNICATION_CENTER_API_CONTRACT.md's open item #1 accordingly. No
site_config key means every delivery is rejected (fails closed).

**Idempotency**: every insert here is guarded by `chatwoot_message_id`
existence, since Chatwoot — like most webhook senders — does not
guarantee exactly-once delivery.
"""

import hmac
import json

import frappe
from frappe.utils import now_datetime

from truth_of_bible.notifications.engine import handle_event

_STATUS_VALUES = ("OPEN", "PENDING", "RESOLVED")
_CONTENT_TYPE_MAP = {
	"text": "TEXT",
	None: "TEXT",
	"input_select": "TEXT",
	"image": "IMAGE",
	"file": "DOCUMENT",
	"audio": "AUDIO",
	"video": "VIDEO",
}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive():
	if not _verify_request():
		frappe.throw("Invalid signature", frappe.PermissionError)

	try:
		payload = json.loads(frappe.request.data or b"{}")
	except Exception:
		frappe.throw("Invalid payload", frappe.ValidationError)

	event = payload.get("event")
	try:
		if event == "message_created":
			_handle_message_created(payload)
		elif event == "conversation_status_changed":
			_handle_status_changed(payload)
	except Exception:
		frappe.log_error(
			title=f"Communication Center: chatwoot_webhook ({event})", message=frappe.get_traceback()
		)
	return {"status": "ok"}


def _verify_request() -> bool:
	secret = frappe.get_site_config().get("chatwoot_webhook_secret")
	if not secret:
		frappe.log_error(
			title="Communication Center: chatwoot_webhook_secret missing",
			message="site_config.json has no 'chatwoot_webhook_secret' key — every Chatwoot webhook delivery is being rejected until this is set.",
		)
		return False
	provided = frappe.form_dict.get("secret") or frappe.get_request_header("X-Chatwoot-Webhook-Secret") or ""
	return hmac.compare_digest(provided, secret)


def _handle_message_created(payload: dict) -> None:
	# Chatwoot's message_type on the base webhook payload: 0 = incoming
	# (from the WhatsApp contact), 1 = outgoing (an agent/bot reply) — only
	# the former needs mirroring here; outbound sends are already recorded
	# by whatsapp.send_message/campaign.py at the moment they're made.
	message_type = payload.get("message_type")
	if message_type not in (0, "incoming"):
		return

	conversation = payload.get("conversation") or {}
	chatwoot_conversation_id = str(conversation.get("id") or payload.get("conversation_id") or "").strip()
	chatwoot_message_id = str(payload.get("id") or "").strip()
	if not chatwoot_conversation_id or not chatwoot_message_id:
		return

	if frappe.db.exists("TOB WhatsApp Message", {"chatwoot_message_id": chatwoot_message_id}):
		return  # already mirrored — a webhook replay

	sender = payload.get("sender") or {}
	phone = (sender.get("phone_number") or "").strip()
	contact_name = sender.get("name") or phone

	convo_name = frappe.db.get_value(
		"TOB WhatsApp Conversation", {"chatwoot_conversation_id": chatwoot_conversation_id}, "name"
	)
	if not convo_name:
		user = frappe.db.get_value("User", {"mobile_no": phone}, "name") if phone else None
		convo = frappe.get_doc(
			{
				"doctype": "TOB WhatsApp Conversation",
				"user": user,
				"chatwoot_conversation_id": chatwoot_conversation_id,
				"phone": phone,
				"status": "OPEN",
			}
		)
		convo.insert(ignore_permissions=True)
		convo_name = convo.name

	content = payload.get("content") or ""
	frappe.get_doc(
		{
			"doctype": "TOB WhatsApp Message",
			"conversation": convo_name,
			"chatwoot_message_id": chatwoot_message_id,
			"direction": "INBOUND",
			"message_type": _CONTENT_TYPE_MAP.get(payload.get("content_type"), "UNSUPPORTED"),
			"message": content,
			"status": "DELIVERED",
		}
	).insert(ignore_permissions=True)

	current_unread = frappe.db.get_value("TOB WhatsApp Conversation", convo_name, "unread_count") or 0
	frappe.db.set_value(
		"TOB WhatsApp Conversation",
		convo_name,
		{
			"last_message_at": now_datetime(),
			"last_message_preview": content[:140],
			"unread_count": current_unread + 1,
		},
	)
	frappe.db.commit()

	handle_event("NEW_WHATSAPP_MESSAGE", None, {"conversation_id": convo_name, "contact_name": contact_name})


def _handle_status_changed(payload: dict) -> None:
	conversation = payload.get("conversation") or payload
	chatwoot_conversation_id = str(conversation.get("id") or "").strip()
	status = (conversation.get("status") or "").upper()
	if not chatwoot_conversation_id or status not in _STATUS_VALUES:
		return
	frappe.db.set_value(
		"TOB WhatsApp Conversation", {"chatwoot_conversation_id": chatwoot_conversation_id}, "status", status
	)
	frappe.db.commit()
