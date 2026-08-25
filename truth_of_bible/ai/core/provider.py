"""Ported from qtt_platform.ai.core.provider (read directly this session) —
the one interface every vendor integration implements. The gateway and
every AI-generating feature depend only on this, never on a concrete
DeepSeekProvider/OpenAiProvider/etc. class."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from truth_of_bible.ai.core.request import AiRequest
from truth_of_bible.ai.core.response import AiResponse


@dataclass(frozen=True)
class AiCapabilities:
	structured_output: bool = False
	max_context_tokens: int | None = None


class AiProvider(ABC):
	name: str
	capabilities: AiCapabilities

	@abstractmethod
	def is_configured(self) -> bool:
		"""True once credentials are present and the provider is enabled.
		The registry checks this before handing the provider to the
		gateway, so a missing key surfaces as ProviderNotConfigured, never
		a crash mid-request."""
		...

	@abstractmethod
	def generate(self, request: AiRequest) -> AiResponse: ...
