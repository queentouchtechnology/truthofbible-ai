"""Extends Frappe's own core `Language` doctype (language_code, language_name,
enabled, and a self-referential `based_on` already usable as a fallback-
language link) rather than building a parallel `TOB Language`/`Bible
Language` doctype — every other doctype's existing Link->Language fields,
and Frappe's own translation system, keep working unmodified. See
fixtures/custom_field.json for the added fields: native_name, direction,
script, is_default.
"""

import frappe
from frappe import _


def enforce_single_default(doc, method=None):
	"""At most one Language row may have is_default checked — mirrors the
	same single-default-enforced-in-validate() pattern documented on
	QTT AI Provider's is_fallback field in qtt_platform."""
	if not doc.get("is_default"):
		return

	existing = frappe.db.get_value(
		"Language", {"is_default": 1, "name": ["!=", doc.name]}, "name"
	)
	if existing:
		frappe.throw(
			_("{0} is already the default language. Unset it before making {1} the default.").format(
				existing, doc.name
			)
		)
