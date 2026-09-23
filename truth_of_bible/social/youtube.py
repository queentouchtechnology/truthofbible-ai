"""YouTube Data API v3 — Phase 2's channel-summary card. Uses a plain API
key (site_config.json's `youtube_public_key`), not OAuth: subscriber/view/
video counts are public channel data, so no consent flow is needed for
this. Deeper YouTube Analytics (watch-time trends, top videos, traffic
sources, audience retention) is private, per-owner data that genuinely
does need OAuth — deliberately not built yet (see the Phase 2 plan's
deferred OAuth design, kept for when GA4 or that data is prioritized).

The channel to report on is identified by `youtube_channel_id` in
site_config.json — either a channel id (starts with "UC") or an @handle.
"""

import frappe
import requests

_BASE_URL = "https://www.googleapis.com/youtube/v3/channels"
_TIMEOUT = 15


def _config():
	config = frappe.get_site_config()
	return config.get("youtube_public_key"), config.get("youtube_channel_id")


def is_configured() -> bool:
	key, channel = _config()
	return bool(key and channel)


def get_channel_summary():
	"""Returns None when the API key/channel isn't configured or the call
	fails — same "None = not connected" convention as
	buffer.list_channels()."""
	key, channel = _config()
	if not key or not channel:
		return None

	params = {"part": "snippet,statistics", "key": key}
	channel = channel.strip()
	if channel.startswith("@"):
		params["forHandle"] = channel
	elif channel.startswith("UC"):
		params["id"] = channel
	else:
		# Admins commonly paste a handle without the leading "@" —
		# treat anything else as a handle rather than erroring, since a
		# real channel id always starts with "UC".
		params["forHandle"] = f"@{channel}"

	try:
		response = requests.get(_BASE_URL, params=params, timeout=_TIMEOUT)
		response.raise_for_status()
		items = response.json().get("items") or []
	except requests.RequestException:
		return None

	if not items:
		return None

	channel_data = items[0]
	stats = channel_data.get("statistics") or {}
	snippet = channel_data.get("snippet") or {}
	return {
		"title": snippet.get("title") or "",
		"subscriber_count": int(stats.get("subscriberCount") or 0),
		"view_count": int(stats.get("viewCount") or 0),
		"video_count": int(stats.get("videoCount") or 0),
	}
