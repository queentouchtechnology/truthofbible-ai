"""Communication Center — WhatsApp inbox (COMMUNICATION_CENTER_API_CONTRACT.md
SS3). Whitelisted, admin-only methods reading/writing the local
`TOB WhatsApp Conversation`/`Message` mirror and calling Chatwoot to
actually send. Inbound messages arrive via `api/chatwoot_webhook.py`, not
through here — this module is the admin Flutter client's read/reply side
of a two-way conversation Chatwoot itself is the system of record for.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from truth_of_bible.communication import chatwoot
from truth_of_bible.communication.auth import require_admin


@frappe.whitelist(methods=["GET"])
def list_templates():
	"""Approved WhatsApp templates the Composer's WhatsApp channel picker
	fetches from — Campaigns must use a template, never free text (see
	chatwoot.py's module docstring for why)."""
	require_admin()
	templates, err = chatwoot.list_templates()
	if templates is None:
		frappe.throw(err or _("Could not load WhatsApp templates."), frappe.ValidationError)
	return {"templates": templates}


def _conversation_dict(c) -> dict:
	user_name = frappe.db.get_value("User", c.user, "full_name") if c.user else ""
	email = frappe.db.get_value("User", c.user, "email") if c.user else None
	return {
		"conversation_id": c.name,
		"user": c.user,
		"user_name": user_name or "",
		"phone": c.phone,
		"email": email,
		"status": c.status,
		"unread_count": c.unread_count or 0,
		"last_message_preview": c.last_message_preview or "",
		"last_message_at": c.last_message_at,
		"assigned_to": c.assigned_to,
	}


@frappe.whitelist(methods=["GET"])
def list_conversations(status=None, search=None, assigned_to=None, limit_start=0, limit_page_length=20):
	require_admin()
	filters = {}
	if status:
		filters["status"] = status.upper()
	if assigned_to and assigned_to != "unassigned":
		filters["assigned_to"] = assigned_to
	elif assigned_to == "unassigned":
		filters["assigned_to"] = ["is", "not set"]

	total_count = frappe.db.count("TOB WhatsApp Conversation", filters)
	conversations = frappe.get_all(
		"TOB WhatsApp Conversation",
		filters=filters,
		fields=["name", "user", "phone", "status", "unread_count", "last_message_preview",
				"last_message_at", "assigned_to"],
		order_by="last_message_at desc",
		limit_start=int(limit_start),
		limit_page_length=int(limit_page_length),
	)

	rows = []
	for c in conversations:
		row = _conversation_dict(c)
		if search:
			haystack = f"{row['user_name']} {row['phone']} {row['email'] or ''}".lower()
			if search.strip().lower() not in haystack:
				continue
		rows.append(row)
	return {"total_count": total_count, "conversations": rows}


@frappe.whitelist(methods=["GET"])
def get_conversation(conversation_id):
	require_admin()
	c = frappe.get_doc("TOB WhatsApp Conversation", conversation_id)
	return _conversation_dict(c)


@frappe.whitelist(methods=["GET"])
def get_messages(conversation_id, before_message_id=None, since_message_id=None, limit=50):
	require_admin()
	filters = {"conversation": conversation_id}
	order_by = "creation asc"
	limit_page_length = int(limit) if limit else 50
	has_more_older = False

	if before_message_id:
		anchor = frappe.db.get_value("TOB WhatsApp Message", before_message_id, "creation")
		if anchor:
			filters["creation"] = ["<", anchor]
		order_by = "creation desc"
	elif since_message_id:
		anchor = frappe.db.get_value("TOB WhatsApp Message", since_message_id, "creation")
		if anchor:
			filters["creation"] = [">", anchor]
		limit_page_length = 0  # no cap on a poll's incremental fetch

	messages = frappe.get_all(
		"TOB WhatsApp Message",
		filters=filters,
		fields=["name", "direction", "message_type", "message", "status", "creation"],
		order_by=order_by,
		limit_page_length=limit_page_length or None,
	)

	if before_message_id:
		has_more_older = len(messages) == limit_page_length
		messages = list(reversed(messages))

	rows = [
		{
			"message_id": m.name,
			"direction": m.direction,
			"message_type": m.message_type,
			"message": m.message,
			"status": m.status,
			"created_at": m.creation,
		}
		for m in messages
	]
	return {"messages": rows, "has_more_older": has_more_older}


@frappe.whitelist(methods=["POST"])
def send_message(conversation_id, message):
	require_admin()
	if not (message or "").strip():
		frappe.throw(_("Message cannot be empty."), frappe.ValidationError)

	convo = frappe.get_doc("TOB WhatsApp Conversation", conversation_id)

	# Chatwoot may reject a send into a resolved conversation (contract
	# SS7's open item #2) — auto-reopen first as the safer default rather
	# than surfacing that as an error to the admin composer.
	reopened = False
	if convo.status == "RESOLVED":
		if chatwoot.toggle_status(convo.chatwoot_conversation_id, "open"):
			reopened = True

	ok, chatwoot_message_id, err = chatwoot.send_message(convo.chatwoot_conversation_id, message)
	if not ok:
		frappe.throw(err or _("Could not send this message."), frappe.ValidationError)

	doc = frappe.get_doc(
		{
			"doctype": "TOB WhatsApp Message",
			"conversation": convo.name,
			"chatwoot_message_id": chatwoot_message_id,
			"direction": "OUTBOUND",
			"message_type": "TEXT",
			"message": message,
			"status": "SENT",
		}
	)
	doc.insert(ignore_permissions=True)

	convo.last_message_at = now_datetime()
	convo.last_message_preview = message[:140]
	if reopened:
		convo.status = "OPEN"
	convo.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"message_id": doc.name,
		"direction": doc.direction,
		"message_type": doc.message_type,
		"message": doc.message,
		"status": doc.status,
		"created_at": doc.creation,
	}


@frappe.whitelist(methods=["POST"])
def mark_read(conversation_id):
	require_admin()
	frappe.db.set_value("TOB WhatsApp Conversation", conversation_id, "unread_count", 0)
	frappe.db.commit()
	return {"conversation_id": conversation_id, "unread_count": 0}


@frappe.whitelist(methods=["POST"])
def close_conversation(conversation_id):
	require_admin()
	convo = frappe.get_doc("TOB WhatsApp Conversation", conversation_id)
	if not chatwoot.toggle_status(convo.chatwoot_conversation_id, "resolved"):
		frappe.throw(_("Could not update this conversation in WhatsApp."), frappe.ValidationError)
	convo.status = "RESOLVED"
	convo.save(ignore_permissions=True)
	frappe.db.commit()
	return {"conversation_id": conversation_id, "status": "RESOLVED"}


@frappe.whitelist(methods=["POST"])
def reopen_conversation(conversation_id):
	require_admin()
	convo = frappe.get_doc("TOB WhatsApp Conversation", conversation_id)
	if not chatwoot.toggle_status(convo.chatwoot_conversation_id, "open"):
		frappe.throw(_("Could not update this conversation in WhatsApp."), frappe.ValidationError)
	convo.status = "OPEN"
	convo.save(ignore_permissions=True)
	frappe.db.commit()
	return {"conversation_id": conversation_id, "status": "OPEN"}
