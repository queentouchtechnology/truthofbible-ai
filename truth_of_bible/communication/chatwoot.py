"""Chatwoot (WhatsApp) HTTP client for the Communication Center.

Credentials live ONLY in site_config.json — see WHATSAPP_CHATWOOT_SETUP.md.
Never logged, never included in an exception message or API response.

v1 sends/receives TEXT only (contract SS3.6) — `send_message` always posts
a plain text message; media is explicitly out of scope for this pass.

Uses the Agent Bot access token (`chatwoot_bot_access_token`), not a
general API token, for every call here — Chatwoot's own convention for
automated/bot-driven sends, keeping them attributable and scoped
separately from a human agent's own token (see WHATSAPP_CHATWOOT_SETUP.md
SS5).
"""

import frappe
import requests


def _config():
	conf = frappe.get_site_config()
	return (
		(conf.get("chatwoot_base_url") or "").rstrip("/"),
		conf.get("chatwoot_bot_access_token"),
		conf.get("chatwoot_account_id"),
		conf.get("chatwoot_inbox_id"),
	)


def _configured() -> bool:
	base_url, token, account_id, inbox_id = _config()
	return bool(base_url and token and account_id and inbox_id)


def _log_not_configured():
	frappe.log_error(
		title="Communication Center: Chatwoot not configured",
		message=(
			"site_config.json is missing one or more of 'chatwoot_base_url', "
			"'chatwoot_bot_access_token', 'chatwoot_account_id', 'chatwoot_inbox_id' — "
			"see WHATSAPP_CHATWOOT_SETUP.md."
		),
	)


def find_or_create_conversation(phone: str, contact_name: str) -> tuple[str | None, str | None]:
	"""Returns (chatwoot_conversation_id, error). Looks up an existing
	contact by phone number first, creating one (and a fresh conversation
	on this inbox) if none exists. Never raises."""
	base_url, token, account_id, inbox_id = _config()
	if not _configured():
		_log_not_configured()
		return None, "WhatsApp is not configured on this site."
	if not phone:
		return None, "This recipient has no WhatsApp number on file."

	headers = {"api_access_token": token, "Content-Type": "application/json"}
	try:
		search = requests.get(
			f"{base_url}/api/v1/accounts/{account_id}/contacts/search",
			headers=headers,
			params={"q": phone},
			timeout=20,
		)
		contact_id = None
		if search.status_code == 200:
			for contact in search.json().get("payload", []):
				if contact.get("phone_number") == phone:
					contact_id = contact.get("id")
					break

		if not contact_id:
			create = requests.post(
				f"{base_url}/api/v1/accounts/{account_id}/contacts",
				headers=headers,
				json={"name": contact_name or phone, "phone_number": phone, "inbox_id": inbox_id},
				timeout=20,
			)
			if create.status_code not in (200, 201):
				frappe.log_error(
					title="Communication Center: Chatwoot contact create failed",
					message=f"HTTP {create.status_code}: {create.text[:2000]}",
				)
				return None, "Could not create this contact in WhatsApp."
			body = create.json()
			contact_id = (body.get("payload") or {}).get("contact", {}).get("id") or body.get("id")

		convo = requests.post(
			f"{base_url}/api/v1/accounts/{account_id}/conversations",
			headers=headers,
			json={"source_id": phone, "inbox_id": inbox_id, "contact_id": contact_id},
			timeout=20,
		)
		if convo.status_code not in (200, 201):
			frappe.log_error(
				title="Communication Center: Chatwoot conversation create failed",
				message=f"HTTP {convo.status_code}: {convo.text[:2000]}",
			)
			return None, "Could not start a WhatsApp conversation."
		return str(convo.json().get("id")), None
	except Exception:
		frappe.log_error(title="Communication Center: Chatwoot request failed", message=frappe.get_traceback())
		return None, "Could not reach WhatsApp."


def send_message(chatwoot_conversation_id: str, message: str) -> tuple[bool, str | None, str | None]:
	"""Returns (ok, chatwoot_message_id, error). Never raises."""
	base_url, token, account_id, inbox_id = _config()
	if not _configured():
		_log_not_configured()
		return False, None, "WhatsApp is not configured on this site."

	headers = {"api_access_token": token, "Content-Type": "application/json"}
	try:
		response = requests.post(
			f"{base_url}/api/v1/accounts/{account_id}/conversations/{chatwoot_conversation_id}/messages",
			headers=headers,
			json={"content": message, "message_type": "outgoing"},
			timeout=20,
		)
	except Exception:
		frappe.log_error(title="Communication Center: Chatwoot send failed", message=frappe.get_traceback())
		return False, None, "Could not reach WhatsApp."

	if response.status_code in (200, 201):
		return True, str(response.json().get("id")), None

	frappe.log_error(
		title="Communication Center: Chatwoot send rejected",
		message=f"HTTP {response.status_code}: {response.text[:2000]}",
	)
	return False, None, "WhatsApp rejected this message."


def toggle_status(chatwoot_conversation_id: str, status: str) -> bool:
	"""status: 'resolved' or 'open'. Never raises — a failed Chatwoot-side
	toggle is handled by the caller (whatsapp.py rolls back the local
	status change rather than letting the two systems disagree)."""
	base_url, token, account_id, inbox_id = _config()
	if not _configured():
		_log_not_configured()
		return False
	headers = {"api_access_token": token, "Content-Type": "application/json"}
	try:
		response = requests.post(
			f"{base_url}/api/v1/accounts/{account_id}/conversations/{chatwoot_conversation_id}/toggle_status",
			headers=headers,
			json={"status": status},
			timeout=20,
		)
		return response.status_code in (200, 201)
	except Exception:
		frappe.log_error(title="Communication Center: Chatwoot toggle_status failed", message=frappe.get_traceback())
		return False
