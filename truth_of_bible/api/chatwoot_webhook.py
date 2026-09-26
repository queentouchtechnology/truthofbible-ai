"""Receives Chatwoot's outbound webhook (Settings -> Integrations ->
Webhooks on the Chatwoot side) for `message_created`,
`conversation_status_changed` and `message_updated` events, keeping the
local TOB WhatsApp Conversation/Message mirror in sync and notifying
admins of new inbound messages via the existing notification engine
(Decision 4/5 — reused, not duplicated).

**`message_updated` — added to close a real correctness gap.**
`chatwoot.send_template_message` (see that module's own docstring) only
confirms Chatwoot *accepted* an outbound send; it never confirms WhatsApp
actually delivered it. A campaign recipient's `whatsapp_status` used to be
written once, synchronously, from that accept response alone, and never
revisited — so a message WhatsApp later rejected (e.g. Cloud API error
131008 "Required parameter is missing", surfaced only inside Chatwoot's
own conversation view) stayed recorded as "Sent" forever. `message_updated`
is Chatwoot's own async delivery-status callback for an outbound message;
`_handle_message_updated` below corrects both `TOB WhatsApp Message.status`
and the owning `TOB Communication Campaign Recipient.whatsapp_status` once
Chatwoot reports the real outcome. **Requires this event to actually be
enabled** on the Chatwoot side (Settings -> Integrations -> Webhooks -> the
event checkboxes) — `message_created`/`conversation_status_changed` being
enabled there does not imply `message_updated` also is.

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
_MESSAGE_STATUS_MAP = {
	"sent": "SENT",
	"delivered": "DELIVERED",
	"read": "READ",
	"failed": "FAILED",
}
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
		elif event == "message_updated":
			_handle_message_updated(payload)
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
	# `frappe.form_dict` merges query-string args with a JSON POST body, and
	# in practice (2026-09-26 live test — see the Error Log entry this same
	# check produced) came back completely empty for this exact request
	# shape: an `allow_guest` whitelisted POST with a `Content-Type:
	# application/json` body. `frappe.request.args` is werkzeug's own,
	# unmerged read of the raw query string — checked first as the more
	# reliable source, with form_dict/header kept only as a fallback.
	provided = (
		frappe.request.args.get("secret")
		or frappe.form_dict.get("secret")
		or frappe.get_request_header("X-Chatwoot-Webhook-Secret")
		or ""
	)
	if not hmac.compare_digest(provided, secret):
		# A mismatch here is otherwise completely silent — `receive()`'s
		# `frappe.throw(..., PermissionError)` produces a clean 403 that
		# Frappe does NOT write to Error Log (only unhandled exceptions
		# are, by default), so without this a wrong secret in
		# site_config.json (e.g. pasting Chatwoot's own separate "Secret"
		# field from its webhook edit dialog, instead of the `?secret=`
		# value actually in the registered URL) looks identical to "the
		# webhook never fired at all". Never logs the real secret values —
		# the raw query string is logged instead, which proves whether
		# Chatwoot is even sending `?secret=...` at all (if it's missing
		# from here too, the gap is Chatwoot/the reverse proxy, not Frappe).
		frappe.log_error(
			title="Communication Center: chatwoot_webhook signature mismatch",
			message=(
				f"Provided secret ({len(provided)} chars, empty={not provided}) does not match "
				f"site_config's chatwoot_webhook_secret ({len(secret)} chars). Raw query string "
				f"received: {frappe.request.query_string.decode(errors='replace')!r}. Check that "
				"chatwoot_webhook_secret is set to the `?secret=` query-param value from the "
				"registered webhook URL in Chatwoot (Settings -> Integrations -> Webhooks), "
				"NOT that same dialog's separate 'Secret' field — this receiver never reads that one."
			),
		)
		return False
	return True


def _handle_message_created(payload: dict) -> None:
	# Chatwoot's message_type on the base webhook payload: 0 = incoming
	# (from the WhatsApp contact), 1 = outgoing (an agent/bot reply) — only
	# the former needs mirroring here; outbound sends are already recorded
	# by whatsapp.send_message/campaign.py at the moment they're made.
	message_type = payload.get("message_type")
	if message_type not in (0, "incoming"):
		# Every other event this webhook is subscribed to (Conversation
		# Created/Updated, Contact Created/Updated, typing events, ...) also
		# arrives here as message_created's sibling events do NOT call this
		# function at all — this branch only sees message_created payloads,
		# so an outbound reply (message_type 1/"outgoing") is the expected,
		# silent case. Logged at low volume specifically to catch the OTHER
		# possibility: this instance's Chatwoot version representing
		# "incoming" differently than 0/"incoming" (e.g. a nested field, a
		# different string) would silently drop every real customer message
		# forever without this trace.
		if message_type not in (1, "outgoing"):
			frappe.log_error(
				title="Communication Center: chatwoot message_created unrecognized message_type",
				message=f"message_type={message_type!r}. Raw payload: {payload}",
			)
		return

	conversation = payload.get("conversation") or {}
	chatwoot_conversation_id = str(conversation.get("id") or payload.get("conversation_id") or "").strip()
	chatwoot_message_id = str(payload.get("id") or "").strip()
	if not chatwoot_conversation_id or not chatwoot_message_id:
		frappe.log_error(
			title="Communication Center: chatwoot message_created missing id(s)",
			message=f"conversation_id={chatwoot_conversation_id!r}, message_id={chatwoot_message_id!r}. Raw payload: {payload}",
		)
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


def _handle_message_updated(payload: dict) -> None:
	"""Chatwoot's async delivery-status callback for a message already
	created (inbound or outbound) — the only place this app learns a
	previously-recorded "Sent" outbound message actually failed downstream
	(WhatsApp rejecting it after Chatwoot already accepted the request; see
	this module's own docstring). Silently returns for anything that isn't
	a status transition on a message this app already has a local mirror
	row for — an inbound message's own status echo, or a status value this
	map doesn't recognize, are both expected no-ops, not errors."""
	chatwoot_message_id = str(payload.get("id") or "").strip()
	raw_status = str(payload.get("status") or "").strip().lower()
	new_status = _MESSAGE_STATUS_MAP.get(raw_status)
	if not chatwoot_message_id or not new_status:
		return

	message_name = frappe.db.get_value(
		"TOB WhatsApp Message", {"chatwoot_message_id": chatwoot_message_id}, "name"
	)
	if not message_name:
		return

	frappe.db.set_value("TOB WhatsApp Message", message_name, "status", new_status)

	# Cascade to whichever campaign recipient this send belongs to, if
	# any — a manually-sent agent reply (not a campaign send) has no
	# matching recipient row, which is fine, nothing to cascade to.
	recipient_name = frappe.db.get_value(
		"TOB Communication Campaign Recipient", {"whatsapp_message_id": chatwoot_message_id}, "name"
	)
	if recipient_name:
		frappe.db.set_value("TOB Communication Campaign Recipient", recipient_name, "whatsapp_status", new_status)
		if new_status == "FAILED":
			error_detail = (
				(payload.get("content_attributes") or {}).get("external_error")
				or payload.get("error")
				or "WhatsApp reported this message as failed after Chatwoot accepted it."
			)
			frappe.db.set_value(
				"TOB Communication Campaign Recipient", recipient_name, "error", str(error_detail)[:500]
			)

	frappe.db.commit()
