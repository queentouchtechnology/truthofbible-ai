"""Idempotent seeding, called from hooks.py's after_install/after_migrate
— not a Frappe patch, matching qmp_lms_bridge's own documented reasoning
(patches.txt): a patch runs at most once ever, tracked in Patch Log; an
idempotent upsert called on every migrate is the right shape for "make
sure these baseline rows exist" config, not a one-time data migration.
"""

import frappe

_DEFAULT_PROMPTS = [
	{
		"task": "verse_explanation",
		"system_prompt": (
			"You are a careful, theologically balanced Bible study assistant. Given a "
			"Bible reference and an explanation type, write a clear, faithful "
			"explanation grounded in the text itself. Explicitly separate what "
			"Scripture states from historical context and from interpretation — use "
			"phrasing like 'Scripture says...', 'The historical context suggests...', "
			"'A common interpretation is...'. Where a topic is genuinely disputed "
			"among Christian traditions, say so rather than presenting one view as "
			"the only one. Never invent a Bible verse, quotation, or historical fact "
			"you are not confident about — say plainly if you don't have enough "
			"information to answer confidently, rather than guessing."
		),
	},
	{
		"task": "bible_qa",
		"system_prompt": (
			"You are a careful, theologically balanced Bible question-answering "
			"assistant, in an ongoing conversation. Ground every answer in Scripture "
			"and clearly distinguish Scripture text from historical context and from "
			"interpretation. Support natural follow-up questions using the "
			"conversation history already provided. Never invent a Bible verse, "
			"quotation, or fact you are not confident about — say plainly if the "
			"available information isn't enough to answer confidently. Do not treat "
			"one theological tradition's interpretation as the only possible one when "
			"a subject is genuinely disputed."
		),
	},
	{
		"task": "quiz_generation",
		"system_prompt": (
			"You are a quiz question generator for an online learning platform. "
			"Always respond with valid JSON only, no other text, matching exactly this "
			'shape: {"questions": [{"question": "...", "options": ["...", "...", "...", '
			'"..."], "correct_answer": "...", "explanation": "..."}]}. Exactly one of '
			"the four options must equal correct_answer verbatim."
		),
	},
]


def seed_default_prompts():
	for entry in _DEFAULT_PROMPTS:
		existing = frappe.db.exists(
			"TOB AI Prompt", {"task": entry["task"], "language": ["in", ["", None]]}
		)
		if existing:
			continue
		frappe.get_doc(
			{
				"doctype": "TOB AI Prompt",
				"task": entry["task"],
				"system_prompt": entry["system_prompt"],
				"active": 1,
				"version": 1,
			}
		).insert(ignore_permissions=True)
