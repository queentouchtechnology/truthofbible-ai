submissions = frappe.form_dict.get("submissions")
amount = frappe.form_dict.get("amount")
expiry = frappe.form_dict.get("expiry")

if not submissions:
    frappe.throw("No submissions selected")

submissions = submissions.split(",")

created = []

for sub_name in submissions:

    sub = frappe.get_doc(
        "LMS Quiz Submission",
        sub_name
    )

    coupon_code = (
        "QUIZ-"
        + (sub.member or "USER")[:5].upper()
        + "-"
        + str(frappe.utils.now_datetime().microsecond)[-4:]
    )

    # Create LMS Coupon
    coupon = frappe.get_doc({

        "doctype": "LMS Coupon",

        "code": coupon_code,

        "discount_type": "Fixed Amount",

        "fixed_amount_discount": float(amount),

        "usage_limit": 1,

        "expires_on": expiry,

        "applicable_items": [
            {
                "reference_doctype": "LMS Batch",
                "reference_name": "quiz-rewards"
            }
        ]

    })

    coupon.insert(ignore_permissions=True)

    # Create Customer Coupon
    customer_coupon = frappe.get_doc({

        "doctype": "Customer Coupon",

        "customer": sub.member.split("@")[0],

        "lms_coupon": coupon.name,

        "coupon_code": coupon.code,

        "reward_type": "Quiz",

        "reward_amount": float(amount),

        "status": "Available",

        "quiz": sub.quiz

    })

    customer_coupon.insert(ignore_permissions=True)

    created.append({
        "member": sub.member,
        "coupon": coupon.code
    })

frappe.response["message"] = {
    "status": "success",
    "created": created
}