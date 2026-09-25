"""Post & comment management for the Truth of Bible Facebook Page and its linked
Instagram account — direct Meta Graph API calls, no Buffer.

What the admin app can do through here: list posts per platform, delete a
post, list comments and replies, comment as the Page, reply to a comment,
delete a comment. Every call needs a specific permission on the Page token;
`get_status()` reads the token's own scopes (debug_token) so the app can show
exactly which actions are available instead of failing on tap. Verified live
(2026-09-25): listing Facebook posts works via /published_posts with
pages_read_engagement, but reading a Facebook post's comments needs
pages_read_user_content, and writing comments needs pages_manage_engagement.
Instagram media deletion is supported (instagram_manage_contents, Instagram
API with Facebook Login only; not single items inside a carousel).

The token comes from TOB Meta Connection (social/meta_connection.py), its
only home; permissions come from that record's daily check.

Every delete is recorded in Frappe's Activity Log (who, what, when): deletes
on Facebook/Instagram can't be undone.
"""

import frappe
import requests
from frappe import _
from frappe.utils import cint

from truth_of_bible.communication.auth import require_admin
from truth_of_bible.social import meta_connection

_GRAPH = "https://graph.facebook.com/v23.0"
_TIMEOUT = 30
_PLATFORMS = ("facebook", "instagram")
_MAX_TEXT = 2200  # Instagram's comment/caption limit; Facebook allows more

# capability -> scopes the Page token needs for it
CAPABILITIES = {
	"list_facebook_posts": ("pages_read_engagement",),
	"read_facebook_comments": ("pages_read_user_content",),
	"write_facebook_comments": ("pages_manage_engagement",),
	"delete_facebook_post": ("pages_manage_posts",),
	"list_instagram_posts": ("instagram_basic",),
	"read_instagram_comments": ("instagram_basic", "instagram_manage_comments"),
	"write_instagram_comments": ("instagram_basic", "instagram_manage_comments"),
	"delete_instagram_post": ("instagram_basic", "instagram_manage_contents"),
}


# ---------------------------------------------------------------------------
# Graph client

def _config():
	return meta_connection.page_id(), meta_connection.page_token()


def _graph(method, path, params=None, data=None):
	_, token = _config()
	try:
		response = requests.request(method, f"{_GRAPH}/{path}", params={**(params or {}), "access_token": token},
			data=data, timeout=_TIMEOUT)
	except requests.RequestException as e:
		frappe.throw(_("Couldn't reach Facebook: {0}").format(type(e).__name__), frappe.ValidationError)
	try:
		body = response.json()
	except ValueError:
		body = {}
	if response.status_code >= 400 or "error" in body:
		error = body.get("error") or {}
		# Meta's error text never contains the token; the path has no secrets either.
		frappe.log_error(title="Meta Graph API error", message=f"{method} {path}: {error or response.text[:1000]}")
		frappe.throw(_("Facebook said: {0}").format(error.get("message") or f"HTTP {response.status_code}"),
			frappe.ValidationError)
	return body


def _scopes():
	granted = meta_connection.scopes()
	if not granted and meta_connection.status()["has_token"]:
		meta_connection.check_connection()  # first use: nothing recorded yet
		granted = meta_connection.scopes()
	return granted


def _capabilities():
	scopes = _scopes()
	return {cap: all(s in scopes for s in needed) for cap, needed in CAPABILITIES.items()}


def _require(capability):
	if not _capabilities().get(capability):
		frappe.throw(_("The Facebook token is missing permission {0}. Regenerate it with that permission and update "
			"it in the Social Automation overview.").format(", ".join(CAPABILITIES[capability])),
			frappe.PermissionError)


def _ig_account():
	return meta_connection.instagram_account_id()


def _platform(platform):
	if platform not in _PLATFORMS:
		frappe.throw(_("Unknown platform: {0}").format(platform), frappe.ValidationError)
	return platform


def _text(message):
	message = (message or "").strip()
	if not message:
		frappe.throw(_("Write something first."), frappe.ValidationError)
	if len(message) > _MAX_TEXT:
		frappe.throw(_("Keep it under {0} characters.").format(_MAX_TEXT), frappe.ValidationError)
	return message


def _audit(subject):
	frappe.get_doc({
		"doctype": "Activity Log",
		"subject": subject[:140],
		"user": frappe.session.user,
		"full_name": frappe.utils.get_fullname(frappe.session.user),
		"status": "Success",
	}).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Normalisers — one shape for both platforms, so the app has one model.

def _fb_post(p, with_counts):
	return {
		"id": p.get("id"),
		"platform": "facebook",
		"text": p.get("message") or "",
		"created_at": p.get("created_time"),
		"permalink": p.get("permalink_url"),
		"image_url": p.get("full_picture"),
		"comments_count": ((p.get("comments") or {}).get("summary") or {}).get("total_count") if with_counts else None,
		"likes_count": ((p.get("reactions") or {}).get("summary") or {}).get("total_count") if with_counts else None,
	}


def _ig_post(m):
	return {
		"id": m.get("id"),
		"platform": "instagram",
		"text": m.get("caption") or "",
		"created_at": m.get("timestamp"),
		"permalink": m.get("permalink"),
		"image_url": m.get("thumbnail_url") if m.get("media_type") == "VIDEO" else m.get("media_url"),
		"media_type": m.get("media_type"),
		"comments_count": m.get("comments_count"),
		"likes_count": m.get("like_count"),
	}


def _fb_comment(c):
	return {
		"id": c.get("id"),
		"text": c.get("message") or "",
		"author": (c.get("from") or {}).get("name") or "Facebook user",
		"created_at": c.get("created_time"),
		"like_count": c.get("like_count"),
		"reply_count": c.get("comment_count"),
		"can_delete": bool(c.get("can_remove", True)),
		"is_hidden": bool(c.get("is_hidden")),
	}


def _ig_comment(c):
	return {
		"id": c.get("id"),
		"text": c.get("text") or "",
		"author": c.get("username") or "Instagram user",
		"created_at": c.get("timestamp"),
		"like_count": c.get("like_count"),
		"reply_count": len(((c.get("replies") or {}).get("data")) or []) if "replies" in c else None,
		"can_delete": True,
		"is_hidden": bool(c.get("hidden")),
	}


def _page(result, items):
	cursors = (result.get("paging") or {}).get("cursors") or {}
	has_next = bool((result.get("paging") or {}).get("next"))
	return {"items": items, "next": cursors.get("after") if has_next else None}


_FB_COMMENT_FIELDS = "id,message,from{id,name},created_time,like_count,comment_count,can_remove,is_hidden"
_IG_COMMENT_FIELDS = "id,text,username,timestamp,like_count,hidden"


# ---------------------------------------------------------------------------
# Admin API (System Manager only, like the rest of Social Intelligence)

@frappe.whitelist(methods=["GET"])
def get_status(refresh=0):
	"""Is Facebook connected, which account IDs, and which actions the token allows."""
	require_admin()
	conn = meta_connection.check_connection() if cint(refresh) else meta_connection.status()
	if not conn["has_token"] or conn["status"] == "Invalid":
		return {"configured": False, "capabilities": {c: False for c in CAPABILITIES},
			"missing_scopes": conn.get("missing_scopes") or [], "status_message": conn.get("status_message"),
			"required": {c: list(s) for c, s in CAPABILITIES.items()}}
	granted = _scopes()
	return {
		"configured": True,
		"page_id": conn["page_id"],
		"instagram_account_id": conn["instagram_account_id"],
		"capabilities": {cap: all(s in granted for s in needed) for cap, needed in CAPABILITIES.items()},
		"missing_scopes": sorted({s for needed in CAPABILITIES.values() for s in needed if s not in granted}),
		"status_message": conn.get("status_message"),
		"required": {c: list(s) for c, s in CAPABILITIES.items()},
	}


@frappe.whitelist(methods=["GET"])
def list_posts(platform, after=None, limit=10):
	require_admin()
	limit = max(1, min(cint(limit) or 10, 25)) if limit else 10
	if _platform(platform) == "facebook":
		_require("list_facebook_posts")
		page_id, _token = _config()
		with_counts = _capabilities()["read_facebook_comments"]
		fields = "id,message,created_time,permalink_url,full_picture"
		if with_counts:
			fields += ",comments.summary(true).limit(0),reactions.summary(true).limit(0)"
		params = {"fields": fields, "limit": limit}
		if after:
			params["after"] = after
		result = _graph("GET", f"{page_id}/published_posts", params)
		return _page(result, [_fb_post(p, with_counts) for p in result.get("data") or []])

	_require("list_instagram_posts")
	params = {"fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,comments_count,like_count",
		"limit": limit}
	if after:
		params["after"] = after
	result = _graph("GET", f"{_ig_account()}/media", params)
	return _page(result, [_ig_post(m) for m in result.get("data") or []])


@frappe.whitelist(methods=["POST"])
def delete_post(platform, post_id):
	require_admin()
	if _platform(platform) == "facebook":
		_require("delete_facebook_post")
		page_id, _token = _config()
		if not str(post_id).startswith(f"{page_id}_"):
			frappe.throw(_("That isn't a post on the Truth of Bible Page."), frappe.ValidationError)
	else:
		_require("delete_instagram_post")
	_graph("DELETE", str(post_id))
	_audit(f"Deleted {platform} post {post_id}")
	return {"deleted": True}


@frappe.whitelist(methods=["GET"])
def list_comments(platform, post_id, after=None):
	"""Top-level comments on a post, newest first."""
	require_admin()
	if _platform(platform) == "facebook":
		_require("read_facebook_comments")
		params = {"fields": _FB_COMMENT_FIELDS, "filter": "toplevel", "order": "reverse_chronological", "limit": 25}
		if after:
			params["after"] = after
		result = _graph("GET", f"{post_id}/comments", params)
		return _page(result, [_fb_comment(c) for c in result.get("data") or []])

	_require("read_instagram_comments")
	params = {"fields": _IG_COMMENT_FIELDS + ",replies{id}", "limit": 25}
	if after:
		params["after"] = after
	result = _graph("GET", f"{post_id}/comments", params)
	return _page(result, [_ig_comment(c) for c in result.get("data") or []])


@frappe.whitelist(methods=["GET"])
def list_replies(platform, comment_id):
	require_admin()
	if _platform(platform) == "facebook":
		_require("read_facebook_comments")
		result = _graph("GET", f"{comment_id}/comments", {"fields": _FB_COMMENT_FIELDS, "limit": 50})
		return _page(result, [_fb_comment(c) for c in result.get("data") or []])
	_require("read_instagram_comments")
	result = _graph("GET", f"{comment_id}/replies", {"fields": _IG_COMMENT_FIELDS, "limit": 50})
	return _page(result, [_ig_comment(c) for c in result.get("data") or []])


@frappe.whitelist(methods=["POST"])
def add_comment(platform, post_id, message):
	"""Comment on a post as the Page (Facebook) / the business account (Instagram)."""
	require_admin()
	_require("write_facebook_comments" if _platform(platform) == "facebook" else "write_instagram_comments")
	result = _graph("POST", f"{post_id}/comments", data={"message": _text(message)})
	return {"id": result.get("id")}


@frappe.whitelist(methods=["POST"])
def reply_to_comment(platform, comment_id, message):
	require_admin()
	if _platform(platform) == "facebook":
		_require("write_facebook_comments")
		result = _graph("POST", f"{comment_id}/comments", data={"message": _text(message)})
	else:
		_require("write_instagram_comments")
		# Instagram has a distinct replies edge; /comments on a comment isn't a reply there.
		result = _graph("POST", f"{comment_id}/replies", data={"message": _text(message)})
	return {"id": result.get("id")}


@frappe.whitelist(methods=["POST"])
def delete_comment(platform, comment_id):
	require_admin()
	_require("write_facebook_comments" if _platform(platform) == "facebook" else "write_instagram_comments")
	_graph("DELETE", str(comment_id))
	_audit(f"Deleted {platform} comment {comment_id}")
	return {"deleted": True}
