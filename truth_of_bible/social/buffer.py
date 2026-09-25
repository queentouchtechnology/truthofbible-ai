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
# A real production timeout (confirmed via Buffer's own request log:
# "Read timed out. (read timeout=15)") showed 15s isn't always enough,
# especially for a createPost call carrying an image/video asset that
# Buffer has to fetch and process before responding.
_TIMEOUT = 30

# Confirmed live via GraphQL schema introspection (`__type(name:
# "PostInputMetaData")`): every service's metadata key matches its
# `channels()`-reported `service` value exactly EXCEPT Google Business
# Profile, whose `service` is "googlebusiness" but whose metadata key is
# "google" — everything else (instagram/facebook/twitter/bluesky/
# mastodon/threads/tiktok/linkedin/pinterest/substack/youtube) needs no
# entry here at all, the `.get(service, service)` fallback covers them.
_METADATA_KEY_BY_SERVICE = {"googlebusiness": "google"}

_CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
	createPost(input: $input) {
		... on PostActionSuccess {
			post { id status }
		}
		... on MutationError {
			message
		}
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
		# While Buffer is rate-limiting (429) every call fails the same way —
		# log it once per 10 minutes instead of once per request, so a quota
		# hit doesn't bury every other error in the log.
		if status == 429:
			if not frappe.cache().get_value("tob_buffer_429_logged"):
				frappe.cache().set_value("tob_buffer_429_logged", 1, expires_in_sec=600)
				frappe.log_error(
					title="Buffer GraphQL request failed (rate limited)",
					message=f"Status: 429\nBody: {body[:2000]}\n(Further 429s are not logged for 10 minutes.)",
				)
		else:
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


_ORG_CACHE_KEY = "tob_buffer_org_id"
_CHANNELS_CACHE_KEY = "tob_buffer_channels"
_CHANNELS_STALE_KEY = "tob_buffer_channels_stale"


def _organization_id():
	"""Buffer's GraphQL API scopes channels/posts by organization. Cached
	for a day (a personal API key is tied to one organization and it
	doesn't change) — Buffer allows only 100 requests per 15 minutes on
	this key, and every channel/post lookup used to spend one of them
	re-fetching this same id. A failed lookup is never cached."""
	cached = frappe.cache().get_value(_ORG_CACHE_KEY)
	if cached:
		return cached
	data = _graphql("query GetOrganizations { account { organizations { id } } }")
	orgs = (data.get("account") or {}).get("organizations") or []
	org_id = orgs[0].get("id") if orgs else None
	if org_id:
		frappe.cache().set_value(_ORG_CACHE_KEY, org_id, expires_in_sec=86400)
	return org_id


def list_channels():
	"""Returns None when Buffer isn't configured, has no organization, or
	the API call fails — the dashboard treats that as "not connected",
	distinct from a genuinely empty (but reachable) list of channels.

	Cached for 5 minutes for the same rate-limit reason as
	`_organization_id()` — the channel list backs every dashboard load,
	post-history load and post creation, and changes rarely. A failure
	is never cached, so "not connected" corrects itself on the next call.

	`avatar`/`isQueuePaused` are confirmed real `Channel` fields (seen on
	Buffer's own "Get Channel" single-channel query) — added to this bulk
	query too since a selection-set addition on an already-working query
	carries far less risk than guessing a new query's argument types, and
	it gives the composer real channel avatars + a paused-queue warning
	for free."""
	if not _token():
		return None
	cached = frappe.cache().get_value(_CHANNELS_CACHE_KEY)
	if cached is not None:
		return cached
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
					avatar
					isQueuePaused
				}
			}
			""",
			{"organizationId": org_id},
		)
	except requests.RequestException:
		# A transient failure (most often Buffer's 429 rate limit) must not
		# flip the whole dashboard to "not connected" — fall back to the
		# last good list (kept for 6 hours). With no prior success there is
		# nothing to fall back on, so a genuinely bad/missing token still
		# reports None.
		return frappe.cache().get_value(_CHANNELS_STALE_KEY)

	channels = data.get("channels") or []
	result = [
		{
			"buffer_channel_id": c.get("id"),
			"platform": c.get("service"),
			"channel_name": c.get("displayName") or "",
			"avatar": c.get("avatar"),
			"is_queue_paused": bool(c.get("isQueuePaused")),
		}
		for c in channels
	]
	frappe.cache().set_value(_CHANNELS_CACHE_KEY, result, expires_in_sec=300)
	frappe.cache().set_value(_CHANNELS_STALE_KEY, result, expires_in_sec=21600)
	return result


def create_draft(channels: list, text: str, **kwargs) -> dict:
	return _create_post(channels, text, save_to_draft=True, **kwargs)


def schedule_post(channels: list, text: str, scheduled_at, **kwargs) -> dict:
	return _create_post(channels, text, scheduled_at=scheduled_at, **kwargs)


def publish_post(channels: list, text: str, **kwargs) -> dict:
	return _create_post(channels, text, now=True, **kwargs)


def _create_post(
	channels: list,
	text: str,
	now: bool = False,
	save_to_draft: bool = False,
	scheduled_at=None,
	image_url: str = None,
	video_url: str = None,
	instagram_tags: list = None,
	thread_texts: list = None,
	post_types: dict = None,
	gbp_title: str = None,
	gbp_start_date: str = None,
	gbp_end_date: str = None,
	gbp_coupon_code: str = None,
) -> dict:
	"""One `createPost` call per channel — the GraphQL mutation takes a
	single `channelId`, unlike the old REST API's `profile_ids[]` array.

	`channels` is a list of `{"id": ..., "service": ...}` dicts (not bare
	ids) — the per-channel `service` is what decides whether Instagram-
	specific metadata, a service-scoped thread, or a required `post_types`
	entry gets attached, so the caller (social/dashboard.py) resolves it
	once via `list_channels()` rather than this module re-fetching it per
	call. A bare string id is also accepted for callers that don't need
	those extras.

	`post_types` is `{service: type}` (e.g. `{"instagram": "reel",
	"facebook": "post", "googlebusiness": "event"}`) — a real device test
	showed Buffer rejects Instagram/Facebook/Google Business Profile posts
	outright without this. Confirmed shape (Buffer's own "Create Instagram
	Post With User Tags" doc example, plus live schema introspection of
	`PostInputMetaData`/`InstagramPostMetadataInput`/
	`FacebookPostMetadataInput`/`GoogleBusinessPostMetadataInput` after a
	real device test surfaced 3 wrong assumptions in one round: Instagram
	also requires `shouldShareToFeed: Boolean!` whenever `metadata.
	instagram` is present at all (not just as an example flourish);
	`schedulingType` is required on every mode including `saveToDraft`;
	and Google Business Profile's metadata key is `google`, not
	`googlebusiness` like every other service's key matches its own
	`channels()` `service` value — see `_METADATA_KEY_BY_SERVICE`.
	Facebook needed no metadata field beyond `type` (confirmed via the
	same introspection).

	`gbp_title`/`gbp_start_date`/`gbp_end_date`/`gbp_coupon_code` only
	apply when a channel's service is `googlebusiness` and its type is
	`offer`/`event`. Confirmed via introspecting `GoogleBusinessEventMeta
	DataInput`/`GoogleBusinessOfferMetaDataInput`: `title` sits at BOTH
	the top level of `google` and (redundantly, harmlessly) inside each
	details object; offer's coupon code is named `code` (not
	`couponCode`, the original guess); both `startDate`/`endDate` are
	`DateTime` (full ISO 8601, not a bare date) and live under
	`detailsEvent`/`detailsOffer`, not flat under `google`;
	`detailsEvent.isFullDayEvent: Boolean!` is required whenever
	`detailsEvent` is sent — this app only collects a date, not a time,
	so it's always `True`. **`startDate`/`endDate` are required for
	`offer` too** — confirmed live via a real Buffer rejection ("Google
	Business offers require a start/end date"), not visible from the
	schema itself (both fields are merely optional on
	`GoogleBusinessOfferMetaDataInput`); `event`'s start must also be
	strictly before its end, same real rejection pattern.
	"""
	assets = []
	if video_url:
		# Confirmed shape: same as an image post, an `assets` entry with a
		# `video` key instead of `image` — no separate upload step.
		assets.append({"video": {"url": video_url}})
	elif image_url:
		# Confirmed via Buffer's current docs: a direct hosted image URL,
		# no separate upload/presigned-URL step — same "reuse an existing
		# hosted URL, no upload endpoint in this app" convention already
		# used for the Communication Center's push_image_url field.
		# altText is a required ImageAssetInput field.
		image_metadata = {"altText": text[:100] or "Image"}
		if instagram_tags:
			# Confirmed shape: per-tag normalized x/y position. This app
			# doesn't offer an interactive image-tagging canvas, so tags
			# are auto-stacked down the image's lower half rather than
			# admin-positioned — good enough for "tag these accounts",
			# not pixel-precise placement.
			image_metadata["userTags"] = [
				{"handle": handle, "x": 0.5, "y": min(0.55 + 0.12 * i, 0.95)}
				for i, handle in enumerate(instagram_tags)
			]
		assets.append({"image": {"url": image_url, "metadata": image_metadata}})

	# Each channel gets its own try/except — a real production incident
	# showed why: a 3-channel post where one channel's call read-timed-out
	# used to raise straight out of this whole function, discarding
	# whatever the OTHER channels' calls had already returned and leaving
	# the caller (dashboard.create_post) no way to tell "all 3 failed"
	# from "2 succeeded, 1 didn't" — it just crashed before saving
	# anything. Per-channel results let the caller record the truth per
	# channel instead of guessing (or worse, marking the whole post
	# "SENT" when it wasn't), matching this app's own "never fabricate"
	# rule from the Buffer/channel status down to a single post's result.
	channel_results = []
	for channel in channels:
		if isinstance(channel, dict):
			channel_id = channel.get("id")
			service = (channel.get("service") or "").lower()
		else:
			channel_id = channel
			service = ""

		post_input = {"channelId": channel_id, "text": text, "assets": assets}
		metadata_key = _METADATA_KEY_BY_SERVICE.get(service, service)

		metadata = {}
		if post_types and service in post_types:
			metadata.setdefault(metadata_key, {})["type"] = post_types[service]
			if service == "instagram":
				# Confirmed live (real GraphQL validation error):
				# `shouldShareToFeed` is a REQUIRED Boolean whenever
				# `metadata.instagram` is present at all, not an optional
				# extra from the one confirmed doc example — omitting it
				# (the earlier assumption) fails every Instagram post.
				metadata["instagram"]["shouldShareToFeed"] = True
		if service == "googlebusiness" and post_types and post_types.get(service) in ("offer", "event"):
			# Confirmed live via schema introspection of
			# `GoogleBusinessPostMetadataInput`/`GoogleBusinessEventMetaData
			# Input`/`GoogleBusinessOfferMetaDataInput` (the metadata KEY is
			# "google", not "googlebusiness" — every other service's key
			# matches its `service` value exactly except this one).
			# `title` sits at the top level of `google` (set unconditionally
			# below, alongside `type`); start/end dates and the coupon code
			# are nested one level deeper, under `detailsEvent`/
			# `detailsOffer` respectively — NOT flat under `google` as
			# first guessed. Offer's coupon field is `code`, not
			# `couponCode`. Dates are `DateTime` (full ISO 8601), not a
			# bare date — `_date_to_iso()` below adds a midnight-UTC time
			# if the caller only sent a date, which is all this app's own
			# UI collects.
			gbp = metadata.setdefault("google", {})
			if gbp_title:
				gbp["title"] = gbp_title
			if post_types[service] == "event":
				details = {"isFullDayEvent": True}  # required; this app collects a date, not a time
				if gbp_title:
					details["title"] = gbp_title
				if gbp_start_date:
					details["startDate"] = _date_to_iso(gbp_start_date)
				if gbp_end_date:
					details["endDate"] = _date_to_iso(gbp_end_date)
				gbp["detailsEvent"] = details
			elif post_types[service] == "offer":
				# Confirmed live (real Buffer rejection, not in the schema
				# itself — `startDate`/`endDate` are optional per
				# introspection but Buffer's business-logic validation
				# requires both): "Google Business offers require a start
				# date., ... require an end date." — same requirement as
				# Event, just not visible from the type system alone.
				details = {}
				if gbp_title:
					details["title"] = gbp_title
				if gbp_coupon_code:
					details["code"] = gbp_coupon_code
				if gbp_start_date:
					details["startDate"] = _date_to_iso(gbp_start_date)
				if gbp_end_date:
					details["endDate"] = _date_to_iso(gbp_end_date)
				if details:
					gbp["detailsOffer"] = details
		if thread_texts and len(thread_texts) > 1 and service:
			# Confirmed shape (Twitter/X example): a `thread` array nested
			# under a metadata key named after the service itself. Only
			# meaningful for thread-capable services (twitter/bluesky/
			# mastodon/threads) — sent as-is for any other service would
			# just be ignored by Buffer, not a hard error, so no extra
			# guard is needed here beyond requiring `service` to be known.
			metadata[metadata_key] = {"thread": [{"text": t} for t in thread_texts]}
		if metadata:
			post_input["metadata"] = metadata

		if save_to_draft:
			post_input["saveToDraft"] = True
			post_input["mode"] = "shareNext"
		elif now:
			post_input["mode"] = "shareNow"
		else:
			post_input["mode"] = "customScheduled"
			post_input["dueAt"] = _unix_to_iso(scheduled_at)

		# Confirmed live (real GraphQL validation error): `schedulingType`
		# is required on EVERY mode, including `saveToDraft`/`shareNext` —
		# not just publish/schedule as first assumed. Always `automatic`;
		# `notification` is Buffer's other documented value but nothing in
		# this app has a use for it.
		post_input["schedulingType"] = "automatic"

		try:
			data = _graphql(_CREATE_POST_MUTATION, {"input": post_input})
			payload = data.get("createPost") or {}
			post = payload.get("post")
			if post and post.get("id"):
				channel_results.append({
					"channel_id": channel_id,
					"success": True,
					"buffer_post_id": post.get("id"),
					"status": post.get("status"),
					"error": None,
				})
			else:
				# Buffer answered but didn't return a post — either a
				# `MutationError` (its `message` is the real reason: bad
				# input, permission, rate limit, ...) or a shape this
				# module doesn't recognize. Either way, this is NOT a
				# success: silently treating an empty `post` as "sent"
				# (the previous behavior) is exactly how a rejected post
				# could look identical to a real one in this app's own
				# history.
				channel_results.append({
					"channel_id": channel_id,
					"success": False,
					"buffer_post_id": None,
					"status": None,
					"error": payload.get("message") or "Buffer didn't confirm this post.",
				})
		except requests.RequestException as e:
			channel_results.append({
				"channel_id": channel_id,
				"success": False,
				"buffer_post_id": None,
				"status": None,
				"error": (
					"Buffer's rate limit was reached (100 requests per 15 minutes) — wait a few minutes and retry."
					if getattr(e.response, "status_code", None) == 429
					else str(e)
				),
			})

	return {
		"channel_results": channel_results,
		"buffer_post_ids": [r["buffer_post_id"] for r in channel_results if r["success"]],
		"status": next((r["status"] for r in channel_results if r["success"]), None),
	}


def _unix_to_iso(timestamp) -> str:
	from datetime import datetime, timezone

	return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_to_iso(date_str: str) -> str:
	"""Google Business Profile's event/offer dates are `DateTime` (full
	ISO 8601), but this app's own UI only collects a bare date
	(`YYYY-MM-DD`) — confirmed via schema introspection, not a doc
	example. Adds a midnight-UTC time if one isn't already present."""
	return date_str if "T" in date_str else f"{date_str}T00:00:00Z"


def get_post_metrics(buffer_post_id: str):
	"""Confirmed shape (Buffer's own "Get Post Metrics" doc): a single
	post's performance numbers — likes/comments/shares/etc, each as a
	{type, name, value, unit} row, since Buffer reports different metric
	sets per platform rather than one fixed schema. Returns None on any
	failure (post not found, key not scoped for metrics, etc.) — personal
	API keys only, per Buffer's own docs."""
	try:
		data = _graphql(
			"""
			query GetPostMetrics($id: String!) {
				post(input: { id: $id }) {
					id
					text
					channelId
					metrics { type name value unit }
					metricsUpdatedAt
				}
			}
			""",
			{"id": buffer_post_id},
		)
	except requests.RequestException:
		return None
	post = data.get("post")
	if not post:
		return None
	return {
		"buffer_post_id": post.get("id"),
		"metrics": post.get("metrics") or [],
		"metrics_updated_at": post.get("metricsUpdatedAt"),
	}


def _list_posts_by_status(status: str, with_metrics: bool = False, first: int = 20):
	"""Shared by `get_scheduled_posts()`/`get_posts_with_metrics()` — both
	are just Buffer's confirmed `posts` query (Buffer's own "Get Paginated
	Posts" doc) filtered to one status. `status` is always one of this
	module's own literal values ("scheduled"/"sent"), never free-form
	input, so it's inlined directly into the query text rather than
	declared as a typed variable — avoids guessing the filter's enum type
	name (the exact mistake `$organizationId: String!` made before it was
	confirmed to need the `OrganizationId!` scalar)."""
	if not _token():
		return None
	try:
		org_id = _organization_id()
		if not org_id:
			return None
		metrics_fields = (
			"\n\t\t\t\t\tmetrics { type name value unit }\n\t\t\t\t\tmetricsUpdatedAt"
			if with_metrics
			else ""
		)
		data = _graphql(
			f"""
			query ListPosts($organizationId: OrganizationId!, $first: Int) {{
				posts(
					first: $first,
					input: {{ organizationId: $organizationId, filter: {{ status: [{status}] }} }}
				) {{
					edges {{
						node {{
							id
							text
							createdAt
							dueAt
							channelId
							status{metrics_fields}
						}}
					}}
				}}
			}}
			""",
			{"organizationId": org_id, "first": first},
		)
	except requests.RequestException:
		return None
	edges = (data.get("posts") or {}).get("edges") or []
	return [e.get("node") or {} for e in edges]


def get_scheduled_posts(first: int = 20):
	"""Posts Buffer will publish in the future — Buffer's own queue, not
	this app's local `TOB Social Post` history (which only knows about
	posts created through this app's own composer)."""
	return _list_posts_by_status("scheduled", first=first)


def get_posts_with_metrics(first: int = 20):
	"""Sent posts with their performance numbers — feeds both the "Post
	Performance" list and the quarterly rollup, computed in
	social/dashboard.py from these real per-post metrics rather than a
	guessed-at Buffer "quarterly report" query (Buffer's docs describe
	that endpoint but don't publish its actual GraphQL field/argument
	shape anywhere this app has seen)."""
	return _list_posts_by_status("sent", with_metrics=True, first=first)
