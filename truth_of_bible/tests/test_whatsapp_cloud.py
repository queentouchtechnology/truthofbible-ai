"""WhatsApp numbers are normalised to E.164 and template payloads built right
(pure functions; no site needed).

    python -m unittest truth_of_bible.tests.test_whatsapp_cloud
"""

import sys
import types
import unittest

sys.modules.setdefault("frappe", types.ModuleType("frappe"))

from truth_of_bible.communication.whatsapp_cloud import template_components, to_e164  # noqa: E402


class E164Test(unittest.TestCase):
	def test_numbers_with_a_country_code_are_kept(self):
		self.assertEqual(to_e164("+91 98765-43210"), "+919876543210")
		self.assertEqual(to_e164("+44 7700 900123"), "+447700900123")
		self.assertEqual(to_e164("0044 7700 900123"), "+447700900123")
		self.assertEqual(to_e164("919876543210"), "+919876543210")

	def test_bare_national_numbers_get_the_default_country(self):
		self.assertEqual(to_e164("9876543210"), "+919876543210")  # what older app builds sent
		self.assertEqual(to_e164("09876543210"), "+919876543210")
		self.assertEqual(to_e164("9876543210", "1"), "+19876543210")

	def test_not_a_phone_number(self):
		self.assertIsNone(to_e164(""))
		self.assertIsNone(to_e164("12345"))
		self.assertIsNone(to_e164("+1234567890123456"))


class ComponentsTest(unittest.TestCase):
	def test_utility_template_has_body_only(self):
		self.assertEqual(
			template_components(["1234"], copy_code=False),
			[{"type": "body", "parameters": [{"type": "text", "text": "1234"}]}],
		)

	def test_authentication_template_also_fills_the_copy_code_button(self):
		button = template_components(["1234"], copy_code=True)[1]
		self.assertEqual(button["sub_type"], "url")
		self.assertEqual(button["parameters"], [{"type": "text", "text": "1234"}])


if __name__ == "__main__":
	unittest.main()
