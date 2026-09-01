"""Ported from qtt_platform.ai.providers.openai_compatible_provider (read
directly this session) — shared base for every provider that speaks the
OpenAI-compatible chat completions format (DeepSeek, OpenAI, OpenRouter):
factors out the identical is_configured()/generate() shape so each
concrete provider file only states its provider_key and default base URL."""

import frappe
from frappe.utils.password import get_decrypted_password

from truth_of_bible.ai.core.provider import AiCapabilities, AiProvider
from truth_of_bible.ai.core.request import AiRequest
from truth_of_bible.ai.core.response import AiResponse
from truth_of_bible.ai.providers.openai_compatible import call_openai_compatible_chat


class OpenAiCompatibleProvider(AiProvider):
	provider_key: str
	default_base_url: str
	capabilities = AiCapabilities(structured_output=True)

	@property
	def name(self) -> str:  # AiProvider.name
		return self.provider_key

	def is_configured(self) -> bool:
		row = frappe.db.get_value("TOB AI Provider", self.provider_key, ["enabled"], as_dict=True)
		if not row or not row.enabled:
			return False
		try:
			# get_decrypted_password is the standard, documented Frappe
			# mechanism for reading a Password fieldtype's real value
			# server-side — never returned by any REST response.
			api_key = get_decrypted_password(
				"TOB AI Provider", self.provider_key, "api_key", raise_exception=False
			)
		except Exception:
			return False
		return bool(api_key)

	def generate(self, request: AiRequest) -> AiResponse:
		provider_row = frappe.db.get_value("TOB AI Provider", self.provider_key, ["base_url"], as_dict=True)
		# .strip() guards against the single most common real-world cause of
		# a provider's own "incorrect/invalid API key" 401 — a stray
		# leading/trailing space or newline picked up when the key was
		# copy-pasted into the Password field via Desk. Frappe does not
		# trim Data/Password field input, and a whitespace-corrupted key
		# looks identical to a valid one everywhere except at the provider,
		# where it's silently rejected. This is a no-op for an already-clean
		# key/base_url, so it can't change behavior for a correctly
		# configured provider.
		api_key = (get_decrypted_password("TOB AI Provider", self.provider_key, "api_key") or "").strip()
		base_url = ((provider_row.base_url if provider_row else None) or self.default_base_url).strip()
		return call_openai_compatible_chat(
			base_url=base_url, api_key=api_key, provider_name=self.provider_key, request=request
		)
