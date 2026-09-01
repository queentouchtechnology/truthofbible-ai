"""Regression tests for OpenAiCompatibleProvider.generate()'s api_key /
base_url whitespace stripping (see fix/ai-provider-error-diagnostics-417).

Prompted by a live 401 "Incorrect API key provided" from a provider right
after its TOB AI Provider row was edited via Desk — a stray leading/
trailing space or newline picked up from a copy-paste is the most common
real-world cause of exactly that symptom, since Frappe does not trim
Data/Password field input. This does not fix a bad/revoked key (that is a
data problem, not a code one), but it removes whitespace corruption as a
possible cause going forward.

OpenAiCompatibleProvider is shared by every OpenAI-compatible vendor
(OpenAI, DeepSeek, OpenRouter, ...), so — deliberately — none of the
fixture values below are a real vendor name, model id, or credential
format; the behavior under test applies identically regardless of which
concrete provider subclass is used.

Pure logic, no live Frappe site required: `frappe.db.get_value`,
`get_decrypted_password`, and `call_openai_compatible_chat` are all
monkeypatched — this module never touches the database or the network.
If the real `frappe` package isn't importable, minimal stubs for
`frappe`, `frappe.utils`, and `frappe.utils.password` are installed
first (built incrementally, so this coexists safely with
test_openai_compatible.py's own lighter `frappe` stub if both happen to
run in the same process); either way the tests monkeypatch whichever
objects end up bound, so they run identically inside a real bench/site
environment.
"""

import sys
import types
import unittest
from unittest import mock

if "frappe" not in sys.modules:
	sys.modules["frappe"] = types.ModuleType("frappe")
_frappe_stub = sys.modules["frappe"]
if not hasattr(_frappe_stub, "db"):
	_frappe_stub.db = types.SimpleNamespace(get_value=lambda *args, **kwargs: None)

if "frappe.utils" not in sys.modules:
	sys.modules["frappe.utils"] = types.ModuleType("frappe.utils")
_frappe_utils_stub = sys.modules["frappe.utils"]
_frappe_stub.utils = _frappe_utils_stub

if "frappe.utils.password" not in sys.modules:
	sys.modules["frappe.utils.password"] = types.ModuleType("frappe.utils.password")
_frappe_utils_password_stub = sys.modules["frappe.utils.password"]
if not hasattr(_frappe_utils_password_stub, "get_decrypted_password"):
	_frappe_utils_password_stub.get_decrypted_password = lambda *args, **kwargs: ""
_frappe_utils_stub.password = _frappe_utils_password_stub

from truth_of_bible.ai.core.request import AiMessage, AiRequest
from truth_of_bible.ai.providers import openai_compatible_provider as provider_module

_PLACEHOLDER_BASE_URL = "https://api.example-provider.test/v1"
_PLACEHOLDER_CREDENTIAL = "PLACEHOLDER-CREDENTIAL-MUST-NEVER-BE-LOGGED"


class _FakeProvider(provider_module.OpenAiCompatibleProvider):
	provider_key = "test-provider"
	default_base_url = _PLACEHOLDER_BASE_URL


def _make_request():
	return AiRequest(task="verse_explanation", messages=[AiMessage(role="user", content="hi")])


class GenerateStripsWhitespaceTests(unittest.TestCase):
	def _generate(self, *, base_url, api_key):
		provider = _FakeProvider()
		call_chat = mock.Mock(return_value="ok")

		with mock.patch.object(
			provider_module.frappe.db, "get_value", return_value=types.SimpleNamespace(base_url=base_url)
		), mock.patch.object(
			provider_module, "get_decrypted_password", return_value=api_key
		), mock.patch.object(
			provider_module, "call_openai_compatible_chat", call_chat
		):
			provider.generate(_make_request())

		return call_chat

	def test_padded_api_key_and_base_url_are_stripped_before_use(self):
		call_chat = self._generate(
			base_url=f" {_PLACEHOLDER_BASE_URL} \n", api_key=f" {_PLACEHOLDER_CREDENTIAL} \n"
		)
		_, kwargs = call_chat.call_args
		self.assertEqual(kwargs["api_key"], _PLACEHOLDER_CREDENTIAL)
		self.assertEqual(kwargs["base_url"], _PLACEHOLDER_BASE_URL)

	def test_clean_api_key_and_base_url_are_unchanged(self):
		call_chat = self._generate(base_url=_PLACEHOLDER_BASE_URL, api_key=_PLACEHOLDER_CREDENTIAL)
		_, kwargs = call_chat.call_args
		self.assertEqual(kwargs["api_key"], _PLACEHOLDER_CREDENTIAL)
		self.assertEqual(kwargs["base_url"], _PLACEHOLDER_BASE_URL)

	def test_missing_base_url_falls_back_to_default_and_is_stripped(self):
		call_chat = self._generate(base_url="", api_key=_PLACEHOLDER_CREDENTIAL)
		_, kwargs = call_chat.call_args
		self.assertEqual(kwargs["base_url"], _PLACEHOLDER_BASE_URL)


if __name__ == "__main__":
	unittest.main()
