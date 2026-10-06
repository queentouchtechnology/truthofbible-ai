name = frappe.form_dict.get("name")

# 🔥 Always fetch latest doc
doc = frappe.get_doc("Wallet Withdrawal Request", name)
# --- access guard (security fix 2026-10-06) ---
# "Administrator" = app builds that still use the shared admin key; they keep
# working until that key is rotated. Any other caller is checked by role.
_me = frappe.session.user
_roles = set(frappe.get_roles(_me))
_is_admin = _me == "Administrator" or bool(_roles & {"System Manager", "Accounts Manager"})
if not _is_admin and doc.owner != _me:
    frappe.throw("Not permitted")
# --- end guard ---

# Submit safely
doc.submit()

frappe.response["message"] = {
    "name": doc.name,
    "status": doc.status,
    "docstatus": doc.docstatus
}