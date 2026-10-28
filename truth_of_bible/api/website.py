"""Endpoints for the public truthofbible.org website (the static site in the
truthofbible-site repo). The site is served from the same domain, so these
are called same-origin at /api/method/truth_of_bible.api.website.*."""

import re

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import escape_html, validate_email_address

_TOPICS = ("Prayer request", "Bible study guidance", "Counselling", "Ministry & events", "The app", "Other")
_LINKS = re.compile(r"https?://|www\.", re.I)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=3600)
def submit_enquiry(
	full_name: str,
	email: str,
	message: str,
	phone: str = "",
	country: str = "",
	topic: str = "Prayer request",
	page: str = "",
	website: str = "",
) -> dict:
	"""Contact / prayer request form. Saved first, then emailed to the
	recipients in TOB Website Settings — a mail failure never loses a message."""
	# `website` is a honeypot: hidden from people, filled in by bots.
	if website:
		return {"ok": True}

	full_name = (full_name or "").strip()[:140]
	email = (email or "").strip().lower()[:140]
	message = (message or "").strip()[:5000]
	if not full_name or not message:
		frappe.throw(_("Please enter your name and message."))
	if not validate_email_address(email):
		frappe.throw(_("Please enter a valid email address."))

	doc = frappe.get_doc(
		{
			"doctype": "TOB Website Enquiry",
			"full_name": full_name,
			"email": email,
			"phone": (phone or "").strip()[:40],
			"country": (country or "").strip()[:80],
			"topic": topic if topic in _TOPICS else "Other",
			"message": message,
			"page": (page or "")[:240],
			"ip_address": frappe.local.request_ip,
			"user_agent": (frappe.get_request_header("User-Agent") or "")[:500],
			# Several links in a short message is the usual spam signature.
			"status": "Spam" if len(_LINKS.findall(message)) > 2 else "New",
		}
	).insert(ignore_permissions=True)

	if doc.status != "Spam":
		frappe.enqueue(_email_enquiry, name=doc.name, enqueue_after_commit=True)
	return {"ok": True}


def _email_enquiry(name: str) -> None:
	doc = frappe.get_doc("TOB Website Enquiry", name)
	settings = frappe.get_single("TOB Website Settings")
	recipients = [r for r in re.split(r"[\s,;]+", settings.enquiry_recipients or "") if "@" in r]
	if not recipients:
		recipients = ["help@truthofbible.org"]

	rows = "".join(
		f"<tr><td style='padding:4px 12px 4px 0;color:#666'>{label}</td><td>{escape_html(value)}</td></tr>"
		for label, value in (
			("Name", doc.full_name),
			("Email", doc.email),
			("Phone", doc.phone),
			("Country", doc.country),
			("Topic", doc.topic),
			("Page", doc.page),
		)
		if value
	)
	body = escape_html(doc.message).replace("\n", "<br>")
	frappe.sendmail(
		recipients=recipients,
		reply_to=doc.email,
		subject=f"{doc.topic}: {doc.full_name} (truthofbible.org)",
		message=f"<table>{rows}</table><hr><p>{body}</p>"
		f"<p style='color:#888'>Saved as {doc.name}. Reply to this email to answer {escape_html(doc.full_name)}.</p>",
		reference_doctype=doc.doctype,
		reference_name=doc.name,
		now=True,
	)
	doc.db_set("email_sent", 1)

	if settings.send_auto_reply and settings.auto_reply_message:
		context = {"full_name": escape_html(doc.full_name), "topic": doc.topic, "message": body}
		frappe.sendmail(
			recipients=[doc.email],
			subject=frappe.render_template(settings.auto_reply_subject or "", context) or _("We received your message"),
			message=frappe.render_template(settings.auto_reply_message, context),
			reference_doctype=doc.doctype,
			reference_name=doc.name,
			now=True,
		)
