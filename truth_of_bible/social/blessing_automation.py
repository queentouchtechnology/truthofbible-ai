"""Social post automation — the control-panel side.

The posting worker itself runs on the separate outreach VPS (the tob-social
project, systemd timer every 15 minutes) and posts directly to the Meta
Graph API. It posts:

- a daily blessing verse (TOB Blessing Verse, fields on the settings), and
- scheduled content (TOB Social Content, one TOB Automation Schedule row per
  content type: App Feature, Salvation Prayer, ...) on chosen weekdays.

Worker methods:
- `get_worker_config`  — settings, schedules and every approved item; also
  records the worker's heartbeat.
- `log_event`          — one TOB Automation Log row per preview/post/failure.
- `import_verse_texts` / `import_content` — add drafts. They never approve
  anything: approval is only ever a human ticking "Checked & approved" in the
  Desk or the app.

The Flutter admin app gets the same control through the admin-only methods
at the bottom — everything the Desk can do, plus a report.

Auth: System Manager, or the dedicated `TOB Social Worker` role the worker's
API user gets (seeded by install.ensure_social_worker_role) — so the VPS
never holds a System Manager key. Worker methods are POST-only, because
Frappe commits database writes (heartbeat, log rows) only on POST requests.
"""

import json

import re

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime, today

from truth_of_bible.communication.auth import require_admin
from truth_of_bible.social import meta_connection, verse_reference

SETTINGS = "TOB Blessing Automation Settings"
CONTENT = "TOB Social Content"
LOG = "TOB Automation Log"
WORKER_ROLE = "TOB Social Worker"
EVENTS = ("Preview Sent", "Posted", "Failed", "Skipped", "No Approved Verse", "No Approved Content")
# Column names on TOB Automation Schedule; index = Python's date.weekday() (Monday = 0).
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_CONTENT_FIELDS = ["name", "content_type", "title", "image_text", "image_footer", "caption", "how_to_find",
	"last_posted_on"]
_CONTENT_ADMIN_FIELDS = _CONTENT_FIELDS + ["social_approved", "approved_by", "approved_on", "source"]
_CONTENT_EDITABLE = ("content_type", "title", "image_text", "image_footer", "caption", "how_to_find")


def content_types():
	return [t for t in (frappe.get_meta(CONTENT).get_field("content_type").options or "").split("\n") if t]


def post_types():
	return ["Blessing"] + content_types()


def require_worker() -> None:
	roles = frappe.get_roles(frappe.session.user)
	if "System Manager" not in roles and WORKER_ROLE not in roles:
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _schedules(settings):
	return [
		{
			"content_type": row.content_type,
			"enabled": bool(row.enabled),
			"post_time": str(row.post_time or "18:00:00"),
			"weekdays": [i for i, d in enumerate(WEEKDAYS) if row.get(d)],
			"hashtags": row.hashtags or "",
		}
		for row in settings.content_schedules or []
	]


@frappe.whitelist(methods=["POST"])
def get_worker_config():
	require_worker()
	settings = frappe.get_single(SETTINGS)
	frappe.db.set_single_value(SETTINGS, "last_heartbeat", now_datetime(), update_modified=False)

	platforms = []
	if settings.post_to_facebook:
		platforms.append("facebook")
		if settings.post_to_instagram:
			platforms.append("instagram")

	schedules = _schedules(settings)
	for schedule in schedules:
		schedule["items"] = frappe.get_all(CONTENT,
			filters={"social_approved": 1, "content_type": schedule["content_type"]},
			fields=_CONTENT_FIELDS, order_by="title asc")
	return {
		"enabled": bool(settings.enabled),
		"post_time": str(settings.post_time or "07:00:00"),
		"design": settings.design,
		"platforms": platforms,
		"preview_channel": settings.preview_channel or "None",
		"slack_channel_id": settings.slack_channel_id or "",
		# Secrets live here, not on the VPS: the worker gets them per run over HTTPS.
		"slack_bot_token": settings.get_password("slack_bot_token", raise_exception=False) or "",
		"timezone": settings.timezone or "Asia/Kolkata",
		"preview_minutes_before": cint(settings.preview_minutes_before),
		"app_link": settings.app_link or "",
		"hashtags": settings.hashtags or "",
		"verses": frappe.get_all(
			"TOB Blessing Verse",
			filters={"social_approved": 1, "kjv_text": ["is", "set"]},
			fields=["name", "reference", "kjv_text", "last_posted_on"],
			order_by="reference asc",
		),
		"schedules": schedules,
		# Page token etc. from TOB Meta Connection — the worker keeps no copy.
		"meta": meta_connection.worker_block(),
	}


@frappe.whitelist(methods=["POST"])
def seed_worker_secrets(slack_bot_token=None):
	"""One-time move of the Slack token from the outreach VPS's .env into these settings. Only fills an
	empty field, so it can never overwrite what an admin set."""
	require_worker()
	settings = frappe.get_single(SETTINGS)
	moved = []
	if (slack_bot_token or "").strip() and not settings.get_password("slack_bot_token", raise_exception=False):
		settings.slack_bot_token = slack_bot_token.strip()
		moved.append("slack_bot_token")
	if moved:
		settings.flags.ignore_permissions = True
		settings.save()
	return {"moved": moved}


@frappe.whitelist(methods=["POST"])
def log_event(event, reference=None, blessing_verse=None, platform=None, post_id=None, message=None,
		post_type="Blessing", social_content=None):
	require_worker()
	if event not in EVENTS:
		frappe.throw(_("Unknown event: {0}").format(event), frappe.ValidationError)
	if post_type not in post_types():
		frappe.throw(_("Unknown post type: {0}").format(post_type), frappe.ValidationError)
	if blessing_verse and not frappe.db.exists("TOB Blessing Verse", blessing_verse):
		blessing_verse = None
	if social_content and not frappe.db.exists(CONTENT, social_content):
		social_content = None

	doc = frappe.get_doc({
		"doctype": LOG,
		"event": event,
		"platform": platform,
		"post_type": post_type,
		"reference": reference,
		"blessing_verse": blessing_verse,
		"social_content": social_content,
		"post_id": post_id,
		"message": (message or "")[:2000],
	}).insert(ignore_permissions=True)

	# Direct set_value: only the bookkeeping date changes, so validate()
	# (which guards the approval) is deliberately not re-run.
	if event == "Posted" and blessing_verse:
		frappe.db.set_value("TOB Blessing Verse", blessing_verse, "last_posted_on", today(), update_modified=False)
	if event == "Posted" and social_content:
		frappe.db.set_value(CONTENT, social_content, "last_posted_on", today(), update_modified=False)

	summary = " ".join(filter(None, [event, post_type if post_type != "Blessing" else "", platform, reference,
		post_id or message]))
	frappe.db.set_single_value(SETTINGS, "last_result", summary[:500], update_modified=False)
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def import_verse_texts(verses):
	"""`verses`: JSON list of {"ref", "text"}. Fills kjv_text only where it is
	empty; creates unknown references as Draft (hidden from the app's Daily
	Verse screen). Never sets or keeps approval."""
	require_worker()
	result = {"filled": [], "created": [], "skipped": [], "unparsed": []}
	for entry in json.loads(verses) if isinstance(verses, str) else verses:
		ref, text = (entry.get("ref") or "").strip(), (entry.get("text") or "").strip()
		parsed = verse_reference.parse(ref)
		if not parsed or not text:
			result["unparsed"].append(ref)
			continue
		name = frappe.db.get_value("TOB Blessing Verse", {
			"bible_book": parsed["bible_book"],
			"chapter": parsed["chapter"],
			"verse_start": parsed["verse_start"],
			"verse_end": parsed["verse_end"] or ["is", "not set"],
		})
		if name:
			doc = frappe.get_doc("TOB Blessing Verse", name)
			if doc.kjv_text:
				result["skipped"].append(doc.reference)
				continue
			doc.kjv_text = text
			doc.save(ignore_permissions=True)
			result["filled"].append(doc.reference)
		else:
			doc = frappe.get_doc({
				"doctype": "TOB Blessing Verse",
				"reference": verse_reference.canonical(parsed),
				"status": "Draft",
				"kjv_text": text,
				**parsed,
			}).insert(ignore_permissions=True)
			result["created"].append(doc.reference)
	return result


@frappe.whitelist(methods=["POST"])
def import_content(items):
	"""`items`: JSON list of {"content_type", "title", "image_text", "image_footer",
	"caption", "how_to_find"}. Creates rows whose (type, title) isn't in the list
	yet; never touches existing ones and never approves anything."""
	require_worker()
	allowed = set(content_types())
	result = {"created": [], "skipped": []}
	for entry in json.loads(items) if isinstance(items, str) else items:
		kind, title = entry.get("content_type"), (entry.get("title") or "").strip()
		if kind not in allowed or not title or frappe.db.exists(CONTENT, {"content_type": kind, "title": title}):
			result["skipped"].append(f"{kind}: {title}")
			continue
		frappe.get_doc({"doctype": CONTENT, "source": "Import", **{f: entry.get(f) for f in _CONTENT_EDITABLE}}).insert(
			ignore_permissions=True)
		result["created"].append(f"{kind}: {title}")
	return result


# ---------------------------------------------------------------------------
# Admin app (Flutter) — System Manager only, the same boundary as the Desk.

SETTINGS_FIELDS = (
	"enabled", "post_time", "design", "post_to_facebook", "post_to_instagram", "preview_channel",
	"slack_channel_id", "preview_minutes_before", "app_link", "hashtags", "timezone",
)
_CHECKS = ("enabled", "post_to_facebook", "post_to_instagram")
_VERSE_FIELDS = [
	"name", "reference", "theme", "status", "kjv_text", "social_approved", "approved_by", "approved_on",
	"last_posted_on",
]
# The worker runs every 15 minutes; more than two missed runs means something is wrong.
_ALIVE_MINUTES = 35


def _settings_dict(settings):
	data = {f: settings.get(f) for f in SETTINGS_FIELDS}
	for f in _CHECKS:
		data[f] = bool(data[f])
	data["post_time"] = str(data["post_time"] or "")
	data["preview_minutes_before"] = cint(data["preview_minutes_before"])
	data["schedules"] = _schedules(settings)
	data["timezone"] = data["timezone"] or "Asia/Kolkata"
	data["has_slack_token"] = bool(settings.get_password("slack_bot_token", raise_exception=False))
	return data


def _parse(value, default):
	if isinstance(value, str):
		return json.loads(value) if value else default
	return value if value is not None else default


def _verse_filters(filter_key):
	return {
		"approved": {"social_approved": 1},
		"needs_check": {"social_approved": 0, "kjv_text": ["is", "set"]},
		"no_text": {"kjv_text": ["is", "not set"]},
	}.get(filter_key, {})


def _content_filters(filter_key, content_type=None):
	filters = {"approved": {"social_approved": 1}, "needs_check": {"social_approved": 0}}.get(filter_key, {})
	if content_type:
		filters = {**filters, "content_type": content_type}
	return filters


def _least_recent(rows, name_key):
	# Same choice the worker makes (tob_social/automation.py _least_recent).
	return min(rows, key=lambda r: (str(r.last_posted_on or ""), r.get(name_key))) if rows else None


def _report(days):
	"""Counts from TOB Automation Log over the last `days` days. Real posts are
	'Posted' rows linked to a verse or content row; manual test posts (unlinked)
	are counted separately so they never inflate the numbers."""
	since = getdate(add_days(today(), -(days - 1)))
	linked_sql = "(blessing_verse IS NOT NULL OR social_content IS NOT NULL)"
	rows = frappe.db.sql(
		f"""
		SELECT DATE(creation) AS day, event, IFNULL(platform, '') AS platform,
			IFNULL(post_type, 'Blessing') AS post_type, {linked_sql} AS linked, COUNT(*) AS n
		FROM `tab{LOG}` WHERE creation >= %s
		GROUP BY DATE(creation), event, IFNULL(platform, ''), IFNULL(post_type, 'Blessing'), {linked_sql}
		""",
		since,
		as_dict=True,
	)
	posted, failed, by_type, by_day = {}, {}, {}, {}
	previews = missed = tests = 0
	for r in rows:
		entry = by_day.setdefault(str(r.day), {"day": str(r.day), "posted": 0, "failed": 0})
		if r.event == "Posted" and r.linked:
			posted[r.platform] = posted.get(r.platform, 0) + r.n
			by_type[r.post_type] = by_type.get(r.post_type, 0) + r.n
			entry["posted"] += r.n
		elif r.event == "Posted":
			tests += r.n
		elif r.event == "Failed":
			failed[r.platform] = failed.get(r.platform, 0) + r.n
			entry["failed"] += r.n
		elif r.event == "Preview Sent":
			previews += r.n
		elif r.event in ("No Approved Verse", "No Approved Content"):
			missed += r.n

	total_posted, total_failed = sum(posted.values()), sum(failed.values())
	top = frappe.db.sql(
		f"""
		SELECT reference, IFNULL(post_type, 'Blessing') AS post_type, COUNT(DISTINCT DATE(creation)) AS days_posted
		FROM `tab{LOG}` WHERE event = 'Posted' AND {linked_sql} AND creation >= %s
		GROUP BY reference, IFNULL(post_type, 'Blessing') ORDER BY days_posted DESC, reference LIMIT 10
		""",
		since,
		as_dict=True,
	)
	days_list = [str(add_days(since, i)) for i in range(days)]
	return {
		"days": days,
		"since": str(since),
		"posted_by_platform": posted,
		"posted_by_type": by_type,
		"failed_by_platform": failed,
		"days_with_post": sum(1 for d in by_day.values() if d["posted"]),
		"previews_sent": previews,
		"no_verse_alerts": missed,
		"test_posts": tests,
		"success_rate": round(total_posted / (total_posted + total_failed), 3) if total_posted + total_failed else None,
		"by_day": [by_day.get(d, {"day": d, "posted": 0, "failed": 0}) for d in days_list],
		"top_verses": [{"reference": t.reference, "post_type": t.post_type, "days_posted": t.days_posted} for t in top],
	}


@frappe.whitelist(methods=["GET"])
def get_overview(days=30):
	require_admin()
	settings = frappe.get_single(SETTINGS)
	heartbeat = settings.last_heartbeat
	minutes_since = (now_datetime() - get_datetime(heartbeat)).total_seconds() / 60 if heartbeat else None

	approved = frappe.get_all("TOB Blessing Verse", filters={"social_approved": 1, "kjv_text": ["is", "set"]},
		fields=["name", "reference", "last_posted_on"])
	next_verse = _least_recent(approved, "reference")

	content = {}
	for kind in content_types():
		rows = frappe.get_all(CONTENT, filters={"social_approved": 1, "content_type": kind},
			fields=["name", "title", "last_posted_on"])
		nxt = _least_recent(rows, "title")
		content[kind] = {
			"approved": len(rows),
			"needs_check": frappe.db.count(CONTENT, _content_filters("needs_check", kind)),
			"next": nxt.title if nxt else "",
		}

	return {
		"settings": _settings_dict(settings),
		"design_options": (frappe.get_meta(SETTINGS).get_field("design").options or "").split("\n"),
		"content_types": content_types(),
		"worker": {
			"last_heartbeat": heartbeat,
			"minutes_since": round(minutes_since) if minutes_since is not None else None,
			"alive": minutes_since is not None and minutes_since <= _ALIVE_MINUTES,
			"last_result": settings.last_result,
		},
		"verse_counts": {k: frappe.db.count("TOB Blessing Verse", _verse_filters(k))
			for k in ("approved", "needs_check", "no_text")},
		"next_verse": next_verse,
		"content": content,
		"meta_connection": meta_connection.status(),
		"today": frappe.get_all(LOG, filters={"creation": [">=", today()]},
			fields=["event", "platform", "post_type", "reference", "post_id", "message", "creation"],
			order_by="creation desc"),
		"report": _report(max(1, min(cint(days) or 30, 365))),
	}


@frappe.whitelist(methods=["POST"])
def update_settings(values):
	"""`values`: any of SETTINGS_FIELDS, plus optional `schedules` — the full list
	of {content_type, enabled, post_time, weekdays, hashtags}, which replaces
	the current schedule rows."""
	require_admin()
	values = _parse(values, {})
	settings = frappe.get_single(SETTINGS)
	for field in SETTINGS_FIELDS:
		if field in values:
			settings.set(field, cint(values[field]) if field in _CHECKS else values[field])
	if (values.get("slack_bot_token") or "").strip():  # write-only; blank keeps the stored one
		settings.slack_bot_token = values["slack_bot_token"].strip()
	if "schedules" in values:
		settings.set("content_schedules", [])
		for row in values["schedules"] or []:
			days = {cint(d) for d in row.get("weekdays") or []}
			settings.append("content_schedules", {
				"content_type": row.get("content_type"),
				"enabled": cint(row.get("enabled")),
				"post_time": row.get("post_time") or "18:00:00",
				"hashtags": row.get("hashtags") or "",
				**{d: 1 if i in days else 0 for i, d in enumerate(WEEKDAYS)},
			})
	settings.save()
	return _settings_dict(settings)


@frappe.whitelist(methods=["GET"])
def list_verses(filter="all", search=None):
	require_admin()
	filters = _verse_filters(filter)
	if search:
		filters["reference"] = ["like", f"%{search}%"]
	return frappe.get_all("TOB Blessing Verse", filters=filters, fields=_VERSE_FIELDS, order_by="reference asc")


@frappe.whitelist(methods=["POST"])
def save_verse(name, kjv_text=None, social_approved=None):
	"""Edit text and/or approval. `approval_cleared` is true when an edit to
	already-approved text voided its approval (see the verse's validate())."""
	require_admin()
	doc = frappe.get_doc("TOB Blessing Verse", name)
	was_approved = bool(doc.social_approved)
	if kjv_text is not None:
		doc.kjv_text = kjv_text
	if social_approved is not None:
		doc.social_approved = cint(social_approved)
	doc.save()
	return {
		"verse": {f: doc.get(f) for f in _VERSE_FIELDS},
		"approval_cleared": was_approved and social_approved is None and not doc.social_approved,
	}


@frappe.whitelist(methods=["POST"])
def add_verse(reference, kjv_text=None, theme=None):
	"""New verse as Draft (hidden from the app's Daily Verse screen), not approved."""
	require_admin()
	parsed = verse_reference.parse(reference)
	if not parsed:
		frappe.throw(_("Couldn't read that reference. Use a form like 'Psalm 23:1' or 'Numbers 6:24-26'."),
			frappe.ValidationError)
	canonical = verse_reference.canonical(parsed)
	if frappe.db.exists("TOB Blessing Verse", {"reference": canonical}):
		frappe.throw(_("{0} is already in the list.").format(canonical), frappe.ValidationError)
	doc = frappe.get_doc({
		"doctype": "TOB Blessing Verse",
		"reference": canonical,
		"status": "Draft",
		"theme": theme or None,
		"kjv_text": (kjv_text or "").strip(),
		**parsed,
	}).insert()
	return {f: doc.get(f) for f in _VERSE_FIELDS}


@frappe.whitelist(methods=["GET"])
def list_content(content_type=None, filter="all", search=None):
	require_admin()
	filters = _content_filters(filter, content_type)
	if search:
		filters["title"] = ["like", f"%{search}%"]
	return frappe.get_all(CONTENT, filters=filters, fields=_CONTENT_ADMIN_FIELDS,
		order_by="content_type asc, title asc")


@frappe.whitelist(methods=["POST"])
def save_content(name, values=None, social_approved=None):
	"""Edit wording and/or approval — same approval rule as save_verse."""
	require_admin()
	values = _parse(values, {})
	doc = frappe.get_doc(CONTENT, name)
	was_approved = bool(doc.social_approved)
	for field in _CONTENT_EDITABLE:
		if field in values:
			doc.set(field, values[field])
	if social_approved is not None:
		doc.social_approved = cint(social_approved)
	doc.save()
	return {
		"content": {f: doc.get(f) for f in _CONTENT_ADMIN_FIELDS},
		"approval_cleared": was_approved and social_approved is None and not doc.social_approved,
	}


@frappe.whitelist(methods=["POST"])
def add_content(values):
	"""New content row, not approved."""
	require_admin()
	values = _parse(values, {})
	title = (values.get("title") or "").strip()
	if not title:
		frappe.throw(_("Give it a title."), frappe.ValidationError)
	if values.get("content_type") not in content_types():
		frappe.throw(_("Choose a content type."), frappe.ValidationError)
	if frappe.db.exists(CONTENT, {"content_type": values["content_type"], "title": title}):
		frappe.throw(_("{0} is already in the list.").format(title), frappe.ValidationError)
	doc = frappe.get_doc({"doctype": CONTENT, "source": "Manual", **{f: values.get(f) for f in _CONTENT_EDITABLE}}).insert()
	return {f: doc.get(f) for f in _CONTENT_ADMIN_FIELDS}


@frappe.whitelist(methods=["GET"])
def list_logs(event=None, start=0, limit=30, post_type=None):
	require_admin()
	filters = {"event": event} if event else {}
	if post_type:
		filters["post_type"] = post_type
	return {
		"logs": frappe.get_all(LOG, filters=filters,
			fields=["name", "event", "platform", "post_type", "reference", "blessing_verse", "social_content",
				"post_id", "message", "creation"],
			order_by="creation desc", limit_start=cint(start), limit_page_length=min(cint(limit) or 30, 100)),
		"total_count": frappe.db.count(LOG, filters),
	}


# ---------------------------------------------------------------------------
# AI drafts — uses the app's own AI gateway (TOB AI Provider/Model/Prompt,
# usage logged in TOB AI Usage Log). One task per content type, e.g.
# "social_content_salvation_prayer"; edit its wording in TOB AI Prompt.
# Every draft is saved unapproved with source "AI Draft".

_MAX_DRAFTS = 5
# App features must come from the admin's facts, never from the model.
_BRIEF_REQUIRED = {"App Feature": "Describe the feature: its name, what it does and where it is in the app."}


def _ai_task(content_type):
	return "social_content_" + content_type.strip().lower().replace(" ", "_")


def _parse_items(text):
	"""The model's JSON, tolerating a ```json fence or stray text around it."""
	match = re.search(r"\{.*\}", text or "", re.S)
	try:
		data = json.loads(match.group(0)) if match else {}
	except ValueError:
		data = {}
	return [i for i in data.get("items") or [] if isinstance(i, dict)]


@frappe.whitelist(methods=["POST"])
def generate_content_drafts(content_type, count=3, brief=""):
	require_admin()
	from truth_of_bible.ai import service
	from truth_of_bible.ai.core.exceptions import AiProviderException
	from truth_of_bible.ai.core.request import AiMessage, AiRequest
	from truth_of_bible.ai.prompts import resolve_prompt

	if content_type not in content_types():
		frappe.throw(_("Choose a content type."), frappe.ValidationError)
	brief = (brief or "").strip()
	if content_type in _BRIEF_REQUIRED and not brief:
		frappe.throw(_(_BRIEF_REQUIRED[content_type]), frappe.ValidationError)
	count = max(1, min(cint(count) or 3, _MAX_DRAFTS))

	existing = frappe.get_all(CONTENT, filters={"content_type": content_type}, pluck="title")
	task = _ai_task(content_type)
	user = (f"Write {count} {content_type} post(s).\n"
		f"Brief: {brief or '(none — choose suitable, different passages)'}\n"
		f"Existing titles, do not repeat: {'; '.join(existing) or '(none)'}")
	request = AiRequest(
		task=task,
		language="en",
		messages=[AiMessage(role="system", content=resolve_prompt(task, "en")), AiMessage(role="user", content=user)],
		structured_output=True,
	)
	try:
		response = service.generate(request)
	except AiProviderException as exc:
		frappe.throw(_("The AI couldn't write drafts: {0}").format(str(exc)), frappe.ValidationError)

	created = []
	for item in _parse_items(response.content)[:count]:
		title = (item.get("title") or "").strip()
		if not title or not (item.get("caption") or "").strip():
			continue
		if frappe.db.exists(CONTENT, {"content_type": content_type, "title": title}):
			continue
		doc = frappe.get_doc({
			"doctype": CONTENT,
			"content_type": content_type,
			"source": "AI Draft",
			**{f: item.get(f) or "" for f in ("title", "image_text", "image_footer", "caption", "how_to_find")},
		}).insert()
		created.append({f: doc.get(f) for f in _CONTENT_ADMIN_FIELDS})
	if not created:
		frappe.throw(_("The AI reply had no usable drafts. Try again, or add more detail to the brief."),
			frappe.ValidationError)
	return {"created": created, "provider": response.provider, "model": response.model}
