"""Buffer's current GraphQL API (https://developers.buffer.com) — the
Social Intelligence Center's execution layer for Facebook/Instagram/
Google Business Profile publishing (Phase 1 plan: Buffer owns
connected-channel state, scheduling and publish status; this app only
owns intelligence — recommendations, research, reporting).

**Replaces an earlier implementation built against Buffer's classic REST
API** (`api.bufferapp.com/1`) — confirmed live (via Buffer's own current
developer docs, 2026-09) that the legacy REST API is deprecated and no
longer issues new OAuth-style access tokens; every account, new or
existing, must use the GraphQL API at `api.buffer.com` with a **personal
API key** (from https://publish.buffer.com/settings/api) instead. This
was found because a real access token, correctly configured, still
reported "not connected" — the endpoint itself no longer works, not a
config problem.

Every Buffer HTTP call lives here, never inline elsewhere in the app —
same "one client module per external service" discipline as
communication/chatwoot.py and communication/brevo.py.

The API key is read from site_config.json's `buffer_api_token` key
(same config key as before — now holding a personal API key rather than
an OAuth access token), never hardcoded, never logged.
"""

import frappe
import requests

_GRAPHQL_URL = "https://api.buffer.com"
_TIMEOUT = 15

_CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
	createPost(input: $input) {
		post { id status }
	}
}
"""


def _token():
	return frappe.get_site_config().get("buffer_api_token")


def is_configured() -> bool:
	return bool(_token())


def _require_token() -> str:
	token = _token()
	if not token:
		frappe.throw(
			frappe._("Buffer isn't configured yet — add 'buffer_api_token' to site_config.json."),
			frappe.ValidationError,
		)
	return token


def _graphql(query: str, variables: dict = None) -> dict:
	token = _require_token()
	try:
		response = requests.post(
			_GRAPHQL_URL,
			json={"query": query, "variables": variables or {}},
			headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
			timeout=_TIMEOUT,
		)
		response.raise_for_status()
	except requests.RequestException as e:
		# Every caller here (list_channels/create_post/...) catches this
		# and just returns None/reports "not connected" — logging the real
		# body is the only way to tell an auth failure apart from a wrong
		# query shape apart from a network issue. Never logs the token
		# itself (only Buffer's own response), so this is safe to leave on.
		status = getattr(e.response, "status_code", "n/a")
		body = getattr(e.response, "text", str(e))
		frappe.log_error(
			title="Buffer GraphQL request failed",
			message=f"Status: {status}\nBody: {body[:2000]}",
		)
		raise

	payload = response.json()
	if payload.get("errors"):
		# GraphQL returns HTTP 200 even for query-level errors — log and
		# surface them as a real exception so callers' except blocks catch
		# this the same way they'd catch a transport-level failure.
		frappe.log_error(
			title="Buffer GraphQL returned errors",
			message=str(payload["errors"])[:2000],
		)
		raise requests.RequestException(str(payload["errors"]))
	return payload.get("data") or {}


def _organization_id():
	"""Buffer's GraphQL API scopes channels/posts by organization — fetched
	fresh each time rather than cached in site_config, since a personal
	API key is normally tied to exactly one organization anyway and this
	keeps the module stateless."""
	data = _graphql("query GetOrganizations { account { organizations { id } } }")
	orgs = (data.get("account") or {}).get("organizations") or []
	return orgs[0].get("id") if orgs else None


def list_channels():
	"""Returns None when Buffer isn't configured, has no organization, or
	the API call fails — the dashboard treats that as "not connected",
	distinct from a genuinely empty (but reachable) list of channels."""
	if not _token():
		return None
	try:
		org_id = _organization_id()
		if not org_id:
			return None
		data = _graphql(
			"""
			query GetChannels($organizationId: OrganizationId!) {
				channels(input: { organizationId: $organizationId }) {
					id
					service
					displayName
				}
			}
			""",
			{"organizationId": org_id},
		)
	except requests.RequestException:
		return None

	channels = data.get("channels") or []
	return [
		{
			"buffer_channel_id": c.get("id"),
			"platform": c.get("service"),
			"channel_name": c.get("displayName") or "",
		}
		for c in channels
	]


def create_draft(channel_ids: list, text: str) -> dict:
	return _create_post(channel_ids, text, save_to_draft=True)


def schedule_post(channel_ids: list, text: str, scheduled_at) -> dict:
	return _create_post(channel_ids, text, scheduled_at=scheduled_at)


def publish_post(channel_ids: list, text: str) -> dict:
	return _create_post(channel_ids, text, now=True)


def _create_post(
	channel_ids: list, text: str, now: bool = False, save_to_draft: bool = False, scheduled_at=None
) -> dict:
	"""One `createPost` call per channel — the GraphQL mutation takes a
	single `channelId`, unlike the old REST API's `profile_ids[]` array."""
	posts = []
	for channel_id in channel_ids:
		post_input = {"channelId": channel_id, "text": text, "assets": []}
		if save_to_draft:
			post_input["saveToDraft"] = True
			post_input["mode"] = "shareNext"
		elif now:
			post_input["mode"] = "shareNow"
			post_input["schedulingType"] = "automatic"
		else:
			post_input["mode"] = "customScheduled"
			post_input["schedulingType"] = "automatic"
			post_input["dueAt"] = _unix_to_iso(scheduled_at)

		data = _graphql(_CREATE_POST_MUTATION, {"input": post_input})
		posts.append((data.get("createPost") or {}).get("post") or {})

	return {
		"buffer_post_ids": [p.get("id") for p in posts],
		"status": posts[0].get("status") if posts else None,
	}


def _unix_to_iso(timestamp) -> str:
	from datetime import datetime, timezone

	return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_post_status(buffer_post_id: str) -> dict:
	"""Unverified against Buffer's current GraphQL schema (no caller in
	this app uses it yet) — the `channels`/`createPost`/`organizations`
	shapes above were each confirmed live against Buffer's own docs; this
	one is a best-effort guess at the equivalent single-post query and
	should be checked against the schema before anything relies on it."""
	data = _graphql(
		"""
		query GetPost($id: String!) {
			post(input: { id: $id }) {
				id
				status
			}
		}
		""",
		{"id": buffer_post_id},
	)
	post = data.get("post") or {}
	return {"status": post.get("status"), "sent_at": None}
