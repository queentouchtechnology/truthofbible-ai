"""Community (Discourse) sign-in from the existing Frappe user.

Two entry points, one identity (the Frappe user, linked to Discourse by
email — never a second password or a separately-created account):

- `sso_login` is Discourse's DiscourseConnect URL. A browser sent here by
  Discourse is bounced through Frappe login if needed, then sent back signed.
- `get_community_credentials` is what the mobile app calls (Frappe session
  auth). It links/creates the member's Discourse account from their Frappe
  identity and hands back a Discourse API key that can act ONLY as that
  member — so the app no longer carries an all-users admin key.

Config (site_config.json, never hardcoded, never sent to a client):
	discourse_url             e.g. "https://community.truthofbible.org"
	discourse_api_key         Discourse admin API key ("All users" scope)
	discourse_connect_secret  DiscourseConnect secret (same one set in Discourse)
"""

import base64
import hashlib
import hmac
import re
from urllib.parse import parse_qs, urlencode

import frappe
import requests
from frappe import _
from frappe.utils import get_fullname
from frappe.utils.password import get_decrypted_password, set_encrypted_password

_TIMEOUT = 15
_KEY_FIELD = "discourse_api_key"
_KEY_ID_FIELD = "discourse_api_key_id"


def _config() -> dict:
	conf = frappe.get_site_config()
	url = (conf.get("discourse_url") or "").rstrip("/")
	admin_key = conf.get("discourse_api_key")
	secret = conf.get("discourse_connect_secret")
	if not (url and admin_key and secret):
		frappe.log_error(
			title="Community SSO config",
			message="site_config.json needs discourse_url, discourse_api_key and discourse_connect_secret.",
		)
		frappe.throw(_("Community sign-in is not configured yet."))
	return {"url": url, "admin_key": admin_key, "secret": secret}


def _sign(secret: str, payload_b64: str) -> str:
	return hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()


def _encode(secret: str, fields: dict) -> tuple[str, str]:
	payload_b64 = base64.b64encode(urlencode(fields).encode()).decode()
	return payload_b64, _sign(secret, payload_b64)


def _username_for(user: str) -> str:
	"""Discourse-safe username: the Frappe username if set, else the email local part."""
	raw = frappe.db.get_value("User", user, "username") or user.split("@")[0]
	clean = re.sub(r"[^A-Za-z0-9_.-]", "_", raw).strip("._-")
	if len(clean) < 3:
		clean = (clean + "_user")[:20]
	return clean[:20]


def _identity_fields(user: str) -> dict:
	return {
		"external_id": user,
		"email": frappe.db.get_value("User", user, "email") or user,
		"username": _username_for(user),
		"name": get_fullname(user),
		"require_activation": "false",
		"suppress_welcome_message": "true",
	}


def _admin_headers(cfg: dict, username: str = "system") -> dict:
	return {"Api-Key": cfg["admin_key"], "Api-Username": username, "Accept": "application/json"}


# --- Browser flow: Discourse -> Frappe login -> Discourse ---------------


@frappe.whitelist(allow_guest=True, methods=["GET"])
def sso_login(sso: str = "", sig: str = ""):
	cfg = _config()
	if not sso or not sig or not hmac.compare_digest(_sign(cfg["secret"], sso), sig):
		frappe.throw(_("Invalid sign-in request."), frappe.PermissionError)

	if frappe.session.user == "Guest":
		here = "/api/method/truth_of_bible.api.community_sso.sso_login?" + urlencode({"sso": sso, "sig": sig})
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = "/login?" + urlencode({"redirect-to": here})
		return

	incoming = parse_qs(base64.b64decode(sso).decode())
	nonce = (incoming.get("nonce") or [""])[0]
	return_url = (incoming.get("return_sso_url") or [""])[0]
	if not return_url.startswith(cfg["url"]):
		frappe.throw(_("Invalid return address."), frappe.PermissionError)

	fields = {"nonce": nonce, **_identity_fields(frappe.session.user)}
	payload_b64, signature = _encode(cfg["secret"], fields)
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = f"{return_url}?" + urlencode({"sso": payload_b64, "sig": signature})


# --- Mobile flow: Frappe session -> per-member Discourse API key ---------


def _sync_user(cfg: dict, user: str) -> dict:
	"""Create-or-link the Discourse account for this Frappe user (matched by email)."""
	fields = {"nonce": frappe.generate_hash(length=16), **_identity_fields(user)}
	payload_b64, signature = _encode(cfg["secret"], fields)
	r = requests.post(
		f"{cfg['url']}/admin/users/sync_sso",
		data={"sso": payload_b64, "sig": signature},
		headers=_admin_headers(cfg),
		timeout=_TIMEOUT,
	)
	if r.status_code != 200:
		frappe.log_error(title="Community SSO sync", message=f"{r.status_code}: {r.text[:500]}")
		frappe.throw(_("Could not link your community account. Please try again later."))
	data = r.json()
	if not data.get("id"):
		lookup = requests.get(
			f"{cfg['url']}/u/by-external/{user}.json", headers=_admin_headers(cfg), timeout=_TIMEOUT
		)
		data = (lookup.json() or {}).get("user", {}) if lookup.status_code == 200 else {}
	if not data.get("username"):
		frappe.throw(_("Could not link your community account. Please try again later."))
	return data


def _revoke_key(cfg: dict, key_id) -> None:
	try:
		requests.post(f"{cfg['url']}/admin/api/keys/{key_id}/revoke", headers=_admin_headers(cfg), timeout=_TIMEOUT)
	except Exception:
		frappe.log_error(title="Community SSO revoke key", message=frappe.get_traceback())


def _issue_key(cfg: dict, user: str, username: str) -> str:
	r = requests.post(
		f"{cfg['url']}/admin/api/keys",
		json={"key": {"description": f"Mobile app - {user}", "username": username}},
		headers=_admin_headers(cfg),
		timeout=_TIMEOUT,
	)
	if r.status_code != 200:
		frappe.log_error(title="Community SSO key", message=f"{r.status_code}: {r.text[:500]}")
		frappe.throw(_("Could not open your community session. Please try again later."))
	key = r.json().get("key", {})
	old_id = get_decrypted_password("User", user, _KEY_ID_FIELD, raise_exception=False)
	set_encrypted_password("User", user, key["key"], _KEY_FIELD)
	set_encrypted_password("User", user, str(key["id"]), _KEY_ID_FIELD)
	if old_id:
		_revoke_key(cfg, old_id)
	return key["key"]


def _key_still_valid(cfg: dict, key: str, username: str) -> bool:
	try:
		r = requests.get(
			f"{cfg['url']}/session/current.json",
			headers={"Api-Key": key, "Api-Username": username, "Accept": "application/json"},
			timeout=_TIMEOUT,
		)
		return r.status_code == 200
	except Exception:
		return False


@frappe.whitelist(methods=["POST"])
def get_community_credentials(refresh: int = 0) -> dict:
	"""Session-authenticated (the real logged-in member). Returns the member's
	own Discourse username + an API key bound to that username only."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in to use the community."), frappe.PermissionError)

	cfg = _config()
	account = _sync_user(cfg, user)
	username = account["username"]

	key = None if int(refresh or 0) else get_decrypted_password("User", user, _KEY_FIELD, raise_exception=False)
	if not key or not _key_still_valid(cfg, key, username):
		key = _issue_key(cfg, user, username)
	return {"username": username, "api_key": key, "base_url": cfg["url"]}


@frappe.whitelist(methods=["POST"])
def get_admin_community_credentials() -> dict:
	"""For the in-app Community admin module only — a `system`-scoped key,
	restricted to Frappe System Managers (Discourse staff status is separate
	from the Frappe admin role)."""
	frappe.only_for("System Manager")
	cfg = _config()
	return {"username": "system", "api_key": cfg["admin_key"], "base_url": cfg["url"]}


# --- Edits: this Discourse's regular accounts get can_edit=false on their own
# posts (trust-level setting), so edits run as `system` — but only after the
# backend has confirmed the caller really authored the post/topic. ----------


def _own_username(cfg: dict) -> str:
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in to use the community."), frappe.PermissionError)
	return _sync_user(cfg, user)["username"]


def _admin_request(cfg: dict, method: str, path: str, **kwargs):
	r = requests.request(method, f"{cfg['url']}{path}", headers=_admin_headers(cfg), timeout=_TIMEOUT, **kwargs)
	if r.status_code != 200:
		frappe.log_error(title="Community edit", message=f"{method} {path} -> {r.status_code}: {r.text[:500]}")
		frappe.throw(_("Could not save your changes. Please try again."))
	return r.json()


@frappe.whitelist(methods=["POST"])
def edit_post(post_id: int, raw: str) -> dict:
	cfg = _config()
	me = _own_username(cfg)
	post = _admin_request(cfg, "GET", f"/posts/{int(post_id)}.json")
	if (post.get("username") or "").lower() != me.lower():
		frappe.throw(_("You can only edit your own posts."), frappe.PermissionError)
	return _admin_request(cfg, "PUT", f"/posts/{int(post_id)}.json", json={"post": {"raw": raw}})


@frappe.whitelist(methods=["POST"])
def edit_topic(topic_id: int, title: str | None = None, tags=None) -> dict:
	cfg = _config()
	me = _own_username(cfg)
	topic = _admin_request(cfg, "GET", f"/t/{int(topic_id)}.json")
	author = ((topic.get("details") or {}).get("created_by") or {}).get("username") or ""
	if author.lower() != me.lower():
		frappe.throw(_("You can only edit your own topics."), frappe.PermissionError)
	body = {}
	if title is not None:
		body["title"] = title
	if tags is not None:
		body["tags"] = frappe.parse_json(tags) if isinstance(tags, str) else tags
	return _admin_request(cfg, "PUT", f"/t/-/{int(topic_id)}.json", json=body)
