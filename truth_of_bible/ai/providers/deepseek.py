from truth_of_bible.ai.providers.openai_compatible_provider import OpenAiCompatibleProvider


class DeepSeekProvider(OpenAiCompatibleProvider):
	provider_key = "deepseek"
	default_base_url = "https://api.deepseek.com/v1"
