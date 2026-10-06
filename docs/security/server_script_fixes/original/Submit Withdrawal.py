name = frappe.form_dict.get("name")

# 🔥 Always fetch latest doc
doc = frappe.get_doc("Wallet Withdrawal Request", name)

# Submit safely
doc.submit()

frappe.response["message"] = {
    "name": doc.name,
    "status": doc.status,
    "docstatus": doc.docstatus
}