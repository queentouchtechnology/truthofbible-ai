"""Chatwoot (WhatsApp) HTTP client for the Communication Center.

Credentials live ONLY in site_config.json — see WHATSAPP_CHATWOOT_SETUP.md.
Never logged, never included in an exception message or API response.

v1's two-way Inbox sends/receives free-form TEXT only (contract SS3.6) —
media is explicitly out of scope for this pass. Campaigns are different:
see the "24-hour window" note below.

**Campaigns must use an approved WhatsApp template, never free text —
confirmed live, not a style choice.** WhatsApp's own Business Platform
policy only allows free-form text within a 24-hour window after the
*customer* has messaged first; a business-initiated message (which is what
every Campaign recipient is, by definition — they may never have messaged
at all) must use a pre-approved template message or WhatsApp will reject
the actual delivery even though Chatwoot's own API may accept the request
and return 200. This module tracks no per-recipient window state (the
architecture has no way to know it), so `send_template_message` is the
ONLY function `campaign.py` is allowed to call — `send_message` (free
text) stays reserved for `whatsapp.py`'s two-way Inbox reply feature,
where the window is guaranteed open because it's a reply to something the
customer just sent.

**Two Chatwoot tokens, not one — confirmed live, not assumed.** An
earlier version of this file used only `chatwoot_bot_access_token`
everywhere. A live test against the real instance returned
`HTTP 401 {"error":"Access to this endpoint is not authorized for bots"}`
on contact search/create — Chatwoot's Agent Bot tokens are scoped to
*acting within* a conversation (sending messages, toggling status), not to
account-management endpoints like Contacts. So:

- `chatwoot_api_token` (a regular agent/admin API access token — Chatwoot
  Profile Settings -> Access Token, NOT the Agent Bot's token) is used for
  contact search/create and conversation creation.
- `chatwoot_bot_access_token` (the Agent Bot's own token) is used for
  `send_message`/`toggle_status` — the actual bot-driven actions Chatwoot
  intends that token for, keeping them attributable to the bot rather than
  a human agent.

This matches Decision 15's original expected config schema (which named
both `chatwoot_api_token` and `chatwoot_bot_access_token` as separate
keys) — the split was dropped by mistake in the first implementation pass
and restored here after the live 401 exposed the gap.
"""

import re

import frappe
import requests


def _config():
	conf = frappe.get_site_config()
	return (
		(conf.get("chatwoot_base_url") or "").rstrip("/"),
		conf.get("chatwoot_api_token"),
		conf.get("chatwoot_bot_access_token"),
		conf.get("chatwoot_account_id"),
		conf.get("chatwoot_inbox_id"),
	)


def _configured() -> bool:
	base_url, api_token, bot_token, account_id, inbox_id = _config()
	return bool(base_url and api_token and bot_token and account_id and inbox_id)


def _log_not_configured():
	frappe.log_error(
		title="Communication Center: Chatwoot not configured",
		message=(
			"site_config.json is missing one or more of 'chatwoot_base_url', "
			"'chatwoot_api_token', 'chatwoot_bot_access_token', 'chatwoot_account_id', "
			"'chatwoot_inbox_id' — see WHATSAPP_CHATWOOT_SETUP.md."
		),
	)


def find_or_create_conversation(phone: str, contact_name: str) -> tuple[str | None, str | None]:
	"""Returns (chatwoot_conversation_id, error). Looks up an existing
	contact by phone number first, creating one (and a fresh conversation
	on this inbox) if none exists. Uses the account-level api_token — the
	bot token is not authorized for contact/conversation management (see
	module docstring). Never raises."""
	base_url, api_token, bot_token, account_id, inbox_id = _config()
	if not _configured():
		_log_not_configured()
		return None, "WhatsApp is not configured on this site."
	if not phone:
		return None, "This recipient has no WhatsApp number on file."

	headers = {"api_access_token": api_token, "Content-Type": "application/json"}
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

		# Confirmed live (2026-09-22): a WhatsApp inbox's `source_id` must
		# match Chatwoot's own validation regex `\A(?:\d{1,15}|...)\z` —
		# plain digits only, no leading '+'. `phone` (E.164, e.g.
		# "+919876543210") is correct for the *contact's* `phone_number`
		# field above, but conversation creation's `source_id` needs it
		# stripped, or Chatwoot returns HTTP 422 "Source invalid source id
		# for whatsapp inbox".
		convo = requests.post(
			f"{base_url}/api/v1/accounts/{account_id}/conversations",
			headers=headers,
			json={"source_id": phone.lstrip("+"), "inbox_id": inbox_id, "contact_id": contact_id},
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
	"""Returns (ok, chatwoot_message_id, error). Uses the Agent Bot token —
	this is the action Chatwoot's bot tokens are actually scoped for. Never
	raises."""
	base_url, api_token, bot_token, account_id, inbox_id = _config()
	if not _configured():
		_log_not_configured()
		return False, None, "WhatsApp is not configured on this site."

	headers = {"api_access_token": bot_token, "Content-Type": "application/json"}
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


def list_templates() -> tuple[list[dict] | None, str | None]:
	"""Returns (templates, error) — the WhatsApp-approved message templates
	configured on this inbox (Chatwoot mirrors these from the WhatsApp
	Business Platform's own template library; confirmed live on 2026-09-22
	against the real 'Truth of Bible' inbox — 3 APPROVED templates exist).
	Only APPROVED templates are returned — a PENDING/REJECTED one can't
	actually be sent. Uses api_token (an inbox-detail read, not a bot
	action). Never raises."""
	base_url, api_token, bot_token, account_id, inbox_id = _config()
	if not _configured():
		_log_not_configured()
		return None, "WhatsApp is not configured on this site."

	headers = {"api_access_token": api_token, "Content-Type": "application/json"}
	try:
		response = requests.get(
			f"{base_url}/api/v1/accounts/{account_id}/inboxes/{inbox_id}", headers=headers, timeout=20
		)
	except Exception:
		frappe.log_error(title="Communication Center: Chatwoot templates request failed", message=frappe.get_traceback())
		return None, "Could not reach WhatsApp."

	if response.status_code != 200:
		frappe.log_error(
			title="Communication Center: Chatwoot templates fetch failed",
			message=f"HTTP {response.status_code}: {response.text[:2000]}",
		)
		return None, "Could not load WhatsApp templates."

	raw = response.json().get("message_templates") or []
	templates = [_parse_template(t) for t in raw if t.get("status") == "APPROVED"]
	return templates, None


def _parse_template(t: dict) -> dict:
	body = next((c for c in (t.get("components") or []) if c.get("type") == "BODY"), {})
	body_text = body.get("text") or ""
	placeholder_count = len(set(re.findall(r"\{\{(\d+)\}\}", body_text)))
	example = ((body.get("example") or {}).get("body_text") or [[]])
	example_values = example[0] if example else []
	return {
		"name": t.get("name"),
		"category": t.get("category"),
		"language": t.get("language"),
		"body_text": body_text,
		"placeholder_count": placeholder_count,
		"example_values": example_values,
	}


def send_template_message(
	chatwoot_conversation_id: str, template_name: str, category: str, language: str, params: list
) -> tuple[bool, str | None, str | None]:
	"""Returns (ok, chatwoot_message_id, error) — sends an approved WhatsApp
	template message (the ONLY thing campaign.py is allowed to call; see
	module docstring). `params` is a plain ordered list of strings
	substituted into the template's numbered {{1}}, {{2}}, ... placeholders.
	Confirmed live shape (2026-09-22): Chatwoot's `template_params` object
	keyed by `name`/`category`/`language`/`processed_params` (the latter a
	dict of 1-indexed string keys), sent with the Agent Bot token — the same
	token scope as `send_message`, since sending is a bot-authorized action.
	Never raises."""
	base_url, api_token, bot_token, account_id, inbox_id = _config()
	if not _configured():
		_log_not_configured()
		return False, None, "WhatsApp is not configured on this site."

	processed_params = {str(i + 1): v for i, v in enumerate(params or [])}
	headers = {"api_access_token": bot_token, "Content-Type": "application/json"}
	try:
		response = requests.post(
			f"{base_url}/api/v1/accounts/{account_id}/conversations/{chatwoot_conversation_id}/messages",
			headers=headers,
			json={
				"template_params": {
					"name": template_name,
					"category": category,
					"language": language,
					"processed_params": processed_params,
				}
			},
			timeout=20,
		)
	except Exception:
		frappe.log_error(title="Communication Center: Chatwoot template send failed", message=frappe.get_traceback())
		return False, None, "Could not reach WhatsApp."

	if response.status_code in (200, 201):
		return True, str(response.json().get("id")), None

	frappe.log_error(
		title="Communication Center: Chatwoot template send rejected",
		message=f"HTTP {response.status_code}: {response.text[:2000]}",
	)
	return False, None, "WhatsApp rejected this template message."


def toggle_status(chatwoot_conversation_id: str, status: str) -> bool:
	"""status: 'resolved' or 'open'. Uses the Agent Bot token, same
	reasoning as send_message. Never raises — a failed Chatwoot-side toggle
	is handled by the caller (whatsapp.py rolls back the local status
	change rather than letting the two systems disagree)."""
	base_url, api_token, bot_token, account_id, inbox_id = _config()
	if not _configured():
		_log_not_configured()
		return False
	headers = {"api_access_token": bot_token, "Content-Type": "application/json"}
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
