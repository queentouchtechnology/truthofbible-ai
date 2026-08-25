"""Generic AI dispatcher — mirrors qtt_platform.api.ai.generate's shape
(task/inputs in, generated content out) minus every tenant/product/credit
check that function has, since this site has no such concept. Every
authenticated Frappe user may call this; there is no per-tenant gating to
do. Errors use plain frappe.throw(), matching qtt_platform's own
authenticated-endpoint convention (the envelope style is reserved there
for guest-accessible endpoints, which this app has none of)."""

import frappe
from frappe import _

from truth_of_bible.ai import service
from truth_of_bible.ai.core.exceptions import AiProviderException
from truth_of_bible.ai.core.request import AiMessage, AiRequest
from truth_of_bible.ai.prompts import language_instruction, resolve_prompt


@frappe.whitelist(methods=["POST"])
def generate(task: str, prompt: str, language: str | None = None, structured_output: bool = False) -> dict:
	"""Low-level generic entry point — mostly useful for admin testing and
	any future task that doesn't need its own bespoke endpoint. The real
	features (bible.explain, bible.qa, lms_ai.generate_quiz) build their
	own AiRequest directly rather than routing through this, since they
	each need their own prompt construction/response parsing."""
	system_prompt = resolve_prompt(task, language) + language_instruction(language)

	request = AiRequest(
		task=task,
		language=language,
		messages=[
			AiMessage(role="system", content=system_prompt),
			AiMessage(role="user", content=prompt),
		],
		structured_output=bool(structured_output),
	)

	try:
		response = service.generate(request)
	except AiProviderException as exc:
		frappe.throw(_("AI generation failed: {0}").format(str(exc)), frappe.ValidationError)

	return {
		"content": response.content,
		"language": language,
		"provider": response.provider,
		"model": response.model,
	}
