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
}

# Idempotent — safe to run on every migrate, matching qmp_lms_bridge's own
# documented reasoning for why this is a plain function call and not a
# Frappe patch (patches.txt).
after_install = "truth_of_bible.install.seed_default_prompts"
after_migrate = "truth_of_bible.install.seed_default_prompts"
