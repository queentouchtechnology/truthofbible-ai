"""Meta WhatsApp Cloud API — direct template sends (app OTP codes).

A one-time code needs no inbox, contact or conversation, so it goes
straight to Meta instead of through Chatwoot (whose contact step rejected
numbers without a country code and adds two extra calls per code).
Chatwoot stays the two-way Inbox / Campaign channel (chatwoot.py).

Settings live in TOB Meta Connection (desk → "WhatsApp Cloud API" section):
the sending number's Phone Number ID, its token (encrypted; blank = the
page's main Meta Access Token), the OTP template and the default country
code. Blank Phone Number ID = not configured (app_auth falls back to
Chatwoot). The token is never logged, never included in an exception
message or API response.
"""

import re

import frappe
import requests

SETTINGS = "TOB Meta Connection"
_API_VERSION = "v21.0"


def _settings():
	return frappe.get_single(SETTINGS)


def _config():
	"""(token, phone_number_id) — either may be empty."""
	settings = _settings()
	phone_number_id = (settings.get("whatsapp_phone_number_id") or "").strip()
	token = settings.get_password("whatsapp_access_token", raise_exception=False) or settings.get_password(
		"access_token", raise_exception=False
	)
	return token, phone_number_id


def configured() -> bool:
	token, phone_number_id = _config()
	return bool(token and phone_number_id)


def otp_settings() -> dict:
	"""Template + default country code for app OTP codes (both channels)."""
	settings = _settings()
	return {
		"template": (settings.get("whatsapp_otp_template") or "").strip() or "reference_number",
		"category": settings.get("whatsapp_otp_template_category") or "UTILITY",
		"language": (settings.get("whatsapp_otp_template_language") or "").strip() or "en",
		"country_code": re.sub(r"\D", "", settings.get("whatsapp_default_country_code") or "") or "91",
	}


def to_e164(number: str, default_country_code: str = "91") -> str | None:
	"""'+91 98765-43210', '0091…', '919876543210', '09876543210' and a bare
	10-digit national number all become '+919876543210'. None when it
	can't be a phone number. A bare 10-digit number is taken as the default
	country's (older app builds sent only the digits typed)."""
	raw = (number or "").strip()
	digits = re.sub(r"\D", "", raw)
	if raw.startswith("+"):
		pass
	elif digits.startswith("00"):
		digits = digits[2:]
	elif len(digits) == 11 and digits.startswith("0"):
		digits = default_country_code + digits[1:]
	elif len(digits) == 10:
		digits = default_country_code + digits
	if not 8 <= len(digits) <= 15 or digits.startswith("0"):
		return None
	return "+" + digits


def template_components(params: list, copy_code: bool) -> list:
	"""Body {{1}}, {{2}}, … and, for an AUTHENTICATION template, its
	copy-code button (Meta requires the code there too)."""
	components = []
	if params:
		components.append({"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]})
	if copy_code and params:
		components.append(
			{"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": str(params[0])}]}
		)
	return components


def send_template(to: str, template_name: str, language: str, params: list, copy_code: bool = False):
	"""Returns (ok, message_id, error). `to` is E.164. Never raises."""
	token, phone_number_id = _config()
	if not (token and phone_number_id):
		return False, None, "WhatsApp Cloud API is not configured on this site."

	payload = {
		"messaging_product": "whatsapp",
		"to": to.lstrip("+"),
		"type": "template",
		"template": {
			"name": template_name,
			"language": {"code": language},
			"components": template_components(params, copy_code),
		},
	}
	try:
		response = requests.post(
			f"https://graph.facebook.com/{_API_VERSION}/{phone_number_id}/messages",
			headers={"Authorization": f"Bearer {token}"},
			json=payload,
			timeout=20,
		)
	except Exception:
		frappe.log_error(title="WhatsApp Cloud: template send failed", message=frappe.get_traceback())
		return False, None, "Could not reach WhatsApp."

	if response.status_code == 200:
		messages = response.json().get("messages") or [{}]
		return True, messages[0].get("id"), None

	frappe.log_error(
		title="WhatsApp Cloud: template send rejected",
		message=f"HTTP {response.status_code} ({template_name}): {response.text[:2000]}",
	)
	return False, None, "WhatsApp rejected this template message."
