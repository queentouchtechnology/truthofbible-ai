"""WooCommerce's webhook ping is recognised (pure function; no site needed).

    python -m unittest truth_of_bible.tests.test_shop_webhook_ping
"""

import sys
import types
import unittest

_frappe = sys.modules.setdefault("frappe", types.ModuleType("frappe"))
if not hasattr(_frappe, "whitelist"):
	_frappe.whitelist = lambda *a, **k: (lambda f: f)
for name in ("truth_of_bible.marketplace.engine", "truth_of_bible.notifications.engine"):
	stub = types.ModuleType(name)
	stub.sync_order_line_items = stub.handle_event = lambda *a, **k: None
	sys.modules.setdefault(name, stub)

from truth_of_bible.api.shop_webhook import is_ping  # noqa: E402


class PingTest(unittest.TestCase):
	def test_ping_is_recognised(self):
		self.assertTrue(is_ping(None, b"webhook_id=3"))
		self.assertTrue(is_ping("", b"webhook_id=12\n"))
		self.assertTrue(is_ping(None, b"", "3"))  # Frappe parsed the form already

	def test_everything_else_still_needs_a_signature(self):
		self.assertFalse(is_ping("abc=", b"webhook_id=3"))  # signed: verified as usual
		self.assertFalse(is_ping(None, b'{"id": 5, "status": "completed"}'))  # an unsigned order: rejected
		self.assertFalse(is_ping(None, b"webhook_id=3&status=completed"))
		self.assertFalse(is_ping(None, b""))
		self.assertFalse(is_ping(None, b"", "x"))


if __name__ == "__main__":
	unittest.main()
