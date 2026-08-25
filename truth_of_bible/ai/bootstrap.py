"""Ported from qtt_platform.ai.bootstrap (read directly this session) —
wires every known provider class into a fresh AiProviderRegistry. One
function, called once per gateway construction, deliberately not a
module-level singleton (Frappe request workers shouldn't share mutable
state across requests).

Only mock/deepseek/openai are wired for Phase 1 — openrouter/gemini/
anthropic would follow the identical OpenAiCompatibleProvider (or a new
subclass) pattern if/when needed; not built speculatively ahead of an
actual provider account existing.
"""

from truth_of_bible.ai.core.registry import AiProviderRegistry
from truth_of_bible.ai.providers.deepseek import DeepSeekProvider
from truth_of_bible.ai.providers.mock import MockProvider
from truth_of_bible.ai.providers.openai_provider import OpenAiProvider

_PROVIDER_CLASSES = (
	MockProvider,
	DeepSeekProvider,
	OpenAiProvider,
)


def build_registry() -> AiProviderRegistry:
	registry = AiProviderRegistry()
	for provider_cls in _PROVIDER_CLASSES:
		registry.register(provider_cls())
	return registry
