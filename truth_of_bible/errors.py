"""One way to fail an API call when something behind it breaks (an AI or voice provider, GitHub, a login):
the real error goes to the desk's Error Log, and the user only ever sees a short, friendly sentence. Provider
replies, status codes, request ids and tracebacks never reach the app.

A frappe.throw on its own is treated as a validation message and isn't logged, which is why a failure has to
be recorded here before throwing."""

import inspect
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import frappe
import requests
from frappe import _

SOMETHING_WENT_WRONG = "Something went wrong on our side. Please try again in a little while."


def log(title: str, exc: BaseException | None = None, **context) -> None:
	"""Records an error in Error Log. Call it inside the `except` block so the traceback is included."""
	lines = [f"{k}: {v}" for k, v in context.items() if v not in (None, "")]
	if exc is not None:
		lines.append(f"{type(exc).__name__}: {exc}")
	trace = frappe.get_traceback() if exc is not None else ""
	message = "\n".join(lines) + ("\n\n" + trace if trace and "NoneType: None" not in trace else "")
	log_error(title=title[:140], message=message)


_CAN_DEFER = "defer_insert" in inspect.signature(frappe.log_error).parameters


def log_error(*args, **kwargs):
	"""Drop-in for frappe.log_error that isn't lost when the request then fails. In a web request the row is
	written outside the request's transaction (deferred insert), so a frappe.throw — which rolls everything
	back — no longer takes the log entry with it. Background jobs write it directly as before."""
	if _CAN_DEFER and getattr(frappe.local, "request", None) is not None:
		kwargs.setdefault("defer_insert", True)
	frappe.log_error(*args, **kwargs)


def fail(title: str, exc: BaseException | None = None, user_message: str | None = None, exc_type=frappe.ValidationError, **context):
	"""Logs the error (see log) and stops the request with `user_message`, or a generic friendly sentence."""
	log(title, exc, **context)
	frappe.throw(user_message or _(SOMETHING_WENT_WRONG), exc_type)


def ai_fail(what: str, exc) -> None:
	"""For an AiProviderException: AI turned off for the site or the user is already a friendly message, so it's
	shown as it is (and not logged — it's a setting, not a failure). Anything else is logged with the
	provider's details and the user gets `what` plus a try-again-later sentence."""
	from truth_of_bible.ai.service import AiAccessDisabled

	if isinstance(exc, AiAccessDisabled):
		frappe.throw(str(exc), frappe.ValidationError)
	fail(
		f"AI: {what} failed ({getattr(exc, 'provider', '?')} {getattr(exc, 'kind', '')})",
		exc,
		_("{0} isn't available right now. Please try again in a little while.").format(what),
		user=frappe.session.user,
	)


# --- GlitchTip (QTT's error monitoring at errors.queentouchtech.in), set up in TOB Error Tracking Settings ---

SETTINGS = "TOB Error Tracking Settings"


def _tracking():
	s = frappe.get_cached_doc(SETTINGS)
	return s if s.enabled and s.server_dsn else None


def _post_event(dsn: str, title: str, details: str, environment: str, **tags) -> requests.Response:
	"""Sends one error to GlitchTip through its Sentry-compatible store endpoint."""
	u = urlparse(dsn.strip())
	project = u.path.strip("/").split("/")[-1]
	event = {
		"event_id": uuid.uuid4().hex,
		"timestamp": datetime.now(timezone.utc).isoformat(),
		"platform": "python",
		"level": "error",
		"logger": "frappe.error_log",
		"server_name": frappe.local.site,
		"environment": environment or "production",
		"message": {"formatted": f"{title}\n\n{details}"[:8000]},
		"fingerprint": [title[:140]],
		"tags": {"site": frappe.local.site, **{k: str(v)[:200] for k, v in tags.items() if v}},
	}
	return requests.post(
		f"{u.scheme}://{u.hostname}{f':{u.port}' if u.port else ''}/api/{project}/store/",
		data=json.dumps(event),
		headers={
			"Content-Type": "application/json",
			"X-Sentry-Auth": f"Sentry sentry_version=7, sentry_client=truth_of_bible/1.0, sentry_key={u.username}",
		},
		timeout=3,
	)


def forward_to_glitchtip(doc, method=None):
	"""Error Log after_insert: every error recorded on the site also goes to GlitchTip. Never raises and never
	logs — a GlitchTip outage must not break the request or loop back into Error Log."""
	try:
		s = _tracking()
		if s:
			_post_event(s.server_dsn, doc.method or "Error", doc.error or "", s.environment,
				error_log=doc.name, reference=" ".join(filter(None, [doc.reference_doctype, doc.reference_name])))
	except Exception:
		pass


@frappe.whitelist()
def send_test():
	frappe.only_for("System Manager")
	s = frappe.get_single(SETTINGS)
	if not s.server_dsn:
		frappe.throw(_("Set the Server DSN first."))
	try:
		r = _post_event(s.server_dsn, "Test error from Truth Of Bible", f"Sent by {frappe.session.user} from TOB Error Tracking Settings.", s.environment)
	except Exception as e:
		frappe.throw(_("Couldn't reach GlitchTip: {0}").format(e))
	if r.status_code >= 300:
		frappe.throw(_("GlitchTip refused the test (HTTP {0}): {1}").format(r.status_code, r.text[:300]))
	return _("Sent. It should appear in the GlitchTip project within a minute.")


@frappe.whitelist(allow_guest=True)
def app_config():
	"""The app reads where to send its own errors at start-up. A DSN is designed to be public (every app that
	reports to Sentry/GlitchTip ships one), so this is safe to serve to guests."""
	s = frappe.get_cached_doc(SETTINGS)
	if not s.enabled:
		return {"dsn": "", "environment": ""}
	return {"dsn": (s.app_dsn or s.server_dsn or "").strip(), "environment": s.environment or "production"}
