"""The one home of the Meta (Facebook/Instagram) token — TOB Meta Connection.

Everything that talks to Meta gets its token from here:
- Manage Posts (social/meta_posts.py) calls `page_token()` directly;
- the outreach VPS worker receives the Page token in `get_worker_config`
  (blessing_automation.py) over HTTPS on each run, so it keeps no copy.

The stored token may be a System User token (recommended), a long-lived User
token, or a Page token. For System User / User tokens the Page token is
derived on demand (GET /{page-id}?fields=access_token) and cached for an hour.

`check_connection()` runs daily (hooks.py scheduler) and on demand from the
admin app. It verifies the token with debug_token, records type, expiry,
data-access expiry and permissions, and renews it where Meta supports that:

  token type                     | Meta behaviour (docs, verified 2026-09-25)      | what we do
  System User, non-expiring      | never expires, no refresh needed                | check only
  System User, 60-day expiring   | refreshable via oauth/access_token              | auto-renew within warn_days
                                 | (fb_exchange_token + app secret)                |
  User (long-lived, ~60 days)    | expired tokens can't be refreshed; the person   | try the same exchange while
                                 | must log in again                               | valid, verify, else warn
  Page from a User login         | never expires, but data access ends 90 days     | warn ahead; only the person
                                 | after the person last authorised the app        | re-authorising fixes it

Nothing here ever logs or returns a token to the admin app.
"""

import hashlib
from datetime import datetime, timezone

import frappe
import requests
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

from truth_of_bible.communication.auth import require_admin

SETTINGS = "TOB Meta Connection"
_GRAPH = "https://graph.facebook.com/v23.0"
_TIMEOUT = 30
_PAGE_TOKEN_CACHE = "tob_meta_page_token"
# What posting + Manage Posts need; anything missing is reported, not guessed.
REQUIRED_SCOPES = (
	"pages_manage_posts", "pages_read_engagement", "pages_read_user_content", "pages_manage_engagement",
	"instagram_basic", "instagram_content_publish", "instagram_manage_comments", "instagram_manage_contents",
)
# Fields safe to show in the admin app (never the token or the app secret).
_PUBLIC_FIELDS = ("page_id", "instagram_account_id", "app_id", "auto_renew", "warn_days", "status", "status_message",
	"token_type", "scopes", "expires_at", "data_access_expires_at", "last_checked", "last_renewed",
	"last_renewal_result")


# ---------------------------------------------------------------------------
# helpers

def _settings():
	return frappe.get_single(SETTINGS)


def _stored_token(settings=None):
	settings = settings or _settings()
	return settings.get_password("access_token", raise_exception=False) or ""


def _get(path, params):
	"""GET on the Graph API; returns the JSON body, raises frappe.ValidationError on errors (no token in text)."""
	try:
		response = requests.get(f"{_GRAPH}/{path}", params=params, timeout=_TIMEOUT)
	except requests.RequestException as e:
		frappe.throw(_("Couldn't reach Facebook: {0}").format(type(e).__name__), frappe.ValidationError)
	try:
		body = response.json()
	except ValueError:
		body = {}
	if response.status_code >= 400 or "error" in body:
		message = (body.get("error") or {}).get("message") or f"HTTP {response.status_code}"
		frappe.throw(_("Facebook said: {0}").format(message), frappe.ValidationError)
	return body


def _inspect(token):
	"""debug_token on the token itself (no app secret needed)."""
	return _get("debug_token", {"input_token": token, "access_token": token}).get("data") or {}


def _ts(value):
	return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None) if cint(value) > 0 else None


def _days_until(dt):
	if not dt:
		return None
	return (get_datetime(dt) - now_datetime()).total_seconds() / 86400


def _token_key(token):
	return hashlib.sha256(token.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# tokens for callers

def page_id():
	value = (_settings().page_id or "").strip()
	if not value:
		frappe.throw(_("Set the Facebook Page ID in TOB Meta Connection."), frappe.ValidationError)
	return value


def page_token():
	"""A Page access token for the configured Page, derived from the stored token when needed."""
	settings = _settings()
	token = _stored_token(settings)
	if not token:
		frappe.throw(_("Facebook isn't connected: add the access token in TOB Meta Connection."),
			frappe.ValidationError)
	if (settings.token_type or "").upper() == "PAGE":
		return token
	cache_key = f"{_PAGE_TOKEN_CACHE}:{_token_key(token)}"
	cached = frappe.cache().get_value(cache_key)
	if cached:
		return cached
	derived = _get(page_id(), {"fields": "access_token", "access_token": token}).get("access_token")
	if not derived:
		frappe.throw(_("This token can't act for the Facebook Page. Give the System User (or your account) access "
			"to the Page and regenerate it."), frappe.ValidationError)
	frappe.cache().set_value(cache_key, derived, expires_in_sec=3600)
	return derived


def instagram_account_id():
	settings = _settings()
	if settings.instagram_account_id:
		return settings.instagram_account_id
	found = ((_get(page_id(), {"fields": "instagram_business_account", "access_token": page_token()})
		.get("instagram_business_account")) or {}).get("id")
	if not found:
		frappe.throw(_("No Instagram business account is linked to the Facebook Page."), frappe.ValidationError)
	frappe.db.set_single_value(SETTINGS, "instagram_account_id", found, update_modified=False)
	return found


def scopes():
	return {s for s in (_settings().scopes or "").split(",") if s}


# ---------------------------------------------------------------------------
# daily check + renewal

def _evaluate(data, warn_days):
	"""(status, message) from a debug_token result."""
	if not data.get("is_valid"):
		reason = ((data.get("error") or {}).get("message")) or "Meta reports the token as invalid."
		return "Invalid", f"{reason} Generate a new token and update it."
	notes, status = [], "OK"
	expires = _days_until(_ts(data.get("expires_at")))
	if expires is not None and expires <= warn_days:
		status = "Expiring Soon"
		notes.append(f"Token expires in {max(0, int(expires))} day(s).")
	access = _days_until(_ts(data.get("data_access_expires_at")))
	if access is not None and access <= warn_days:
		status = "Action Needed"
		notes.append(f"Meta data access ends in {max(0, int(access))} day(s). Log in to Meta again and update the "
			"token (or switch to a non-expiring System User token).")
	missing = [s for s in REQUIRED_SCOPES if s not in (data.get("scopes") or [])]
	if missing:
		status = "Action Needed"
		notes.append(f"Missing permissions: {', '.join(missing)}.")
	return status, " ".join(notes) or "Connected. Nothing to do."


def _renew(settings, token, data):
	"""Try Meta's token exchange; returns (new_token or None, result message). Never raises."""
	app_secret = settings.get_password("app_secret", raise_exception=False)
	if not (settings.app_id and app_secret):
		return None, "Can't renew automatically: add the Meta App ID and App Secret."
	params = {"grant_type": "fb_exchange_token", "client_id": settings.app_id, "client_secret": app_secret,
		"fb_exchange_token": token}
	if (data.get("type") or "").upper() == "SYSTEM_USER":
		params["set_token_expires_in_60_days"] = "true"
	try:
		new_token = _get("oauth/access_token", params).get("access_token")
		if not new_token:
			return None, "Renewal failed: Meta returned no token."
		new_data = _inspect(new_token)
	except frappe.ValidationError as e:
		return None, f"Renewal failed: {e}"
	old_exp, new_exp = cint(data.get("expires_at")), cint(new_data.get("expires_at"))
	if not new_data.get("is_valid") or (old_exp and new_exp and new_exp <= old_exp):
		# e.g. a User token Meta won't extend without the person logging in again.
		return None, "Meta didn't extend this token; the person who authorised it needs to log in again."
	return new_token, f"Renewed; now {'never expires' if not new_exp else 'expires ' + str(_ts(new_exp))} (UTC)."


def check_connection():
	"""Verify, renew where supported, and record the result. Scheduled daily; safe to call any time."""
	settings = _settings()
	token = _stored_token(settings)
	values = {"last_checked": now_datetime()}
	if not token:
		values.update(status="Not Configured", status_message="Add the access token.", token_type=None, scopes=None,
			expires_at=None, data_access_expires_at=None)
		_save_status(values)
		return status()

	warn = cint(settings.warn_days) or 14
	try:
		data = _inspect(token)
	except frappe.ValidationError as e:
		values.update(status="Invalid", status_message=str(e))
		_save_status(values)
		return status()

	expires_in = _days_until(_ts(data.get("expires_at")))
	if data.get("is_valid") and cint(settings.auto_renew) and expires_in is not None and expires_in <= warn:
		new_token, result = _renew(settings, token, data)
		values.update(last_renewal_result=result)
		if new_token:
			settings = _settings()
			settings.access_token = new_token
			settings.flags.ignore_permissions = True
			settings.save()
			values["last_renewed"] = now_datetime()
			token, data = new_token, _inspect(new_token)

	status_value, message = _evaluate(data, warn)
	values.update(
		status=status_value,
		status_message=message,
		token_type=(data.get("type") or "").upper(),
		scopes=",".join(sorted(data.get("scopes") or [])),
		expires_at=_ts(data.get("expires_at")),
		data_access_expires_at=_ts(data.get("data_access_expires_at")),
	)
	_save_status(values)
	if data.get("is_valid"):
		try:
			frappe.db.set_single_value(SETTINGS, "instagram_account_id", None, update_modified=False)
			instagram_account_id()
		except frappe.ValidationError:
			pass
	return status()


def _save_status(values):
	for field, value in values.items():
		frappe.db.set_single_value(SETTINGS, field, value, update_modified=False)
	frappe.db.commit()


def status():
	"""Everything the admin app may see — never the token or the secret."""
	settings = _settings()
	data = {f: settings.get(f) for f in _PUBLIC_FIELDS}
	data["auto_renew"] = bool(data["auto_renew"])
	data["has_token"] = bool(_stored_token(settings))
	data["has_app_secret"] = bool(settings.get_password("app_secret", raise_exception=False))
	data["expires_in_days"] = _whole_days(settings.expires_at)
	data["data_access_expires_in_days"] = _whole_days(settings.data_access_expires_at)
	data["missing_scopes"] = [s for s in REQUIRED_SCOPES if s not in scopes()] if data["has_token"] else []
	return data


def _whole_days(dt):
	days = _days_until(dt)
	return None if days is None else max(0, int(days))


# ---------------------------------------------------------------------------
# API

@frappe.whitelist(methods=["GET"])
def get_connection():
	require_admin()
	return status()


@frappe.whitelist(methods=["POST"])
def check_now():
	require_admin()
	return check_connection()


@frappe.whitelist(methods=["POST"])
def update_connection(access_token=None, app_secret=None, page_id=None, app_id=None, auto_renew=None,
		warn_days=None):
	"""Replace the token / app secret (write-only) or settings. A new token is verified with Meta first and
	refused if Meta says it's invalid, so a typo can't take posting offline."""
	require_admin()
	settings = _settings()
	access_token = (access_token or "").strip()
	if access_token:
		if not _inspect(access_token).get("is_valid"):
			frappe.throw(_("Meta says this token isn't valid. Nothing was changed."), frappe.ValidationError)
		settings.access_token = access_token
	if (app_secret or "").strip():
		settings.app_secret = app_secret.strip()
	for field, value in (("page_id", page_id), ("app_id", app_id)):
		if value is not None:
			settings.set(field, str(value).strip())
	if auto_renew is not None:
		settings.auto_renew = cint(auto_renew)
	if warn_days is not None:
		settings.warn_days = cint(warn_days)
	settings.save()
	return check_connection()


@frappe.whitelist(methods=["POST"])
def seed_from_worker(page_id, access_token):
	"""One-time move of the token from the outreach VPS into this record. Only works while no token is
	stored, so it can never overwrite what an admin set."""
	from truth_of_bible.social.blessing_automation import require_worker

	require_worker()
	settings = _settings()
	if _stored_token(settings):
		frappe.throw(_("A token is already stored in TOB Meta Connection."), frappe.ValidationError)
	if not _inspect(access_token).get("is_valid"):
		frappe.throw(_("Meta says this token isn't valid."), frappe.ValidationError)
	settings.page_id = str(page_id).strip()
	settings.access_token = access_token.strip()
	settings.flags.ignore_permissions = True
	settings.save()
	result = check_connection()
	return {"status": result["status"], "status_message": result["status_message"]}


def worker_block():
	"""What the VPS worker needs to post: Page ID, Page token, Instagram ID and the connection status."""
	try:
		settings = _settings()
		if not _stored_token(settings):
			return {"status": "Not Configured"}
		return {
			"page_id": page_id(),
			"page_access_token": page_token(),
			"instagram_account_id": instagram_account_id(),
			"status": settings.status,
			"status_message": settings.status_message,
		}
	except frappe.ValidationError as e:
		return {"status": "Invalid", "status_message": str(e)}
