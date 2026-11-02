"""The weekly newsletter: once a week (TOB Newsletter Settings — day, hour, on/off) the next enabled
TOB Newsletter Issue goes to every user as a Communication Center campaign (email and/or push), so delivery,
opens and failures show in the admin app's Campaign history like any other campaign. After the last issue
the series starts again from the first, so people who joined later get it from the beginning.

The email has two app sections and campaign.personalize_email keeps one per recipient: an "Open in the
app" button for users with the app (a registered FCM token), or a short "get the free app" invitation for
the rest. Both link to /open, which opens the app if it's installed and otherwise goes to the Play Store,
carrying the screen through the install.

Every email carries a one-click unsubscribe link (signed per user), which sets the same
communication_center_email_opt_out that Brevo's own unsubscribe webhook sets.
"""

import hashlib
import hmac
import re
import urllib.parse
from html import unescape

import frappe
from frappe import _
from frappe.utils import escape_html, get_url, getdate, now_datetime

from truth_of_bible.communication import brevo, campaign
from truth_of_bible.communication.auth import require_admin

_SETTINGS = "TOB Newsletter Settings"
_ISSUE = "TOB Newsletter Issue"
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# Same landing page as notifications/email_delivery._APP_OPEN_LINK_BASE.
_APP_OPEN_LINK_BASE = "https://learn.truthofbible.org/open"


# ─────────────────────────── Scheduler ───────────────────────────


def weekly_check():
	"""Hourly (hooks.py). Sends at most one issue a week: on the chosen day, at or after the chosen hour, once."""
	try:
		s = frappe.get_single(_SETTINGS)
		if not s.enabled or not (s.send_email or s.send_push):
			return
		now = now_datetime()
		if _WEEKDAYS[now.weekday()] != s.send_weekday or now.hour < int(s.send_hour or 0):
			return
		if s.last_sent_on and getdate(s.last_sent_on) == now.date():
			return
		issue = _next_issue(s.last_issue_no or 0)
		if issue:
			_send_issue(s, issue)
	except Exception:
		frappe.log_error(title="Newsletter: weekly send failed", message=frappe.get_traceback())


def _next_issue(last_issue_no: int):
	rows = frappe.get_all(_ISSUE, filters={"enabled": 1}, fields=["name", "issue_no"], order_by="issue_no asc")
	if not rows:
		return None
	row = next((r for r in rows if r.issue_no > last_issue_no), rows[0])
	return frappe.get_doc(_ISSUE, row.name)


def _send_issue(s, issue) -> str:
	channels = {}
	if s.send_email:
		subject, html = render_email(issue)
		channels["email"] = {"subject": subject, "body_html": html, "body_text": render_text(issue)}
	if s.send_push:
		channels["push"] = {
			"title": issue.push_title or issue.title,
			"body": issue.push_body or issue.verse_text or "",
			"deeplink_route": issue.app_route or "/dashboard",
		}
	result = campaign.create_campaign(
		name=f"Newsletter #{issue.issue_no}: {issue.title}",
		audience_type="ALL_ELIGIBLE_USERS",
		action="send_now",
		channels=channels,
	)
	today = now_datetime().date()
	frappe.db.set_single_value(
		_SETTINGS,
		{"last_issue_no": issue.issue_no, "last_sent_on": today, "last_campaign": result["campaign_id"]},
	)
	frappe.db.set_value(_ISSUE, issue.name, {"times_sent": (issue.times_sent or 0) + 1, "last_sent_on": today})
	frappe.db.commit()
	return result["campaign_id"]


# ─────────────────────────── Email ───────────────────────────


def _open_link(route: str | None) -> str:
	return f"{_APP_OPEN_LINK_BASE}?{urllib.parse.urlencode({'route': route or '/dashboard'})}"


# The Email Template every issue is rendered with (Jinja) — edit it in the desk (Email Template → TOB Newsletter)
# to change the look. Seeded once by seed(); a later migrate never overwrites it. Variables: issue (the TOB
# Newsletter Issue), app_link (the /open link for the issue's screen), first_name. Keep the two app sections
# and {{ unsubscribe_url }}: campaign.personalize_email resolves those per recipient.
TEMPLATE = "TOB Newsletter"
_TEMPLATE_SUBJECT = "{{ issue.subject }}"
_TEMPLATE_HTML = """<!doctype html><html><body style="margin:0;background:#F5F1E8;">
<div style="display:none;max-height:0;overflow:hidden;">{{ issue.preheader or "" }}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F5F1E8;padding:24px 12px;"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:14px;overflow:hidden;font-family:Arial,Helvetica,sans-serif;color:#2b2b2b;font-size:15px;line-height:1.6;">
<tr><td style="background:#14161c;padding:18px 24px;color:#ffffff;font-size:18px;font-weight:bold;">Truth of <span style="color:#C8902E;">Bible</span></td></tr>
<tr><td style="padding:26px 24px 8px;">
<h1 style="font-family:Georgia,serif;font-weight:normal;font-size:24px;line-height:1.3;margin:0 0 6px;color:#14161c;">{{ issue.title }}</h1>
{% if issue.verse_text %}<div style="border-left:4px solid #C8902E;background:#FBF6EC;padding:14px 18px;margin:18px 0;font-family:Georgia,serif;font-size:17px;line-height:1.5;color:#3a2f1c;">&ldquo;{{ issue.verse_text }}&rdquo;
<div style="margin-top:6px;font-size:13px;font-style:italic;color:#C8902E;">&mdash; {{ issue.verse_ref }} (KJV)</div></div>{% endif %}
{{ issue.body_html or "" }}
{% if issue.action %}<div style="background:#F3F4F6;border-radius:10px;padding:14px 18px;margin:18px 0;">
<div style="font-weight:bold;color:#C8902E;margin-bottom:4px;">Try this week</div>{{ issue.action }}</div>{% endif %}
<!--if_app--><div style="text-align:center;margin:24px 0 8px;"><a href="{{ app_link }}" style="display:inline-block;background:#C8902E;color:#ffffff;text-decoration:none;font-weight:bold;padding:12px 22px;border-radius:24px;">&#128241; {{ issue.app_button or "Open the app" }}</a></div><!--end_if_app-->
<!--if_no_app--><div style="text-align:center;background:#FBF6EC;border-radius:12px;padding:18px;margin:24px 0 8px;">
<div style="font-weight:bold;font-size:16px;margin-bottom:4px;">Grow every day with the free Truth of Bible app</div>
<div style="color:#555;margin-bottom:14px;">Bible reading plans, prayer, songs, the daily verse and the Prayer Wall &mdash; all in one place.</div>
<a href="{{ app_link }}" style="display:inline-block;background:#C8902E;color:#ffffff;text-decoration:none;font-weight:bold;padding:12px 22px;border-radius:24px;">Get the free app</a></div><!--end_if_no_app-->
</td></tr>
<tr><td style="padding:18px 24px 24px;color:#888;font-size:12px;line-height:1.5;border-top:1px solid #eee;">
You're getting this because you have a Truth of Bible account. <a href="{{ unsubscribe_url }}" style="color:#888;">Unsubscribe</a> &middot;
<a href="https://truthofbible.org/" style="color:#888;">truthofbible.org</a></td></tr>
</table></td></tr></table></body></html>"""


def render_email(issue) -> tuple[str, str]:
	"""(subject, html) from the TOB Newsletter Email Template. The per-recipient parts stay as tags for
	campaign.personalize_email: {{first_name}}, {{unsubscribe_url}} and the two app sections."""
	context = {
		"issue": issue,
		"app_link": _open_link(issue.app_route),
		"first_name": "{{first_name}}",
		"unsubscribe_url": "{{unsubscribe_url}}",
	}
	try:
		t = frappe.get_cached_doc("Email Template", TEMPLATE)
		subject_src, html_src = t.subject, (t.response_html if t.use_html else t.response)
	except frappe.DoesNotExistError:
		subject_src, html_src = _TEMPLATE_SUBJECT, _TEMPLATE_HTML
	return frappe.render_template(subject_src or _TEMPLATE_SUBJECT, context), frappe.render_template(html_src or _TEMPLATE_HTML, context)


def _html_to_text(html: str | None) -> str:
	"""Body HTML as plain text, keeping a blank line between paragraphs and list items."""
	text = re.sub(r"(?i)<br\s*/?>|</(p|li|h[1-6]|div)>", "\n", html or "")
	text = re.sub(r"(?i)<li[^>]*>", "• ", text)
	text = unescape(frappe.utils.strip_html(text))
	return re.sub(r"\n{2,}", "\n\n", "\n".join(line.strip() for line in text.splitlines())).strip()


def render_text(issue) -> str:
	parts = [issue.title, ""]
	if issue.verse_text:
		parts += [f"“{issue.verse_text}” — {issue.verse_ref} (KJV)", ""]
	parts += [_html_to_text(issue.body_html), ""]
	if issue.action:
		parts += [f"Try this week: {issue.action}", ""]
	parts += [f"{issue.app_button or 'Open the app'}: {_open_link(issue.app_route)}", "", "Unsubscribe: {{unsubscribe_url}}"]
	return "\n".join(parts)


# ─────────────────────────── Unsubscribe ───────────────────────────


def _sig(user: str) -> str:
	key = (frappe.local.conf.get("encryption_key") or frappe.local.conf.get("db_password") or "").encode()
	return hmac.new(key, user.encode(), hashlib.sha256).hexdigest()[:32]


def unsubscribe_url(user: str) -> str:
	query = urllib.parse.urlencode({"u": user, "k": _sig(user)})
	return get_url(f"/api/method/truth_of_bible.communication.newsletter.unsubscribe?{query}")


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def unsubscribe(u: str = "", k: str = "", confirm: str = ""):
	"""GET shows a confirm button (mail scanners open links on their own); the POST it sends unsubscribes."""
	if not (u and k and hmac.compare_digest(_sig(u), k) and frappe.db.exists("User", u)):
		frappe.respond_as_web_page(_("Link not valid"), _("This unsubscribe link isn't valid."), indicator_color="red")
		return
	if frappe.request.method != "POST" or not confirm:
		form = (
			f'<form method="post"><input type="hidden" name="u" value="{escape_html(u)}">'
			f'<input type="hidden" name="k" value="{escape_html(k)}"><input type="hidden" name="confirm" value="1">'
			f'<p>{escape_html(_("Stop the Truth of Bible newsletter and announcement emails to {0}?").format(u))}</p>'
			f'<button type="submit" class="btn btn-primary">{escape_html(_("Unsubscribe"))}</button></form>'
		)
		frappe.respond_as_web_page(_("Unsubscribe"), form, indicator_color="orange")
		return
	from truth_of_bible.notifications.preferences import update_preference

	update_preference(u, {"communication_center_email_opt_out": 1})
	frappe.db.commit()
	frappe.respond_as_web_page(
		_("Unsubscribed"),
		_("You won't get these emails any more. You can turn them back on in the app's notification settings."),
		indicator_color="green",
	)


# ─────────────────────────── Admin API (desk + app) ───────────────────────────


def _settings_dict(s) -> dict:
	return {
		"enabled": int(s.enabled or 0),
		"send_weekday": s.send_weekday or "Sunday",
		"send_hour": int(s.send_hour or 0),
		"send_email": int(s.send_email or 0),
		"send_push": int(s.send_push or 0),
		"last_issue_no": s.last_issue_no or 0,
		"last_sent_on": s.last_sent_on,
		"last_campaign": s.last_campaign,
	}


@frappe.whitelist(methods=["GET", "POST"])
def get_newsletter() -> dict:
	require_admin()
	s = frappe.get_single(_SETTINGS)
	issues = frappe.get_all(
		_ISSUE,
		fields=["name", "issue_no", "title", "enabled", "times_sent", "last_sent_on"],
		order_by="issue_no asc",
	)
	nxt = _next_issue(s.last_issue_no or 0)
	return {**_settings_dict(s), "issues": issues, "next_issue_no": nxt.issue_no if nxt else None,
	        "next_issue_title": nxt.title if nxt else None}


@frappe.whitelist(methods=["POST"])
def save_newsletter_settings(enabled=None, send_weekday=None, send_hour=None, send_email=None, send_push=None) -> dict:
	require_admin()
	s = frappe.get_single(_SETTINGS)
	if enabled is not None:
		s.enabled = 1 if frappe.utils.cint(enabled) else 0
	if send_weekday is not None:
		if send_weekday not in _WEEKDAYS:
			frappe.throw(_("Choose a day of the week."), frappe.ValidationError)
		s.send_weekday = send_weekday
	if send_hour is not None:
		hour = frappe.utils.cint(send_hour)
		if not 0 <= hour <= 23:
			frappe.throw(_("The hour must be between 0 and 23."), frappe.ValidationError)
		s.send_hour = hour
	if send_email is not None:
		s.send_email = 1 if frappe.utils.cint(send_email) else 0
	if send_push is not None:
		s.send_push = 1 if frappe.utils.cint(send_push) else 0
	s.save(ignore_permissions=True)
	return get_newsletter()


@frappe.whitelist(methods=["POST"])
def send_test(issue_no=None) -> dict:
	"""Emails one issue (default: the next one) to the admin asking, personalised as for them. Doesn't count as sent."""
	require_admin()
	if issue_no:
		name = frappe.db.get_value(_ISSUE, {"issue_no": frappe.utils.cint(issue_no)})
		if not name:
			frappe.throw(_("No issue with that number."), frappe.DoesNotExistError)
		issue = frappe.get_doc(_ISSUE, name)
	else:
		issue = _next_issue(frappe.db.get_single_value(_SETTINGS, "last_issue_no") or 0)
		if not issue:
			frappe.throw(_("There are no newsletter issues yet."), frappe.ValidationError)
	user = frappe.session.user
	row = frappe.db.get_value("User", user, ["email", "first_name", "last_name", "full_name"], as_dict=True) or {}
	values = {"first_name": row.get("first_name") or "", "last_name": row.get("last_name") or "", "email": row.get("email") or ""}
	subject, html = render_email(issue)
	ok, _message_id, err = brevo.send_email(
		to_email=row.get("email") or user,
		to_name=row.get("full_name") or user,
		subject="[Test] " + campaign.personalize_email(subject, user, values),
		html_content=campaign.personalize_email(html, user, values),
		text_content=campaign.personalize_email(render_text(issue), user, values),
	)
	if not ok:
		frappe.throw(_("The test email wasn't sent: {0}").format(err or "unknown error"))
	return {"sent_to": row.get("email") or user, "issue_no": issue.issue_no}


@frappe.whitelist(methods=["POST"])
def send_next_now() -> dict:
	"""Sends the next issue to everyone right away (also when switched off) — for the desk's Send Now button."""
	require_admin()
	s = frappe.get_single(_SETTINGS)
	if not (s.send_email or s.send_push):
		frappe.throw(_("Turn on email or push first."), frappe.ValidationError)
	issue = _next_issue(s.last_issue_no or 0)
	if not issue:
		frappe.throw(_("There are no newsletter issues yet."), frappe.ValidationError)
	return {"campaign_id": _send_issue(s, issue), "issue_no": issue.issue_no}


# ─────────────────────────── Seed ───────────────────────────


def seed():
	"""after_migrate, create-only: the TOB Newsletter Email Template, and the first series while there are no
	issues at all. Edits and deletions made in the desk stay."""
	if not frappe.db.exists("Email Template", TEMPLATE):
		frappe.get_doc({"doctype": "Email Template", "name": TEMPLATE, "subject": _TEMPLATE_SUBJECT, "use_html": 1,
		                "response_html": _TEMPLATE_HTML}).insert(ignore_permissions=True)
		frappe.db.commit()
	if not frappe.db.table_exists(_ISSUE) or frappe.db.count(_ISSUE):
		return
	from truth_of_bible.communication.newsletter_issues import ISSUES

	for no, data in enumerate(ISSUES, start=1):
		frappe.get_doc({"doctype": _ISSUE, "issue_no": no, "enabled": 1, **data}).insert(ignore_permissions=True)
	frappe.db.commit()
