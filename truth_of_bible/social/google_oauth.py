"""Shared Google OAuth 2.0 plumbing for the Social Intelligence Center —
covers both YouTube Analytics and GA4 website analytics (one consent
screen requests scopes for both, so connecting once here unlocks both
future phases). This is deliberately separate from YouTube's own public
channel-summary card (social/youtube.py), which uses a plain API key —
no consent needed there since subscriber/view/video counts are public
data. This module exists only for the genuinely private data: YouTube
Analytics (watch time, traffic, audience retention) and GA4 — neither is
consumed yet; this phase only builds the connection itself.

Flow (standard OAuth2 authorization-code, web-app flow):
1. Flutter asks dashboard.get_google_connect_url() for the consent URL
   and opens it in an external browser (never in-app webview, so Google's
   own bot/automation detection never blocks the login).
2. Google redirects the browser here (`oauth_callback`) with a `code`.
3. This module exchanges the code for tokens and stores them.

Credentials are read from site_config.json's `google_clientid`/
`google_clientsecret` — never hardcoded, never logged.

Also provides `get_ga4_service_account_token()` — a second, independent
way for GA4 specifically to get an access token, for a deployment that
prefers a dedicated service account over per-admin OAuth consent (see
SOCIAL_INTELLIGENCE_CONTRACT.md §5.1 for why). Same
`service_account.Credentials` + `google.auth.transport.requests.Request`
pattern already proven on this bench by
truth_of_bible/notifications/delivery.py's `firebase_service_account`
handling — independently implemented here rather than imported, same
reasoning as that module's own docstring (this app owns its own source).
"""

import secrets
import urllib.parse

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, get_url, now_datetime
from google.auth.transport.requests import Request
from google.oauth2 import service_account
import requests

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_SCOPES = [
	"https://www.googleapis.com/auth/yt-analytics.readonly",
	"https://www.googleapis.com/auth/analytics.readonly",
]
_GA4_SERVICE_ACCOUNT_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
_STATE_CACHE_PREFIX = "social_google_oauth_state:"
_STATE_TTL_SECONDS = 600
_TIMEOUT = 15


def _client_id():
	return frappe.get_site_config().get("google_clientid")


def _client_secret():
	return frappe.get_site_config().get("google_clientsecret")


def _redirect_uri() -> str:
	return get_url("/api/method/truth_of_bible.social.google_oauth.oauth_callback")


def is_connected() -> bool:
	doc = frappe.get_single("TOB Google OAuth Token")
	return bool(doc.refresh_token)


def get_connect_url() -> str:
	client_id = _client_id()
	if not client_id:
		frappe.throw(
			_("Google OAuth isn't configured — add 'google_clientid'/'google_clientsecret' to site_config.json."),
			frappe.ValidationError,
		)

	state = secrets.token_urlsafe(24)
	frappe.cache().set_value(f"{_STATE_CACHE_PREFIX}{state}", "1", expires_in_sec=_STATE_TTL_SECONDS)

	params = {
		"client_id": client_id,
		"redirect_uri": _redirect_uri(),
		"response_type": "code",
		"scope": " ".join(_SCOPES),
		"access_type": "offline",
		"prompt": "consent",
		"state": state,
	}
	return f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"


@frappe.whitelist(allow_guest=True, methods=["GET"])
def oauth_callback(code=None, state=None, error=None):
	"""Google's browser redirect lands here — deliberately `allow_guest`
	(no Frappe session is guaranteed in this external browser); security
	instead comes from validating the cached `state` nonce below."""
	if error:
		frappe.respond_as_web_page(
			"Google connection failed",
			f"Google reported: {error}. Please try connecting again from the app.",
			success=False,
		)
		return

	cache_key = f"{_STATE_CACHE_PREFIX}{state}" if state else None
	if not state or not frappe.cache().get_value(cache_key):
		frappe.respond_as_web_page(
			"Google connection failed",
			"This connection link has expired or was already used. Please try again from the app.",
			success=False,
		)
		return
	frappe.cache().delete_value(cache_key)

	try:
		response = requests.post(
			_TOKEN_URL,
			data={
				"code": code,
				"client_id": _client_id(),
				"client_secret": _client_secret(),
				"redirect_uri": _redirect_uri(),
				"grant_type": "authorization_code",
			},
			timeout=_TIMEOUT,
		)
		response.raise_for_status()
		tokens = response.json()
	except requests.RequestException:
		frappe.log_error(title="Google OAuth token exchange failed")
		frappe.respond_as_web_page(
			"Google connection failed",
			"Something went wrong completing the connection. Please try again from the app.",
			success=False,
		)
		return

	_store_tokens(tokens)
	frappe.respond_as_web_page(
		"Connected",
		"Your Google account is connected. You can close this tab and return to the app.",
		success=True,
	)


def _store_tokens(tokens: dict) -> None:
	doc = frappe.get_single("TOB Google OAuth Token")
	doc.access_token = tokens.get("access_token")
	if tokens.get("refresh_token"):
		# A refresh-grant response has no refresh_token field of its own —
		# guard so refreshing an existing connection never blanks out the
		# refresh_token already stored from the original consent.
		doc.refresh_token = tokens.get("refresh_token")
	expires_in = int(tokens.get("expires_in") or 3600)
	doc.expires_at = add_to_date(now_datetime(), seconds=expires_in)
	doc.scope = tokens.get("scope") or " ".join(_SCOPES)
	doc.connected_at = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()


def get_valid_access_token():
	"""Returns None if never connected or a refresh attempt fails."""
	doc = frappe.get_single("TOB Google OAuth Token")
	if not doc.refresh_token:
		return None

	if doc.expires_at and get_datetime(doc.expires_at) > add_to_date(now_datetime(), seconds=60):
		return doc.access_token

	try:
		response = requests.post(
			_TOKEN_URL,
			data={
				"refresh_token": doc.refresh_token,
				"client_id": _client_id(),
				"client_secret": _client_secret(),
				"grant_type": "refresh_token",
			},
			timeout=_TIMEOUT,
		)
		response.raise_for_status()
		tokens = response.json()
	except requests.RequestException:
		return None

	_store_tokens(tokens)
	return tokens.get("access_token")


def get_ga4_service_account_token():
	"""Alternative to get_valid_access_token() above, for GA4 specifically:
	mints a short-lived access token from a dedicated service account
	(site_config.json's `ga4_service_account`, the full JSON key dict)
	instead of the per-admin OAuth consent flow. Returns None if
	unconfigured — silent, not logged, since not using a service account
	is the normal/expected state for a site that instead relies on the
	OAuth connection above; social/ga4.py falls back to that when this
	returns None, so the two paths are additive, not a hard switch.

	Requires the service account to be separately granted Viewer access
	on the actual GA4 property via Analytics Admin -> Property Access
	Management — a step in Google Analytics itself, not Cloud Console
	IAM. A service account has zero GA4 access by default even with the
	Analytics Data API enabled on its project.
	"""
	config = frappe.get_site_config().get("ga4_service_account")
	if not config:
		return None

	credentials = service_account.Credentials.from_service_account_info(
		config, scopes=_GA4_SERVICE_ACCOUNT_SCOPES
	)
	credentials.refresh(Request())
	return credentials.token
