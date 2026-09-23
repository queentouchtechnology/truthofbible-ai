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
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import frappe
from frappe.utils import get_datetime, now_datetime, today

from truth_of_bible.communication.auth import require_admin
from truth_of_bible.social import app_analytics as app_analytics_mod
from truth_of_bible.social import buffer as buffer_mod
from truth_of_bible.social import ga4 as ga4_mod
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
	ga4_summary = ga4_mod.get_website_summary()
	ga4_connected = ga4_summary is not None
	app_summary = app_analytics_mod.get_app_summary()
	app_connected = app_summary is not None

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
			"ga4": {
				"connected": ga4_connected,
				**({"website_summary": ga4_summary} if ga4_connected else {}),
			},
			"app_analytics": {
				"connected": app_connected,
				**({"app_summary": app_summary} if app_connected else {}),
			},
			# Whether the shared connector itself is linked — deeper YouTube
			# Analytics (watch time/traffic/top videos) is the one private
			# source still not built on top of this connection yet.
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
			"name", "content", "platforms", "status", "image_url", "video_url",
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
			"image_url": row.image_url,
			"video_url": row.video_url,
			"scheduled_at": row.scheduled_at,
			"published_at": row.published_at,
			"error": row.error,
			"created_at": row.creation,
		})
	return {"posts": posts, "total_count": frappe.db.count("TOB Social Post")}


@frappe.whitelist(methods=["POST"])
def create_post(
	channels,
	text,
	action="draft",
	scheduled_at=None,
	image_url=None,
	video_url=None,
	instagram_tags=None,
	thread_texts=None,
):
	require_admin()
	channel_ids = _parse_json(channels, [])
	text = (text or "").strip()
	image_url = (image_url or "").strip() or None
	video_url = (video_url or "").strip() or None
	instagram_tags = [t for t in _parse_json(instagram_tags, []) if t]
	thread_texts = [t for t in _parse_json(thread_texts, []) if t]

	if not channel_ids:
		frappe.throw(frappe._("Choose at least one channel."), frappe.ValidationError)
	if not text:
		frappe.throw(frappe._("Write something to post."), frappe.ValidationError)
	if action not in _ACTIONS:
		frappe.throw(frappe._("Invalid action."), frappe.ValidationError)
	if action == "schedule" and not scheduled_at:
		frappe.throw(frappe._("scheduled_at is required to schedule a post."), frappe.ValidationError)

	# Resolves each channel id to its Buffer `service` (instagram/twitter/…)
	# so buffer_mod can decide whether Instagram-tag metadata or a
	# service-scoped thread actually applies — a post to a non-Instagram
	# channel just never gets the instagram metadata block, no separate
	# per-channel calls needed for this lookup.
	channels_by_id = {c["buffer_channel_id"]: c for c in (buffer_mod.list_channels() or [])}
	channel_specs = [
		{"id": cid, "service": (channels_by_id.get(cid) or {}).get("platform", "")}
		for cid in channel_ids
	]

	post_kwargs = dict(
		image_url=image_url,
		video_url=video_url,
		instagram_tags=instagram_tags or None,
		thread_texts=thread_texts or None,
	)

	if action == "publish":
		result = buffer_mod.publish_post(channel_specs, text, **post_kwargs)
		status = "SENT"
	elif action == "schedule":
		result = buffer_mod.schedule_post(
			channel_specs, text, get_datetime(scheduled_at).timestamp(), **post_kwargs
		)
		status = "SCHEDULED"
	else:
		result = buffer_mod.create_draft(channel_specs, text, **post_kwargs)
		status = "DRAFT"

	doc = frappe.get_doc(
		{
			"doctype": "TOB Social Post",
			"content": text,
			"platforms": json.dumps(channel_ids),
			"status": status,
			"image_url": image_url,
			"video_url": video_url,
			"buffer_post_id": (result.get("buffer_post_ids") or [None])[0],
			"scheduled_at": get_datetime(scheduled_at) if scheduled_at else None,
			"published_at": now_datetime() if status == "SENT" else None,
		}
	)
	doc.insert(ignore_permissions=True)
	return {"post_id": doc.name, "status": status}


def _format_buffer_posts(nodes, channels_by_id, with_metrics=False):
	"""Shapes Buffer's own `posts` query nodes (see buffer.py's
	`_list_posts_by_status`) the same way `list_posts()` above already
	shapes local `TOB Social Post` rows — resolved platform/channel name,
	not a raw Buffer channel id — so both lists render with one Flutter
	model."""
	if not nodes:
		return []
	rows = []
	for node in nodes:
		ch = channels_by_id.get(node.get("channelId")) or {}
		row = {
			"buffer_post_id": node.get("id"),
			"content": node.get("text"),
			"status": node.get("status"),
			"platform": ch.get("platform", ""),
			"channel_name": ch.get("channel_name", ""),
			"created_at": node.get("createdAt"),
			"due_at": node.get("dueAt"),
		}
		if with_metrics:
			row["metrics"] = node.get("metrics") or []
		rows.append(row)
	return rows


@frappe.whitelist(methods=["GET"])
def get_scheduled_posts():
	require_admin()
	nodes = buffer_mod.get_scheduled_posts()
	if nodes is None:
		return {"posts": []}
	channels_by_id = {c["buffer_channel_id"]: c for c in (buffer_mod.list_channels() or [])}
	return {"posts": _format_buffer_posts(nodes, channels_by_id)}


@frappe.whitelist(methods=["GET"])
def get_post_performance():
	require_admin()
	nodes = buffer_mod.get_posts_with_metrics()
	if nodes is None:
		return {"posts": [], "quarterly_report": {"posts_count": 0, "totals": {}}}
	channels_by_id = {c["buffer_channel_id"]: c for c in (buffer_mod.list_channels() or [])}
	formatted = _format_buffer_posts(nodes, channels_by_id, with_metrics=True)

	# A quarterly rollup computed from Buffer's own real per-post metrics
	# rather than a separate "quarterly report" Buffer query — that
	# query's exact GraphQL shape isn't published anywhere this app has
	# seen, so summing what's already fetched here is the honest option
	# rather than guessing a second query that might silently 400.
	#
	# Buffer's createdAt is an ISO 8601 string with a "Z" suffix, which
	# parses as timezone-aware UTC; frappe's now_datetime()/add_to_date()
	# return naive datetimes (Frappe's own convention — DB times are naive,
	# in the site's system timezone). Comparing the two raw raises
	# "can't compare offset-naive and offset-aware datetimes" (a real
	# production error) — every parsed timestamp is normalized to naive
	# UTC before comparing, and the cutoff is computed in UTC too rather
	# than via frappe's local-time now_datetime().
	quarter_cutoff = datetime.now(dt_timezone.utc).replace(tzinfo=None) - timedelta(days=90)
	totals = {}
	posts_in_quarter = 0
	for row in formatted:
		created_at = row.get("created_at")
		if created_at:
			parsed = get_datetime(created_at)
			if parsed.tzinfo is not None:
				parsed = parsed.astimezone(dt_timezone.utc).replace(tzinfo=None)
			if parsed < quarter_cutoff:
				continue
		posts_in_quarter += 1
		for metric in row.get("metrics", []):
			key = metric.get("name") or metric.get("type") or "metric"
			totals[key] = totals.get(key, 0) + (metric.get("value") or 0)

	return {
		"posts": formatted,
		"quarterly_report": {"posts_count": posts_in_quarter, "totals": totals},
	}
