# No import needed

user = frappe.form_dict.get("user")
fcm_token = frappe.form_dict.get("fcm_token")
device = frappe.form_dict.get("device")

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