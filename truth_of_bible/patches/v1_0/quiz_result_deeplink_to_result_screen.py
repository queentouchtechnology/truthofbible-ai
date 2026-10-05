"""QUIZ_RESULT_AVAILABLE used to deep-link to /viewQuiz with the quiz id, so
tapping "Your result is ready" opened the quiz-taking screen. It now opens
the submission's result screen (/viewQuizResult + submission_id).

`seed_notification_templates` is create-only, so an already-seeded row keeps
the old route. Only rows still on the old values are moved — a route an admin
changed by hand in the app is left alone."""

import frappe


def execute():
	name = "QUIZ_RESULT_AVAILABLE"
	current = frappe.db.get_value(
		"TOB Notification Template", name, ["deeplink_route", "deeplink_id_field"], as_dict=True
	)
	if not current or current.deeplink_route != "/viewQuiz" or current.deeplink_id_field != "quiz_id":
		return
	frappe.db.set_value(
		"TOB Notification Template",
		name,
		{"deeplink_route": "/viewQuizResult", "deeplink_id_field": "submission_id"},
	)
