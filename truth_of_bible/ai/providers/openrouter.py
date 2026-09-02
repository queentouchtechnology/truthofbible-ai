from truth_of_bible.ai.providers.openai_compatible_provider import OpenAiCompatibleProvider


class OpenRouterProvider(OpenAiCompatibleProvider):
	provider_key = "openrouter"
	default_base_url = "https://openrouter.ai/api/v1"
