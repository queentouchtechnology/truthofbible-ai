quiz = frappe.form_dict.get("quiz")
member_filter = frappe.form_dict.get("member")
top_rank = frappe.form_dict.get("top_rank")
min_percentage = frappe.form_dict.get("min_percentage")
max_percentage = frappe.form_dict.get("max_percentage")
min_score = frappe.form_dict.get("min_score")
max_score = frappe.form_dict.get("max_score")
passed_only = frappe.form_dict.get("passed_only")
latest_attempt_only = frappe.form_dict.get("latest_attempt_only")
from_date = frappe.form_dict.get("from_date")
to_date = frappe.form_dict.get("to_date")

if not quiz:
    frappe.throw("Quiz parameter is required")

quiz_doc = frappe.get_doc("LMS Quiz", quiz)

all_submissions = frappe.get_all(
    "LMS Quiz Submission",
    filters={"quiz": quiz},
    fields=[
        "name",
        "member",
        "member_name",
        "percentage",
        "score",
        "score_out_of",
        "creation"
    ],
    order_by="creation desc"
)

# Latest Attempt Only
if latest_attempt_only != "0":

    latest_submissions = {}

    for sub in all_submissions:

        member = sub.get("member")

        if member not in latest_submissions:
            latest_submissions[member] = sub

    submissions = list(latest_submissions.values())

else:

    submissions = all_submissions

filtered_submissions = []

for sub in submissions:

    percentage = sub.get("percentage") or 0
    score = sub.get("score") or 0
    creation = str(sub.get("creation") or "")

    # Member Filter
    if member_filter:

        search_text = member_filter.lower()

        member_email = (sub.get("member") or "").lower()
        member_name = (sub.get("member_name") or "").lower()

        if (
            search_text not in member_email
            and search_text not in member_name
        ):
            continue

    # Date Filters
    if from_date:
        if creation[:10] < from_date:
            continue

    if to_date:
        if creation[:10] > to_date:
            continue

    # Percentage Filters
    if min_percentage:
        if percentage < float(min_percentage):
            continue

    if max_percentage:
        if percentage > float(max_percentage):
            continue

    # Score Filters
    if min_score:
        if score < float(min_score):
            continue

    if max_score:
        if score > float(max_score):
            continue

    # Passed Only
    if passed_only == "1":
        if percentage < (quiz_doc.passing_percentage or 0):
            continue

    filtered_submissions.append(sub)

submissions = filtered_submissions

# Rank Wise Sort
submissions.sort(
    key=lambda x: (
        -(x.get("percentage") or 0),
        -(x.get("score") or 0)
    )
)

# Top Rank Filter
if top_rank:
    submissions = submissions[:int(top_rank)]

columns = [
    {
        "label": "Question",
        "fieldname": "question",
        "width": 350
    },
    {
        "label": "Option 1",
        "fieldname": "option_1",
        "width": 180
    },
    {
        "label": "Option 2",
        "fieldname": "option_2",
        "width": 180
    },
    {
        "label": "Option 3",
        "fieldname": "option_3",
        "width": 180
    },
    {
        "label": "Option 4",
        "fieldname": "option_4",
        "width": 180
    },
    {
        "label": "Correct Answer",
        "fieldname": "correct_answer",
        "width": 180
    }
]

for idx, sub in enumerate(submissions, start=1):

    fieldname = (
        sub["name"]
        .replace("-", "_")
        .replace(" ", "_")
    )

    percentage = str(sub.get("percentage") or 0)
    score = str(sub.get("score") or 0)

    columns.append({
        "label":
            str(idx)
            + ". "
            + (sub.get("member_name") or "Unknown")
            + " ["
            + score
            + "] "
            + "("
            + percentage
            + "%)",
        "fieldname": fieldname,
        "width": 100
    })

answers = {}

for sub in submissions:

    doc = frappe.get_doc(
        "LMS Quiz Submission",
        sub["name"]
    )

    answers[sub["name"]] = {}

    for r in doc.result:

        answers[sub["name"]][r.question] = {
            "answer": r.answer,
            "correct": r.is_correct
        }

data = []


for q in quiz_doc.questions:

    option_1 = ""
    option_2 = ""
    option_3 = ""
    option_4 = ""
    correct_answer = ""

    try:

        qdoc = frappe.get_doc(
            "LMS Question",
            q.question
        )

        option_1 = qdoc.get("option_1") or ""
        option_2 = qdoc.get("option_2") or ""
        option_3 = qdoc.get("option_3") or ""
        option_4 = qdoc.get("option_4") or ""

        if qdoc.get("is_correct_1"):
            correct_answer = option_1

        elif qdoc.get("is_correct_2"):
            correct_answer = option_2

        elif qdoc.get("is_correct_3"):
            correct_answer = option_3

        elif qdoc.get("is_correct_4"):
            correct_answer = option_4

    except:
        pass

    row = {
        "question": q.question_detail or "",
        "option_1": option_1,
        "option_2": option_2,
        "option_3": option_3,
        "option_4": option_4,
        "correct_answer": correct_answer
    }

    for sub in submissions:

        fieldname = (
            sub["name"]
            .replace("-", "_")
            .replace(" ", "_")
        )

        ans = answers.get(
            sub["name"],
            {}
        ).get(q.name)

        if ans:

            mark = "✗"

            if ans.get("correct"):
                mark = "✓"

            answer = ans.get("answer")

            if answer:
                row[fieldname] = str(answer) + " " + mark
            else:
                row[fieldname] = mark

        else:

            row[fieldname] = ""

    data.append(row)

frappe.response["message"] = {
    "success": True,
    "quiz": quiz,
    "filters": {
        "member": member_filter,
        "top_rank": top_rank,
        "min_percentage": min_percentage,
        "max_percentage": max_percentage,
        "min_score": min_score,
        "max_score": max_score,
        "passed_only": passed_only,
        "latest_attempt_only": latest_attempt_only,
        "from_date": from_date,
        "to_date": to_date
    },
    "columns": columns,
    "data": data,
    "total_students": len(submissions),
    "total_questions": len(quiz_doc.questions)
}