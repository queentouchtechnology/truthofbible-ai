"""Bible intelligence endpoints — explanation (cached) and conversational
Q&A. Neither one stores or looks up scripture text itself: `reference` is
always a plain string the client already resolved against its own
on-device Bible data (see hooks.py's own note on why). Every generated
result is honestly AI-generated content, never presented as Scripture
text itself.
"""

import frappe
from frappe import _

from truth_of_bible.ai import service
from truth_of_bible.ai.core.exceptions import AiProviderException
from truth_of_bible.ai.core.request import AiMessage, AiRequest
from truth_of_bible.ai.prompts import language_instruction, resolve_prompt

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
		frappe.throw(_("Could not generate an explanation: {0}").format(str(exc)), frappe.ValidationError)

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
		frappe.throw(_("Could not answer that question: {0}").format(str(exc)), frappe.ValidationError)

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
