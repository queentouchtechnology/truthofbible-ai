from . import __version__ as app_version

app_name = "truth_of_bible"
app_title = "Truth Of Bible"
app_publisher = "Queen Touch Technology"
app_description = (
	"Independent multilingual Bible intelligence AI backend for "
	"learn.truthofbible.org. Owns its own AI gateway (provider/model "
	"config, routing, retry/fallback — ported from qtt_platform's proven "
	"design, not imported from it), Bible explanation/Q&A generation, and "
	"LMS AI quiz generation. Deliberately has ZERO dependency on "
	"qtt_platform: this site is not a QTT SaaS product, so no QTT Tenant/"
	"Product Access/AI Provider/AI Model concept is used here. Real Bible "
	"verse text and cross-references already exist on-device in the "
	"truthofbible-app Flutter client (offline SQLite modules) — this app "
	"never stores or serves scripture text itself, only AI-generated "
	"content keyed to a plain reference string the client already knows."
)
app_email = "queentouchtech@gmail.com"
app_license = "Proprietary"

# `lms` is a real, publicly gettable app, so it belongs directly here —
# unlike qtt_platform's own bridge apps, which self-check `lms`/qtt_platform
# via a before_install hook because a private app with no public git
# remote can't be resolved through required_apps. This app has no such
# private dependency at all: it depends on nothing beyond frappe + lms.
required_apps = ["lms"]

# The Language Custom Fields (native_name, direction, script, is_default)
# added to Frappe's own core `Language` doctype — applied by `bench
# migrate` directly from fixtures/custom_field.json, no Python needed for
# this part. See truth_of_bible/language.py for the is_default
# single-default enforcement, registered below via doc_events.
fixtures = ["Custom Field"]

doc_events = {
	"Language": {
		"validate": "truth_of_bible.language.enforce_single_default",
	},
	# Quiz / support-ticket User-audience notification triggers — see
	# notifications/triggers.py's own docstring for the field-name
	# provenance and why each trigger never lets a failure reach the real
	# LMS/ticket save that fired it.
	"LMS Quiz": {
		"after_insert": "truth_of_bible.notifications.triggers.on_quiz_created",
	},
	"LMS Quiz Submission": {
		"after_insert": "truth_of_bible.notifications.triggers.on_quiz_submission_created",
	},
	"Communication": {
		"after_insert": "truth_of_bible.notifications.triggers.on_communication_created",
	},
	# Admin-audience events (engine.py fans these out to admin_users()).
	"Issue": {
		"after_insert": "truth_of_bible.notifications.triggers.on_issue_created",
		"on_update": "truth_of_bible.notifications.triggers.on_issue_updated",
	},
	"User": {
		"after_insert": "truth_of_bible.notifications.triggers.on_user_created",
	},
	"LMS Enrollment": {
		"after_insert": "truth_of_bible.notifications.triggers.on_enrollment_created",
	},
	# Course/batch lifecycle (NOTIFICATION_ENGINE_PLAN.md "What's still
	# open" item 5) — see triggers.py's own docstring for the field-name
	# provenance.
	"LMS Batch Enrollment": {
		"after_insert": "truth_of_bible.notifications.triggers.on_batch_enrollment_created",
	},
	"Course Lesson": {
		"after_insert": "truth_of_bible.notifications.triggers.on_lesson_created",
	},
	"LMS Batch": {
		"on_update": "truth_of_bible.notifications.triggers.on_batch_updated",
	},
}

# Idempotent — safe to run on every migrate, matching qmp_lms_bridge's own
# documented reasoning for why this is a plain function call and not a
# Frappe patch (patches.txt).
after_install = [
	"truth_of_bible.install.seed_default_prompts",
	"truth_of_bible.install.seed_ai_model_routing",
	"truth_of_bible.install.seed_bible_battle_questions",
	"truth_of_bible.install.seed_blessing_verses",
	"truth_of_bible.install.seed_notification_templates",
	"truth_of_bible.install.ensure_social_worker_role",
	"truth_of_bible.install.seed_social_content",
]
after_migrate = [
	"truth_of_bible.install.seed_default_prompts",
	"truth_of_bible.install.seed_ai_model_routing",
	"truth_of_bible.install.seed_bible_battle_questions",
	"truth_of_bible.install.seed_blessing_verses",
	"truth_of_bible.install.seed_notification_templates",
	"truth_of_bible.install.ensure_social_worker_role",
	"truth_of_bible.install.seed_social_content",
]

# Bible Battle's only background-job-shaped mechanism: a cron backstop for
# question advancement/forfeit, used only when nobody has polled an
# In Progress battle recently enough for check_and_advance() to run
# opportunistically (both apps died mid-question). Mirrors qtt_platform's
# own scheduler_events convention — the only cron precedent in this
# codebase; frappe.enqueue has none, so V1 deliberately doesn't introduce it.
#
# "hourly" runs the spiritual/reading notification scan (see
# notifications/reading.py) — checked every hour rather than via a finer
# cron because a per-user reminder "hour" (not minute) is all the product
# ever promises (see NOTIFICATION_ENGINE_PLAN.md Phase 35).
scheduler_events = {
	"cron": {
		"* * * * *": ["truth_of_bible.games.bible_battle.engine.sweep_stale_battles"],
		# Communication Center campaign queue (Decision 10): every 2 minutes
		# is small/frequent enough that a "Send Now" campaign starts moving
		# almost immediately, while staying a bounded, batch-per-tick job
		# rather than the HTTP request that creates a campaign ever blocking
		# on its own size — see communication/campaign.py's own docstring.
		"*/2 * * * *": ["truth_of_bible.communication.campaign.process_queue"],
	},
	"hourly": [
		"truth_of_bible.notifications.reading.daily_scan",
		"truth_of_bible.notifications.prayer.daily_scan",
		"truth_of_bible.notifications.bible_study.daily_scan",
	],
	# Meta token health: verify, renew where Meta allows it, warn ahead of
	# expiry (see social/meta_connection.py).
	"daily": [
		"truth_of_bible.social.meta_connection.check_connection",
		# NOTIFICATION_ENGINE_PLAN.md "What's still open" items 3/4 — a
		# slow-moving trend signal each, daily is enough for both (see each
		# module's own docstring for why).
		"truth_of_bible.notifications.stock.daily_check",
		"truth_of_bible.notifications.selfcheck.daily_check",
	],
}
