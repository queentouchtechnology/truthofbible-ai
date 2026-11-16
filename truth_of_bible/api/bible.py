"""Bible intelligence endpoints — explanation (cached) and conversational
Q&A. Neither one stores or looks up scripture text itself: `reference` is
always a plain string the client already resolved against its own
on-device Bible data (see hooks.py's own note on why). Every generated
result is honestly AI-generated content, never presented as Scripture
text itself.
"""

from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import getdate, today

from truth_of_bible import errors, verse_of_the_day

from truth_of_bible.ai import service
from truth_of_bible.ai.core.exceptions import AiProviderException
from truth_of_bible.ai.core.request import AiMessage, AiRequest
from truth_of_bible.ai.prompts import language_instruction, resolve_prompt
from truth_of_bible.rewards.gate import charge_ai

_EXPLANATION_TASK = "verse_explanation"
_QA_TASK = "bible_qa"


def _cache_key(reference: str, explanation_type: str, language: str, prompt_version: int) -> str:
	return f"{reference}|{explanation_type}|{language}|{prompt_version}"


@frappe.whitelist(methods=["POST"])
def explain(reference: str, language: str, explanation_type: str = "verse") -> dict:
	prompt_row = frappe.db.get_value(
		"TOB AI Prompt", {"task": _EXPLANATION_TASK, "active": 1}, ["name", "version"], as_dict=True
	)
	prompt_version = prompt_row.version if prompt_row else 1
	cache_key = _cache_key(reference, explanation_type, language, prompt_version)

	cached = frappe.db.get_value(
		"TOB Bible Explanation", {"cache_key": cache_key}, ["content", "provider", "model"], as_dict=True
	)
	if cached:
		return {
			"reference": reference,
			"language": language,
			"explanation_type": explanation_type,
			"content": cached.content,
			"provider": cached.provider,
			"model": cached.model,
			"cached": True,
		}

	system_prompt = resolve_prompt(_EXPLANATION_TASK, language) + language_instruction(language)
	request = AiRequest(
		task=_EXPLANATION_TASK,
		language=language,
		messages=[
			AiMessage(role="system", content=system_prompt),
			AiMessage(
				role="user",
				content=f"Explanation type: {explanation_type}\nReference: {reference}",
			),
		],
	)

	try:
		response = service.generate(request)
	except AiProviderException as exc:
		errors.ai_fail(_("The AI explanation"), exc)

	frappe.get_doc(
		{
			"doctype": "TOB Bible Explanation",
			"reference": reference,
			"explanation_type": explanation_type,
			"language": language,
			"cache_key": cache_key,
			"prompt_version": prompt_version,
			"content": response.content,
			"provider": response.provider,
			"model": response.model,
			"generated_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)

	return {
		"reference": reference,
		"language": language,
		"explanation_type": explanation_type,
		"content": response.content,
		"provider": response.provider,
		"model": response.model,
		"cached": False,
	}


@frappe.whitelist(methods=["POST"])
@charge_ai
def qa(question: str, language: str) -> dict:
	"""Starts a new conversation. Use qa_followup to continue it."""
	conversation = frappe.get_doc(
		{
			"doctype": "TOB Bible Conversation",
			"user": frappe.session.user,
			"title": question[:140],
			"language": language,
		}
	)
	conversation.insert(ignore_permissions=True)

	return _ask(conversation.name, question, language)


@frappe.whitelist(methods=["POST"])
@charge_ai
def qa_followup(conversation: str, question: str) -> dict:
	convo = frappe.get_doc("TOB Bible Conversation", conversation)
	if convo.user != frappe.session.user:
		frappe.throw(_("This conversation does not belong to you."), frappe.PermissionError)

	return _ask(convo.name, question, convo.language)


def _ask(conversation_name: str, question: str, language: str) -> dict:
	frappe.get_doc(
		{
			"doctype": "TOB Bible Conversation Message",
			"conversation": conversation_name,
			"role": "user",
			"content": question,
		}
	).insert(ignore_permissions=True)

	history = frappe.get_all(
		"TOB Bible Conversation Message",
		filters={"conversation": conversation_name},
		fields=["role", "content"],
		order_by="creation asc",
	)

	system_prompt = resolve_prompt(_QA_TASK, language) + language_instruction(language)
	messages = [AiMessage(role="system", content=system_prompt)]
	messages += [AiMessage(role=row.role, content=row.content) for row in history]

	request = AiRequest(task=_QA_TASK, language=language, messages=messages)

	try:
		response = service.generate(request)
	except AiProviderException as exc:
		errors.ai_fail(_("The AI answer"), exc)

	frappe.get_doc(
		{
			"doctype": "TOB Bible Conversation Message",
			"conversation": conversation_name,
			"role": "assistant",
			"content": response.content,
		}
	).insert(ignore_permissions=True)

	return {
		"conversation": conversation_name,
		"language": language,
		"answer": response.content,
		"provider": response.provider,
		"model": response.model,
	}


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def get_blessing_verse(date: str | None = None) -> dict:
	"""The Verse of the Day (see truth_of_bible.verse_of_the_day): the same pinned verse for every user on a
	date, with its background, other backgrounds for the picker, and the day's app feature line. `date` is the
	phone's own local date (YYYY-MM-DD); it may be a day either side of the server's, never further. Never
	returns verse text -- the client resolves that on-device from its own Bible translation. Also the anchor
	reference the daily_devotional AI task writes around."""
	verse = verse_of_the_day.for_date(_local_day(date))
	if not verse:
		frappe.throw(_("No blessing verses are configured yet."))
	return {**verse, "popup": _verse_popup_on()}


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def get_verse_history(before: str | None = None, limit: int = 30) -> list[dict]:
	"""Past Verses of the Day, newest first, for the Verse Wallpapers screen. `before` is exclusive (a date);
	blank means up to and including today. Pages of at most 60."""
	start = getdate(before) if before else getdate(today()) + timedelta(days=1)
	return verse_of_the_day.history(start, min(max(int(limit or 30), 1), 60))


def blessing_of_the_day() -> dict | None:
	"""Today's Verse of the Day (None when there is none). Shared by the website popup
	(truth_of_bible.api.website.popup)."""
	return verse_of_the_day.for_date(getdate(today()))


def _verse_popup_on() -> bool:
	"""TOB Website Settings → Show the Verse of the Day popup: Everyone, Admins only (System Managers, to try it
	first; also when the field was never saved) or Off."""
	mode = frappe.db.get_single_value("TOB Website Settings", "app_verse_popup") or "Admins only"
	if mode == "Everyone":
		return True
	return mode == "Admins only" and "System Manager" in frappe.get_roles()


def _local_day(value: str | None) -> date:
	server = getdate(today())
	if not value:
		return server
	try:
		day = getdate(value)
	except Exception:
		return server
	return day if abs((day - server).days) <= 1 else server
