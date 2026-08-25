"""Ported from qtt_platform.ai.core.registry (read directly this session) —
a simple name -> AiProvider lookup. Deliberately dumb: it doesn't know
about routing, retry, or fallback (that's AiGateway's job); it only
resolves a name to a configured provider instance."""

from truth_of_bible.ai.core.exceptions import AiProviderException, ProviderNotConfigured
from truth_of_bible.ai.core.provider import AiProvider


class AiProviderRegistry:
	def __init__(self):
		self._providers: dict[str, AiProvider] = {}

	def register(self, provider: AiProvider) -> None:
		self._providers[provider.name] = provider

	def resolve(self, name: str) -> AiProvider:
		provider = self._providers.get(name)
		if not provider:
			raise AiProviderException("UnknownProvider", name, f"No provider registered: {name}")
		if not provider.is_configured():
			raise ProviderNotConfigured(name)
		return provider
