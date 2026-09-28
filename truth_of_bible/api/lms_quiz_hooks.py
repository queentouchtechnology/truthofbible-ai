"""Reacts to a new `LMS Quiz Submission` (any submission, from any app
user, via the app's existing quiz-taking flow) and awards Sunday School
points if — and only if — that quiz is this week's Active
`TOB Sunday School Quiz Assignment`. See sunday_school/engine.py::
on_lms_quiz_submission for the actual logic; this is just the doc_event
wrapper (hooks.py), matching every other trigger in notifications/
triggers.py: never let a failure here touch the real submission save
that fired it.
"""

import frappe

from truth_of_bible.sunday_school import engine


def on_submission_created(doc, method=None):
	try:
		engine.on_lms_quiz_submission(doc.member, doc.quiz, doc.score)
	except Exception:
		frappe.log_error(title="Sunday School: on_lms_quiz_submission failed", message=frappe.get_traceback())
