issue_name = frappe.form_dict.get("issue_name")

if not issue_name:
    frappe.throw("Issue name is required")

# 🔹 Get Issue
issue = frappe.get_doc("Issue", issue_name)
# --- access guard (security fix 2026-10-06) ---
# "Administrator" = app builds that still use the shared admin key; they keep
# working until that key is rotated. Members only see their own tickets.
_me = frappe.session.user
_roles = set(frappe.get_roles(_me))
_is_admin = _me == "Administrator" or bool(_roles & {"System Manager", "Support Team", "Batch Evaluator", "Moderator", "Course Creator"})
if not _is_admin and _me not in (issue.owner, (issue.raised_by or "").lower()):
    frappe.throw("Not permitted")
# --- end guard ---

# 🔹 Issue Attachments
issue_files = frappe.get_all(
    "File",
    filters={
        "attached_to_doctype": "Issue",
        "attached_to_name": issue_name
    },
    fields=["name", "file_name", "file_url", "is_private"]
)

# 🔹 Communications
communications = frappe.get_all(
    "Communication",
    filters={
        "reference_doctype": "Issue",
        "reference_name": issue_name
    },
    fields=[
        "name",
        "content",
        "sender",
        "recipients",
        "sent_or_received",
        "creation"
    ],
    order_by="creation asc"
)

# 🔹 Attachments per Communication
full_replies = []

for comm in communications:
    comm_files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Communication",
            "attached_to_name": comm.name
        },
        fields=["file_name", "file_url"]
    )

    full_replies.append({
        "name": comm.name,
        "message": comm.content,
        "sender": comm.sender,
        "recipients": comm.recipients,
        "type": comm.sent_or_received,
        "time": comm.creation,
        "attachments": comm_files
    })

# 🔹 Response
frappe.response["message"] = {
    "issue": {
        "name": issue.name,
        "subject": issue.subject,
        "description": issue.description,
        "status": issue.status,
        "priority": issue.priority,
        "issue_type": issue.issue_type,
        "customer": issue.customer,
        "created_on": issue.creation,
        "attachments": issue_files
    },
    "replies": full_replies
}