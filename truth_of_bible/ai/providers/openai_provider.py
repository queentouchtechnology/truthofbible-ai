# Named openai_provider.py, not openai.py, to avoid import ambiguity with
# the real third-party `openai` Python package.
from truth_of_bible.ai.providers.openai_compatible_provider import OpenAiCompatibleProvider


class OpenAiProvider(OpenAiCompatibleProvider):
	provider_key = "openai"
	default_base_url = "https://api.openai.com/v1"
