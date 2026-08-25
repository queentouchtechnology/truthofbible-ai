"""Resolves a TOB AI Prompt for a given task/language — prefers a
language-specific override if one exists and is active, otherwise falls
back to the language-independent default (language_override left blank
on the TOB AI Prompt row), which is the normal case per the product's own
'one robust prompt with dynamic language instructions' preference.

The field is named language_override, not language — deliberately, and
not a style choice: a Link field literally named `language` is a Frappe
reserved default key, silently auto-populated from the site's own
default language on insert even when never explicitly set. Confirmed
live, not guessed: this app's first deployment seeded rows came back
with language='en' despite install.py never setting it, which would have
silently broken every non-English request's fallback lookup below."""

import frappe
from frappe import _


def resolve_prompt(task: str, language: str | None) -> str:
	if language:
		override = frappe.db.get_value(
			"TOB AI Prompt", {"task": task, "language_override": language, "active": 1}, "system_prompt"
		)
		if override:
			return override

	default = frappe.db.get_value(
		"TOB AI Prompt", {"task": task, "language_override": ["is", "not set"], "active": 1}, "system_prompt"
	)
	if not default:
		frappe.throw(_("No active prompt configured for task '{0}'.").format(task))
	return default


def language_instruction(language: str | None) -> str:
	"""Appended to the system prompt so a single language-independent
	prompt still produces output in the right language — the 'dynamic
	language instructions' half of the pattern."""
	if not language:
		return ""
	language_name = frappe.db.get_value("Language", language, "language_name") or language
	return f"\n\nRespond entirely in {language_name} ({language}). Do not mix languages."
