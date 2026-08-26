"""Standalone Bible practice quizzes — same quiz_generation task/prompt
as lms_ai.generate_quiz, but ephemeral: no LMS Course required, no
LMS Quiz/Question docs created. Returns the raw question list straight
to the client for an immediate practice session (self-graded client-side),
distinct from lms_ai.generate_quiz's persisted, course-attached quizzes.
"""

import json

import frappe
from frappe import _

from truth_of_bible.ai import service
from truth_of_bible.ai.core.exceptions import AiProviderException
from truth_of_bible.ai.core.request import AiMessage, AiRequest
from truth_of_bible.ai.prompts import language_instruction, resolve_prompt

_TASK = "quiz_generation"
_DIFFICULTIES = ("easy", "medium", "hard")
_MAX_QUESTIONS = 20


@frappe.whitelist(methods=["POST"])
def generate_practice_quiz(topic: str, language: str, count: int = 5, difficulty: str = "medium") -> dict:
	if difficulty not in _DIFFICULTIES:
		frappe.throw(_("difficulty must be one of: {0}").format(", ".join(_DIFFICULTIES)), frappe.ValidationError)

	try:
		count = max(1, min(int(count), _MAX_QUESTIONS))
	except (TypeError, ValueError):
		frappe.throw(_("count must be a number."), frappe.ValidationError)

	user_message = (
		f"Generate {count} {difficulty}-difficulty multiple-choice Bible quiz questions about '{topic}'. "
		"Each question needs exactly 4 options and a clear explanation."
	)

	system_prompt = resolve_prompt(_TASK, language) + language_instruction(language)
	request = AiRequest(
		task=_TASK,
		language=language,
		messages=[
			AiMessage(role="system", content=system_prompt),
			AiMessage(role="user", content=user_message),
		],
		structured_output=True,
	)

	try:
		response = service.generate(request)
	except AiProviderException as exc:
		frappe.throw(_("Could not generate quiz questions: {0}").format(str(exc)), frappe.ValidationError)

	questions = _parse_quiz_response(response.content)
	usable = [
		q for q in questions
		if len(q.get("options") or []) == 4 and q.get("correct_answer") in (q.get("options") or [])
	]

	if not usable:
		frappe.throw(_("The AI provider's response did not contain any usable questions. Please try again."), frappe.ValidationError)

	return {
		"topic": topic,
		"language": language,
		"difficulty": difficulty,
		"questions": usable,
		"provider": response.provider,
		"model": response.model,
	}


def _parse_quiz_response(content: str) -> list[dict]:
	try:
		data = json.loads(content)
	except (TypeError, ValueError):
		frappe.throw(_("The AI provider returned an unreadable response. Please try again."), frappe.ValidationError)

	questions = data.get("questions") if isinstance(data, dict) else None
	if not isinstance(questions, list):
		frappe.throw(_("The AI provider returned an unexpected response shape."), frappe.ValidationError)
	return questions
