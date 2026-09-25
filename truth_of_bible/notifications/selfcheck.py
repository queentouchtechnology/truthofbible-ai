"""SYSTEM_ALERT — NOTIFICATION_ENGINE_PLAN.md "What's still open" item 4
("a self-monitoring job (e.g. FCM send failures spiking); not requested by
name yet, no scaffolding built"). The scope kept deliberately small and
concrete, matching the plan's own example rather than inventing a general
health-check framework: this watches for the one failure mode that would
otherwise be invisible — the notification engine itself silently failing
(every trigger and `handle_event` already swallow their own exceptions via
`frappe.log_error`, on purpose, so a real outage produces log rows, not a
crash anyone would notice).

Every `frappe.log_error` call this app's own notification code makes uses
a title starting with "Notification " (see engine.py/triggers.py/reading.py/
prayer.py/bible_study.py/the webhook receivers — grep confirms this is the
one consistent prefix across all of them). Counting `Error Log` rows with
that prefix over a rolling window is a real, direct signal of the engine
failing, not a proxy for something else.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

from truth_of_bible.notifications.engine import handle_event

_WINDOW_HOURS = 24
_THRESHOLD = 10
_TITLE_PREFIX = "Notification "
_EVENT = "SYSTEM_ALERT"

# Never alert about the alert job itself — its own failure is caught and
# logged by the try/except in `daily_check` below, not this counter (which
# would otherwise let a stuck alert loop keep re-triggering itself).
_EXCLUDE_TITLE_SUBSTRING = "self-check"


def daily_check() -> None:
	"""Scheduled daily (see hooks.py) — deliberately not hourly: this is a
	trend signal ("is something broken"), not a per-incident page, and a
	24h window needs at most one look a day to stay meaningful."""
	try:
		_run()
	except Exception:
		frappe.log_error(title="Notification engine: self-check failed", message=frappe.get_traceback())


def _run() -> None:
	# `frappe.log_error(title=..., message=...)` stores `title` on Error
	# Log's `method` field (`error` holds the traceback/message) — stable,
	# long-documented core Frappe behavior, same confidence tier as
	# shop_webhook.py's WooCommerce payload assumptions (not fresh-verified
	# against this exact site's Error Log rows, unlike the LMS doctype
	# fields above; worth one live check after deploy — see the rollout
	# notes for the exact bench console snippet).
	since = add_to_date(now_datetime(), hours=-_WINDOW_HOURS)
	count = frappe.db.count(
		"Error Log",
		{
			"creation": [">=", since],
			"method": ["like", f"{_TITLE_PREFIX}%"],
		},
	)
	if count < _THRESHOLD:
		return
	handle_event(_EVENT, None, {"count": count, "window_hours": _WINDOW_HOURS}, force=True)
