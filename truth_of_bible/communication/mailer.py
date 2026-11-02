"""Sends one Communication Center email, either through Brevo (brevo.py — the default for campaigns) or
through a Frappe Email Account (the site's default outgoing account, or a chosen one). The Frappe route goes
through frappe.sendmail, so those emails show in the desk's Email Queue like any other Frappe mail.

Same contract as brevo.send_email: returns (ok, message_id, error) and never raises, so one bad address
can't stop a campaign batch.
"""

from email.utils import formataddr

import frappe

from truth_of_bible.communication import brevo

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
) -> tuple[bool, str | None, str | None]:
	"""`now` sends straight away instead of through the Email Queue (Frappe route only) — for test sends,
	so a broken mail server shows up as an error right then."""
	if via != VIA_FRAPPE:
		return brevo.send_email(to_email, to_name, subject, html_content, text_content)
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
		frappe.log_error(title="Communication Center: Frappe email failed", message=frappe.get_traceback())
		return False, None, "The mail server didn't accept the email (see Error Log)."
	name = getattr(queued, "name", None)
	if now and name:
		# A failed immediate send is recorded on the Email Queue row rather than raised.
		status, error = frappe.db.get_value("Email Queue", name, ["status", "error"]) or (None, None)
		if status in ("Error", "Partially Errored"):
			last_line = (error or "").strip().splitlines()[-1:]
			return False, name, last_line[0] if last_line else "The mail server didn't accept the email (see Email Queue)."
	return True, name, None
