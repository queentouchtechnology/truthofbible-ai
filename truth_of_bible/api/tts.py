"""Text-to-speech — the Premium (Google Cloud TTS) alternative to the
app's free on-device voice. One student-facing endpoint (`synthesize`)
does cache-check -> call vendor -> cache -> log, so replaying the same
text+locale+voice combination never re-pays Google (see
TOB TTS Audio Cache's own docstring). Admin settings mirror
api/translation.py's get/set shape exactly.

Access control: `synthesize` goes through the exact same
truth_of_bible.ai.service.check_ai_access() every text-generation AI
feature already goes through — one kill switch (TOB AI Settings.ai_enabled)
and one block list (TOB AI Blocked User) cover both, not two parallel
ones — plus its own TOB TTS Provider.enabled switch layered on top, the
same "feature flag under the global gate" layering translation.py's
translation_feature_enabled already uses."""

import hashlib

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.file_manager import save_file

from truth_of_bible.ai.service import check_ai_access
from truth_of_bible.communication.auth import require_admin
from truth_of_bible.tts import service as tts_service
from truth_of_bible.tts.usage import record_tts_usage

_PROVIDER_KEY = "google"


def _hash(text: str, locale: str, voice_type: str | None, audio_encoding: str) -> str:
	key = f"{text}|{locale}|{voice_type or ''}|{audio_encoding}"
	return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _language_code(locale: str) -> str | None:
	"""TOB TTS Usage Log.language is a Link to Language, whose rows are
	plain codes ('ta', 'en') — a full BCP-47 locale like 'ta-IN' would
	fail that Link's existence check. Strip the region suffix; falls back
	to None (an empty Link is valid) if the base code isn't a real
	Language row either, rather than letting a bad locale block logging."""
	code = (locale or "").split("-")[0].lower()
	return code if frappe.db.exists("Language", code) else None


@frappe.whitelist(methods=["GET"])
def get_tts_settings():
	settings = tts_service.get_settings()
	if settings is None:
		return {"enabled": False}
	return {
		"enabled": settings.enabled,
		"voice_type": settings.voice_type,
		"price_per_million_chars_usd": settings.price_per_million_chars_usd,
	}


@frappe.whitelist(methods=["POST"])
def set_tts_provider_settings(
	enabled=None,
	voice_type=None,
	audio_encoding=None,
	price_per_million_chars_usd=None,
	character_limit_per_request=None,
	api_key=None,
):
	"""Get-or-creates the single 'google' TOB TTS Provider row — it won't
	exist until an admin first saves this screen. api_key is only
	overwritten when a non-blank value is actually submitted, so a
	re-save from a UI that shows the key masked/blank never wipes the
	stored secret."""
	require_admin()
	if frappe.db.exists("TOB TTS Provider", _PROVIDER_KEY):
		doc = frappe.get_doc("TOB TTS Provider", _PROVIDER_KEY)
	else:
		doc = frappe.get_doc({"doctype": "TOB TTS Provider", "provider_key": _PROVIDER_KEY})

	if enabled is not None:
		doc.enabled = 1 if str(enabled).lower() in ("1", "true", "yes") else 0
	if voice_type:
		doc.voice_type = voice_type
	if audio_encoding:
		doc.audio_encoding = audio_encoding
	if price_per_million_chars_usd is not None:
		doc.price_per_million_chars_usd = float(price_per_million_chars_usd)
	if character_limit_per_request is not None:
		doc.character_limit_per_request = int(character_limit_per_request)
	if api_key:
		doc.api_key = api_key

	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"enabled": bool(doc.enabled)}


@frappe.whitelist(methods=["POST"])
def synthesize(text: str, locale: str, task: str = "general"):
	"""On-demand speech synthesis for the Premium voice option. Returns
	{"audio_url": ..., "cached": bool}. Raises a clean frappe.throw on any
	failure — the client falls back to the free on-device voice rather
	than surfacing this to the user (see tts_playback_controller.dart)."""
	check_ai_access()

	text = (text or "").strip()
	if not text:
		frappe.throw(_("No text to speak."))

	settings = tts_service.get_settings()
	if settings is None or not settings.enabled:
		frappe.throw(_("Premium voice is currently unavailable."))
	if len(text) > settings.character_limit_per_request:
		frappe.throw(_("That text is too long to read aloud ({0} character limit).").format(settings.character_limit_per_request))

	language_code = _language_code(locale)
	cache_key = _hash(text, locale, settings.voice_type, settings.audio_encoding)
	existing = frappe.db.get_value("TOB TTS Audio Cache", {"cache_key": cache_key}, "name")
	if existing:
		cache_doc = frappe.get_doc("TOB TTS Audio Cache", existing)
		cache_doc.hit_count = (cache_doc.hit_count or 0) + 1
		cache_doc.last_used = now_datetime()
		cache_doc.save(ignore_permissions=True)
		frappe.db.commit()
		record_tts_usage(
			task=task, language=language_code, provider=_PROVIDER_KEY, voice_type=settings.voice_type,
			was_cache_hit=True, character_count=len(text), estimated_cost_usd=0, status="success",
		)
		return {"audio_url": cache_doc.audio_file, "cached": True}

	try:
		audio_bytes, voice_name = tts_service.synthesize_speech(text, locale)
	except (tts_service.TtsProviderDisabled, tts_service.TtsProviderError) as exc:
		record_tts_usage(
			task=task, language=language_code, provider=_PROVIDER_KEY, voice_type=settings.voice_type,
			was_cache_hit=False, character_count=len(text), estimated_cost_usd=0, status="error",
			error_message=str(exc),
		)
		frappe.throw(_("Could not generate speech: {0}").format(str(exc)))

	character_count = len(text)
	estimated_cost_usd = (character_count / 1_000_000) * settings.price_per_million_chars_usd

	cache_doc = frappe.get_doc(
		{
			"doctype": "TOB TTS Audio Cache",
			"cache_key": cache_key,
			"locale": locale,
			"voice_type": settings.voice_type,
			"character_count": character_count,
			"source_text": text[:2000],
			"hit_count": 0,
			"last_used": now_datetime(),
		}
	).insert(ignore_permissions=True)

	extension = "ogg" if settings.audio_encoding == "OGG_OPUS" else ("wav" if settings.audio_encoding == "LINEAR16" else "mp3")
	file_doc = save_file(
		fname=f"{cache_doc.name}.{extension}",
		content=audio_bytes,
		dt="TOB TTS Audio Cache",
		dn=cache_doc.name,
		is_private=0,
	)
	cache_doc.audio_file = file_doc.file_url
	cache_doc.save(ignore_permissions=True)
	frappe.db.commit()

	record_tts_usage(
		task=task, language=language_code, provider=_PROVIDER_KEY, voice_type=settings.voice_type,
		was_cache_hit=False, character_count=character_count, estimated_cost_usd=estimated_cost_usd, status="success",
	)
	# voice_name included temporarily for on-device diagnosis of a report
	# that Premium and Free sound identical — remove once confirmed.
	return {"audio_url": file_doc.file_url, "cached": False, "voice_name": voice_name}
