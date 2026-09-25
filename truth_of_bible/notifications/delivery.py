"""Fully independent FCM delivery for the truth_of_bible notification
engine.

Deliberately does NOT call `frappe.api.fcm_api.send_fcm` — that function
lives at `apps/frappe/frappe/api/fcm_api.py`, i.e. it's patched directly
into the `frappe` framework package itself on this bench, not owned by any
app. Depending on it would mean this app's push delivery could silently
break the next time frappe itself is reinstalled/updated, and it's outside
this app's own source control entirely. Per an explicit decision on
2026-09-22 (see NOTIFICATION_ENGINE_PLAN.md), this module instead talks to
FCM's HTTP v1 API directly, using the same `firebase_service_account`
site-config key and the same `User FCM Token` doctype (ordinary site data,
not framework-patched code, so reusing it is fine) — same proven approach,
independently implemented so `truth_of_bible` never depends on code it
doesn't own.
"""

import frappe
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]


def _access_token():
	"""Returns (access_token, project_id), or (None, None) if this site has
	no `firebase_service_account` key configured — logged once per attempt
	rather than raised, since a missing push credential must never break
	whatever triggered the notification (the Notification Log row is
	already written by the time this runs)."""
	firebase_config = frappe.get_site_config().get("firebase_service_account")
	if not firebase_config:
		frappe.log_error(
			title="Notification engine: firebase_service_account missing",
			message="site_config.json has no 'firebase_service_account' key — cannot send FCM push.",
		)
		return None, None

	credentials = service_account.Credentials.from_service_account_info(firebase_config, scopes=_SCOPES)
	credentials.refresh(Request())
	return credentials.token, firebase_config.get("project_id")


def send_push(
	user: str,
	title: str,
	body: str = "",
	route: str | None = None,
	ref_id: str | None = None,
	notif_type: str = "",
	image: str | None = None,
	sound: str = "default",
	send_id: str | None = None,
) -> bool:
	"""Sends to every device token this user has registered (`User FCM
	Token`), pruning any token FCM reports as UNREGISTERED. Returns True if
	at least one device was reached. Never raises — a push failure must
	never break the caller, since the in-app Notification Log entry has
	already been created regardless.
	"""
	tokens = frappe.get_all("User FCM Token", filters={"user": user}, pluck="fcm_token")
	if not tokens:
		_record_result(send_id, 0, 0, "No push token registered")
		return False

	access_token, project_id = _access_token()
	if not access_token:
		_record_result(send_id, 0, 0, "Push service credentials unavailable")
		return False

	url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
	headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

	sent_any = False
	pruned = 0
	reached = 0
	failed = 0
	reasons = []
	for token in tokens:
		notification = {"title": title, "body": body or ""}
		if image:
			notification["image"] = image

		payload = {
			"message": {
				"token": token,
				"notification": notification,
				"data": {
					"title": str(title),
					"body": str(body or ""),
					"route": str(route or ""),
					"id": str(ref_id or ""),
					"type": str(notif_type or ""),
					"image": str(image or ""),
					"send_id": str(send_id or ""),
				},
				"android": {
					"priority": "HIGH",
					"notification": {"sound": sound, "image": image or ""},
				},
				"apns": {
					"payload": {"aps": {"sound": sound}},
					"fcm_options": {"image": image or ""},
				},
			}
		}

		try:
			response = requests.post(url, headers=headers, json=payload, timeout=20)
		except Exception:
			frappe.log_error(
				title=f"Notification engine: FCM request failed ({notif_type})",
				message=frappe.get_traceback(),
			)
			failed += 1
			reasons.append("Could not reach the push service")
			continue

		if response.status_code == 200:
			sent_any = True
			reached += 1
			continue

		failed += 1
		if _is_unregistered(response):
			frappe.db.delete("User FCM Token", {"fcm_token": token})
			pruned += 1
			reasons.append("Device token no longer valid (app removed or reinstalled)")
		elif _is_invalid_token(response):
			# Google says the token string itself isn't a valid FCM token
			# (INVALID_ARGUMENT on `message.token`) — it can never work, so
			# remove it. Before this, only UNREGISTERED tokens were pruned:
			# malformed ones failed and wrote an error-log entry on every
			# single send, forever.
			frappe.db.delete("User FCM Token", {"fcm_token": token})
			pruned += 1
			reasons.append("Device token was malformed (removed)")
		else:
			reasons.append(_failure_reason(response))
			frappe.log_error(
				title=f"Notification engine: FCM send failed ({notif_type})",
				message=f"HTTP {response.status_code}: {response.text[:2000]}",
			)

	if pruned:
		frappe.db.commit()

	_record_result(send_id, reached, failed, "; ".join(dict.fromkeys(reasons)))
	return sent_any


def _failure_reason(response) -> str:
	"""A short, readable reason from an FCM error body — never the raw
	response, which can be long."""
	try:
		err = response.json().get("error", {})
		return f"{err.get('status') or response.status_code}: {(err.get('message') or '')[:120]}".strip(": ")
	except Exception:
		return f"HTTP {response.status_code}"


def _record_result(send_id, reached: int, failed: int, reason: str) -> None:
	"""Stores what Google's push service said on the send-log row, so the
	admin report can show delivery rate and failure reasons. `reached`
	means accepted for delivery (HTTP 200), not proof the phone showed it."""
	if not send_id:
		return
	try:
		frappe.db.set_value(
			"TOB Notification Send Log",
			send_id,
			{"devices_reached": reached, "devices_failed": failed, "failure_reason": (reason or "")[:500]},
			update_modified=False,
		)
	except Exception:
		frappe.log_error(title="Notification engine: recording delivery result failed", message=frappe.get_traceback())


def _is_invalid_token(response) -> bool:
	"""True only when FCM's error points at the token field itself — an
	INVALID_ARGUMENT about anything else (a bad payload) must NOT delete a
	perfectly good token."""
	try:
		details = response.json().get("error", {}).get("details", [])
	except Exception:
		return False
	for d in details:
		for v in d.get("fieldViolations", []) or []:
			if v.get("field") == "message.token":
				return True
	return False


def _is_unregistered(response) -> bool:
	try:
		details = response.json().get("error", {}).get("details", [])
	except Exception:
		return False
	return any(d.get("errorCode") == "UNREGISTERED" for d in details)
