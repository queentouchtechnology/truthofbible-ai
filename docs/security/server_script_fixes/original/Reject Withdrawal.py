name = frappe.form_dict.get("name")

doc = frappe.get_doc("Wallet Withdrawal Request", name)

if doc.status != "Pending":
    frappe.throw("Only Pending requests can be rejected")

# 🔁 Reverse HOLD → Wallet
je = frappe.new_doc("Journal Entry")
je.company = "Truth of Bible"
je.posting_date = frappe.utils.today()
je.voucher_type = "Journal Entry"

# Hold ↓ (NO advance here)
je.append("accounts", {
    "account": "User Wallet Hold - TOB",
    "party_type": "Customer",
    "party": doc.customer,
    "debit_in_account_currency": doc.amount
})

# Wallet ↑ (ONLY here advance allowed)
je.append("accounts", {
    "account": "User Wallet - TOB",
    "party_type": "Customer",
    "party": doc.customer,
    "credit_in_account_currency": doc.amount,
    "is_advance": "Yes"
})

je.insert(ignore_permissions=True)
je.submit()

# Update status
doc.db_set("status", "Rejected")

frappe.response["message"] = "Rejected successfully"