"""Google Cloud Text-to-Speech client — the one place that actually calls
out to the vendor. Deliberately NOT routed through ai/service.py's
AiGateway: that machinery exists to pick among N interchangeable LLM
providers with retry/fallback, and TTS has exactly one vendor with no
fallback requirement in scope, so wrapping a single REST call in that
scaffolding would be premature abstraction. Synchronous `requests`,
matching every other provider call in this app (Frappe's WSGI worker
model has no event loop) — see ai/providers/openai_compatible.py for the
same pattern applied to chat completions."""

import base64
import json

import frappe
import requests
from frappe.utils.password import get_decrypted_password

_PROVIDER_KEY = "google"
_DEFAULT_BASE_URL = "https://texttospeech.googleapis.com"
DEFAULT_TIMEOUT_SECONDS = 30
_VOICES_CACHE_TTL_SECONDS = 24 * 60 * 60


class TtsProviderDisabled(Exception):
	"""Raised when TOB TTS Provider('google') doesn't exist, is disabled,
	or has no API key configured — never transient, no provider to fall
	back to."""


class TtsProviderError(Exception):
	"""Raised on any failure talking to Google itself (network, timeout,
	non-2xx response)."""


class TtsSettings:
	def __init__(self, doc):
		self.enabled = bool(doc.enabled)
		self.base_url = (doc.base_url or _DEFAULT_BASE_URL).rstrip("/")
		# `site_config.json`'s `google_tts_api_key` is the primary source now
		# (same pattern as `google_maps_api_key`/`firebase_service_account`/
		# `buffer_api_token` elsewhere in this app) — the admin screen no
		# longer collects this key at all. The doctype's own encrypted
		# `api_key` field is kept only as a fallback for any site that set
		# it the old way (via the TTS Settings screen or Desk) before this
		# changed, so an existing working setup doesn't silently break.
		self.api_key = frappe.get_site_config().get("google_tts_api_key") or get_decrypted_password(
			"TOB TTS Provider", doc.name, "api_key", raise_exception=False
		)
		self.voice_type = doc.voice_type
		self.audio_encoding = doc.audio_encoding or "MP3"
		self.price_per_million_chars_usd = float(doc.price_per_million_chars_usd or 0)
		self.character_limit_per_request = int(doc.character_limit_per_request or 5000)


def get_settings() -> TtsSettings | None:
	"""None when the 'google' row doesn't exist yet (admin has never saved
	the TTS Settings screen) — callers treat that the same as disabled."""
	if not frappe.db.exists("TOB TTS Provider", _PROVIDER_KEY):
		return None
	return TtsSettings(frappe.get_doc("TOB TTS Provider", _PROVIDER_KEY))


def _list_voices(settings: TtsSettings, locale: str) -> list[dict]:
	"""Google's available voices for `locale` — cached a day at a time
	(this almost never changes) so picking a tier doesn't cost an extra
	external call on every single synthesize request. Returns [] on any
	failure; callers treat that the same as "no tier match, use Google's
	own default" rather than failing the whole synthesize call over it."""
	cache_key = f"tts_voices::{locale}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return json.loads(cached)
	try:
		response = requests.get(
			f"{settings.base_url}/v1/voices",
			params={"languageCode": locale, "key": settings.api_key},
			timeout=DEFAULT_TIMEOUT_SECONDS,
		)
		response.raise_for_status()
		voices = response.json().get("voices", [])
	except requests.RequestException:
		voices = []
	frappe.cache().set_value(cache_key, json.dumps(voices), expires_in_sec=_VOICES_CACHE_TTL_SECONDS)
	return voices


def _pick_voice_name(settings: TtsSettings, locale: str) -> str | None:
	"""A real voice matching the configured tier for `locale` — without
	this, every call omitted voice.name entirely and Google silently
	resolved it to its most basic Standard-tier voice regardless of
	TOB TTS Provider.voice_type, which is why Premium sounded identical
	to the free on-device voice no matter which tier was selected. Not
	every tier exists for every language (e.g. many non-English languages
	have no Neural2/Studio voices at all) — falls back to whatever Google
	does offer for this language rather than failing the request."""
	voices = _list_voices(settings, locale)
	if not voices:
		return None
	tier = (settings.voice_type or "Standard").lower()
	for voice in voices:
		if tier in voice.get("name", "").lower():
			return voice["name"]
	return voices[0].get("name")


def synthesize_speech(text: str, locale: str) -> bytes:
	"""Returns raw audio bytes (encoding per TOB TTS Provider.audio_encoding,
	MP3 by default). Raises TtsProviderDisabled / TtsProviderError — never
	returns a partial/empty result silently."""
	settings = get_settings()
	if settings is None or not settings.enabled:
		raise TtsProviderDisabled("Premium voice is currently unavailable.")
	if not settings.api_key:
		raise TtsProviderDisabled("Premium voice is not configured.")

	voice_name = _pick_voice_name(settings, locale)
	voice = {"languageCode": locale}
	if voice_name:
		voice["name"] = voice_name

	payload = {
		"input": {"text": text},
		"voice": voice,
		"audioConfig": {"audioEncoding": settings.audio_encoding},
	}

	try:
		response = requests.post(
			f"{settings.base_url}/v1/text:synthesize",
			params={"key": settings.api_key},
			json=payload,
			timeout=DEFAULT_TIMEOUT_SECONDS,
		)
	except requests.Timeout as exc:
		raise TtsProviderError("Request to the voice provider timed out.") from exc
	except requests.RequestException as exc:
		raise TtsProviderError(str(exc)) from exc

	if response.status_code >= 400:
		frappe.log_error(title="TTS synthesize failed", message=response.text)
		raise TtsProviderError(f"Voice provider returned {response.status_code}.")

	audio_content = response.json().get("audioContent")
	if not audio_content:
		raise TtsProviderError("Voice provider returned no audio.")
	return base64.b64decode(audio_content)
