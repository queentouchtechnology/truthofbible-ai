"""Regression tests for call_openai_compatible_chat's HTTP error
normalization (see the fix/ai-provider-error-diagnostics-417 branch).

Pure logic, no live Frappe site required: `requests.post` is replaced
with a fake response, and `frappe.log_error` is monkeypatched — this
module never touches the database, the network, or frappe.session. If
the real `frappe` package isn't importable in the environment running
these tests (e.g. `python -m unittest` outside `bench`), a minimal stub
is installed first so `import frappe` inside the module under test still
succeeds; either way the tests monkeypatch whichever `frappe` object
ends up bound to the module, so they run identically inside a real
bench/site environment (`bench run-tests`) or standalone.
"""

import sys
import types
import unittest
from unittest import mock

if "frappe" not in sys.modules:
	_frappe_stub = types.ModuleType("frappe")
	_frappe_stub.generate_hash = lambda length=10: "0" * length
	_frappe_stub.log_error = lambda *args, **kwargs: None
	sys.modules["frappe"] = _frappe_stub

from truth_of_bible.ai.core.exceptions import AiProviderException
from truth_of_bible.ai.core.request import AiMessage, AiRequest
from truth_of_bible.ai.providers import openai_compatible

_FAKE_API_KEY = "sk-should-never-appear-in-any-message-or-log"


class _FakeHttpResponse:
	def __init__(self, status_code, text="", json_data=None):
		self.status_code = status_code
		self.text = text
		self._json_data = json_data or {}

	def json(self):
		return self._json_data


def _make_request(model="gpt-5-mini"):
	return AiRequest(
		task="verse_explanation",
		messages=[AiMessage(role="user", content="hi")],
		model=model,
	)


class CallOpenAiCompatibleChatErrorTests(unittest.TestCase):
	def setUp(self):
		patcher = mock.patch.object(openai_compatible.frappe, "log_error")
		self.mock_log_error = patcher.start()
		self.addCleanup(patcher.stop)

	def _call(self, fake_response, base_url="https://api.openai.com/v1"):
		with mock.patch.object(openai_compatible.requests, "post", return_value=fake_response):
			with self.assertRaises(AiProviderException) as ctx:
				openai_compatible.call_openai_compatible_chat(
					base_url=base_url,
					api_key=_FAKE_API_KEY,
					provider_name="openai",
					request=_make_request(),
				)
		return ctx.exception

	def test_verse_explanation_payload_has_no_temperature_max_tokens_or_response_format(self):
		"""verse_explanation never sets temperature/max_output_tokens/
		structured_output (see truth_of_bible/api/bible.py), so none of
		those optional keys should end up in the outgoing payload — rules
		out 'unsupported parameter' as the cause of a verse_explanation
		failure specifically."""
		captured = {}

		def fake_post(url, headers, json, timeout):
			captured["payload"] = json
			return _FakeHttpResponse(200, json_data={
				"id": "resp-1",
				"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
				"usage": {},
			})

		with mock.patch.object(openai_compatible.requests, "post", side_effect=fake_post):
			openai_compatible.call_openai_compatible_chat(
				base_url="https://api.openai.com/v1",
				api_key=_FAKE_API_KEY,
				provider_name="openai",
				request=_make_request(),
			)

		self.assertNotIn("temperature", captured["payload"])
		self.assertNotIn("max_tokens", captured["payload"])
		self.assertNotIn("response_format", captured["payload"])
		self.assertEqual(captured["payload"]["model"], "gpt-5-mini")

	def test_400_is_not_transient_and_message_carries_diagnostics(self):
		body = '{"error": {"message": "some provider-side validation failure"}}'
		exc = self._call(_FakeHttpResponse(400, text=body))

		self.assertEqual(exc.kind, "ProviderRequestError")
		self.assertFalse(exc.is_transient)
		self.assertTrue(exc.is_fallback_eligible)
		message = str(exc)
		self.assertIn("provider=openai", message)
		self.assertIn("model=gpt-5-mini", message)
		self.assertIn("status=400", message)
		self.assertIn("https://api.openai.com/v1/chat/completions", message)
		# v1/chat/completions must appear exactly once — no doubled path
		# segment even when base_url already ends without/with a slash.
		self.assertEqual(message.count("/chat/completions"), 1)
		self.assertIn(body, message)
		self.assertNotIn(_FAKE_API_KEY, message)

	def test_429_is_transient_and_carries_diagnostics(self):
		exc = self._call(_FakeHttpResponse(429, text="rate limit exceeded for this project"))
		self.assertEqual(exc.kind, "RateLimited")
		self.assertTrue(exc.is_transient)
		self.assertIn("status=429", str(exc))
		self.assertIn("rate limit exceeded", str(exc))

	def test_500_is_transient_and_carries_diagnostics(self):
		exc = self._call(_FakeHttpResponse(503, text="upstream temporarily unavailable"))
		self.assertEqual(exc.kind, "ProviderServerError")
		self.assertTrue(exc.is_transient)
		self.assertIn("status=503", str(exc))

	def test_base_url_trailing_slash_does_not_duplicate_path(self):
		exc = self._call(_FakeHttpResponse(400, text="bad request"), base_url="https://api.openai.com/v1/")
		self.assertIn("endpoint=https://api.openai.com/v1/chat/completions", str(exc))
		self.assertNotIn("//chat/completions", str(exc))

	def test_error_is_logged_server_side_without_the_api_key(self):
		self._call(_FakeHttpResponse(400, text="bad request"))
		self.assertTrue(self.mock_log_error.called)
		_, kwargs = self.mock_log_error.call_args
		logged_text = " ".join(str(v) for v in kwargs.values())
		self.assertNotIn(_FAKE_API_KEY, logged_text)
		self.assertIn("openai", logged_text)
		self.assertIn("400", logged_text)


if __name__ == "__main__":
	unittest.main()
