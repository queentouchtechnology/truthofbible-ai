"""Generalized AI content generation — one endpoint covering any
'generate text about a subject' feature (character profiles, place
overviews, event summaries, devotionals, prayers, sermon outlines,
doctrine explanations, discovery facts, book introductions, theme/topic
deep-dives...) via TOB AI Content's cache instead of a bespoke doctype
+ endpoint per feature. `bible.explain`/`bible.qa`/`lms_ai.generate_quiz`
stay as their own endpoints since they have their own request/response
shapes and are already deployed and in use — this is for the growing
catalog of simpler "task + subject -> generated text" features.

Every task used here must have a matching active TOB AI Prompt row
(same requirement as ai.generate/bible.explain) — resolve_prompt()
throws a clear error otherwise, it never falls back to a hardcoded
default that could drift from the safety-reviewed prompt catalog.
"""

import frappe
from frappe import _

from truth_of_bible.ai import service
from truth_of_bible.ai.core.exceptions import AiProviderException
from truth_of_bible.ai.core.request import AiMessage, AiRequest
from truth_of_bible.ai.prompts import language_instruction, resolve_prompt


def _cache_key(task: str, subject: str, variant: str, language: str, prompt_version: int) -> str:
	return f"{task}|{subject}|{variant}|{language}|{prompt_version}"


@frappe.whitelist(methods=["POST"])
def generate(task: str, subject: str, language: str, variant: str = "") -> dict:
	prompt_row = frappe.db.get_value(
		"TOB AI Prompt", {"task": task, "active": 1}, ["name", "version"], as_dict=True
	)
	prompt_version = prompt_row.version if prompt_row else 1
	cache_key = _cache_key(task, subject, variant, language, prompt_version)

	cached = frappe.db.get_value(
		"TOB AI Content", {"cache_key": cache_key}, ["content", "provider", "model"], as_dict=True
	)
	if cached:
		return {
			"task": task,
			"subject": subject,
			"variant": variant,
			"language": language,
			"content": cached.content,
			"provider": cached.provider,
			"model": cached.model,
			"cached": True,
		}

	system_prompt = resolve_prompt(task, language) + language_instruction(language)
	user_message = f"Subject: {subject}" + (f"\nVariant: {variant}" if variant else "")
	request = AiRequest(
		task=task,
		language=language,
		messages=[
			AiMessage(role="system", content=system_prompt),
			AiMessage(role="user", content=user_message),
		],
	)

	try:
		response = service.generate(request)
	except AiProviderException as exc:
		frappe.throw(_("Could not generate content: {0}").format(str(exc)), frappe.ValidationError)

	frappe.get_doc(
		{
			"doctype": "TOB AI Content",
			"task": task,
			"subject": subject,
			"variant": variant,
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
		"task": task,
		"subject": subject,
		"variant": variant,
		"language": language,
		"content": response.content,
		"provider": response.provider,
		"model": response.model,
		"cached": False,
	}
