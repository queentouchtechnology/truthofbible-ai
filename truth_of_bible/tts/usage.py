"""Writes one TOB TTS Usage Log row per synthesize call — mirrors
ai/usage.py's record_usage shape (characters instead of tokens). Called
directly from api/tts.py rather than as an on_call hook, since there's no
gateway here to hook into."""

import frappe


def record_tts_usage(
	*,
	task: str,
	language: str | None,
	provider: str,
	voice_type: str | None,
	was_cache_hit: bool,
	character_count: int,
	estimated_cost_usd: float,
	status: str,
	duration_ms: int | None = None,
	error_message: str | None = None,
):
	frappe.get_doc(
		{
			"doctype": "TOB TTS Usage Log",
			"user": frappe.session.user,
			"task": task,
			"language": language,
			"provider": provider,
			"voice_type": voice_type,
			"was_cache_hit": 1 if was_cache_hit else 0,
			"character_count": character_count,
			"estimated_cost_usd": 0 if was_cache_hit else estimated_cost_usd,
			"status": status,
			"duration_ms": duration_ms,
			"error_message": error_message,
		}
	).insert(ignore_permissions=True)
