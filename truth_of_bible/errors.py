"""One way to fail an API call when something behind it breaks (an AI or voice provider, GitHub, a login):
the real error goes to the desk's Error Log, and the user only ever sees a short, friendly sentence. Provider
replies, status codes, request ids and tracebacks never reach the app.

A frappe.throw on its own is treated as a validation message and isn't logged, which is why a failure has to
be recorded here before throwing."""

import inspect

import frappe
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
