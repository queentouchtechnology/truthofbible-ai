customer = frappe.form_dict.get("customer")
account = frappe.form_dict.get("account") or "User Wallet - TOB"
check_amount = frappe.form_dict.get("amount")  # optional

if not customer:
    frappe.throw("Customer is required")
# --- access guard (security fix 2026-10-06) ---
# "Administrator" = app builds that still use the shared admin key; they keep
# working until that key is rotated. Any other caller is checked by role.
_me = frappe.session.user
_roles = set(frappe.get_roles(_me))
_is_admin = _me == "Administrator" or bool(_roles & {"System Manager", "Accounts Manager"})
if not _is_admin and customer != _me.split("@")[0] and frappe.db.get_value("Customer", customer, "email_id") != _me:
    frappe.throw("Not permitted")
# --- end guard ---

# 🔹 1. Get totals (FAST SQL)
result = frappe.db.sql("""
    SELECT 
        SUM(debit) as total_debit,
        SUM(credit) as total_credit
    FROM `tabGL Entry`
    WHERE 
        account = %s
        AND party_type = 'Customer'
        AND party = %s
""", (account, customer), as_dict=True)

row = result[0] if result else {}

total_debit = float(row.get("total_debit") or 0)
total_credit = float(row.get("total_credit") or 0)

# ✅ Correct for Liability Wallet
balance = total_credit - total_debit

# 🔒 2. Prevent Negative Wallet (if amount passed)
can_spend = True

if check_amount:
    try:
        amt = float(check_amount)
        if balance < amt:
            can_spend = False
    except:
        frappe.throw("Invalid amount")

# 🔹 3. Get Top 20 Transactions
transactions = frappe.get_all(
    "GL Entry",
    filters={
        "account": account,
        "party_type": "Customer",
        "party": customer
    },
    fields=[
        "posting_date",
        "debit",
        "credit",
        "voucher_type",
        "voucher_no",
        "remarks"
    ],
    order_by="posting_date desc",
    limit_page_length=20
)

# 🔹 4. Add transaction type (corrected logic)
for t in transactions:
    if t["credit"] > 0:
        t["type"] = "credit"   # money added to wallet
        t["amount"] = t["credit"]
    else:
        t["type"] = "debit"    # money deducted from wallet
        t["amount"] = t["debit"]

# 📤 Final Response
frappe.response["message"] = {
    "customer": customer,
    "wallet_account": account,
    "total_debit": total_debit,
    "total_credit": total_credit,
    "balance": balance,
    "can_spend": can_spend,
    "transactions": transactions
}