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

import frappe
import requests
from frappe.utils.password import get_decrypted_password

_PROVIDER_KEY = "google"
_DEFAULT_BASE_URL = "https://texttospeech.googleapis.com"
DEFAULT_TIMEOUT_SECONDS = 30


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


def synthesize_speech(text: str, locale: str) -> bytes:
	"""Returns raw audio bytes (encoding per TOB TTS Provider.audio_encoding,
	MP3 by default). Raises TtsProviderDisabled / TtsProviderError — never
	returns a partial/empty result silently."""
	settings = get_settings()
	if settings is None or not settings.enabled:
		raise TtsProviderDisabled("Premium voice is currently unavailable.")
	if not settings.api_key:
		raise TtsProviderDisabled("Premium voice is not configured.")

	payload = {
		"input": {"text": text},
		# Deliberately no voice.name — a bare languageCode always resolves
		# to at least one voice Google guarantees exists for that
		# language, so this can never 400 on a typo'd/renamed voice name
		# and needs no per-language voice-name map to maintain. Trade-off:
		# this typically returns a Standard-tier voice regardless of
		# TOB TTS Provider.voice_type; a real per-tier voice picker (via
		# GET /v1/voices?languageCode=...) is a future enhancement.
		"voice": {"languageCode": locale},
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
