name = frappe.form_dict.get("name")

doc = frappe.get_doc("Wallet Withdrawal Request", name)

if doc.status != "Pending":
    frappe.throw("Only Pending requests can be approved")

je = frappe.new_doc("Journal Entry")
je.company = "Truth of Bible"
je.posting_date = frappe.utils.today()
je.voucher_type = "Journal Entry"

# Hold ↓
je.append("accounts", {
    "account": "User Wallet Hold - TOB",
    "party_type": "Customer",
    "party": doc.customer,
    "debit_in_account_currency": doc.amount,
   
})

# Bank ↑
je.append("accounts", {
    "account": "Bank - TOB - TOB",
    "credit_in_account_currency": doc.amount
})

je.insert(ignore_permissions=True)
je.submit()

doc.db_set("status", "Approved")

frappe.response["message"] = "Approved successfully"