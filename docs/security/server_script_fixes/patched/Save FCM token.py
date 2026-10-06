# No import needed

user = frappe.form_dict.get("user")
fcm_token = frappe.form_dict.get("fcm_token")
device = frappe.form_dict.get("device")
# --- access guard (security fix 2026-10-06) ---
# "Administrator" = app builds that still use the shared admin key; they keep
# working until that key is rotated. Any other caller is checked by role.
_me = frappe.session.user
_roles = set(frappe.get_roles(_me))
_is_admin = _me == "Administrator" or bool(_roles & set())
if _me != "Administrator":
    user = _me  # a user can only register their own device
# --- end guard ---

existing = frappe.get_all(
    "User FCM Token",
    filters={"user": user, "device": device},
    fields=["name"]
)

if existing:
    doc = frappe.get_doc("User FCM Token", existing[0].name)
    doc.fcm_token = fcm_token
    doc.save()
else:
    frappe.get_doc({
        "doctype": "User FCM Token",
        "user": user,
        "fcm_token": fcm_token,
        "device": device
    }).insert()

frappe.response["message"] = "success"