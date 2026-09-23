"""Social Intelligence — Phase 1's dashboard + Quick Create Post.
Deliberately minimal: no AI recommendation engine yet (a later phase per
the Phase 1 plan) — `top_actions` is a plain rule, and every source
besides Buffer reports `connected: false` honestly rather than
fabricating numbers, per the product spec's explicit "never fabricate"
requirement.

Every whitelisted method here starts with `require_admin()` — the same
System-Manager-only boundary every Communication Center method already
uses (communication/auth.py), reused rather than duplicated.
"""

import json

import frappe
from frappe.utils import get_datetime, now_datetime, today

from truth_of_bible.communication.auth import require_admin
from truth_of_bible.social import buffer as buffer_mod
from truth_of_bible.social import google_oauth
from truth_of_bible.social import youtube as youtube_mod

_ACTIONS = ("draft", "schedule", "publish")


def _parse_json(value, default):
	if isinstance(value, str):
		try:
			return json.loads(value) if value else default
		except Exception:
			return default
	return value if value is not None else default


@frappe.whitelist(methods=["GET"])
def get_dashboard():
	require_admin()

	channels = buffer_mod.list_channels()
	buffer_connected = channels is not None
	youtube_summary = youtube_mod.get_channel_summary()
	youtube_connected = youtube_summary is not None

	posted_today = bool(
		frappe.db.exists(
			"TOB Social Post",
			{"status": "SENT", "published_at": [">=", today()]},
		)
	)

	top_actions = []
	if not buffer_connected:
		top_actions.append({
			"title": "Connect Buffer",
			"why": "Add a Buffer API token to publish to Facebook, Instagram and Google Business Profile.",
			"action": "connect_buffer",
		})
	elif not posted_today:
		top_actions.append({
			"title": "Create today's post",
			"why": "No post has gone out today.",
			"action": "create_post",
		})

	return {
		"sources": {
			"buffer": {
				"connected": buffer_connected,
				"channel_count": len(channels) if channels else 0,
			},
			"youtube": {
				"connected": youtube_connected,
				**({"channel_summary": youtube_summary} if youtube_connected else {}),
			},
			"ga4": {"connected": False},
			"app_analytics": {"connected": False},
			# Whether the *connector* itself is linked — GA4/deeper YouTube
			# Analytics still report false above until their own data-fetch
			# is actually built on top of this connection (never fabricate
			# "connected" for a source with no real query behind it yet).
			"google_account": {"connected": google_oauth.is_connected()},
		},
		"channels": channels or [],
		"top_actions": top_actions,
	}


@frappe.whitelist(methods=["GET"])
def get_google_connect_url():
	require_admin()
	return {"url": google_oauth.get_connect_url()}


@frappe.whitelist(methods=["GET"])
def list_channels():
	require_admin()
	return buffer_mod.list_channels() or []


@frappe.whitelist(methods=["GET"])
def list_posts(limit_page_length=20, limit_start=0):
	require_admin()
	rows = frappe.get_all(
		"TOB Social Post",
		fields=[
			"name", "content", "platforms", "status",
			"scheduled_at", "published_at", "error", "creation",
		],
		order_by="creation desc",
		limit_page_length=int(limit_page_length),
		limit_start=int(limit_start),
	)

	# Buffer's own channel names, so a post's stored channel ids display
	# as "Facebook · Truth of Bible" instead of a raw id — same channel
	# list get_dashboard() already fetches, just resolved here too since
	# this is its own independent call.
	channels_by_id = {c["buffer_channel_id"]: c for c in (buffer_mod.list_channels() or [])}

	posts = []
	for row in rows:
		platform_ids = _parse_json(row.platforms, [])
		posts.append({
			"post_id": row.name,
			"content": row.content,
			"status": row.status,
			"platforms": [
				{
					"channel_id": pid,
					"platform": (channels_by_id.get(pid) or {}).get("platform", ""),
					"channel_name": (channels_by_id.get(pid) or {}).get("channel_name", ""),
				}
				for pid in platform_ids
			],
			"scheduled_at": row.scheduled_at,
			"published_at": row.published_at,
			"error": row.error,
			"created_at": row.creation,
		})
	return {"posts": posts, "total_count": frappe.db.count("TOB Social Post")}


@frappe.whitelist(methods=["POST"])
def create_post(channels, text, action="draft", scheduled_at=None):
	require_admin()
	channel_ids = _parse_json(channels, [])
	text = (text or "").strip()

	if not channel_ids:
		frappe.throw(frappe._("Choose at least one channel."), frappe.ValidationError)
	if not text:
		frappe.throw(frappe._("Write something to post."), frappe.ValidationError)
	if action not in _ACTIONS:
		frappe.throw(frappe._("Invalid action."), frappe.ValidationError)
	if action == "schedule" and not scheduled_at:
		frappe.throw(frappe._("scheduled_at is required to schedule a post."), frappe.ValidationError)

	if action == "publish":
		result = buffer_mod.publish_post(channel_ids, text)
		status = "SENT"
	elif action == "schedule":
		result = buffer_mod.schedule_post(
			channel_ids, text, get_datetime(scheduled_at).timestamp()
		)
		status = "SCHEDULED"
	else:
		result = buffer_mod.create_draft(channel_ids, text)
		status = "DRAFT"

	doc = frappe.get_doc(
		{
			"doctype": "TOB Social Post",
			"content": text,
			"platforms": json.dumps(channel_ids),
			"status": status,
			"buffer_post_id": (result.get("buffer_post_ids") or [None])[0],
			"scheduled_at": get_datetime(scheduled_at) if scheduled_at else None,
			"published_at": now_datetime() if status == "SENT" else None,
		}
	)
	doc.insert(ignore_permissions=True)
	return {"post_id": doc.name, "status": status}
