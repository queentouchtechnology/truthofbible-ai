"""Keeps a Sunday-School-assigned `LMS Quiz` out of the app-wide public
quiz list, without touching LMS Quiz's own schema or permissions.

**Why not `permission_query_conditions`**: the Flutter app's admin quiz
management screens AND its public "browse all quizzes" screen both call
the same generic `/api/resource/LMS Quiz` REST endpoint with the same
shared `erpToken` — there is no way to tell them apart by *who* is
asking, only by *which screen* is asking. A permission hook would hide
an assigned quiz from admin's own management screen just as much as from
the public list, defeating the point (admin still needs to find and edit
the quiz's questions there). So this is a parallel endpoint instead:
`list_public_quizzes` mirrors the exact request shape
`quizList_api.dart` already sends (same field/filter/pagination
parameters), with one extra exclusion appended server-side. Only the
public quiz list's Flutter call points here; admin quiz management keeps
hitting `/api/resource/LMS Quiz` directly, unaffected.
"""

import json

import frappe
from frappe.utils import cint

from truth_of_bible.sunday_school import engine


@frappe.whitelist(allow_guest=True, methods=["GET"])
def list_public_quizzes(fields=None, filters=None, order_by=None, limit_page_length=None, limit_start=None):
	all_filters = json.loads(filters) if filters else []
	if not isinstance(all_filters, list):
		all_filters = []

	assigned = engine.assigned_lms_quiz_ids()
	if assigned:
		all_filters.append(["name", "not in", list(assigned)])

	rows = frappe.get_list(
		"LMS Quiz",
		fields=json.loads(fields) if fields else ["*"],
		filters=all_filters,
		order_by=order_by or "creation desc",
		# 0 means "all" (the admin Assessments screen asks for the whole list);
		# only a missing value falls back to a page of 20.
		limit_page_length=20 if limit_page_length in (None, "") else cint(limit_page_length),
		limit_start=cint(limit_start) or 0,
	)
	# Mirrors the wire shape of a plain `/api/resource/LMS Quiz` list GET
	# (`{"data": [...]}`), so the Flutter client's existing
	# `QuizListResponse.fromJson(response.data)` needs no change beyond
	# the endpoint URL itself.
	frappe.local.response["data"] = rows
