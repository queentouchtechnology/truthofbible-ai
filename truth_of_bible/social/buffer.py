"""Buffer Publish API (https://buffer.com/developers/api) — the Social
Intelligence Center's execution layer for Facebook/Instagram/Google
Business Profile publishing (Phase 1 plan: Buffer owns connected-channel
state, scheduling and publish status; this app only owns intelligence —
recommendations, research, reporting — never a second publishing engine).

Every Buffer HTTP call lives here, never inline elsewhere in the app —
same "one client module per external service" discipline as
communication/chatwoot.py and communication/brevo.py.

Endpoint paths match Buffer's classic Publish API (REST/JSON, documented
at the URL above); re-verify against Buffer's current docs if any call
here starts failing, since third-party APIs do change shape over time.

The token is read from site_config.json's `buffer_api_token` key, never
hardcoded and never logged — same convention as
notifications/delivery.py's `firebase_service_account`.
"""

import frappe
import requests

_BASE_URL = "https://api.bufferapp.com/1"
_TIMEOUT = 15


def _token():
	return frappe.get_site_config().get("buffer_api_token")


def is_configured() -> bool:
	return bool(_token())


def _require_token() -> str:
	token = _token()
	if not token:
		frappe.throw(
			frappe._("Buffer isn't configured yet — add 'buffer_api_token' to site_config.json."),
			frappe.ValidationError,
		)
	return token


def list_channels():
	"""Returns None when Buffer isn't configured or the API call fails —
	the dashboard treats that as "not connected", distinct from a
	genuinely empty (but reachable) list of channels."""
	token = _token()
	if not token:
		return None
	try:
		response = requests.get(
			f"{_BASE_URL}/profiles.json", params={"access_token": token}, timeout=_TIMEOUT
		)
		response.raise_for_status()
		profiles = response.json()
	except requests.RequestException:
		return None

	return [
		{
			"buffer_channel_id": p.get("id"),
			"platform": p.get("service"),
			"channel_name": p.get("formatted_username") or p.get("service_username") or "",
		}
		for p in (profiles or [])
	]


def create_draft(channel_ids: list, text: str) -> dict:
	return _create_update(channel_ids, text, now=False, scheduled_at=None)


def schedule_post(channel_ids: list, text: str, scheduled_at) -> dict:
	return _create_update(channel_ids, text, now=False, scheduled_at=scheduled_at)


def publish_post(channel_ids: list, text: str) -> dict:
	return _create_update(channel_ids, text, now=True, scheduled_at=None)


def _create_update(channel_ids: list, text: str, now: bool, scheduled_at) -> dict:
	token = _require_token()
	data = {
		"access_token": token,
		"profile_ids[]": channel_ids,
		"text": text,
	}
	if now:
		data["now"] = "true"
	elif scheduled_at:
		data["scheduled_at"] = int(scheduled_at)

	response = requests.post(f"{_BASE_URL}/updates/create.json", data=data, timeout=_TIMEOUT)
	response.raise_for_status()
	payload = response.json()
	updates = payload.get("updates") or []
	return {
		"buffer_post_ids": [u.get("id") for u in updates],
		"status": updates[0].get("status") if updates else None,
	}


def get_post_status(buffer_post_id: str) -> dict:
	token = _require_token()
	response = requests.get(
		f"{_BASE_URL}/updates/{buffer_post_id}.json",
		params={"access_token": token},
		timeout=_TIMEOUT,
	)
	response.raise_for_status()
	payload = response.json()
	return {"status": payload.get("status"), "sent_at": payload.get("sent_at")}
