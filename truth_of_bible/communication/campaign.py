"""Communication Center — Campaigns (COMMUNICATION_CENTER_API_CONTRACT.md
SS1). Whitelisted methods for the admin Flutter client, plus `process_queue`
(SS4/Decision 10), the scheduler-invoked function that actually sends
anything.

Deliberately separate from `truth_of_bible.notifications.engine`
(Decision 5): a campaign is an ad-hoc, admin-confirmed send with an
explicit audience, never an event-driven one — but delivery for Push
reuses `notifications.delivery.send_push` directly (Decision 4), not a
duplicate FCM client.

Every whitelisted method here starts with `auth.require_admin()` —
Decision 12, never trust client-side UI visibility as the real boundary.
"""

import json

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from truth_of_bible.communication import audience as audience_mod
from truth_of_bible.communication import brevo, chatwoot
from truth_of_bible.communication.auth import require_admin
from truth_of_bible.notifications import delivery
from truth_of_bible.notifications.preferences import get_or_create_preference

_CANCELLABLE = ("SCHEDULED", "QUEUED", "PROCESSING")
_AUDIENCE_TYPES = (
	"SINGLE_USER", "SELECTED_USERS", "ALL_ELIGIBLE_USERS", "GROUP", "BATCH_MEMBERS",
)
_ACTIONS = ("draft", "send_now", "schedule")
_BATCH_SIZE = 50


def _parse_json(value, default):
	if isinstance(value, str):
		try:
			return json.loads(value) if value else default
		except Exception:
			return default
	return value if value is not None else default


# ─────────────────────────── Whitelisted API ───────────────────────────


@frappe.whitelist(methods=["POST"])
def create_campaign(
	name, audience_type, action, audience_user_ids=None, audience_ref=None, channels=None, scheduled_at=None
):
	require_admin()

	audience_user_ids = _parse_json(audience_user_ids, [])
	channels = _parse_json(channels, {})

	if not (name or "").strip():
		frappe.throw(_("Give this campaign a name."), frappe.ValidationError)
	if audience_type not in _AUDIENCE_TYPES:
		frappe.throw(_("Invalid audience_type."), frappe.ValidationError)
	if action not in _ACTIONS:
		frappe.throw(_("Invalid action."), frappe.ValidationError)
	if action == "schedule" and not scheduled_at:
		frappe.throw(_("scheduled_at is required when scheduling."), frappe.ValidationError)

	push = channels.get("push")
	email = channels.get("email")
	whatsapp = channels.get("whatsapp")
	if not (push or email or whatsapp):
		frappe.throw(_("Select at least one channel."), frappe.ValidationError)
	# Campaigns must use an approved WhatsApp template, never free text —
	# see chatwoot.py's module docstring for why (the 24-hour customer
	# window rule; a campaign recipient may never have messaged first).
	if whatsapp and not (whatsapp.get("template_name") and whatsapp.get("category") and whatsapp.get("language")):
		frappe.throw(_("Choose a WhatsApp template."), frappe.ValidationError)

	users = audience_mod.resolve_audience(audience_type, audience_user_ids, audience_ref)
	if not users:
		frappe.throw(_("No eligible recipients for this audience."), frappe.ValidationError)

	status = {"draft": "DRAFT", "schedule": "SCHEDULED", "send_now": "QUEUED"}[action]

	doc = frappe.get_doc(
		{
			"doctype": "TOB Communication Campaign",
			"campaign_name": name.strip(),
			"status": status,
			"audience_type": audience_type,
			"audience_user_ids": json.dumps(audience_user_ids),
			"audience_ref": audience_ref,
			"recipient_count": len(users),
			"push_enabled": 1 if push else 0,
			"push_title": (push or {}).get("title"),
			"push_body": (push or {}).get("body"),
			"push_image_url": (push or {}).get("image_url"),
			"push_deeplink_route": (push or {}).get("deeplink_route"),
			"push_deeplink_id": (push or {}).get("deeplink_id"),
			"email_enabled": 1 if email else 0,
			"email_subject": (email or {}).get("subject"),
			"email_body_html": (email or {}).get("body_html"),
			"email_body_text": (email or {}).get("body_text"),
			"whatsapp_enabled": 1 if whatsapp else 0,
			"whatsapp_template_name": (whatsapp or {}).get("template_name"),
			"whatsapp_template_category": (whatsapp or {}).get("category"),
			"whatsapp_template_language": (whatsapp or {}).get("language"),
			"whatsapp_template_params": json.dumps((whatsapp or {}).get("params") or []),
			"scheduled_at": get_datetime(scheduled_at) if scheduled_at else None,
		}
	)
	doc.insert(ignore_permissions=True)

	channel_recipient_counts = {"push": 0, "email": 0, "whatsapp": 0}
	for user in users:
		pref = get_or_create_preference(user)
		row = frappe.get_doc(
			{
				"doctype": "TOB Communication Campaign Recipient",
				"campaign": doc.name,
				"user": user,
				"user_name": frappe.db.get_value("User", user, "full_name") or user,
				"push_status": "NOT_APPLICABLE",
				"email_status": "NOT_APPLICABLE",
				"whatsapp_status": "NOT_APPLICABLE",
			}
		)
		if push and audience_mod.channel_eligible(user, "push", pref):
			row.push_status = "QUEUED"
			channel_recipient_counts["push"] += 1
		if email and audience_mod.channel_eligible(user, "email", pref):
			row.email_status = "QUEUED"
			channel_recipient_counts["email"] += 1
		if whatsapp and audience_mod.channel_eligible(user, "whatsapp", pref):
			row.whatsapp_status = "QUEUED"
			channel_recipient_counts["whatsapp"] += 1
		row.insert(ignore_permissions=True)

	frappe.db.commit()

	return {
		"campaign_id": doc.name,
		"status": doc.status,
		"audience_type": doc.audience_type,
		"recipient_count": doc.recipient_count,
		"channel_recipient_counts": channel_recipient_counts,
		"created_at": doc.creation,
		"scheduled_at": doc.scheduled_at,
	}


@frappe.whitelist(methods=["POST"])
def estimate_audience(audience_type, audience_user_ids=None, audience_ref=None):
	require_admin()
	audience_user_ids = _parse_json(audience_user_ids, [])
	if audience_type not in _AUDIENCE_TYPES:
		frappe.throw(_("Invalid audience_type."), frappe.ValidationError)
	return audience_mod.estimate(audience_type, audience_user_ids, audience_ref)


@frappe.whitelist(methods=["GET"])
def list_campaigns_with_stats(status=None, limit_start=0, limit_page_length=20):
	require_admin()
	filters = {}
	if status:
		filters["status"] = status

	total_count = frappe.db.count("TOB Communication Campaign", filters)
	campaigns = frappe.get_all(
		"TOB Communication Campaign",
		filters=filters,
		fields=[
			"name", "campaign_name", "status", "audience_type", "recipient_count",
			"creation", "scheduled_at", "completed_at",
		],
		order_by="creation desc",
		limit_start=int(limit_start),
		limit_page_length=int(limit_page_length),
	)

	rows = [
		{
			"campaign_id": c.name,
			"campaign_name": c.campaign_name,
			"status": c.status,
			"audience_type": c.audience_type,
			"recipient_count": c.recipient_count,
			"stats": _channel_stats(c.name),
			"created_at": c.creation,
			"scheduled_at": c.scheduled_at,
			"completed_at": c.completed_at,
		}
		for c in campaigns
	]
	return {"total_count": total_count, "campaigns": rows}


def _channel_stats(campaign_id: str) -> dict:
	stats = {}
	for channel, field in (("push", "push_status"), ("email", "email_status"), ("whatsapp", "whatsapp_status")):
		counts = frappe.get_all(
			"TOB Communication Campaign Recipient",
			filters={"campaign": campaign_id},
			group_by=field,
			fields=[field, "count(name) as count"],
		)
		channel_counts = {
			row[field].lower(): row["count"] for row in counts if row[field] and row[field] != "NOT_APPLICABLE"
		}
		if channel_counts:
			stats[channel] = channel_counts
	return stats


@frappe.whitelist(methods=["GET"])
def get_campaign(campaign_id):
	require_admin()
	doc = frappe.get_doc("TOB Communication Campaign", campaign_id)

	channels = {}
	if doc.push_enabled:
		channels["push"] = {
			"title": doc.push_title,
			"body": doc.push_body,
			"image_url": doc.push_image_url,
			"deeplink_route": doc.push_deeplink_route,
			"deeplink_id": doc.push_deeplink_id,
		}
	if doc.email_enabled:
		channels["email"] = {
			"subject": doc.email_subject,
			"body_html": doc.email_body_html,
			"body_text": doc.email_body_text,
		}
	if doc.whatsapp_enabled:
		channels["whatsapp"] = {
			"template_name": doc.whatsapp_template_name,
			"category": doc.whatsapp_template_category,
			"language": doc.whatsapp_template_language,
			"params": json.loads(doc.whatsapp_template_params or "[]"),
		}

	page_size = 50
	recipients = frappe.get_all(
		"TOB Communication Campaign Recipient",
		filters={"campaign": campaign_id},
		fields=["user", "user_name", "push_status", "email_status", "whatsapp_status", "error"],
		order_by="name asc",
		limit_page_length=page_size,
	)
	total_count = frappe.db.count("TOB Communication Campaign Recipient", {"campaign": campaign_id})

	return {
		"campaign": {
			"campaign_id": doc.name,
			"campaign_name": doc.campaign_name,
			"status": doc.status,
			"audience_type": doc.audience_type,
			"audience_ref": doc.audience_ref,
			"recipient_count": doc.recipient_count,
			"stats": _channel_stats(doc.name),
			"created_at": doc.creation,
			"scheduled_at": doc.scheduled_at,
			"completed_at": doc.completed_at,
		},
		"channels": channels,
		"recipients_page": {"recipients": recipients, "total_count": total_count},
	}


@frappe.whitelist(methods=["POST"])
def cancel_campaign(campaign_id):
	require_admin()
	doc = frappe.get_doc("TOB Communication Campaign", campaign_id)
	if doc.status not in _CANCELLABLE:
		frappe.throw(_("This campaign can no longer be cancelled."), frappe.ValidationError)

	doc.status = "CANCELLED"
	doc.completed_at = now_datetime()
	doc.save(ignore_permissions=True)

	# Recipients not yet reached must stop being picked up by the next
	# process_queue tick — flip any still-QUEUED per-channel status to
	# NOT_APPLICABLE so this campaign simply stops matching its selection
	# filter, rather than tracking cancellation as a third dimension.
	for field in ("push_status", "email_status", "whatsapp_status"):
		frappe.db.set_value(
			"TOB Communication Campaign Recipient",
			{"campaign": campaign_id, field: "QUEUED"},
			field,
			"NOT_APPLICABLE",
		)
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def send_campaign(campaign_id):
	require_admin()
	doc = frappe.get_doc("TOB Communication Campaign", campaign_id)
	if doc.status != "DRAFT":
		frappe.throw(_("Only a draft campaign can be sent."), frappe.ValidationError)
	doc.status = "QUEUED"
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True}


def _delete_campaign_and_related(campaign_id: str) -> None:
	# Both are standalone DocTypes linked by a plain field, not child
	# tables — frappe.delete_doc on the campaign alone would leave these
	# orphaned rather than cascading.
	frappe.db.delete("TOB Communication Campaign Recipient", {"campaign": campaign_id})
	frappe.db.delete("TOB Notification Send Log", {"event_code": campaign_id})
	frappe.delete_doc("TOB Communication Campaign", campaign_id, ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def delete_campaign(campaign_id):
	require_admin()
	status = frappe.db.get_value("TOB Communication Campaign", campaign_id, "status")
	if status is None:
		frappe.throw(_("Campaign not found."), frappe.DoesNotExistError)
	if status in _CANCELLABLE:
		frappe.throw(_("Cancel this campaign before deleting it."), frappe.ValidationError)
	_delete_campaign_and_related(campaign_id)
	frappe.db.commit()
	return {"deleted": True}


@frappe.whitelist(methods=["POST"])
def delete_campaigns(campaign_ids):
	"""Bulk delete for the Composer history list's multi-select/"select
	all" actions — one round trip instead of the client looping
	`delete_campaign` once per row. Campaigns still in flight (SCHEDULED/
	QUEUED/PROCESSING) are skipped rather than failing the whole batch, so
	the admin can still clear out everything else in one go and cancel the
	in-flight ones separately."""
	require_admin()
	ids = _parse_json(campaign_ids, [])
	deleted, skipped = [], []
	for campaign_id in ids:
		status = frappe.db.get_value("TOB Communication Campaign", campaign_id, "status")
		if status is None:
			continue
		if status in _CANCELLABLE:
			skipped.append(campaign_id)
			continue
		_delete_campaign_and_related(campaign_id)
		deleted.append(campaign_id)
	frappe.db.commit()
	return {"deleted": deleted, "skipped": skipped}


# ────────────────────── Scheduler: actually sending ──────────────────────


def process_queue():
	"""Registered in hooks.py's scheduler_events (every 2 minutes) — the
	ONLY place that actually sends anything for a campaign. Processes a
	small, bounded batch per tick rather than an entire campaign at once
	(Decision 10 — the whitelisted `create_campaign` above never sends
	anything itself, so the HTTP request that creates a campaign never
	blocks on its size), matching the existing scheduler precedent
	(`games/bible_battle/engine.sweep_stale_battles`)."""
	try:
		_promote_scheduled()
		_process_batch()
	except Exception:
		frappe.log_error(title="Communication Center: process_queue failed", message=frappe.get_traceback())


def _promote_scheduled():
	due = frappe.get_all(
		"TOB Communication Campaign",
		filters={"status": "SCHEDULED", "scheduled_at": ["<=", now_datetime()]},
		pluck="name",
	)
	for campaign_id in due:
		frappe.db.set_value("TOB Communication Campaign", campaign_id, "status", "QUEUED")
	if due:
		frappe.db.commit()


def _process_batch():
	campaign_ids = frappe.get_all(
		"TOB Communication Campaign",
		filters={"status": ["in", ("QUEUED", "PROCESSING")]},
		pluck="name",
	)
	for campaign_id in campaign_ids:
		try:
			_process_campaign(campaign_id)
		except Exception:
			frappe.log_error(
				title=f"Communication Center: process_campaign failed ({campaign_id})",
				message=frappe.get_traceback(),
			)


def _process_campaign(campaign_id: str):
	doc = frappe.get_doc("TOB Communication Campaign", campaign_id)
	if doc.status == "QUEUED":
		doc.status = "PROCESSING"
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	pending = frappe.get_all(
		"TOB Communication Campaign Recipient",
		filters={"campaign": campaign_id},
		or_filters={"push_status": "QUEUED", "email_status": "QUEUED", "whatsapp_status": "QUEUED"},
		pluck="name",
		limit_page_length=_BATCH_SIZE,
	)

	for recipient_name in pending:
		_process_recipient(doc, recipient_name)

	_finalize_if_done(doc)


def _process_recipient(doc, recipient_name: str):
	recipient = frappe.get_doc("TOB Communication Campaign Recipient", recipient_name)
	user = recipient.user
	errors = []

	# Built once, reused by both Email and WhatsApp below — push needs no
	# personalization, so it's skipped there to avoid an unnecessary query.
	user_row = {}
	merge_values = {"first_name": "", "last_name": "", "email": ""}
	if doc.email_enabled or doc.whatsapp_enabled:
		user_row = frappe.db.get_value(
			"User", user, ["email", "first_name", "last_name"], as_dict=True
		) or {}
		merge_values = {
			"first_name": user_row.get("first_name") or "",
			"last_name": user_row.get("last_name") or "",
			"email": user_row.get("email") or "",
		}

	if doc.push_enabled and recipient.push_status == "QUEUED":
		if _already_sent(doc.name, user, "PUSH"):
			recipient.push_status = "SENT"
		else:
			# Recorded BEFORE the push, exactly like `engine.py`'s own
			# automatic sends — its id travels in the FCM payload as
			# `send_id`, which is what lets `delivery._record_result` fill in
			# devices_reached/failed afterward, lets the app's own
			# `notification_tapped` report be attributed back to this exact
			# send, and (via `tracked=1`) is what makes a campaign push show
			# up in the engagement report at all — none of that happened
			# before, since `_record_channel_send` used to run AFTER the
			# send with no id to pass in, so campaign pushes were entirely
			# invisible to delivery/tap/engagement reporting.
			send_id = _record_channel_send(doc.name, user, "PUSH", tracked=1)
			ok = delivery.send_push(
				user=user,
				title=doc.push_title or "",
				body=doc.push_body or "",
				notif_type="COMMUNICATION_CAMPAIGN",
				image=doc.push_image_url or None,
				route=doc.push_deeplink_route or None,
				ref_id=doc.push_deeplink_id or None,
				send_id=send_id,
			)
			recipient.push_status = "SENT" if ok else "FAILED"
			if not ok:
				errors.append("push: delivery failed")

	if doc.email_enabled and recipient.email_status == "QUEUED":
		if _already_sent(doc.name, user, "EMAIL"):
			recipient.email_status = "SENT"
		else:
			ok, message_id, err = brevo.send_email(
				to_email=user_row.get("email"),
				to_name=recipient.user_name,
				subject=_render_merge_tags(doc.email_subject or "", merge_values),
				html_content=_render_merge_tags(doc.email_body_html or "", merge_values),
				text_content=_render_merge_tags(doc.email_body_text or "", merge_values),
			)
			recipient.email_status = "SENT" if ok else "FAILED"
			if message_id:
				recipient.email_message_id = message_id
			_record_channel_send(doc.name, user, "EMAIL")
			if not ok:
				errors.append(f"email: {err}")

	if doc.whatsapp_enabled and recipient.whatsapp_status == "QUEUED":
		if _already_sent(doc.name, user, "WHATSAPP"):
			recipient.whatsapp_status = "SENT"
		else:
			raw_params = json.loads(doc.whatsapp_template_params or "[]")
			params = [_render_merge_tags(p, merge_values) for p in raw_params]
			empty_at = [i + 1 for i, p in enumerate(params) if not (p or "").strip()]
			if empty_at:
				# A blank template param (almost always a personalization
				# tag like {{first_name}} that had nothing to substitute for
				# this recipient) is what WhatsApp itself rejects with Cloud
				# API error 131008 "Required parameter is missing" — but
				# only AFTER Chatwoot has already 200'd the request, which
				# is why this used to show as a false "Sent" (see
				# chatwoot_webhook.py's message_updated handler for the
				# other half of this fix). Catching it here means this
				# never reaches Chatwoot at all, and fails honestly instead.
				ok, message_id, err = False, None, (
					f"Template param(s) #{', '.join(map(str, empty_at))} resolved to an empty "
					"value for this recipient — not sent."
				)
			else:
				ok, message_id, err = _send_whatsapp(
					user,
					recipient.user_name,
					doc.whatsapp_template_name,
					doc.whatsapp_template_category,
					doc.whatsapp_template_language,
					params,
				)
			recipient.whatsapp_status = "SENT" if ok else "FAILED"
			if message_id:
				recipient.whatsapp_message_id = message_id
			_record_channel_send(doc.name, user, "WHATSAPP")
			if not ok:
				errors.append(f"whatsapp: {err}")

	if errors:
		recipient.error = "; ".join(errors)
	recipient.save(ignore_permissions=True)
	frappe.db.commit()


def _send_whatsapp(
	user: str, user_name: str, template_name: str, category: str, language: str, params: list
) -> tuple[bool, str | None, str | None]:
	"""Always sends via an approved template — never free text (see
	chatwoot.py's module docstring: a campaign recipient may never have
	messaged first, so WhatsApp's 24-hour free-text window cannot be
	assumed open)."""
	phone = frappe.db.get_value("User", user, "mobile_no")
	existing = frappe.db.get_value(
		"TOB WhatsApp Conversation", {"user": user}, ["name", "chatwoot_conversation_id"], as_dict=True
	)
	# A conversation for this phone number may already exist WITHOUT a
	# `user` link — e.g. mirrored from an inbound webhook message before
	# any campaign ever linked it to this account. Checking by `user` alone
	# (the only lookup here before 2026-09-26) missed that row entirely and
	# went on to call find_or_create_conversation for a phone that already
	# had a thread, which is exactly what produced duplicate rows for the
	# same number in the admin's WhatsApp inbox.
	if not existing and phone:
		existing = frappe.db.get_value(
			"TOB WhatsApp Conversation", {"phone": phone}, ["name", "chatwoot_conversation_id"], as_dict=True
		)
		if existing:
			frappe.db.set_value("TOB WhatsApp Conversation", existing.name, "user", user)

	conversation_id = existing.chatwoot_conversation_id if existing else None

	if not conversation_id:
		conversation_id, err = chatwoot.find_or_create_conversation(phone, user_name)
		if not conversation_id:
			return False, None, err or "Could not start a WhatsApp conversation."
		frappe.get_doc(
			{
				"doctype": "TOB WhatsApp Conversation",
				"user": user,
				"chatwoot_conversation_id": conversation_id,
				"phone": phone,
				"status": "OPEN",
			}
		).insert(ignore_permissions=True)

	ok, message_id, err = chatwoot.send_template_message(conversation_id, template_name, category, language, params)
	if ok:
		# The raw template body text lives in Chatwoot, not locally — a
		# short, readable stand-in is stored in the local mirror instead of
		# re-fetching Chatwoot's template list just to render one preview.
		preview = f"[{template_name}] " + " | ".join(params) if params else f"[{template_name}]"
		_record_outbound_whatsapp_message(conversation_id, message_id, preview)
	return ok, message_id, err


def _record_outbound_whatsapp_message(chatwoot_conversation_id: str, chatwoot_message_id, message: str):
	convo_name = frappe.db.get_value(
		"TOB WhatsApp Conversation", {"chatwoot_conversation_id": chatwoot_conversation_id}, "name"
	)
	if not convo_name:
		return
	frappe.get_doc(
		{
			"doctype": "TOB WhatsApp Message",
			"conversation": convo_name,
			"chatwoot_message_id": chatwoot_message_id,
			"direction": "OUTBOUND",
			"message_type": "TEXT",
			"message": message,
			"status": "SENT",
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value(
		"TOB WhatsApp Conversation",
		convo_name,
		{"last_message_at": now_datetime(), "last_message_preview": message[:140]},
	)


def _render_merge_tags(text: str, values: dict) -> str:
	"""Literal `{{first_name}}`/`{{last_name}}`/`{{email}}` substitution for
	email content — deliberately plain string replacement, not Jinja
	(`frappe.render_template`), matching this module's "keep v1 simple"
	principle: exactly 3 known tokens, no arbitrary template logic a
	campaign body could otherwise exploit. Missing values become an empty
	string rather than leaving the raw token visible."""
	if not text:
		return text
	for key, value in values.items():
		text = text.replace("{{" + key + "}}", value or "")
	return text


def _already_sent(campaign_id: str, user: str, channel: str) -> bool:
	"""Decision 14's minimum frequency-protection rule: a given campaign
	cannot send to the same user on the same channel twice. Reuses the
	existing TOB Notification Send Log table (now with a `channel` field)
	rather than a parallel one — keyed on (event_code=campaign_id, user,
	channel). No retry path exists in `_process_recipient` above (a FAILED
	channel simply stays FAILED), so this guard only ever matters for a
	genuine concurrent-worker race, not normal single-pass processing."""
	return bool(
		frappe.db.exists(
			"TOB Notification Send Log", {"user": user, "event_code": campaign_id, "channel": channel}
		)
	)


def _record_channel_send(campaign_id: str, user: str, channel: str, tracked: int = 0) -> str:
	doc = frappe.get_doc(
		{
			"doctype": "TOB Notification Send Log",
			"user": user,
			"event_code": campaign_id,
			"channel": channel,
			"sent_at": now_datetime(),
			"tracked": tracked,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _finalize_if_done(doc):
	still_pending = frappe.get_all(
		"TOB Communication Campaign Recipient",
		filters={"campaign": doc.name},
		or_filters={"push_status": "QUEUED", "email_status": "QUEUED", "whatsapp_status": "QUEUED"},
		limit_page_length=1,
	)
	if still_pending:
		return

	failed_exists = frappe.get_all(
		"TOB Communication Campaign Recipient",
		filters={"campaign": doc.name},
		or_filters={"push_status": "FAILED", "email_status": "FAILED", "whatsapp_status": "FAILED"},
		limit_page_length=1,
	)
	sent_exists = frappe.get_all(
		"TOB Communication Campaign Recipient",
		filters={"campaign": doc.name},
		or_filters={"push_status": "SENT", "email_status": "SENT", "whatsapp_status": "SENT"},
		limit_page_length=1,
	)

	if failed_exists and sent_exists:
		doc.status = "PARTIALLY_SENT"
	elif failed_exists and not sent_exists:
		doc.status = "FAILED"
	else:
		doc.status = "COMPLETED"
	doc.completed_at = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()
