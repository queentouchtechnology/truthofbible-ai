# API: Get Quiz Submission Compare View
# Final Updated Version

submission_id = frappe.form_dict.get("submission_id")

if not submission_id:
    frappe.throw("submission_id is required")

# Get submission document
submission = frappe.get_doc("LMS Quiz Submission", submission_id)

if not submission.quiz:
    frappe.throw("Quiz not found for this submission")

quiz = submission.quiz

# Fetch all quiz questions
quiz_questions = frappe.get_all(
    "LMS Quiz Question",
    filters={"parent": quiz},
    fields=["name", "question"]
)

# Build submitted answers map
# Actual child table = result
# Fields:
# question   -> LMS Quiz Question row ID
# answer     -> selected option (if saved during submit)
# is_correct -> correctness status

submitted_answers = {}
submitted_correct_status = {}

for row in submission.get("result") or []:
    submitted_answers[row.question] = row.answer
    submitted_correct_status[row.question] = row.is_correct

output = []

for qq in quiz_questions:

    if not qq.question:
        continue

    qdoc = frappe.get_doc("LMS Question", qq.question)

    qdata = {
        "question_id": qq.name,
        "question_master_id": qq.question,
        "question": qdoc.get("question"),
        "type": qdoc.get("type"),
        "options": [],
        "correct_option": None,

        # selected option from saved answer
        # NOTE:
        # if answer is null in DB, selected_option will also be null
        "selected_option": submitted_answers.get(qq.name),

        "status": "Not Answered"
    }

    if qdoc.get("type") == "Choices":

        # Load options and detect correct answer
        for i in range(1, 5):
            opt = qdoc.get("option_" + str(i))
            is_correct = int(qdoc.get("is_correct_" + str(i)) or 0)

            if opt:
                qdata["options"].append({
                    "no": i,
                    "text": opt
                })

            if is_correct == 1:
                qdata["correct_option"] = i

        # Status logic

        # If selected answer is saved
        if qdata["selected_option"] is not None:

            try:
                if int(qdata["selected_option"]) == int(qdata["correct_option"]):
                    qdata["status"] = "Correct"
                else:
                    qdata["status"] = "Wrong"
            except:
                qdata["status"] = "Wrong"

        # If selected answer is NOT saved
        # fallback using LMS correctness flag
        else:
            result_status = submitted_correct_status.get(qq.name)

            if result_status == 1:
                qdata["status"] = "Correct"
            elif result_status == 0:
                qdata["status"] = "Wrong"
            else:
                qdata["status"] = "Not Answered"

    output.append(qdata)

frappe.response["message"] = {
    "submission_id": submission_id,
    "quiz": quiz,
    "results": output
}