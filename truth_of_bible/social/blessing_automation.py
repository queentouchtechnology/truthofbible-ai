"""Daily blessing post automation — the control-panel side.

The posting worker itself runs on the separate outreach VPS (the tob-social
project, systemd timer every 15 minutes) and posts directly to the Meta
Graph API. This module is the only thing it talks to here:

- `get_worker_config`  — settings from TOB Blessing Automation Settings plus
  the approved verse list; also records the worker's heartbeat.
- `log_event`          — one TOB Automation Log row per preview/post/failure.
- `import_verse_texts` — fills empty KJV text on existing verses (and creates
  missing ones as Draft). It never approves anything: approval is only ever
  a human ticking "Checked & approved" in the Desk.

Auth: System Manager, or the dedicated `TOB Social Worker` role the worker's
API user gets (seeded by install.ensure_social_worker_role) — so the VPS
never holds a System Manager key. POST-only, because Frappe commits
database writes (heartbeat, log rows) only on POST requests.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, today

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
