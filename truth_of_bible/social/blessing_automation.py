"""Daily blessing post automation — the control-panel side.

The posting worker itself runs on the separate outreach VPS (the tob-social
project, systemd timer every 15 minutes) and posts directly to the Meta
Graph API. This module is the only thing it talks to here:

- `get_worker_config`  — settings from TOB Blessing Automation Settings plus
  the approved verse list; also records the worker's heartbeat.
- `log_event`          — one TOB Automation Log row per preview/post/failure.
- `import_verse_texts` — fills empty KJV text on existing verses (and creates
  missing ones as Draft). It never approves anything: approval is only ever
  a human ticking "Checked & approved" in the Desk or the app.

The Flutter admin app gets the same control through the admin-only methods
at the bottom (`get_overview`, `update_settings`, `list_verses`, `save_verse`,
`add_verse`, `list_logs`) — everything the Desk can do, plus a report.

Auth: System Manager, or the dedicated `TOB Social Worker` role the worker's
API user gets (seeded by install.ensure_social_worker_role) — so the VPS
never holds a System Manager key. POST-only, because Frappe commits
database writes (heartbeat, log rows) only on POST requests.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime, today

from truth_of_bible.communication.auth import require_admin
from truth_of_bible.social import verse_reference

SETTINGS = "TOB Blessing Automation Settings"
WORKER_ROLE = "TOB Social Worker"
EVENTS = ("Preview Sent", "Posted", "Failed", "Skipped", "No Approved Verse")


def require_worker() -> None:
	roles = frappe.get_roles(frappe.session.user)
	if "System Manager" not in roles and WORKER_ROLE not in roles:
		frappe.throw(_("Not permitted"), frappe.PermissionError)


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

	verses = frappe.get_all(
		"TOB Blessing Verse",
		filters={"social_approved": 1, "kjv_text": ["is", "set"]},
		fields=["name", "reference", "kjv_text", "last_posted_on"],
		order_by="reference asc",
	)
	return {
		"enabled": bool(settings.enabled),
		"post_time": str(settings.post_time or "07:00:00"),
		"design": settings.design,
		"platforms": platforms,
		"preview_channel": settings.preview_channel or "None",
		"slack_channel_id": settings.slack_channel_id or "",
		"preview_minutes_before": cint(settings.preview_minutes_before),
		"app_link": settings.app_link or "",
		"hashtags": settings.hashtags or "",
		"verses": verses,
	}


@frappe.whitelist(methods=["POST"])
def log_event(event, reference=None, blessing_verse=None, platform=None, post_id=None, message=None):
	require_worker()
	if event not in EVENTS:
		frappe.throw(_("Unknown event: {0}").format(event), frappe.ValidationError)
	if blessing_verse and not frappe.db.exists("TOB Blessing Verse", blessing_verse):
		blessing_verse = None

	doc = frappe.get_doc({
		"doctype": "TOB Automation Log",
		"event": event,
		"platform": platform,
		"reference": reference,
		"blessing_verse": blessing_verse,
		"post_id": post_id,
		"message": (message or "")[:2000],
	}).insert(ignore_permissions=True)

	if event == "Posted" and blessing_verse:
		# Direct set_value: only the bookkeeping date changes, so the verse's
		# validate() (which guards the approval) is deliberately not re-run.
		frappe.db.set_value("TOB Blessing Verse", blessing_verse, "last_posted_on", today(), update_modified=False)

	summary = " ".join(filter(None, [event, platform, reference, post_id or message]))
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


# ---------------------------------------------------------------------------
# Admin app (Flutter) — System Manager only, the same boundary as the Desk.

LOG = "TOB Automation Log"
SETTINGS_FIELDS = (
	"enabled", "post_time", "design", "post_to_facebook", "post_to_instagram", "preview_channel",
	"slack_channel_id", "preview_minutes_before", "app_link", "hashtags",
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


def _report(days):
	"""Counts from TOB Automation Log over the last `days` days. Real posts are
	'Posted' rows linked to a verse; manual test posts (unlinked) are counted
	separately so they never inflate the numbers."""
	since = getdate(add_days(today(), -(days - 1)))
	rows = frappe.db.sql(
		f"""
		SELECT DATE(creation) AS day, event, IFNULL(platform, '') AS platform,
			blessing_verse IS NOT NULL AS linked, COUNT(*) AS n
		FROM `tab{LOG}` WHERE creation >= %s
		GROUP BY DATE(creation), event, IFNULL(platform, ''), blessing_verse IS NOT NULL
		""",
		since,
		as_dict=True,
	)
	posted, failed, by_day = {}, {}, {}
	previews = missed = tests = 0
	for r in rows:
		entry = by_day.setdefault(str(r.day), {"day": str(r.day), "posted": 0, "failed": 0})
		if r.event == "Posted" and r.linked:
			posted[r.platform] = posted.get(r.platform, 0) + r.n
			entry["posted"] += r.n
		elif r.event == "Posted":
			tests += r.n
		elif r.event == "Failed":
			failed[r.platform] = failed.get(r.platform, 0) + r.n
			entry["failed"] += r.n
		elif r.event == "Preview Sent":
			previews += r.n
		elif r.event == "No Approved Verse":
			missed += r.n

	total_posted, total_failed = sum(posted.values()), sum(failed.values())
	top_verses = frappe.db.sql(
		f"""
		SELECT reference, COUNT(DISTINCT DATE(creation)) AS days_posted
		FROM `tab{LOG}` WHERE event = 'Posted' AND blessing_verse IS NOT NULL AND creation >= %s
		GROUP BY reference ORDER BY days_posted DESC, reference LIMIT 10
		""",
		since,
		as_dict=True,
	)
	days_list = [str(add_days(since, i)) for i in range(days)]
	return {
		"days": days,
		"since": str(since),
		"posted_by_platform": posted,
		"failed_by_platform": failed,
		"days_with_post": sum(1 for d in by_day.values() if d["posted"]),
		"previews_sent": previews,
		"no_verse_alerts": missed,
		"test_posts": tests,
		"success_rate": round(total_posted / (total_posted + total_failed), 3) if total_posted + total_failed else None,
		"by_day": [by_day.get(d, {"day": d, "posted": 0, "failed": 0}) for d in days_list],
		"top_verses": [{"reference": v.reference, "days_posted": v.days_posted} for v in top_verses],
	}


@frappe.whitelist(methods=["GET"])
def get_overview(days=30):
	require_admin()
	settings = frappe.get_single(SETTINGS)
	heartbeat = settings.last_heartbeat
	minutes_since = (now_datetime() - get_datetime(heartbeat)).total_seconds() / 60 if heartbeat else None

	approved = frappe.get_all("TOB Blessing Verse", filters={"social_approved": 1, "kjv_text": ["is", "set"]},
		fields=["name", "reference", "last_posted_on"])
	# Same choice the worker makes (tob_social/automation.py choose_verse).
	next_verse = min(approved, key=lambda v: (str(v.last_posted_on or ""), v.reference)) if approved else None

	return {
		"settings": _settings_dict(settings),
		"design_options": (frappe.get_meta(SETTINGS).get_field("design").options or "").split("\n"),
		"worker": {
			"last_heartbeat": heartbeat,
			"minutes_since": round(minutes_since) if minutes_since is not None else None,
			"alive": minutes_since is not None and minutes_since <= _ALIVE_MINUTES,
			"last_result": settings.last_result,
		},
		"verse_counts": {k: frappe.db.count("TOB Blessing Verse", _verse_filters(k))
			for k in ("approved", "needs_check", "no_text")},
		"next_verse": next_verse,
		"today": frappe.get_all(LOG, filters={"creation": [">=", today()]},
			fields=["event", "platform", "reference", "post_id", "message", "creation"], order_by="creation desc"),
		"report": _report(max(1, min(cint(days) or 30, 365))),
	}


@frappe.whitelist(methods=["POST"])
def update_settings(values):
	require_admin()
	values = _parse(values, {})
	settings = frappe.get_single(SETTINGS)
	for field in SETTINGS_FIELDS:
		if field in values:
			settings.set(field, cint(values[field]) if field in _CHECKS else values[field])
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
def list_logs(event=None, start=0, limit=30):
	require_admin()
	filters = {"event": event} if event else {}
	return {
		"logs": frappe.get_all(LOG, filters=filters,
			fields=["name", "event", "platform", "reference", "blessing_verse", "post_id", "message", "creation"],
			order_by="creation desc", limit_start=cint(start), limit_page_length=min(cint(limit) or 30, 100)),
		"total_count": frappe.db.count(LOG, filters),
	}
