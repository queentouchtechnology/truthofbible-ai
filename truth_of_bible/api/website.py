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


@frappe.whitelist(allow_guest=True, methods=["GET"])
def popup() -> dict:
	"""The truthofbible.org popup (TOB Website Settings → Website Popup): whether it is on, when to show it,
	and today's blessing verse as a reference -- the site shows its text in the reader's own Bible.
	Not under the cached bible_web prefix, so switching it off takes effect at once."""
	from truth_of_bible.api.bible import blessing_of_the_day

	s = frappe.get_cached_doc("TOB Website Settings")
	if not s.get("popup_enabled"):
		return {"enabled": False}
	return {
		"enabled": True,
		"title": (s.get("popup_title") or "").strip()[:120],
		"delay": max(int(s.get("popup_delay_seconds") or 0), 3),
		"every_days": max(int(s.get("popup_every_days") or 1), 1),
		"show_app": bool(s.get("popup_show_app")),
		"verse": blessing_of_the_day(),
	}


# --- Festival themes -----------------------------------------------------------------------------------------------

_FESTIVAL_FIELDS = ["name", "scene", "start", "end", "show_in_app", "show_on_website", "app_intro", "motion", "greeting",
	"greeting_ta", "message", "message_ta", "verse_reference", "bible_book", "chapter", "verse_start", "verse_end",
	"modified"]
_SCENE_IDS = {"Advent": "advent", "Christmas": "christmas", "New Year": "new_year", "Palm Sunday": "palm_sunday",
	"Good Friday": "good_friday", "Easter": "easter", "Ascension": "ascension", "Pentecost": "pentecost",
	"Harvest Thanksgiving": "harvest"}
_FESTIVAL_AHEAD_DAYS = 60


@frappe.whitelist(allow_guest=True, methods=["GET"])
def festival_theme(client: str = "app", preview: str = "") -> dict:
	"""The festival looks (TOB Festival Theme) for the app's Home and truthofbible.org.

	Sends the one showing now and those starting in the next 60 days, each with its Start/End as an exact moment,
	so a phone switches by itself at the right time even offline. TOB Website Settings → Festival Themes is the
	master switch: Off, Admins only (System Managers; the website, which has no sign-in, then shows nothing) or
	Everyone. preview=<scene id> (e.g. christmas) returns that scene's latest festival whatever the switch and the
	dates, so the look can be tried on the website. Not under the cached bible_web prefix: a change shows at once."""
	from zoneinfo import ZoneInfo

	from frappe.utils import add_days, get_system_timezone, now_datetime

	tz = ZoneInfo(get_system_timezone())

	def payload(r) -> dict:
		return {
			"id": r.name,
			"scene": _SCENE_IDS.get(r.scene, "christmas"),
			"start": r.start.replace(tzinfo=tz).isoformat(),
			"end": r.end.replace(tzinfo=tz).isoformat(),
			"intro": bool(r.app_intro),
			"motion": (r.motion or "Normal").lower(),
			"greeting": r.greeting or "",
			"greeting_ta": r.greeting_ta or "",
			"message": r.message or "",
			"message_ta": r.message_ta or "",
			"verse": {"reference": r.verse_reference, "book": r.bible_book, "chapter": r.chapter,
				"verse_start": r.verse_start, "verse_end": r.verse_end or r.verse_start} if r.bible_book and r.chapter else None,
			"version": str(r.modified),
		}

	scene = next((name for name, sid in _SCENE_IDS.items() if sid == (preview or "").strip().lower()), None)
	if scene:
		rows = frappe.get_all("TOB Festival Theme", filters={"scene": scene}, fields=_FESTIVAL_FIELDS,
			order_by="start desc", limit=1)
		return {"on": True, "preview": True, "festivals": [payload(r) for r in rows]}

	mode = frappe.db.get_single_value("TOB Website Settings", "festival_themes") or "Admins only"
	website = client == "website"
	on = mode == "Everyone" or (mode == "Admins only" and not website and "System Manager" in frappe.get_roles())
	if not on:
		return {"on": False, "festivals": []}

	now = now_datetime()
	where = {"show_on_website": 1} if website else {"show_in_app": 1}
	rows = frappe.get_all("TOB Festival Theme",
		filters={"enabled": 1, "end": [">", now], "start": ["<", add_days(now, _FESTIVAL_AHEAD_DAYS)], **where},
		fields=_FESTIVAL_FIELDS, order_by="start asc", limit=10)
	return {"on": True, "festivals": [payload(r) for r in rows]}
