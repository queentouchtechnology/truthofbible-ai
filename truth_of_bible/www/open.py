import urllib.parse

import frappe

_PACKAGE_NAME = "in.bizzui.truthofbible"
_CUSTOM_SCHEME = "truthofbible"
_PLAY_STORE_URL = f"https://play.google.com/store/apps/details?id={_PACKAGE_NAME}"


def get_context(context):
	"""`/open?route=<app route>&id=<optional id>` — the landing page every
	"Insert app link" (the Communication Center's campaign composer, and
	this app's own automated-event emails — see `notifications/
	email_delivery.py`'s `_app_link()`) points at. Tries the app's own URL
	scheme first; falls back to the Play Store, carrying the same route/id
	through as the install referrer so the Flutter app's `ReferrerService` +
	`splash_screen.dart` can still open it once sign-in finishes post-install
	(Android only is not fixable from this page — see HANDOFF.md §47.10)."""
	context.no_cache = 1
	context.no_sitemap = 1

	route = (frappe.form_dict.get("route") or "").strip()
	ref_id = (frappe.form_dict.get("id") or "").strip()

	context.has_route = bool(route)
	context.app_scheme_url = _scheme_url(route, ref_id)
	context.play_store_url = _play_store_url(route, ref_id)


def _scheme_url(route: str, ref_id: str) -> str:
	params = {"route": route}
	if ref_id:
		params["id"] = ref_id
	return f"{_CUSTOM_SCHEME}://open?{urllib.parse.urlencode(params)}"


def _play_store_url(route: str, ref_id: str) -> str:
	if not route:
		return _PLAY_STORE_URL
	# One Play Store install-referrer string, in exactly the shape the
	# Flutter app's `ReferrerService.read()` already expects (`dl_` prefix).
	inner = urllib.parse.urlencode({"route": route, "id": ref_id})
	return f"{_PLAY_STORE_URL}&{urllib.parse.urlencode({'referrer': f'dl_{inner}'})}"
