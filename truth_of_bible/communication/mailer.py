"""Sends one Communication Center email, either through Brevo (brevo.py — the default for campaigns) or
through a Frappe Email Account (the site's default outgoing account, or a chosen one). The Frappe route goes
through frappe.sendmail, so those emails show in the desk's Email Queue like any other Frappe mail.

Same contract as brevo.send_email: returns (ok, message_id, error) and never raises, so one bad address
can't stop a campaign batch.
"""

from email.utils import formataddr

import frappe

from truth_of_bible.communication import brevo
from truth_of_bible import errors

VIA_BREVO = "Brevo"
VIA_FRAPPE = "Frappe Email Account"
VIAS = (VIA_FRAPPE, VIA_BREVO)


def validate(via: str | None, email_account: str | None) -> None:
	if (via or VIA_BREVO) not in VIAS:
		frappe.throw(frappe._("Choose how to send email: {0}.").format(" or ".join(VIAS)), frappe.ValidationError)
	if via == VIA_FRAPPE and email_account:
		if not frappe.db.get_value("Email Account", email_account, "enable_outgoing"):
			frappe.throw(
				frappe._("Email Account {0} doesn't exist or isn't enabled for outgoing mail.").format(email_account),
				frappe.ValidationError,
			)


def send_email(
	via: str | None,
	email_account: str | None,
	to_email: str,
	to_name: str,
	subject: str,
	html_content: str,
	text_content: str = "",
	now: bool = False,
	unsubscribe_url: str | None = None,
) -> tuple[bool, str | None, str | None]:
	"""`now` sends straight away instead of through the Email Queue (Frappe route only) — for test sends,
	so a broken mail server shows up as an error right then.

	`unsubscribe_url` becomes the List-Unsubscribe / one-click headers Gmail and Yahoo expect on bulk mail
	(without them it's far more likely to land in spam). Brevo route only: Frappe prefixes "X-" to every
	custom header (email_body.add_headers), so it can't send these."""
	if via != VIA_FRAPPE:
		headers = None
		if unsubscribe_url:
			headers = {"List-Unsubscribe": f"<{unsubscribe_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
		return brevo.send_email(to_email, to_name, subject, html_content, text_content, headers=headers)
	if not to_email:
		return False, None, "This recipient has no email address."
	sender = None
	if email_account:
		sender = formataddr(("Truth Of Bible", frappe.db.get_value("Email Account", email_account, "email_id")))
	try:
		queued = frappe.sendmail(
			recipients=[to_email],
			sender=sender,
			subject=subject or "",
			message=html_content or "<p></p>",
			add_unsubscribe_link=0,  # the newsletter carries its own signed unsubscribe link
			delayed=not now,
			now=now,
		)
	except Exception:
		errors.log_error(title="Communication Center: Frappe email failed", message=frappe.get_traceback())
		return False, None, "The mail server didn't accept the email (see Error Log)."
	name = getattr(queued, "name", None)
	if now and name:
		# A failed immediate send is recorded on the Email Queue row rather than raised.
		status, error = frappe.db.get_value("Email Queue", name, ["status", "error"]) or (None, None)
		if status in ("Error", "Partially Errored"):
			last_line = (error or "").strip().splitlines()[-1:]
			return False, name, last_line[0] if last_line else "The mail server didn't accept the email (see Email Queue)."
	return True, name, None
