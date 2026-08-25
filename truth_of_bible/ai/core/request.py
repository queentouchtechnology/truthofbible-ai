"""Ported from qtt_platform.ai.core.request (read directly this session) —
the vendor-neutral request shape every AI-generating feature builds,
regardless of which provider ends up handling it. Do not add
provider-specific fields here — if a capability can't be expressed
generically, it belongs in `metadata` (advisory) or the provider
implementation reads it from its own TOB AI Provider/Model config, not
from the request.

`language` is this app's own addition beyond the qtt_platform shape it's
ported from — every AI request in a multilingual-first app needs to know
which language the response should be generated in, not just which task
it's for.
"""

import dataclasses
from dataclasses import dataclass


@dataclass(frozen=True)
class AiMessage:
	role: str  # "system" | "user" | "assistant"
	content: str


@dataclass(frozen=True)
class AiRequest:
	#: Logical task name, e.g. "verse_explanation", "quiz_generation" — used
	#: for task-based model routing (routing.py) and usage logging.
	task: str
	messages: list[AiMessage]
	#: The language the generated content itself should be in (not the UI
	#: language) — a Language.language_code, e.g. "ta", "hi", "ar". Callers
	#: build this into the prompt/messages themselves; this field exists so
	#: routing/logging/caching can key on it without re-parsing the prompt.
	language: str | None = None
	#: Explicit provider/model override. Omit to route by task (routing.py).
	provider: str | None = None
	model: str | None = None
	temperature: float | None = None
	max_output_tokens: int | None = None
	#: Ask the provider to return valid JSON matching the caller's schema
	#: (the schema itself lives in the prompt, built by the calling
	#: feature — not this layer). The provider implementation decides *how*
	#: (JSON mode, tool calling, prompt-only).
	structured_output: bool = False
	metadata: dict | None = None

	def with_model(self, model: str) -> "AiRequest":
		return dataclasses.replace(self, model=model)

	def with_provider_and_model(self, provider: str, model: str) -> "AiRequest":
		return dataclasses.replace(self, provider=provider, model=model)
