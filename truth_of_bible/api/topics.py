"""Topic search — reads TOB Bible Topic Translation directly, no AI call
involved. This is curated/admin-entered data, not generated."""

import frappe


@frappe.whitelist()
def search(query: str, language: str) -> list[dict]:
	return frappe.get_all(
		"TOB Bible Topic Translation",
		filters={
			"language": language,
			"name_local": ["like", f"%{query}%"],
			"translation_status": "Published",
		},
		fields=["topic", "name_local", "description_local"],
		order_by="name_local asc",
		limit_page_length=50,
	)
