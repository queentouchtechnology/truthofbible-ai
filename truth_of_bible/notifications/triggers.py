"""Doc-event triggers that fan out into the notification engine
(engine.handle_event) — Quiz and Support-Ticket User-audience events (the
second slice, after the spiritual/Bible-reading reminders in reading.py),
plus the first Frappe-native Admin-audience events (New Support Ticket,
Ticket Escalated, New User, New Enrollment — see engine.py's `admin_users`
fan-out). Admin-audience triggers pass `user=None`: `handle_event` resolves
its own recipients for an Admin-audience template.

Every trigger here is deliberately defensive: a notification is a
side-effect of a real save (a quiz being created, a submission being
graded, a support agent replying), never a precondition for it. A bug or
outage in the notification engine must never break the actual LMS/ticket
save that triggered it, so every trigger wraps its own body in
try/except + frappe.log_error and never re-raises — registered in
hooks.py's doc_events the same way, as a plain function reference.

Field names used below — LMS Quiz / LMS Quiz Submission / LMS Enrollment
(`course`, `member`, `quiz_title`, `percentage`) and Issue / Communication
(`raised_by`, `reference_doctype`, `reference_name`, `sender`,
`sent_or_received`) — are core Frappe-LMS / Frappe-core fields, cross-
checked against this project's own qmp_lms_bridge app (which already
relies on these exact field names for its own quiz grading / tenant
scoping) and verified live against learn.truthofbible.org's real schema
and sample rows before this file was written.
"""

import frappe

from truth_of_bible.notifications.engine import handle_event

# A single "new quiz" fan-out is capped — a large course shouldn't turn one
# quiz save into thousands of pushes within one request/transaction. 200
# gives real headroom over this site's current enrollment sizes; a
# genuinely larger course is a future background-job problem, not a reason
# to complicate this trigger's contract today.
_MAX_QUIZ_FANOUT = 200


def on_quiz_created(doc, method=None):
	try:
		_on_quiz_created(doc)
	except Exception:
		frappe.log_error(
			title="Notification trigger: on_quiz_created", message=frappe.get_traceback()
		)


def _on_quiz_created(doc):
	course = doc.get("course")
	if not course:
		return

	members = frappe.get_all(
		"LMS Enrollment",
		filters={"course": course},
		pluck="member",
		limit_page_length=_MAX_QUIZ_FANOUT,
	)
	for member in members:
		handle_event(
			"NEW_QUIZ_AVAILABLE",
			member,
			{"quiz_title": doc.get("title") or "", "quiz_id": doc.name, "course": course},
		)


def on_quiz_submission_created(doc, method=None):
	try:
		_on_quiz_submission_created(doc)
	except Exception:
		frappe.log_error(
			title="Notification trigger: on_quiz_submission_created",
			message=frappe.get_traceback(),
		)


def _on_quiz_submission_created(doc):
	member = doc.get("member")
	if not member:
		return

	handle_event(
		"QUIZ_RESULT_AVAILABLE",
		member,
		{
			"quiz_title": doc.get("quiz_title") or "",
			"quiz_id": doc.get("quiz"),
			"percentage": doc.get("percentage") or 0,
		},
	)


def on_communication_created(doc, method=None):
	try:
		_on_communication_created(doc)
	except Exception:
		frappe.log_error(
			title="Notification trigger: on_communication_created",
			message=frappe.get_traceback(),
		)


def _on_communication_created(doc):
	if doc.get("reference_doctype") != "Issue" or not doc.get("reference_name"):
		return
	# `sent_or_received == "Sent"` is set by BOTH an agent's reply to a
	# ticket AND the customer's own "reply to my ticket" flow — it cannot
	# distinguish the two on its own (confirmed against the Flutter client's
	# own addReply_request.dart, which posts the customer's replies through
	# the exact same field). The only reliable discriminator is comparing
	# who actually sent this Communication against who raised the ticket.
	if doc.get("sent_or_received") != "Sent":
		return

	raised_by = frappe.db.get_value("Issue", doc.reference_name, "raised_by")
	if not raised_by:
		return

	sender = (doc.get("sender") or "").strip().lower()
	if sender == raised_by.strip().lower():
		return  # the ticket's own raiser replying to themselves — not an agent reply

	# Issue.raised_by is an email; Frappe's User.name is normally that same
	# email (autoname), but this falls back to a lookup rather than assuming
	# it, matching this codebase's existing defensive style.
	user = frappe.db.get_value("User", {"email": raised_by}, "name") or raised_by
	handle_event("TICKET_AGENT_REPLIED", user, {"ticket_id": doc.reference_name})


# ───────────────────────── Admin-audience events ─────────────────────────


def on_issue_created(doc, method=None):
	try:
		handle_event(
			"NEW_SUPPORT_TICKET",
			None,
			{"ticket_id": doc.name, "subject": doc.get("subject") or ""},
		)
	except Exception:
		frappe.log_error(title="Notification trigger: on_issue_created", message=frappe.get_traceback())


def on_issue_updated(doc, method=None):
	try:
		_on_issue_updated(doc)
	except Exception:
		frappe.log_error(title="Notification trigger: on_issue_updated", message=frappe.get_traceback())


def _on_issue_updated(doc):
	if not doc.has_value_changed("priority"):
		return
	if doc.get("priority") not in ("High", "Urgent"):
		return
	handle_event(
		"TICKET_HIGH_PRIORITY",
		None,
		{"ticket_id": doc.name, "subject": doc.get("subject") or "", "priority": doc.get("priority")},
	)


def on_user_created(doc, method=None):
	try:
		_on_user_created(doc)
	except Exception:
		frappe.log_error(title="Notification trigger: on_user_created", message=frappe.get_traceback())


def _on_user_created(doc):
	# Only real app sign-ups, not System User accounts created from Desk
	# (an admin adding a colleague, a framework-created service account,
	# etc.) — those aren't "a new user joined the app" in any sense an
	# admin would want a push about.
	if doc.get("user_type") != "Website User":
		return
	handle_event(
		"NEW_USER_REGISTERED",
		None,
		{"user_name": doc.get("full_name") or doc.name, "email": doc.name},
	)


def on_enrollment_created(doc, method=None):
	try:
		handle_event(
			"NEW_ENROLLMENT",
			None,
			{"member": doc.get("member") or "", "course": doc.get("course") or ""},
		)
	except Exception:
		frappe.log_error(title="Notification trigger: on_enrollment_created", message=frappe.get_traceback())
