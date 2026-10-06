# 🔐 Get inputs
student = frappe.form_dict.get("student")
quiz = frappe.form_dict.get("quiz")

# ✅ Validate student
if not student:
    frappe.throw("Student is required")

student = student.strip().lower()

if not frappe.db.exists("User", student):
    frappe.throw("Invalid student")

# ✅ Role check (SAFE)
roles = frappe.get_all(
    "Has Role",
    filters={"parent": student},
    fields=["role"]
)

role_list = [r.role for r in roles]

if "LMS Student" not in role_list:
    frappe.throw("User not allowed")

# 📘 Get quiz
quiz_doc = frappe.get_doc("LMS Quiz", quiz)

# 📊 Get submissions
submissions = frappe.get_all(
    "LMS Quiz Submission",
    filters={
        "quiz": quiz,
        "member": student
    },
    fields=["name", "score", "percentage", "creation"],
    order_by="creation desc"
)

# 🔢 Attempts calculation
attempts_used = len(submissions)
max_attempts = quiz_doc.max_attempts or 0
attempts_left = max(max_attempts - attempts_used, 0)

# ✅ Response
frappe.response["message"] = {
    "quiz": quiz_doc.name,
    "title": quiz_doc.title,
    "max_attempts": max_attempts,
    "attempts_used": attempts_used,
    "attempts_left": attempts_left,
    "can_attempt": attempts_left > 0,
    "attempts": submissions
}