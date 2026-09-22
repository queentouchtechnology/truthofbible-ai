"""Brevo (email) HTTP client for the Communication Center. Deliberately
its own module, not shared with anything else — this app's only other
email-ish surface is Frappe's native Communication/Issue reply flow
(Support Tickets), which this deliberately does NOT touch or migrate
(Decision 2, COMMUNICATION_CENTER_ARCHITECTURE.md SS1).

Credential lives ONLY in site_config.json — see BREVO_SETUP.md. Never
logged, never included in any exception message or API response (matches
this app's existing rule, see e.g. delivery.py's `firebase_service_account`
handling).
"""

import frappe
import requests

_SEND_URL = "https://api.brevo.com/v3/smtp/email"


def send_email(
	to_email: str,
	to_name: str,
	subject: str,
	html_content: str,
	text_content: str = "",
) -> tuple[bool, str | None, str | None]:
	"""Returns (ok, message_id, error). Never raises — a Brevo outage must
	never break the campaign-processing batch calling this."""
	conf = frappe.get_site_config()
	api_key = conf.get("brevo_api_key")
	sender_email = conf.get("brevo_sender_email")
	if not api_key or not sender_email:
		frappe.log_error(
			title="Communication Center: Brevo not configured",
			message="site_config.json is missing 'brevo_api_key' and/or 'brevo_sender_email' — see BREVO_SETUP.md.",
		)
		return False, None, "Email is not configured on this site."

	if not to_email:
		return False, None, "This recipient has no email address."

	reply_to = conf.get("brevo_reply_to_email") or "help@truthofbible.org"

	payload = {
		"sender": {"email": sender_email, "name": "Truth Of Bible"},
		"to": [{"email": to_email, "name": to_name or to_email}],
		"subject": subject or "",
		"htmlContent": html_content or "<p></p>",
		"replyTo": {"email": reply_to},
	}
	if text_content:
		payload["textContent"] = text_content

	try:
		response = requests.post(
			_SEND_URL,
			headers={
				"api-key": api_key,
				"Content-Type": "application/json",
				"Accept": "application/json",
			},
			json=payload,
			timeout=20,
		)
	except Exception:
		frappe.log_error(title="Communication Center: Brevo request failed", message=frappe.get_traceback())
		return False, None, "Could not reach the email provider."

	if response.status_code in (200, 201):
		try:
			message_id = response.json().get("messageId")
		except Exception:
			message_id = None
		return True, message_id, None

	# Never surface the raw provider response to a client — log it, return
	# a generic sentence only (this app's existing "never expose provider
	# internals in an error response" rule).
	frappe.log_error(
		title="Communication Center: Brevo send failed",
		message=f"HTTP {response.status_code}: {response.text[:2000]}",
	)
	return False, None, "The email provider rejected this message."
