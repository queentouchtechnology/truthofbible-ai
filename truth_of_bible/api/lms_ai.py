"""LMS AI quiz generation — the prompt/response-parsing shape is ported
from qmp_lms_bridge/ai_features.py::generate_quiz (read directly this
session), which is real, working code against the same `lms` app version.
Two real differences from that port, not accidental omissions:

1. Multilingual: `language` drives both the system prompt's dynamic
   language instruction and the generated question/option text itself —
   qmp_lms_bridge's version has no language dimension at all, since
   QuizMasterPlus is English-only today.
2. Scoped to `Choices` questions only for Phase 1. qmp_lms_bridge's
   `Open Ended` support depends on a `sample_answer` Custom Field ITS OWN
   fixture adds to `LMS Question` — that Custom Field will not exist on
   learn.truthofbible.org (qmp_lms_bridge isn't installed there), so
   relying on it here would silently corrupt data. `User Input`/
   `Open Ended` support can be added later behind its own Custom Field
   fixture in this app, once actually needed — not built speculatively
   against a field that doesn't exist on this site.

Real LMS field names used below, confirmed live this session via
qmp_lms_bridge's own verified-live documentation: LMS Course.title/
short_introduction/description, LMS Quiz.title/course/questions/
passing_percentage, LMS Question.question/type/option_1..4/is_correct_1..4.
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
def generate_quiz(course: str, topic: str, language: str, count: int = 5, difficulty: str = "medium") -> dict:
	if not frappe.db.exists("LMS Course", course):
		frappe.throw(_("No such course: {0}").format(course), frappe.ValidationError)

	if difficulty not in _DIFFICULTIES:
		frappe.throw(_("difficulty must be one of: {0}").format(", ".join(_DIFFICULTIES)), frappe.ValidationError)

	try:
		count = max(1, min(int(count), _MAX_QUESTIONS))
	except (TypeError, ValueError):
		frappe.throw(_("count must be a number."), frappe.ValidationError)

	user_message = (
		f"Generate {count} {difficulty}-difficulty multiple-choice quiz questions about '{topic}'. "
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

	quiz = frappe.get_doc(
		{
			"doctype": "LMS Quiz",
			"title": f"{topic} ({difficulty.title()})",
			"course": course,
			"passing_percentage": 50,
		}
	)

	for q in questions:
		options = q.get("options") or []
		correct_answer = q.get("correct_answer")
		if len(options) != 4 or correct_answer not in options:
			# Skip a malformed question rather than failing the whole quiz
			# — the AI occasionally drops an option or mismatches the
			# correct answer text; better to create a smaller, correct
			# quiz than none at all.
			continue

		question_doc = frappe.get_doc(
			{
				"doctype": "LMS Question",
				"question": q.get("question"),
				"type": "Choices",
				"multiple": 0,
			}
		)
		for i, option_text in enumerate(options, start=1):
			question_doc.set(f"option_{i}", option_text)
			question_doc.set(f"is_correct_{i}", 1 if option_text == correct_answer else 0)
		question_doc.insert(ignore_permissions=True)

		quiz.append("questions", {"question": question_doc.name, "marks": 1})

	if not quiz.questions:
		frappe.throw(_("The AI provider's response did not contain any usable questions. Please try again."), frappe.ValidationError)

	quiz.insert(ignore_permissions=True)

	return {
		"quiz": quiz.name,
		"course": course,
		"language": language,
		"question_count": len(quiz.questions),
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
