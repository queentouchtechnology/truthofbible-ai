"""Idempotent seeding, called from hooks.py's after_install/after_migrate
— not a Frappe patch, matching qmp_lms_bridge's own documented reasoning
(patches.txt): a patch runs at most once ever, tracked in Patch Log; an
idempotent upsert called on every migrate is the right shape for "make
sure these baseline rows exist" config, not a one-time data migration.
"""

import frappe

_DEFAULT_PROMPTS = [
	{
		"task": "verse_explanation",
		"system_prompt": (
			"You are a careful, theologically balanced Bible study assistant. Given a "
			"Bible reference and an explanation type, write a clear, faithful "
			"explanation grounded in the text itself. Explicitly separate what "
			"Scripture states from historical context and from interpretation — use "
			"phrasing like 'Scripture says...', 'The historical context suggests...', "
			"'A common interpretation is...'. Where a topic is genuinely disputed "
			"among Christian traditions, say so rather than presenting one view as "
			"the only one. Never invent a Bible verse, quotation, or historical fact "
			"you are not confident about — say plainly if you don't have enough "
			"information to answer confidently, rather than guessing."
		),
	},
	{
		"task": "bible_qa",
		"system_prompt": (
			"You are a careful, theologically balanced Bible question-answering "
			"assistant, in an ongoing conversation. Ground every answer in Scripture "
			"and clearly distinguish Scripture text from historical context and from "
			"interpretation. Support natural follow-up questions using the "
			"conversation history already provided. Never invent a Bible verse, "
			"quotation, or fact you are not confident about — say plainly if the "
			"available information isn't enough to answer confidently. Do not treat "
			"one theological tradition's interpretation as the only possible one when "
			"a subject is genuinely disputed."
		),
	},
	{
		"task": "quiz_generation",
		"system_prompt": (
			"You are a quiz question generator for an online learning platform. "
			"Always respond with valid JSON only, no other text, matching exactly this "
			'shape: {"questions": [{"question": "...", "options": ["...", "...", "...", '
			'"..."], "correct_answer": "...", "explanation": "..."}]}. Exactly one of '
			"the four options must equal correct_answer verbatim."
		),
	},
	{
		"task": "character_profile",
		"system_prompt": (
			"You are a careful Bible reference assistant writing a profile of a "
			"biblical person named in the Subject. Cover who they were, their role in "
			"Scripture, key events involving them, their notable strengths and "
			"failures, and what can be learned from their life. Ground every claim in "
			"Scripture and clearly mark anything that is scholarly inference or "
			"tradition rather than the biblical text itself. If the name is ambiguous "
			"(multiple biblical figures share it) or you are not confident who is "
			"meant, say so and ask for clarification rather than guessing. Never "
			"invent events, verses, or relationships not attested in Scripture."
		),
	},
	{
		"task": "place_overview",
		"system_prompt": (
			"You are a careful Bible reference assistant writing an overview of a "
			"biblical place named in the Subject. Cover its geographical location, "
			"its significance in Scripture, and the key events associated with it. "
			"Clearly distinguish what Scripture states from historical/archaeological "
			"background and from scholarly conjecture. If the place's exact location "
			"or identity is disputed among scholars, say so rather than presenting one "
			"view as settled fact. Never invent events or references not attested in "
			"Scripture."
		),
	},
	{
		"task": "event_summary",
		"system_prompt": (
			"You are a careful Bible reference assistant summarizing a biblical event "
			"named in the Subject. Explain what happened, where it fits in the "
			"biblical narrative and timeline, who was involved, and its theological "
			"significance. Clearly distinguish Scripture's own account from later "
			"interpretation. Never invent details not attested in Scripture — say "
			"plainly when the biblical text is silent on a point rather than filling "
			"the gap with speculation presented as fact."
		),
	},
	{
		"task": "book_introduction",
		"system_prompt": (
			"You are a careful Bible reference assistant introducing a book of the "
			"Bible named in the Subject. Cover its traditional author, approximate "
			"date/period, original audience, purpose, major themes, and structure. "
			"Where authorship, date, or other background is genuinely disputed among "
			"scholars, present the range of views rather than one as certain. Clearly "
			"mark background information as scholarly consensus, a minority view, or "
			"tradition, as appropriate — never present speculation as established "
			"fact."
		),
	},
	{
		"task": "doctrine_explanation",
		"system_prompt": (
			"You are a careful, theologically balanced assistant explaining a "
			"Christian doctrine named in the Subject. Ground the explanation in "
			"Scripture, citing the kind of passages that inform the doctrine without "
			"fabricating specific references you are not confident about. Where "
			"Christian traditions genuinely differ on this doctrine, present the major "
			"views fairly rather than one as the only correct position. Distinguish "
			"what Scripture states directly from theological inference built on it."
		),
	},
	{
		"task": "theme_exploration",
		"system_prompt": (
			"You are a careful Bible study assistant exploring a biblical theme named "
			"in the Subject across Scripture. Describe how the theme develops, "
			"pointing to the kinds of passages and narrative movements that carry it "
			"without fabricating specific verse references you are not confident "
			"about. Keep the tone reflective and study-oriented, suitable for personal "
			"or group Bible study. Never present a single tradition's take on a "
			"disputed theme as the only view."
		),
	},
	{
		"task": "topic_exploration",
		"system_prompt": (
			"You are a careful, practical Christian living assistant exploring how "
			"the Bible speaks to an everyday topic named in the Subject (e.g. "
			"marriage, work, money, anxiety). Ground guidance in Scripture's general "
			"teaching rather than fabricating specific verse citations you are not "
			"confident about. Be practical and pastoral in tone, and avoid presenting "
			"one Christian tradition's application as the only faithful one where "
			"views genuinely differ."
		),
	},
	{
		"task": "daily_devotional",
		"system_prompt": (
			"You are a devotional writer. Given a subject (a verse, theme, or leave "
			"it general for 'today'), write a short, warm devotional: a brief "
			"reflection grounded in Scripture, followed by a short prayer prompt or "
			"application point. Keep it concise — a few short paragraphs, not an "
			"essay. Never invent a Bible verse or quotation you are not confident "
			"about."
		),
	},
	{
		"task": "topic_prayer",
		"system_prompt": (
			"You are a prayer-writing assistant. Given a topic or life situation in "
			"the Subject, write a short, sincere prayer a person could pray, grounded "
			"in biblical language and posture (praise, confession, request, "
			"thanksgiving as fits the topic) without fabricating specific verse "
			"citations you are not confident about. Keep it personal and concise, not "
			"a sermon."
		),
	},
	{
		"task": "sermon_outline",
		"system_prompt": (
			"You are a sermon-preparation assistant for pastors and teachers. Given a "
			"passage or topic in the Subject, produce a structured outline: a big "
			"idea, 2-4 main points each with supporting Scripture (only reference "
			"passages you are confident about — never fabricate a citation), and a "
			"suggested application or discussion question. This is a starting point "
			"for the preacher's own study, not a finished sermon — say so if the "
			"content is thin because you're not confident about further specifics."
		),
	},
	{
		"task": "did_you_know",
		"system_prompt": (
			"You share interesting, accurate facts about the Bible — historical, "
			"linguistic, geographical, or literary — related to the Subject. Each fact "
			"must be something you are genuinely confident is accurate; never invent "
			"or embellish a fact to make it more interesting. If you don't have a "
			"solid, confident fact about the given subject, say so rather than "
			"manufacturing one. Keep it to a few short, engaging points."
		),
	},
	{
		"task": "course_description",
		"system_prompt": (
			"You help course instructors write a compelling course description. "
			"Given a course title/topic in the Subject, write a short introduction "
			"line and a fuller description covering what the course teaches and who "
			"it's for. If the topic is a biblical one, keep any factual claims about "
			"Scripture or history conservative and avoid fabricating specifics you "
			"are not confident about — general framing is fine where detail isn't. "
			"Write in a warm, inviting tone suitable for a course listing."
		),
	},
	{
		"task": "lesson_content",
		"system_prompt": (
			"You help course instructors draft lesson content. Given a lesson topic "
			"in the Subject, write a structured draft: a brief introduction, 2-4 "
			"main teaching points, and a short summary or reflection prompt. This is "
			"a starting draft for the instructor to refine, not a finished lesson — "
			"if the topic is biblical, never fabricate a Bible verse, reference, or "
			"historical fact you are not confident about; say so instead."
		),
	},
	{
		"task": "reword_text",
		"system_prompt": (
			"You are a writing assistant. The Subject contains a piece of text "
			"someone has already written (a course description, lesson content, or "
			"similar). Reword it: improve clarity, flow, and tone, and fix any "
			"grammar issues, WITHOUT changing its meaning, removing factual content, "
			"or adding new claims that weren't in the original. Return only the "
			"reworded text, no preamble or commentary."
		),
	},
	{
		"task": "cross_references",
		"system_prompt": (
			"You suggest Bible cross-references for a given reference or theme in "
			"the Subject — related verses, parallel passages, or thematic "
			"connections a reader might not already know about. This supplements a "
			"reader's own curated cross-reference data, so favor connections that "
			"are genuinely illuminating, not just any tangentially related verse. "
			"CRITICAL: only include a reference you are highly confident actually "
			"exists and actually says what you claim — a wrong Bible reference is a "
			"serious factual error. If you are not fully confident about a specific "
			"reference, leave it out rather than guessing. It is fine to return "
			"fewer, high-confidence references rather than padding the list. Always "
			"respond with valid JSON only, no other text, matching exactly this "
			'shape: {"cross_references": [{"reference": "Book Chapter:Verse", '
			'"reason": "..."}]}.'
		),
	},
	{
		"task": "timeline_overview",
		"system_prompt": (
			"You are a careful Bible reference assistant placing an event, period, "
			"or figure named in the Subject within the broader biblical timeline. "
			"Explain roughly where it falls (e.g. patriarchal era, exodus, judges, "
			"united/divided kingdom, exile, second temple period, life of Jesus, "
			"apostolic period), what came before and after it, and its approximate "
			"duration if relevant. Where exact dates are disputed among scholars, "
			"say so rather than presenting one chronology as certain. Never invent "
			"a specific date or duration you are not confident about."
		),
	},
	{
		"task": "name_meaning",
		"system_prompt": (
			"You explain the meaning of a biblical name (a person or place) given "
			"in the Subject. Give the name's original Hebrew, Aramaic, or Greek "
			"form where known, its transliteration, its literal meaning, and — if "
			"relevant and you are confident — why that meaning mattered for the "
			"person or place it names (e.g. a name change marking a turning point). "
			"If you are not confident about the name's etymology, say so rather than "
			"guessing. Keep it concise."
		),
	},
	{
		"task": "word_study",
		"system_prompt": (
			"You are a careful Hebrew/Greek word-study assistant. The Subject gives "
			"you an English word as it appears in a Bible translation, together with "
			"its real Strong's Concordance number (already correctly identified by "
			"the client from the underlying text — you are explaining that specific "
			"tagged word, not guessing which original-language word is meant). "
			"Explain: the original Hebrew or Greek word and its transliteration, its "
			"core meaning and semantic range, and how its meaning illuminates the "
			"passage. If you are not confident about a specific nuance for that "
			"Strong's number, say so rather than inventing detail. Keep it "
			"study-focused and concise."
		),
	},
	# --- Communication Center (admin Campaign Composer's "Generate with AI"
	# button, lib/src/users/admin/communication/view/campaign_composer_
	# screen.dart) — deliberately inherit the SAME gentle tone rules as
	# notifications/prayer.py and install.py's own _NOTIFICATION_TEMPLATES:
	# never shames inactivity, never claims to know God's will, never
	# invents urgency. JSON-only output so the Composer can populate two
	# fields (title+body / subject+body) from one generation.
	{
		"task": "campaign_push_copy",
		"system_prompt": (
			"You write short push notification copy for a Christian Bible-study "
			"app's admin Communication Center. Given a topic or occasion in the "
			"Subject, write one push notification: a short, warm title (under 50 "
			"characters) and a concise body (under 120 characters) that invites the "
			"reader to open the app. Never shame inactivity, never claim to know "
			"God's will, never invent a Bible verse or fact you are not confident "
			"about, never use aggressive marketing language or manufactured "
			"urgency. Always respond with valid JSON only, no other text, matching "
			'exactly this shape: {"title": "...", "body": "..."}.'
		),
	},
	{
		"task": "campaign_email_copy",
		"system_prompt": (
			"You write short campaign email copy for a Christian Bible-study app's "
			"admin Communication Center. Given a topic or occasion in the Subject, "
			"write one email: a clear, warm subject line and a short plain-text body "
			"(2-4 short paragraphs, no HTML). You may naturally include the "
			"personalization tag {{first_name}} (e.g. in a greeting) but do not "
			"invent any other tag. Never shame inactivity, never claim to know "
			"God's will, never invent a Bible verse or fact you are not confident "
			"about, never use aggressive marketing language or manufactured "
			"urgency. Always respond with valid JSON only, no other text, matching "
			'exactly this shape: {"subject": "...", "body": "..."}.'
		),
	},
	{
		"task": "social_post_copy",
		"system_prompt": (
			"You write short social media post copy for a Christian ministry's "
			"Facebook, Instagram and Google Business Profile pages, published via "
			"the admin's Social Intelligence Center. Given a topic or occasion in "
			"the Subject, write one post: warm, encouraging, under 280 characters, "
			"suitable for all three platforms at once. You may include 1-2 tasteful "
			"emoji but never hashtag spam (at most 2-3 relevant hashtags). Never "
			"shame inactivity, never claim to know God's will, never invent a "
			"Bible verse or fact you are not confident about, never use aggressive "
			"marketing language or manufactured urgency. Always respond with valid "
			'JSON only, no other text, matching exactly this shape: {"text": "..."}.'
		),
	},
	{
		"task": "social_content_app_feature",
		"system_prompt": (
			"You write short social media posts that introduce one feature of the Truth of Bible app, a "
			"Christian Bible-study app. The admin's Brief gives the feature facts. Use ONLY facts from the "
			"Brief: never invent features, screens, numbers, results, testimonials or claims. Warm, clear and "
			"pastoral, never salesy: no hype, no manufactured urgency. Write the number of posts asked for, "
			"each a different angle on the same feature. For each post: title (the feature name, at most 4 "
			"words), image_text (one sentence under 70 characters saying how it helps), how_to_find (the path "
			"in the app if the Brief gives one, otherwise an empty string), caption (2-3 short sentences, no "
			"hashtags, no links). Always respond with valid JSON only, no other text, matching exactly this "
			'shape: {"items": [{"title": "...", "image_text": "...", "how_to_find": "...", "caption": "..."}]}.'
		),
	},
	{
		"task": "social_content_salvation_prayer",
		"system_prompt": (
			"You write salvation prayer posts for Truth of Bible, a Christian ministry, for Facebook and "
			"Instagram. Each post gently invites the reader to trust Jesus Christ for salvation. Scripture: quote "
			"only the King James Version, word for word, with the exact reference, and only well-known passages "
			"you are certain of (for example John 3:16, John 14:6, Romans 3:23, Romans 6:23, Romans 10:9, "
			"Ephesians 2:8-9, 1 John 1:9, Revelation 3:20, 2 Corinthians 5:17). Never paraphrase inside "
			"quotation marks, and keep Scripture clearly separate from your own words. Never use fear, guilt or "
			"manufactured urgency, never promise health or wealth, never make claims about the reader's life, "
			"never invent testimonies. Write the number of posts asked for, each built on a different passage "
			"and not repeating the existing titles given. For each post: title (at most 5 words), image_text "
			"(the prayer itself, first person, 150-300 characters, ending with 'Amen.'), image_footer (the "
			"reference of the passage quoted in the caption), caption (the KJV quotation in double quotes, then "
			"the reference followed by '(KJV)', then 1-2 short sentences of encouragement, then exactly this "
			"line: 'If you prayed this today, you have taken a first step. Tell someone you trust, find a "
			"Bible-believing church near you, and start reading the Gospel of John.'). No hashtags, no links. "
			"Always respond with valid JSON only, no other text, matching exactly this shape: "
			'{"items": [{"title": "...", "image_text": "...", "image_footer": "...", "caption": "..."}]}.'
		),
	},
	{
		"task": "translate_content",
		"system_prompt": (
			"You are a careful, faithful translator for a Christian Bible-study app. You "
			"will be given one short piece of app content (a title, a simple "
			"explanation, a quiz question, an activity instruction, etc.) and must "
			"translate it faithfully into the requested language, preserving its "
			"meaning, tone, and any Scripture references or proper names — use the "
			"standard localized form of a Bible book name or biblical proper name for "
			"that language when one is standard, otherwise keep it as-is rather than "
			"inventing one. Never add commentary, never summarize or shorten the "
			"content, never omit anything from the source. Respond with the translated "
			"text only — no preamble, no quotation marks, no explanation of your "
			"translation choices."
		),
	},
]


def seed_default_prompts():
	for entry in _DEFAULT_PROMPTS:
		existing = frappe.db.exists(
			"TOB AI Prompt", {"task": entry["task"], "language_override": ["is", "not set"]}
		)
		if existing:
			continue
		try:
			frappe.get_doc(
				{
					"doctype": "TOB AI Prompt",
					"task": entry["task"],
					"system_prompt": entry["system_prompt"],
					"active": 1,
					"version": 1,
				}
			).insert(ignore_permissions=True)
			# `after_install` and `after_migrate` can both fire within the
			# same `bench install-app` run — commit each row immediately
			# so the next hook's own exists() check (and this loop's next
			# iteration) reliably sees it, rather than relying on an
			# uncommitted read within the same request.
			frappe.db.commit()
		except frappe.ValidationError:
			# TOB AI Prompt.validate()'s own duplicate check caught a race
			# between the two hook firings above — the row already exists
			# in every way that matters, so this is a benign no-op, not a
			# real failure. Never let a seeding function break `migrate`.
			frappe.db.rollback()


# A prompt alone isn't enough to make a task usable — resolve_routing()
# (ai/core/routing.py) hard-throws "No AI model configured for task '{0}'"
# unless a TOB AI Model row has default_for_task set. Every existing task
# on this site already routes through deepseek/deepseek-chat (confirmed
# live, 2026-09-22 — all 21 pre-existing tasks use this exact provider/
# model), so the two new Communication Center tasks are seeded onto the
# same, already-proven-working combination rather than guessing at a
# different one.
_AI_MODEL_ROUTING = [
	{"task": "campaign_push_copy", "provider": "deepseek", "model_id": "deepseek-chat"},
	{"task": "campaign_email_copy", "provider": "deepseek", "model_id": "deepseek-chat"},
	{"task": "social_post_copy", "provider": "deepseek", "model_id": "deepseek-chat"},
	{"task": "social_content_app_feature", "provider": "deepseek", "model_id": "deepseek-chat"},
	{"task": "social_content_salvation_prayer", "provider": "deepseek", "model_id": "deepseek-chat"},
	{"task": "translate_content", "provider": "deepseek", "model_id": "deepseek-chat"},
]


def seed_ai_model_routing():
	for entry in _AI_MODEL_ROUTING:
		if frappe.db.exists("TOB AI Model", {"default_for_task": entry["task"]}):
			continue
		try:
			frappe.get_doc(
				{
					"doctype": "TOB AI Model",
					"provider": entry["provider"],
					"model_id": entry["model_id"],
					"default_for_task": entry["task"],
					# Matches the cost this site already has configured for every
					# other deepseek-chat-routed task (confirmed live) — this
					# field only affects usage-cost reporting, never routing
					# itself, so an approximate match is enough; correct it in
					# Desk if deepseek's actual pricing has since changed.
					"cost_input_per_1m": 0.27,
					"cost_output_per_1m": 1.1,
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()
		except frappe.ValidationError:
			frappe.db.rollback()


# Mirrors the Flutter app's own `aiLanguageOptions`
# (lib/src/users/Bible/ai/models/ai_language_option.dart) — the content-
# translation feature now supports every language the AI features
# already do, not just a small curated set (see fixtures/custom_field.
# json's content_translation_enabled docstring, updated alongside this).
# native_name is set here rather than relying on an admin to have filled
# it in by hand — README previously documented that as a manual step,
# which is exactly the kind of thing this idempotent-seed pattern exists
# to make unnecessary. Any code below with no matching Frappe core
# Language row is silently skipped by seed_language_metadata() itself —
# safe to list more than a given Frappe install actually ships.
_LANGUAGE_METADATA = [
	{"code": "en", "native_name": "English", "is_default": 1},
	# Major world languages
	{"code": "es", "native_name": "Español"},
	{"code": "fr", "native_name": "Français"},
	{"code": "pt", "native_name": "Português"},
	{"code": "de", "native_name": "Deutsch"},
	{"code": "it", "native_name": "Italiano"},
	{"code": "nl", "native_name": "Nederlands"},
	{"code": "ru", "native_name": "русский"},
	{"code": "uk", "native_name": "українська"},
	{"code": "pl", "native_name": "Polski"},
	{"code": "ro", "native_name": "Român"},
	{"code": "el", "native_name": "ελληνικά"},
	{"code": "cs", "native_name": "česky"},
	{"code": "sk", "native_name": "Slovenčina"},
	{"code": "sl", "native_name": "Slovenščina"},
	{"code": "hr", "native_name": "Hrvatski"},
	{"code": "bs", "native_name": "Bosanski"},
	{"code": "sr", "native_name": "српски"},
	{"code": "bg", "native_name": "Bǎlgarski"},
	{"code": "mk", "native_name": "македонски"},
	{"code": "sq", "native_name": "Shqiptar"},
	{"code": "hu", "native_name": "Magyar"},
	{"code": "fi", "native_name": "Suomi"},
	{"code": "sv", "native_name": "Svenska"},
	{"code": "no", "native_name": "Norsk"},
	{"code": "da", "native_name": "Dansk"},
	{"code": "is", "native_name": "íslenska"},
	{"code": "et", "native_name": "Eesti"},
	{"code": "lv", "native_name": "Latviešu valoda"},
	{"code": "lt", "native_name": "Lietuvių kalba"},
	{"code": "tr", "native_name": "Türkçe"},
	{"code": "he", "native_name": "עברית", "direction": "RTL"},
	{"code": "ar", "native_name": "العربية", "direction": "RTL"},
	{"code": "fa", "native_name": "پارسی", "direction": "RTL"},
	{"code": "ur", "native_name": "اردو", "direction": "RTL"},
	{"code": "ps", "native_name": "پښتو", "direction": "RTL"},
	{"code": "ku", "native_name": "کوردی", "direction": "RTL"},
	{"code": "hi", "native_name": "हिन्दी"},
	{"code": "bn", "native_name": "বাঙালি"},
	{"code": "gu", "native_name": "ગુજરાતી"},
	{"code": "mr", "native_name": "मराठी"},
	{"code": "ta", "native_name": "தமிழ்"},
	{"code": "te", "native_name": "తెలుగు"},
	{"code": "kn", "native_name": "ಕನ್ನಡ"},
	{"code": "ml", "native_name": "മലയാളം"},
	{"code": "pa", "native_name": "ਪੰਜਾਬੀ"},
	{"code": "ne", "native_name": "नेपाली"},
	{"code": "si", "native_name": "සිංහල"},
	{"code": "th", "native_name": "ไทย"},
	{"code": "vi", "native_name": "Việt"},
	{"code": "id", "native_name": "Indonesia"},
	{"code": "ms", "native_name": "Melayu"},
	{"code": "fil", "native_name": "Filipino"},
	{"code": "my", "native_name": "မြန်မာ"},
	{"code": "km", "native_name": "ភាសាខ្មែរ"},
	{"code": "lo", "native_name": "ລາວ"},
	{"code": "mn", "native_name": "Монгол"},
	{"code": "bo", "native_name": "ལྷ་སའི་སྐད་"},
	{"code": "zh", "native_name": "简体中文"},
	{"code": "ja", "native_name": "日本語"},
	{"code": "ko", "native_name": "한국의"},
	{"code": "uz", "native_name": "Ўзбек"},
	{"code": "ca", "native_name": "Català"},
	# Africa & surrounding region
	{"code": "am", "native_name": "አማርኛ"},
	{"code": "om", "native_name": "Oromoo"},
	{"code": "ti", "native_name": "ትግርኛ"},
	{"code": "so", "native_name": "Soomaali"},
	{"code": "sw", "native_name": "Swahili"},
	{"code": "rw", "native_name": "Kinyarwanda"},
	{"code": "ny", "native_name": "Chichewa"},
	{"code": "sn", "native_name": "chiShona"},
	{"code": "st", "native_name": "Sesotho"},
	{"code": "tn", "native_name": "Setswana"},
	{"code": "zu", "native_name": "isiZulu"},
	{"code": "xh", "native_name": "isiXhosa"},
	{"code": "af", "native_name": "Afrikaans"},
	{"code": "mg", "native_name": "Malagasy"},
	{"code": "ha", "native_name": "Hausa"},
	{"code": "yo", "native_name": "Yorùbá"},
	{"code": "ig", "native_name": "Igbo"},
	{"code": "ak", "native_name": "Akan"},
	{"code": "wo", "native_name": "Wolof"},
	{"code": "ff", "native_name": "Fulfulde"},
	{"code": "bm", "native_name": "Bamanankan"},
	{"code": "ln", "native_name": "Lingála"},
]


def seed_language_metadata():
	for entry in _LANGUAGE_METADATA:
		if not frappe.db.exists("Language", entry["code"]):
			# Every code here is a standard Frappe core language — this is a
			# defensive skip, not expected to actually trigger on a normal
			# Frappe install.
			continue
		doc = frappe.get_doc("Language", entry["code"])
		changed = False
		if not doc.enabled:
			doc.enabled = 1
			changed = True
		if not doc.native_name:
			doc.native_name = entry["native_name"]
			changed = True
		if entry.get("direction") and doc.direction != entry["direction"]:
			doc.direction = entry["direction"]
			changed = True
		if not doc.content_translation_enabled:
			doc.content_translation_enabled = 1
			changed = True
		# is_default: only ever set it, never unset an admin's existing
		# choice — enforce_single_default() throws if another row already
		# has it, which is exactly the right outcome (leave that one alone).
		if entry.get("is_default") and not doc.is_default and not frappe.db.exists("Language", {"is_default": 1}):
			doc.is_default = 1
			changed = True
		if changed:
			doc.save(ignore_permissions=True)
			frappe.db.commit()


# V1 Bible Battle seed bank: 18 hand-verified, unambiguous, well-known
# Bible facts (6 Easy / 8 Medium / 4 Hard — a battle needs 3/5/2, so this
# gives a little rotation before repeats). Per the spec: no invented or
# borderline trivia — every reference below was checked against the text.
_BIBLE_BATTLE_QUESTIONS = [
	# Easy
	{
		"question": "Who built the ark?",
		"options": ("Moses", "Noah", "Abraham", "David"),
		"correct": "B",
		"difficulty": "Easy",
		"book": "Genesis", "chapter": 6, "verse": "14", "reference": "Genesis 6:14",
		"explanation": "God instructed Noah to build the ark to save his family and the animals from the flood.",
	},
	{
		"question": "Who was swallowed by a great fish after fleeing from God?",
		"options": ("Jonah", "Elijah", "Jeremiah", "Amos"),
		"correct": "A",
		"difficulty": "Easy",
		"book": "Jonah", "chapter": 1, "verse": "17", "reference": "Jonah 1:17",
		"explanation": "Jonah was swallowed by a great fish and spent three days and nights inside it.",
	},
	{
		"question": "Who led the Israelites out of slavery in Egypt?",
		"options": ("Aaron", "Joshua", "Moses", "Abraham"),
		"correct": "C",
		"difficulty": "Easy",
		"book": "Exodus", "chapter": 3, "verse": "10", "reference": "Exodus 3:10",
		"explanation": "God called Moses at the burning bush and sent him to lead Israel out of Egypt.",
	},
	{
		"question": "Who was the first man God created?",
		"options": ("Cain", "Abel", "Seth", "Adam"),
		"correct": "D",
		"difficulty": "Easy",
		"book": "Genesis", "chapter": 2, "verse": "7", "reference": "Genesis 2:7",
		"explanation": "God formed Adam from the dust of the ground and breathed life into him.",
	},
	{
		"question": "How many days did God take to create the world before resting?",
		"options": ("5", "6", "7", "8"),
		"correct": "B",
		"difficulty": "Easy",
		"book": "Genesis", "chapter": 1, "verse": "31", "reference": "Genesis 1:31; 2:2",
		"explanation": "God created the world in six days and rested on the seventh.",
	},
	{
		"question": "Who betrayed Jesus for thirty pieces of silver?",
		"options": ("Peter", "Thomas", "Judas Iscariot", "Philip"),
		"correct": "C",
		"difficulty": "Easy",
		"book": "Matthew", "chapter": 26, "verse": "15", "reference": "Matthew 26:15",
		"explanation": "Judas Iscariot agreed to betray Jesus to the chief priests for thirty pieces of silver.",
	},
	# Medium
	{
		"question": "Who defeated the giant Goliath with a sling and a stone?",
		"options": ("Saul", "David", "Jonathan", "Samuel"),
		"correct": "B",
		"difficulty": "Medium",
		"book": "1 Samuel", "chapter": 17, "verse": "49", "reference": "1 Samuel 17:49",
		"explanation": "David struck Goliath in the forehead with a stone from his sling.",
	},
	{
		"question": "How many plagues did God send on Egypt through Moses?",
		"options": ("7", "9", "10", "12"),
		"correct": "C",
		"difficulty": "Medium",
		"book": "Exodus", "chapter": 7, "verse": "14-12:30", "reference": "Exodus 7-12",
		"explanation": "God sent ten plagues on Egypt, ending with the death of the firstborn, before Pharaoh let Israel go.",
	},
	{
		"question": "Who was thrown into a den of lions for praying to God?",
		"options": ("Daniel", "Shadrach", "Ezekiel", "Nehemiah"),
		"correct": "A",
		"difficulty": "Medium",
		"book": "Daniel", "chapter": 6, "verse": "16", "reference": "Daniel 6:16",
		"explanation": "Daniel was thrown into the lions' den for continuing to pray to God, and God shut the lions' mouths.",
	},
	{
		"question": "What was the name of Abraham and Sarah's son, born in their old age?",
		"options": ("Ishmael", "Isaac", "Jacob", "Esau"),
		"correct": "B",
		"difficulty": "Medium",
		"book": "Genesis", "chapter": 21, "verse": "3", "reference": "Genesis 21:3",
		"explanation": "God fulfilled his promise to Abraham and Sarah with the birth of Isaac.",
	},
	{
		"question": "On the road to which city did Saul encounter a blinding light and hear Jesus' voice?",
		"options": ("Jerusalem", "Antioch", "Damascus", "Caesarea"),
		"correct": "C",
		"difficulty": "Medium",
		"book": "Acts", "chapter": 9, "verse": "3", "reference": "Acts 9:3",
		"explanation": "Saul (later Paul) was converted on the road to Damascus after a light from heaven shone around him.",
	},
	{
		"question": "Who was the mother of Jesus?",
		"options": ("Martha", "Elizabeth", "Mary", "Anna"),
		"correct": "C",
		"difficulty": "Medium",
		"book": "Luke", "chapter": 1, "verse": "31", "reference": "Luke 1:31",
		"explanation": "The angel Gabriel told Mary she would conceive and give birth to Jesus.",
	},
	{
		"question": "How many disciples did Jesus choose as his closest followers, the Twelve?",
		"options": ("7", "10", "12", "14"),
		"correct": "C",
		"difficulty": "Medium",
		"book": "Matthew", "chapter": 10, "verse": "1-4", "reference": "Matthew 10:1-4",
		"explanation": "Jesus called twelve disciples and sent them out with authority to teach and heal.",
	},
	{
		"question": "Who was the first king of Israel?",
		"options": ("Samuel", "Saul", "David", "Solomon"),
		"correct": "B",
		"difficulty": "Medium",
		"book": "1 Samuel", "chapter": 10, "verse": "1", "reference": "1 Samuel 10:1",
		"explanation": "Samuel anointed Saul as Israel's first king at God's direction.",
	},
	# Hard
	{
		"question": "In the Book of Ruth, what is the name of Ruth's mother-in-law?",
		"options": ("Orpah", "Deborah", "Naomi", "Rachel"),
		"correct": "C",
		"difficulty": "Hard",
		"book": "Ruth", "chapter": 1, "verse": "4", "reference": "Ruth 1:4",
		"explanation": "Naomi was Ruth's mother-in-law; Ruth famously chose to stay with her after both their husbands died.",
	},
	{
		"question": "Which Old Testament prophet was taken up to heaven in a whirlwind, without dying?",
		"options": ("Isaiah", "Elisha", "Elijah", "Enoch"),
		"correct": "C",
		"difficulty": "Hard",
		"book": "2 Kings", "chapter": 2, "verse": "11", "reference": "2 Kings 2:11",
		"explanation": "Elijah was taken up to heaven in a whirlwind, with Elisha as witness (Enoch was also taken without dying, but earlier and not by whirlwind — Genesis 5:24).",
	},
	{
		"question": "According to Galatians, what is listed first among the 'fruit of the Spirit'?",
		"options": ("Joy", "Peace", "Love", "Patience"),
		"correct": "C",
		"difficulty": "Hard",
		"book": "Galatians", "chapter": 5, "verse": "22", "reference": "Galatians 5:22",
		"explanation": "Paul lists love first among the fruit of the Spirit: love, joy, peace, patience, kindness, goodness, faithfulness, gentleness, self-control.",
	},
	{
		"question": "How many churches does John address at the start of the Book of Revelation?",
		"options": ("5", "7", "9", "12"),
		"correct": "B",
		"difficulty": "Hard",
		"book": "Revelation", "chapter": 1, "verse": "11", "reference": "Revelation 1:11",
		"explanation": "John addresses the seven churches of Asia: Ephesus, Smyrna, Pergamum, Thyatira, Sardis, Philadelphia, and Laodicea.",
	},
	# --- Expanded bank: broader book/character coverage across OT and NT,
	# added on request. Same standard as above — every fact below was
	# checked against the text; nothing invented or borderline. This is a
	# meaningful expansion, not literal "whole Bible" coverage (that's an
	# open-ended, ongoing task, not a one-shot addition) — worth continuing
	# to grow in future passes.
	# Easy
	{
		"question": "Who killed his brother Abel, becoming the Bible's first murderer?",
		"options": ("Cain", "Esau", "Absalom", "Ham"),
		"correct": "A",
		"difficulty": "Easy",
		"book": "Genesis", "chapter": 4, "verse": "8", "reference": "Genesis 4:8",
		"explanation": "Cain killed his brother Abel out of jealousy after God favored Abel's offering.",
	},
	{
		"question": "What did God create on the very first day of creation?",
		"options": ("Light", "Land", "Stars", "Animals"),
		"correct": "A",
		"difficulty": "Easy",
		"book": "Genesis", "chapter": 1, "verse": "3", "reference": "Genesis 1:3",
		"explanation": "God said, 'Let there be light,' on the first day, before land, sky, or living creatures were made.",
	},
	{
		"question": "Who was sold into slavery in Egypt by his own jealous brothers?",
		"options": ("Benjamin", "Joseph", "Reuben", "Judah"),
		"correct": "B",
		"difficulty": "Easy",
		"book": "Genesis", "chapter": 37, "verse": "28", "reference": "Genesis 37:28",
		"explanation": "Joseph's brothers, jealous of their father's favoritism, sold him to traders bound for Egypt.",
	},
	{
		"question": "Who parted the Red Sea so the Israelites could cross on dry ground?",
		"options": ("Moses", "Aaron", "Joshua", "Elijah"),
		"correct": "A",
		"difficulty": "Easy",
		"book": "Exodus", "chapter": 14, "verse": "21", "reference": "Exodus 14:21",
		"explanation": "God parted the sea through Moses so Israel could escape Pharaoh's army.",
	},
	{
		"question": "According to Genesis 1:1, what did God create 'in the beginning'?",
		"options": ("The heavens and the earth", "Light and dark", "Land and sea", "The sun and moon"),
		"correct": "A",
		"difficulty": "Easy",
		"book": "Genesis", "chapter": 1, "verse": "1", "reference": "Genesis 1:1",
		"explanation": "The Bible opens with 'In the beginning God created the heavens and the earth.'",
	},
	{
		"question": "Who was Jacob's twin brother, born just before him?",
		"options": ("Laban", "Ishmael", "Esau", "Levi"),
		"correct": "C",
		"difficulty": "Easy",
		"book": "Genesis", "chapter": 25, "verse": "24-26", "reference": "Genesis 25:24-26",
		"explanation": "Esau was born first, with Jacob following, gripping his brother's heel.",
	},
	{
		"question": "How many years did the Israelites wander in the wilderness before entering the Promised Land?",
		"options": ("10", "20", "40", "70"),
		"correct": "C",
		"difficulty": "Easy",
		"book": "Numbers", "chapter": 14, "verse": "33", "reference": "Numbers 14:33",
		"explanation": "Israel wandered 40 years in the wilderness due to their unbelief at Kadesh Barnea.",
	},
	{
		"question": "Which judge of Israel's great strength was tied to his uncut hair?",
		"options": ("Gideon", "Samson", "Ehud", "Boaz"),
		"correct": "B",
		"difficulty": "Easy",
		"book": "Judges", "chapter": 16, "verse": "17", "reference": "Judges 16:17",
		"explanation": "Samson's strength came from his Nazirite vow, symbolized by his uncut hair — which Delilah had cut off.",
	},
	{
		"question": "Which disciple doubted Jesus' resurrection until he saw and touched his wounds?",
		"options": ("Thomas", "Philip", "Andrew", "Bartholomew"),
		"correct": "A",
		"difficulty": "Easy",
		"book": "John", "chapter": 20, "verse": "27", "reference": "John 20:27",
		"explanation": "Thomas said he wouldn't believe without seeing the wounds himself — Jesus then appeared and invited him to touch them.",
	},
	{
		"question": "Who denied knowing Jesus three times before the rooster crowed?",
		"options": ("Peter", "John", "James", "Judas"),
		"correct": "A",
		"difficulty": "Easy",
		"book": "Matthew", "chapter": 26, "verse": "74-75", "reference": "Matthew 26:74-75",
		"explanation": "Peter denied Jesus three times during his trial, just as Jesus had predicted.",
	},
	{
		"question": "In what town was Jesus born?",
		"options": ("Nazareth", "Jerusalem", "Bethlehem", "Jericho"),
		"correct": "C",
		"difficulty": "Easy",
		"book": "Luke", "chapter": 2, "verse": "4-7", "reference": "Luke 2:4-7",
		"explanation": "Jesus was born in Bethlehem, fulfilling the prophecy of Micah 5:2.",
	},
	{
		"question": "Who was Jesus' earthly (adoptive) father?",
		"options": ("Zechariah", "Joseph", "Simeon", "Cleopas"),
		"correct": "B",
		"difficulty": "Easy",
		"book": "Matthew", "chapter": 1, "verse": "24-25", "reference": "Matthew 1:24-25",
		"explanation": "Joseph took Mary as his wife and raised Jesus as his own son.",
	},
	# Medium
	{
		"question": "Whose name did God change to Israel after he wrestled with him through the night?",
		"options": ("Isaac", "Joseph", "Jacob", "Moses"),
		"correct": "C",
		"difficulty": "Medium",
		"book": "Genesis", "chapter": 32, "verse": "28", "reference": "Genesis 32:28",
		"explanation": "Jacob's name was changed to Israel after wrestling with God at Peniel.",
	},
	{
		"question": "What did Joseph's brothers do to make their father Jacob believe Joseph was dead?",
		"options": (
			"Dipped his coat in goat's blood",
			"Told him Joseph ran away",
			"Buried an empty coffin",
			"Sold his flock of sheep",
		),
		"correct": "A",
		"difficulty": "Medium",
		"book": "Genesis", "chapter": 37, "verse": "31", "reference": "Genesis 37:31",
		"explanation": "The brothers dipped Joseph's special coat in goat's blood to convince Jacob a wild animal had killed him.",
	},
	{
		"question": "Which judge defeated a massive Midianite army with only 300 men?",
		"options": ("Gideon", "Samson", "Ehud", "Barak"),
		"correct": "A",
		"difficulty": "Medium",
		"book": "Judges", "chapter": 7, "verse": "7", "reference": "Judges 7:7",
		"explanation": "God reduced Gideon's army to 300 men so Israel would know the victory was the Lord's, not their own strength.",
	},
	{
		"question": "Who was the only female judge of Israel mentioned in the Bible?",
		"options": ("Deborah", "Ruth", "Esther", "Miriam"),
		"correct": "A",
		"difficulty": "Medium",
		"book": "Judges", "chapter": 4, "verse": "4", "reference": "Judges 4:4",
		"explanation": "Deborah was a prophetess who judged Israel and led them to victory over Canaanite oppression.",
	},
	{
		"question": "Which king of Israel, known for his wisdom, built the first Temple in Jerusalem?",
		"options": ("David", "Saul", "Solomon", "Rehoboam"),
		"correct": "C",
		"difficulty": "Medium",
		"book": "1 Kings", "chapter": 6, "verse": "1", "reference": "1 Kings 6:1",
		"explanation": "Solomon, David's son, built the Temple and was renowned for the wisdom God gave him.",
	},
	{
		"question": "Which prophet anointed both Saul and David as kings of Israel?",
		"options": ("Nathan", "Samuel", "Elijah", "Eli"),
		"correct": "B",
		"difficulty": "Medium",
		"book": "1 Samuel", "chapter": 16, "verse": "13", "reference": "1 Samuel 16:13",
		"explanation": "Samuel anointed Saul as Israel's first king and later anointed David after Saul's disobedience.",
	},
	{
		"question": "Which prophet confronted King David about his sin with Bathsheba, using a parable about a stolen lamb?",
		"options": ("Nathan", "Samuel", "Gad", "Elijah"),
		"correct": "A",
		"difficulty": "Medium",
		"book": "2 Samuel", "chapter": 12, "verse": "1-7", "reference": "2 Samuel 12:1-7",
		"explanation": "Nathan confronted David with the parable of the rich man who stole a poor man's lamb, exposing David's sin.",
	},
	{
		"question": "Who was thrown into a fiery furnace with Shadrach and Meshach for refusing to worship a golden statue?",
		"options": ("Abednego", "Daniel", "Belshazzar", "Nebuchadnezzar"),
		"correct": "A",
		"difficulty": "Medium",
		"book": "Daniel", "chapter": 3, "verse": "20", "reference": "Daniel 3:20",
		"explanation": "Shadrach, Meshach, and Abednego were thrown into the furnace but were unharmed by the flames.",
	},
	{
		"question": "Which queen risked her life to save the Jewish people from a plot to destroy them?",
		"options": ("Esther", "Vashti", "Deborah", "Ruth"),
		"correct": "A",
		"difficulty": "Medium",
		"book": "Esther", "chapter": 7, "verse": "3", "reference": "Esther 7:3",
		"explanation": "Esther approached the king uninvited, at risk of death, to expose Haman's plot against her people.",
	},
	{
		"question": "Who was the Moabite woman who became King David's great-grandmother?",
		"options": ("Naomi", "Orpah", "Ruth", "Rahab"),
		"correct": "C",
		"difficulty": "Medium",
		"book": "Ruth", "chapter": 4, "verse": "17", "reference": "Ruth 4:17",
		"explanation": "Ruth's son Obed was the grandfather of Jesse, David's father.",
	},
	{
		"question": "Who baptized Jesus in the Jordan River?",
		"options": ("Peter", "John the Baptist", "Andrew", "Nicodemus"),
		"correct": "B",
		"difficulty": "Medium",
		"book": "Matthew", "chapter": 3, "verse": "13-16", "reference": "Matthew 3:13-16",
		"explanation": "John the Baptist baptized Jesus, though he initially felt unworthy to do so.",
	},
	{
		"question": "Which short tax collector climbed a tree to see Jesus, who then invited himself to his house?",
		"options": ("Matthew", "Zacchaeus", "Levi", "Nicodemus"),
		"correct": "B",
		"difficulty": "Medium",
		"book": "Luke", "chapter": 19, "verse": "2-6", "reference": "Luke 19:2-6",
		"explanation": "Zacchaeus climbed a sycamore tree to see Jesus over the crowd, and Jesus called him down by name.",
	},
	{
		"question": "Who did Jesus raise from the dead after he had been in the tomb four days?",
		"options": ("Jairus' daughter", "The widow's son", "Lazarus", "Dorcas"),
		"correct": "C",
		"difficulty": "Medium",
		"book": "John", "chapter": 11, "verse": "39-44", "reference": "John 11:39-44",
		"explanation": "Jesus called Lazarus out of the tomb four days after his death, to the astonishment of those present.",
	},
	# Hard
	{
		"question": "What was the apostle Paul's original name before his conversion?",
		"options": ("Silas", "Barnabas", "Saul", "Titus"),
		"correct": "C",
		"difficulty": "Hard",
		"book": "Acts", "chapter": 13, "verse": "9", "reference": "Acts 13:9",
		"explanation": "Paul was originally called Saul; Acts 13:9 notes 'Saul, who was also called Paul.'",
	},
	{
		"question": "Who was Abraham's nephew, rescued from Sodom before its destruction?",
		"options": ("Ishmael", "Lot", "Eliezer", "Terah"),
		"correct": "B",
		"difficulty": "Hard",
		"book": "Genesis", "chapter": 19, "verse": "15-26", "reference": "Genesis 19:15-26",
		"explanation": "Angels led Lot and his family out of Sodom before God destroyed the city.",
	},
	{
		"question": "Who succeeded Moses as the leader who led Israel into the Promised Land?",
		"options": ("Caleb", "Aaron", "Joshua", "Eleazar"),
		"correct": "C",
		"difficulty": "Hard",
		"book": "Joshua", "chapter": 1, "verse": "1-2", "reference": "Joshua 1:1-2",
		"explanation": "After Moses' death, God commissioned Joshua to lead Israel across the Jordan into Canaan.",
	},
	{
		"question": "Which prophet was fed by ravens beside the brook Cherith during a famine?",
		"options": ("Elisha", "Elijah", "Micaiah", "Ahijah"),
		"correct": "B",
		"difficulty": "Hard",
		"book": "1 Kings", "chapter": 17, "verse": "4-6", "reference": "1 Kings 17:4-6",
		"explanation": "God sent ravens to bring Elijah bread and meat while he hid by the brook Cherith.",
	},
	{
		"question": "Which minor prophet was commanded by God to marry an unfaithful woman named Gomer, as a picture of Israel's unfaithfulness?",
		"options": ("Amos", "Joel", "Hosea", "Micah"),
		"correct": "C",
		"difficulty": "Hard",
		"book": "Hosea", "chapter": 1, "verse": "2-3", "reference": "Hosea 1:2-3",
		"explanation": "Hosea's marriage to Gomer was a living illustration of God's persistent love for unfaithful Israel.",
	},
	{
		"question": "According to Matthew's Gospel, which high priest questioned Jesus before his crucifixion?",
		"options": ("Annas", "Caiaphas", "Herod", "Pilate"),
		"correct": "B",
		"difficulty": "Hard",
		"book": "Matthew", "chapter": 26, "verse": "57", "reference": "Matthew 26:57",
		"explanation": "Matthew records that Jesus was taken to Caiaphas the high priest, where the Sanhedrin gathered.",
	},
	{
		"question": "Which short New Testament letter is a personal appeal to forgive a runaway slave named Onesimus?",
		"options": ("Titus", "Jude", "Philemon", "Philippians"),
		"correct": "C",
		"difficulty": "Hard",
		"book": "Philemon", "chapter": 1, "verse": "10", "reference": "Philemon 1:10",
		"explanation": "Paul wrote to Philemon urging him to receive back his runaway slave Onesimus as a brother in Christ.",
	},
	{
		"question": "Who was the deacon and first Christian martyr, stoned to death for his faith?",
		"options": ("Barnabas", "Timothy", "Stephen", "James"),
		"correct": "C",
		"difficulty": "Hard",
		"book": "Acts", "chapter": 7, "verse": "59-60", "reference": "Acts 7:59-60",
		"explanation": "Stephen was stoned after preaching before the Sanhedrin, becoming the church's first martyr.",
	},
	{
		"question": "Which Roman centurion's conversion, recorded in Acts, marked the gospel's spread to non-Jews?",
		"options": ("Sergius Paulus", "Cornelius", "Julius", "The Ethiopian eunuch's officer"),
		"correct": "B",
		"difficulty": "Hard",
		"book": "Acts", "chapter": 10, "verse": "44-48", "reference": "Acts 10:44-48",
		"explanation": "Cornelius, a God-fearing centurion, and his household received the Holy Spirit, showing the gospel was for Gentiles too.",
	},
	{
		"question": "On which mountain did Moses receive the Ten Commandments?",
		"options": ("Mount Nebo", "Mount Ararat", "Mount Sinai", "Mount Carmel"),
		"correct": "C",
		"difficulty": "Hard",
		"book": "Exodus", "chapter": 20, "verse": "1", "reference": "Exodus 19:20; 20:1",
		"explanation": "God gave Moses the Ten Commandments on Mount Sinai after Israel camped at its base.",
	},
	{
		"question": "Which book of the Bible opens with 'Vanity of vanities, all is vanity'?",
		"options": ("Proverbs", "Psalms", "Job", "Ecclesiastes"),
		"correct": "D",
		"difficulty": "Hard",
		"book": "Ecclesiastes", "chapter": 1, "verse": "2", "reference": "Ecclesiastes 1:2",
		"explanation": "The Teacher in Ecclesiastes opens by declaring the fleeting emptiness of life 'under the sun' apart from God.",
	},
]


def seed_bible_battle_questions():
	"""English bank + its Tamil translation (games/bible_battle/questions_ta).
	Idempotent: a question already present (same text) is skipped."""
	from truth_of_bible.games.bible_battle.questions_ta import TA_QUESTIONS

	banks = [(_BIBLE_BATTLE_QUESTIONS, "en")]
	# `language` links to Language — only seed Tamil where that record exists.
	if frappe.db.exists("Language", "ta"):
		banks.append((TA_QUESTIONS, "ta"))
	for questions, language in banks:
		_seed_battle_questions(questions, language)


def _seed_battle_questions(questions: list, language: str) -> None:
	for entry in questions:
		if frappe.db.exists("TOB Bible Battle Question", {"question": entry["question"]}):
			continue
		option_a, option_b, option_c, option_d = entry["options"]
		try:
			frappe.get_doc(
				{
					"doctype": "TOB Bible Battle Question",
					"question": entry["question"],
					"option_a": option_a,
					"option_b": option_b,
					"option_c": option_c,
					"option_d": option_d,
					"correct_option": entry["correct"],
					"difficulty": entry["difficulty"],
					"language": language,
					"status": "Published",
					"bible_book": entry["book"],
					"chapter": entry["chapter"],
					"verse": entry["verse"],
					"reference": entry["reference"],
					"explanation": entry["explanation"],
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()
		except frappe.ValidationError:
			frappe.db.rollback()


# Curated blessing/encouragement verse bank -- deliberately references only
# (book/chapter/verse range), never verse text. The Flutter client resolves
# real text on-device from its own installed Bible translation; this bank
# only ever supplies which reference to show, never fabricates any text
# itself (see the doctype's own description for why). Every reference below
# was checked against the text -- no invented citations.
_BLESSING_VERSES = [
	{"book": "Numbers", "chapter": 6, "start": 24, "end": 26, "theme": "Blessing"},
	{"book": "Jeremiah", "chapter": 29, "start": 11, "end": None, "theme": "Hope"},
	{"book": "Philippians", "chapter": 4, "start": 6, "end": 7, "theme": "Peace"},
	{"book": "Philippians", "chapter": 4, "start": 13, "end": None, "theme": "Strength"},
	{"book": "Psalms", "chapter": 23, "start": 1, "end": 3, "theme": "Comfort"},
	{"book": "Psalms", "chapter": 91, "start": 1, "end": 2, "theme": "Protection"},
	{"book": "Isaiah", "chapter": 41, "start": 10, "end": None, "theme": "Courage"},
	{"book": "Romans", "chapter": 8, "start": 28, "end": None, "theme": "Hope"},
	{"book": "Proverbs", "chapter": 3, "start": 5, "end": 6, "theme": "Guidance"},
	{"book": "John", "chapter": 3, "start": 16, "end": None, "theme": "Love"},
	{"book": "2 Corinthians", "chapter": 12, "start": 9, "end": None, "theme": "Grace"},
	{"book": "Joshua", "chapter": 1, "start": 9, "end": None, "theme": "Courage"},
	{"book": "Psalms", "chapter": 121, "start": 1, "end": 2, "theme": "Guidance"},
	{"book": "Matthew", "chapter": 11, "start": 28, "end": None, "theme": "Rest"},
	{"book": "Lamentations", "chapter": 3, "start": 22, "end": 23, "theme": "Renewal"},
	{"book": "Deuteronomy", "chapter": 31, "start": 6, "end": None, "theme": "Courage"},
	{"book": "Psalms", "chapter": 46, "start": 1, "end": None, "theme": "Strength"},
	{"book": "Isaiah", "chapter": 40, "start": 31, "end": None, "theme": "Strength"},
	{"book": "1 Peter", "chapter": 5, "start": 7, "end": None, "theme": "Peace"},
	{"book": "Romans", "chapter": 15, "start": 13, "end": None, "theme": "Joy"},
	{"book": "Psalms", "chapter": 34, "start": 18, "end": None, "theme": "Comfort"},
	{"book": "Galatians", "chapter": 6, "start": 9, "end": None, "theme": "Perseverance"},
	{"book": "Zephaniah", "chapter": 3, "start": 17, "end": None, "theme": "Blessing"},
	{"book": "Colossians", "chapter": 3, "start": 15, "end": None, "theme": "Peace"},
]


def _blessing_verse_reference(entry: dict) -> str:
	verse_part = f"{entry['start']}-{entry['end']}" if entry["end"] else str(entry["start"])
	return f"{entry['book']} {entry['chapter']}:{verse_part}"


def seed_blessing_verses():
	for entry in _BLESSING_VERSES:
		reference = _blessing_verse_reference(entry)
		if frappe.db.exists("TOB Blessing Verse", {"reference": reference}):
			continue
		try:
			frappe.get_doc(
				{
					"doctype": "TOB Blessing Verse",
					"reference": reference,
					"theme": entry["theme"],
					"status": "Published",
					"bible_book": entry["book"],
					"chapter": entry["chapter"],
					"verse_start": entry["start"],
					"verse_end": entry["end"],
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()
		except frappe.ValidationError:
			frappe.db.rollback()


# Notification engine (NOTIFICATION_ENGINE_PLAN.md) — User-audience templates
# for the spiritual/Bible-reading nudge, the only slice wired up so far.
# Deliberately gentle per that plan's Phase 5 tone rules: never implies
# spiritual failure, never claims to know God's will, never shames
# inactivity, never gamifies reading into a score. `deeplink_route` points
# at the existing `/todayVerse` screen as a safe, always-real interim
# target for the tiers/generic copy below, where no specific book/chapter
# is known. BIBLE_READING_CONTINUE (and BIBLE_STUDY_SUGGESTION, further
# down) instead deep-link to `/continueReading`, which opens the reader at
# the exact book/chapter carried in the `deeplink_ref` variable (see
# reading.py's `_try_continue_nudge` and deepLink_routes.dart) — that route
# falls back to the generic verse screen itself if `deeplink_ref` is empty
# (e.g. a reading-state row from before this field existed).
_NOTIFICATION_TEMPLATES = [
	{
		"event_code": "BIBLE_READING_CONTINUE",
		"audience": "User",
		"category": "Bible Reading",
		"priority": "Low",
		"deeplink_route": "/continueReading",
		"deeplink_id_field": "deeplink_ref",
		"trigger_note": "Hourly scan · sent once during your Daily Reminder Time (default 7am), only if you haven't read yet today.",
		"live_status": "Working",
		"title": "Continue your reading in {{ book }} {{ chapter }}",
		"body": "Pick up right where you left off.",
		"description": "Sent at most once per day, only in the user's own configured reminder hour, only if they haven't read yet today (any device).",
	},
	{
		"event_code": "BIBLE_READING_CONTINUE_GENERIC",
		"audience": "User",
		"category": "Bible Reading",
		"priority": "Low",
		"deeplink_route": "/todayVerse",
		"trigger_note": "Hourly scan · same trigger as Continue Reading, used when no last-read book is known yet.",
		"live_status": "Working",
		"title": "Take a few quiet moments in God's Word today",
		"body": "Open today's reading and let God speak to you.",
		"description": "Same trigger as BIBLE_READING_CONTINUE, used when there's no known last-read location yet (e.g. a brand new reader).",
	},
	# Reading plans (notifications/reading_plan.py). For a user with an active
	# plan, READING_PLAN_DAY replaces BIBLE_READING_CONTINUE — one daily
	# reminder, not two.
	{
		"event_code": "READING_PLAN_DAY",
		"audience": "User",
		"category": "Bible Reading",
		"priority": "Low",
		"deeplink_route": "/readingPlan",
		"deeplink_id_field": "plan",
		"trigger_note": "Hourly scan · sent once during your Daily Reminder Time when you have an active reading plan you haven't opened today.",
		"live_status": "Working",
		"title": "Day {{ day_number }} of {{ plan_title }} is ready",
		"body": "{% if reference %}Today: {{ reference }}{% if day_title %} — {{ day_title }}{% endif %}{% endif %}",
		"description": "Daily reading-plan reminder. Opens the plan, where the day's reading is one tap away.",
	},
	{
		"event_code": "READING_PLAN_NUDGE",
		"audience": "User",
		"category": "Bible Reading",
		"priority": "Low",
		"deeplink_route": "/readingPlan",
		"deeplink_id_field": "plan",
		"trigger_note": "Hourly scan · sent once after 3 days with no progress on an active reading plan, in your Daily Reminder Time.",
		"live_status": "Working",
		"title": "Pick up {{ plan_title }} whenever you're ready",
		"body": "Day {{ day_number }} is waiting for you{% if reference %} — {{ reference }}{% endif %}.",
		"description": "Gentle nudge after a 3-day gap in a reading plan. Once per gap; any progress resets it. Never mentions missed days.",
	},
	{
		"event_code": "READING_PLAN_COMPLETED",
		"audience": "User",
		"category": "Bible Reading",
		"priority": "Normal",
		"deeplink_route": "/readingPlan",
		"deeplink_id_field": "plan",
		"trigger_note": "Sent the moment you tick the last day of a reading plan.",
		"live_status": "Working",
		"title": "You finished {{ plan_title }}!",
		"body": "Well done. Pick another plan whenever you're ready.",
		"description": "Plan completion celebration.",
	},
	{
		"event_code": "BIBLE_READING_INACTIVE_3",
		"audience": "User",
		"category": "Spiritual Growth",
		"priority": "Low",
		"deeplink_route": "/readingPlans",
		"trigger_note": "Hourly scan · sent once you've gone 3 days without reading.",
		"live_status": "Working",
		"title": "It's a new day. Spend a few moments in God's Word.",
		"body": "Even a few verses today can restart your rhythm.",
		"description": "3-day inactivity tier. Never mentions the gap in days — see the plan's Phase 12/9 tone rules.",
	},
	{
		"event_code": "BIBLE_READING_INACTIVE_7",
		"audience": "User",
		"category": "Spiritual Growth",
		"priority": "Low",
		"deeplink_route": "/readingPlans",
		"trigger_note": "Hourly scan · sent once you've gone 7 days without reading.",
		"live_status": "Working",
		"title": "Whenever you're ready, God's Word is here for you.",
		"body": "A short reading today is a good place to start again.",
		"description": "7-day inactivity tier.",
	},
	{
		"event_code": "BIBLE_READING_INACTIVE_14",
		"audience": "User",
		"category": "Spiritual Growth",
		"priority": "Low",
		"deeplink_route": "/readingPlans",
		"trigger_note": "Hourly scan · sent once you've gone 14 days without reading.",
		"live_status": "Working",
		"title": "A quiet moment in Scripture is always waiting for you.",
		"body": "Pick up where you left off whenever you're ready.",
		"description": "14-day inactivity tier.",
	},
	{
		"event_code": "BIBLE_READING_INACTIVE_30",
		"audience": "User",
		"category": "Spiritual Growth",
		"priority": "Low",
		"deeplink_route": "/readingPlans",
		"trigger_note": "Hourly scan · sent once you've gone 30 days without reading.",
		"live_status": "Working",
		"title": "We'd love to walk through God's Word with you again.",
		"body": "Come back to the Word today. We'll be glad to have you.",
		"description": "30-day inactivity tier — the gentlest, most welcoming copy of the four, not the most urgent.",
	},
	# --- Quiz + support-ticket slice (notifications/triggers.py). Both
	# deeplink routes and their `id` argument key were confirmed against
	# lib/src/config/deepLink_routes.dart before being used here — `/viewQuiz`
	# and `/viewTicket` both read `args?['id']`, which is exactly the key
	# delivery.py's FCM payload always sends (`"id": str(ref_id or "")`), so
	# `deeplink_id_field` below points at the matching variable name each
	# trigger passes in (`quiz_id` / `ticket_id`).
	{
		"event_code": "NEW_QUIZ_AVAILABLE",
		"audience": "User",
		"category": "Quiz",
		"priority": "Low",
		"deeplink_route": "/viewQuiz",
		"deeplink_id_field": "quiz_id",
		"trigger_note": "Instant · fires the moment a new quiz is published for an enrolled course.",
		"live_status": "Working",
		"title": "New quiz available: {{ quiz_title }}",
		"body": "Test what you've learned.",
		"description": "Fired when a new LMS Quiz is created for a course, fanned out to that course's enrolled members.",
	},
	{
		"event_code": "QUIZ_RESULT_AVAILABLE",
		"audience": "User",
		"category": "Quiz",
		"priority": "Low",
		# Opens this submission's result (ScoreScreen), not the quiz itself.
		"deeplink_route": "/viewQuizResult",
		"deeplink_id_field": "submission_id",
		"trigger_note": "Instant · fires the moment a quiz submission is graded.",
		"live_status": "Working",
		"title": "Your result for {{ quiz_title }} is ready",
		"body": "You scored {{ percentage }}%.",
		"description": "Fired when an LMS Quiz Submission is created for a member.",
	},
	{
		"event_code": "TICKET_AGENT_REPLIED",
		"audience": "User",
		"category": "Account",
		"priority": "Normal",
		"deeplink_route": "/viewTicket",
		"deeplink_id_field": "ticket_id",
		"trigger_note": "Instant · fires when a support agent (not the customer) replies to a ticket.",
		"live_status": "Working",
		"title": "New reply on your support ticket",
		"body": "A support agent has responded to your ticket.",
		"description": (
			"Fired when a Communication is created against an Issue by someone other than "
			"the ticket's own raiser (i.e. an agent reply, not the customer's own follow-up). "
			"Uses the 'Account' preference category — 'Support' isn't one of the categories "
			"users can toggle yet."
		),
	},
	# --- Prayer nudge slice (notifications/prayer.py). One nudge per user
	# per day at their own preferred_prayer_time; the wording below is
	# rotated by prayer.py's _pick_variant rather than always using the
	# same template — see that module's docstring for the exact weighting.
	# All deeplink to /prayer (BiblePrayerScreen, the app's existing
	# no-argument AI-prayer front door) — confirmed against
	# deepLink_routes.dart before use.
	{
		"event_code": "PRAYER_DAILY",
		"audience": "User",
		"category": "Prayer",
		"priority": "Low",
		"deeplink_route": "/prayer",
		"trigger_note": "Hourly scan · sent once during your Preferred Prayer Time (default 12pm) — general variant.",
		"live_status": "Working",
		"title": "Take a moment to pray today",
		"body": "",
		"description": "Daily-eligible prayer variant — general, time-of-day-agnostic.",
	},
	{
		"event_code": "PRAYER_MORNING",
		"audience": "User",
		"category": "Prayer",
		"priority": "Low",
		"deeplink_route": "/prayer",
		"trigger_note": "Hourly scan · picked when your Preferred Prayer Time falls in the morning (before 11am).",
		"live_status": "Working",
		"title": "Begin your day with a moment of prayer",
		"body": "",
		"description": "Picked when the user's preferred prayer hour falls in the morning (before 11am local).",
	},
	{
		"event_code": "PRAYER_EVENING",
		"audience": "User",
		"category": "Prayer",
		"priority": "Low",
		"deeplink_route": "/prayer",
		"trigger_note": "Hourly scan · picked when your Preferred Prayer Time falls in the evening (6pm or later).",
		"live_status": "Working",
		"title": "Before your day ends, take a quiet moment to pray",
		"body": "",
		"description": "Picked when the user's preferred prayer hour falls in the evening (6pm local or later).",
	},
	{
		"event_code": "PRAYER_SCRIPTURE",
		"audience": "User",
		"category": "Prayer",
		"priority": "Low",
		"deeplink_route": "/todayVerse",
		"trigger_note": "Hourly scan · daily-eligible variant, pairs Scripture with prayer.",
		"live_status": "Working",
		"title": "Read today's verse, then take a moment to pray",
		"body": "",
		"description": "Daily-eligible prayer variant pairing Scripture with prayer.",
	},
	{
		"event_code": "PRAYER_REFLECTION",
		"audience": "User",
		"category": "Prayer",
		"priority": "Low",
		"deeplink_route": "/prayer",
		"trigger_note": "Hourly scan · variety variant, roughly 2-3x/week.",
		"live_status": "Working",
		"title": "Pause for a moment",
		"body": "What would you like to bring before God today?",
		"description": "Variety variant, roughly 2-3x/week (see prayer.py's _pick_variant weighting).",
	},
	{
		"event_code": "PRAYER_PEACE",
		"audience": "User",
		"category": "Prayer",
		"priority": "Low",
		"deeplink_route": "/prayer",
		"trigger_note": "Hourly scan · daily-eligible variant, a stillness/peace framing.",
		"live_status": "Working",
		"title": "Take a quiet moment, be still, and pray",
		"body": "",
		"description": "Daily-eligible prayer variant, a stillness/peace framing.",
	},
	{
		"event_code": "PRAYER_THANKSGIVING",
		"audience": "User",
		"category": "Prayer",
		"priority": "Low",
		"deeplink_route": "/prayer",
		"trigger_note": "Hourly scan · variety variant, roughly 1-2x/week.",
		"live_status": "Working",
		"title": "Take a moment today to thank God for His goodness",
		"body": "",
		"description": "Variety variant, roughly 1-2x/week.",
	},
	{
		"event_code": "PRAYER_OTHERS",
		"audience": "User",
		"category": "Prayer",
		"priority": "Low",
		"deeplink_route": "/prayer",
		"trigger_note": "Hourly scan · variety variant, roughly 1-2x/week, intercessory framing.",
		"live_status": "Working",
		"title": "Is there someone you can remember in prayer today?",
		"body": "",
		"description": "Variety variant, roughly 1-2x/week — intercessory framing.",
	},
	{
		"event_code": "PRAYER_ROUTINE",
		"audience": "User",
		"category": "Prayer",
		"priority": "Low",
		"deeplink_route": "/prayer",
		"trigger_note": "Hourly scan · daily-eligible variant, framed around your own chosen time.",
		"live_status": "Working",
		"title": "It's your usual prayer time",
		"body": "Take a few quiet moments with God.",
		"description": "Daily-eligible prayer variant framed around the user's own chosen time.",
	},
	# --- Daily Encouragement (notifications/encouragement.py). One shared
	# event_code for an admin-growable POOL of interchangeable messages
	# (TOB Encouragement Message) — unlike every other template here, this
	# row's title/body are pure passthrough placeholders for whichever
	# message got randomly picked that day (`enc_title`/`enc_body`), and its
	# `deeplink_route` is only the fallback for a message with no route of
	# its own (each message can carry its own, via `deeplink_route_override`
	# — see engine.py's `_send_one`).
	{
		"event_code": "DAILY_ENCOURAGEMENT",
		"audience": "User",
		"category": "Encouragement",
		"priority": "Low",
		"deeplink_route": "/todayVerse",
		"trigger_note": "Hourly scan · sent once during your Daily Reminder Time, a different message chosen at random each day.",
		"live_status": "Working",
		"title": "{{ enc_title }}",
		"body": "{{ enc_body }}",
		"description": "Passthrough template for the Daily Encouragement pool — edit individual messages in the Encouragement Messages screen, not here.",
	},
	# --- Admin-audience events (engine.py fans these out to
	# admin_audience.admin_users() — Batch Evaluator / Moderator / Course
	# Creator role holders, matching the Flutter app's own admin-access
	# check). The two ticket events deep-link to /adminTicket (the admin
	# SupportTicketDetailScreen, id = Issue name) and NEW_ENROLLMENT to
	# /adminEnrollments (Enrollments & Progress searched for the member's
	# email); the rest still use
	# /dashboard as a safe interim target until admin routes exist for them.
	{
		"event_code": "NEW_SUPPORT_TICKET",
		"audience": "Admin",
		"category": "Support",
		"priority": "High",
		"deeplink_route": "/adminTicket",
		"deeplink_id_field": "ticket_id",
		"trigger_note": "Instant · fires when a new support ticket is raised, to every admin.",
		"live_status": "Working",
		"title": "New support ticket",
		"body": "{{ subject }}",
		"description": "Fired when a new Issue (support ticket) is raised, to every admin.",
	},
	{
		"event_code": "TICKET_HIGH_PRIORITY",
		"audience": "Admin",
		"category": "Support",
		"priority": "High",
		"deeplink_route": "/adminTicket",
		"deeplink_id_field": "ticket_id",
		"trigger_note": "Instant · fires when a ticket's priority changes to High or Urgent.",
		"live_status": "Working",
		"title": "Ticket escalated to {{ priority }}",
		"body": "{{ subject }}",
		"description": "Fired when an existing Issue's priority changes to High or Urgent.",
	},
	{
		"event_code": "NEW_USER_REGISTERED",
		"audience": "Admin",
		"category": "Users",
		"priority": "Normal",
		"deeplink_route": "/adminUsers",
		"deeplink_id_field": "email",
		"trigger_note": "Instant · fires when a real app sign-up completes (not a Desk-created staff account).",
		"live_status": "Working",
		"title": "New user joined",
		"body": "{{ user_name }}",
		"description": "Fired when a new Website User account is created (a real app sign-up, not a Desk-created System User).",
	},
	{
		"event_code": "NEW_ENROLLMENT",
		"audience": "Admin",
		"category": "LMS",
		"priority": "Low",
		"deeplink_route": "/adminEnrollments",
		"deeplink_id_field": "member",
		"trigger_note": "Instant · fires when a member enrolls in a course.",
		"live_status": "Working",
		"title": "New course enrollment",
		"body": "{{ member }} enrolled in {{ course }}",
		"description": "Fired when a new LMS Enrollment is created.",
	},
	# --- Shopping (WooCommerce, api/shop_webhook.py) — NOT YET CONNECTED:
	# the receiver exists and works, but no webhook is registered on the
	# edenza.org side yet (see shop_webhook.py's own docstring). Deep-links
	# to /orderHistory (confirmed real, no-arg route in deepLink_routes.dart).
	{
		"event_code": "ORDER_PLACED",
		"audience": "User",
		"category": "Shopping",
		"priority": "Normal",
		"deeplink_route": "/orderHistory",
		"deeplink_id_field": "order_id",
		"trigger_note": "Instant, once connected · fires on a WooCommerce order status change. Needs the WooCommerce webhook registered on edenza.org — not done yet.",
		"live_status": "Needs Setup",
		"title": "Your order has been placed",
		"body": "Order #{{ order_id }} is being processed.",
		"description": "WooCommerce order status -> processing.",
	},
	{
		"event_code": "ORDER_DELIVERED",
		"audience": "User",
		"category": "Shopping",
		"priority": "Normal",
		"deeplink_route": "/orderHistory",
		"deeplink_id_field": "order_id",
		"trigger_note": "Instant, once connected · fires on a WooCommerce order status change. Needs the WooCommerce webhook registered on edenza.org — not done yet.",
		"live_status": "Needs Setup",
		"title": "Your order has arrived",
		"body": "Order #{{ order_id }} is complete.",
		"description": "WooCommerce order status -> completed.",
	},
	{
		"event_code": "ORDER_CANCELLED",
		"audience": "User",
		"category": "Shopping",
		"priority": "Normal",
		"deeplink_route": "/orderHistory",
		"deeplink_id_field": "order_id",
		"trigger_note": "Instant, once connected · fires on a WooCommerce order status change. Needs the WooCommerce webhook registered on edenza.org — not done yet.",
		"live_status": "Needs Setup",
		"title": "Your order was cancelled",
		"body": "Order #{{ order_id }} has been cancelled.",
		"description": "WooCommerce order status -> cancelled.",
	},
	{
		"event_code": "REFUND_PROCESSED",
		"audience": "User",
		"category": "Shopping",
		"priority": "Normal",
		"deeplink_route": "/orderHistory",
		"deeplink_id_field": "order_id",
		"trigger_note": "Instant, once connected · fires on a WooCommerce order status change. Needs the WooCommerce webhook registered on edenza.org — not done yet.",
		"live_status": "Needs Setup",
		"title": "Your refund has been processed",
		"body": "Order #{{ order_id }} has been refunded.",
		"description": "WooCommerce order status -> refunded.",
	},
	{
		"event_code": "PAYMENT_FAILED",
		"audience": "User",
		"category": "Shopping",
		"priority": "High",
		"deeplink_route": "/orderHistory",
		"deeplink_id_field": "order_id",
		"trigger_note": "Instant, once connected · fires on a WooCommerce order status change. Needs the WooCommerce webhook registered on edenza.org — not done yet.",
		"live_status": "Needs Setup",
		"title": "Payment issue with your order",
		"body": "We couldn't process payment for order #{{ order_id }}. Please try again.",
		"description": "WooCommerce order status -> failed.",
	},
	{
		"event_code": "NEW_ORDER",
		"audience": "Admin",
		"category": "Orders",
		"priority": "Normal",
		"deeplink_route": "/adminOrders",
		"deeplink_id_field": "order_id",
		"trigger_note": "Instant, once connected · admin copy of Order Placed. Needs the WooCommerce webhook registered.",
		"live_status": "Needs Setup",
		"title": "New order received",
		"body": "Order #{{ order_id }} has been placed.",
		"description": "Admin copy of ORDER_PLACED — WooCommerce order status -> processing.",
	},
	{
		"event_code": "PAYMENT_FAILED_ADMIN",
		"audience": "Admin",
		"category": "Payments",
		"priority": "High",
		"deeplink_route": "/adminOrders",
		"deeplink_id_field": "order_id",
		"trigger_note": "Instant, once connected · admin copy of Payment Failed. Needs the WooCommerce webhook registered.",
		"live_status": "Needs Setup",
		"title": "Payment failed",
		"body": "Order #{{ order_id }} — payment could not be processed.",
		"description": "Admin copy of PAYMENT_FAILED.",
	},
	# --- Community (Discourse, api/community_webhook.py) — NOT YET
	# CONNECTED, and the trigger side is explicitly flagged UNVERIFIED (see
	# community_webhook.py's own docstring) pending a live test delivery.
	# Deep-links to /communityActivity (CommunityNotificationsScreen,
	# confirmed real, no-arg route).
	{
		"event_code": "COMMUNITY_REPLY",
		"audience": "User",
		"category": "Community",
		"priority": "Normal",
		"deeplink_route": "/communityActivity",
		"trigger_note": "Instant, once connected · Discourse notification webhook isn't registered yet, and the exact trigger values are unverified.",
		"live_status": "Unverified",
		"title": "New reply on your post",
		"body": "{{ topic_title }}",
		"description": "Discourse notification_type 'replied' (unverified for this instance — see community_webhook.py).",
	},
	{
		"event_code": "COMMUNITY_MENTION",
		"audience": "User",
		"category": "Community",
		"priority": "Normal",
		"deeplink_route": "/communityActivity",
		"trigger_note": "Instant, once connected · Discourse notification webhook isn't registered yet, and the exact trigger values are unverified.",
		"live_status": "Unverified",
		"title": "You were mentioned",
		"body": "{{ topic_title }}",
		"description": "Discourse notification_type 'mentioned' (unverified for this instance — see community_webhook.py).",
	},
	{
		"event_code": "COMMUNITY_LIKE",
		"audience": "User",
		"category": "Community",
		"priority": "Low",
		"deeplink_route": "/communityActivity",
		"trigger_note": "Instant, once connected · Discourse notification webhook isn't registered yet (the trigger values themselves are confirmed).",
		"live_status": "Needs Setup",
		"title": "Someone liked your post",
		"body": "{{ topic_title }}",
		"description": "Discourse notification_type 'liked'/'liked_consolidated' (5/15) — confirmed values, already used by the in-app My Activity list.",
	},
	{
		"event_code": "COMMUNITY_BADGE",
		"audience": "User",
		"category": "Community",
		"priority": "Normal",
		"deeplink_route": "/communityActivity",
		"trigger_note": "Instant, once connected · Discourse notification webhook isn't registered yet (the trigger value itself is confirmed).",
		"live_status": "Needs Setup",
		"title": "You earned a badge!",
		"body": "{{ badge_name }}",
		"description": "Discourse notification_type 'granted_badge' (12) — confirmed value, already used by the in-app My Activity list.",
	},
	# --- Communication Center (api/chatwoot_webhook.py) — nudges an admin
	# that a new inbound WhatsApp message arrived, reusing this same
	# Admin-audience/FCM pipeline rather than a second notification
	# mechanism (Decision 1). Uses the 'Support' admin category/preference
	# toggle (admin_support) — a WhatsApp reply is a support-desk concern
	# in the same sense a new ticket is, so it doesn't need its own
	# preference field. Deep-links to /dashboard as a safe interim target,
	# same reasoning as every other Admin-audience template above: no
	# dedicated admin deep-link route exists yet in the Flutter app.
	{
		"event_code": "NEW_WHATSAPP_MESSAGE",
		"audience": "Admin",
		"category": "Support",
		"priority": "Normal",
		"deeplink_route": "/adminWhatsApp",
		"trigger_note": "Instant · fires when a new inbound WhatsApp message arrives (Communication Center).",
		"live_status": "Working",
		"title": "New WhatsApp message",
		"body": "{{ contact_name }} sent a message.",
		"description": "Fired when api/chatwoot_webhook.py mirrors a new inbound WhatsApp message.",
	},
	# --- Course/batch lifecycle (notifications/triggers.py) —
	# NOTIFICATION_ENGINE_PLAN.md "What's still open" item 5. All 'Courses'
	# category, the same preference toggle that existed with no real
	# template behind it before this slice.
	{
		"event_code": "COURSE_ENROLLED",
		"audience": "User",
		"category": "Courses",
		"priority": "Low",
		"deeplink_route": "/viewCourse",
		"deeplink_id_field": "course",
		"trigger_note": "Instant · fires when a member enrolls in a course (their own copy of New Enrollment).",
		"live_status": "Working",
		"title": "You're enrolled!",
		"body": "Your course is ready whenever you are.",
		"description": "Fired alongside the existing admin-only NEW_ENROLLMENT, same LMS Enrollment.after_insert trigger — this copy goes to the member themselves.",
	},
	{
		"event_code": "USER_ADDED_TO_BATCH",
		"audience": "User",
		"category": "Courses",
		"priority": "Low",
		"deeplink_route": "/batch",
		"deeplink_id_field": "batch",
		"trigger_note": "Instant · fires when a member is added to a batch.",
		"live_status": "Working",
		"title": "You've been added to {{ batch_title }}",
		"body": "Check your batch for schedule and details.",
		"description": "Fired on LMS Batch Enrollment.after_insert.",
	},
	{
		"event_code": "LESSON_AVAILABLE",
		"audience": "User",
		"category": "Courses",
		"priority": "Low",
		"deeplink_route": "/viewLesson",
		"deeplink_id_field": "lesson_id",
		"trigger_note": "Instant · fires when a new lesson is published in an enrolled course.",
		"live_status": "Working",
		"title": "New lesson available: {{ lesson_title }}",
		"body": "Continue your course.",
		"description": "Fired on Course Lesson.after_insert, fanned out to that course's enrolled members (capped at 200, same convention as NEW_QUIZ_AVAILABLE).",
	},
	{
		"event_code": "BATCH_UPDATED",
		"audience": "User",
		"category": "Courses",
		"priority": "Normal",
		"deeplink_route": "/batch",
		"deeplink_id_field": "batch",
		"trigger_note": "Instant · fires when a batch's dates or publish status change.",
		"live_status": "Working",
		"title": "{{ batch_title }} has been updated",
		"body": "Check the batch for what changed.",
		"description": "Fired on LMS Batch.on_update when start_date/end_date/published actually changed, fanned to that batch's enrolled members only.",
	},
	# --- Bible Study suggestion (notifications/bible_study.py) —
	# NOTIFICATION_ENGINE_PLAN.md "What's still open" item 6 (half of it —
	# see that module's own docstring for why this reuses last_book rather
	# than the plan's original, never-built "recentBooks" concept).
	{
		"event_code": "BIBLE_STUDY_SUGGESTION",
		"audience": "User",
		"category": "Bible Study",
		"priority": "Low",
		"deeplink_route": "/continueReading",
		"deeplink_id_field": "deeplink_ref",
		"trigger_note": "Hourly scan · at most 2 per week, only sent to someone who already read today.",
		"live_status": "Working",
		"title": "Go deeper into {{ book }}",
		"body": "There's always more to discover in God's Word.",
		"description": "Hourly scan, at most 2/week per user, only for someone who read today — see bible_study.py.",
	},
	# --- Self-monitoring (notifications/selfcheck.py) —
	# NOTIFICATION_ENGINE_PLAN.md "What's still open" item 4.
	{
		"event_code": "SYSTEM_ALERT",
		"audience": "Admin",
		"category": "System",
		"priority": "Critical",
		"deeplink_route": "/adminNotifications",
		"trigger_note": "Daily check · fires if notification errors spike in the last 24 hours. Bypasses quiet hours and daily caps.",
		"live_status": "Working",
		"title": "Notification system needs attention",
		"body": "{{ count }} notification errors in the last {{ window_hours }} hours — check Error Log.",
		"description": "Fired when Error Log rows titled 'Notification ...' exceed a threshold in a rolling 24h window — see selfcheck.py.",
	},
	# --- Stock poll (notifications/stock.py) —
	# NOTIFICATION_ENGINE_PLAN.md "What's still open" item 3. Share the
	# 'Orders' admin category/preference toggle — same reasoning as
	# PAYMENT_FAILED_ADMIN sharing it: a stock problem is an order-desk
	# concern for an admin, not a separate thing to opt in/out of.
	{
		"event_code": "OUT_OF_STOCK",
		"audience": "Admin",
		"category": "Orders",
		"priority": "Normal",
		"deeplink_route": "/adminShopProducts",
		"trigger_note": "Daily poll, once connected · needs a WooCommerce API key (woocommerce_api_auth) added to site config — not confirmed set.",
		"live_status": "Needs Setup",
		"title": "{{ count }} product(s) out of stock",
		"body": "{{ products }}",
		"description": "Daily WooCommerce stock poll — see stock.py. Needs 'woocommerce_api_auth' in site_config.json before it can fire.",
	},
	{
		"event_code": "LOW_STOCK",
		"audience": "Admin",
		"category": "Orders",
		"priority": "Low",
		"deeplink_route": "/adminShopProducts",
		"trigger_note": "Daily poll, once connected · needs a WooCommerce API key (woocommerce_api_auth) added to site config — not confirmed set.",
		"live_status": "Needs Setup",
		"title": "{{ count }} product(s) running low",
		"body": "{{ products }}",
		"description": "Daily WooCommerce stock poll — see stock.py. Needs 'woocommerce_api_auth' in site_config.json before it can fire.",
	},
	# --- Community moderation (api/community_webhook.py's flag_created) —
	# NOTIFICATION_ENGINE_PLAN.md "What's still open" item 2.
	{
		"event_code": "COMMUNITY_REPORT",
		"audience": "Admin",
		"category": "Moderation",
		"priority": "High",
		"deeplink_route": "/adminCommunity",
		"trigger_note": "Instant, once connected · Discourse moderation-flag webhook isn't registered yet, payload shape unverified.",
		"live_status": "Unverified",
		"title": "A post was flagged for review",
		"body": "{{ topic_title }}",
		"description": "Fired by community_webhook.py's flag_created receiver — payload shape UNVERIFIED, see that function's own docstring.",
	},
	# --- Sunday School weekly rewards system (fully separate from the
	# app-wide rewards system's own notifications, if it ever gets any) —
	# see sunday_school/engine.py and notifications/sunday_school.py.
	{
		"event_code": "SS_WEEKLY_RESULTS",
		"audience": "User",
		"category": "Sunday School",
		"priority": "Normal",
		"deeplink_route": "/sundaySchoolLeaderboard",
		"deeplink_id_field": "week_start",
		"trigger_note": "Monday 00:00 weekly reset · sent to every student who scored at least one point that week.",
		"live_status": "Working",
		"title": "Your weekly results are in!",
		"body": "You finished #{{ rank }} this week with {{ points }} points. See the full leaderboard!",
		"description": "Sent by notifications/sunday_school.py::weekly_reset_scan to every student ranked that week.",
	},
	{
		"event_code": "SS_NEW_QUIZ_AVAILABLE",
		"audience": "User",
		"category": "Sunday School",
		"priority": "Normal",
		"deeplink_route": "/viewQuiz",
		"deeplink_id_field": "quiz",
		"trigger_note": "Fires when an admin assigns a Weekly Bible Quiz or Faith Leader Exam.",
		"live_status": "Working",
		"title": "This week's {{ quiz_type }} is ready!",
		"body": "Take it now and add your marks straight to your points.",
		"description": "Fired from notifications/triggers.py::on_sunday_school_quiz_assigned when a TOB Sunday School Quiz Assignment is created — takes the student straight into the app's existing quiz screen (ViewQuiz), same as any other quiz.",
	},
	{
		"event_code": "SS_NEW_MEMORY_VERSE",
		"audience": "User",
		"category": "Sunday School",
		"priority": "Normal",
		"deeplink_route": "/sundaySchoolVerse",
		"deeplink_id_field": "memory_verse",
		"trigger_note": "Fires when an admin publishes this week's memory verse.",
		"live_status": "Working",
		"title": "This week's memory verse: {{ reference }}",
		"body": "Learn it, recite it, and climb the Complete Verse leaderboard.",
		"description": "Fired from the admin Sunday School control panel when a TOB Sunday School Memory Verse is published.",
	},
	{
		"event_code": "SS_POINTS_EXPIRING_SOON",
		"audience": "User",
		"category": "Sunday School",
		"priority": "High",
		"deeplink_route": "/sundaySchoolDashboard",
		"trigger_note": "Daily scan · fires exactly on the configured warning day(s) before a student's unredeemed balance expires (TOB Sunday School Settings).",
		"live_status": "Working",
		"title": "{{ points }} points expire in {{ days_left }} day(s)!",
		"body": "Redeem them to your wallet now before you lose them.",
		"description": "Fired by sunday_school/engine.py::check_expiry_warnings, called from notifications/sunday_school.py::daily_scan. Only the Sunday School reward system expires — the app-wide one never does.",
	},
	{
		"event_code": "SS_POINTS_EXPIRED",
		"audience": "User",
		"category": "Sunday School",
		"priority": "Normal",
		"deeplink_route": "/sundaySchoolDashboard",
		"trigger_note": "Daily scan · fires the day a student's unredeemed balance actually expires.",
		"live_status": "Working",
		"title": "Your {{ points }} unredeemed points have expired",
		"body": "Redeem your points to your wallet next time before the deadline!",
		"description": "Fired by sunday_school/engine.py::expire_stale_points, called from notifications/sunday_school.py::daily_scan.",
	},
	{
		"event_code": "SELLER_APPLICATION_RECEIVED",
		"audience": "Admin",
		"category": "Orders",
		"priority": "Normal",
		"deeplink_route": "/adminSellerApplications",
		"trigger_note": "Fires when a Sunday School Student applies to become a seller on edenza.org.",
		"live_status": "Working",
		"title": "New seller application: {{ student_name }}",
		"body": "Review their request and set up a WCFM vendor account to approve them.",
		"description": "Fired from marketplace/engine.py::apply_to_sell.",
	},
	{
		"event_code": "SELLER_ACCOUNT_APPROVED",
		"audience": "User",
		"category": "Marketplace",
		"priority": "High",
		"deeplink_route": "/sellerDashboard",
		"trigger_note": "Fires when an admin provisions this student's seller account (WCFM vendor + WooCommerce key).",
		"live_status": "Working",
		"title": "You're approved to sell on edenza.org!",
		"body": "Start listing your own products — every new product needs a quick admin check before it goes live.",
		"description": "Fired from marketplace/engine.py::provision_seller.",
	},
	{
		"event_code": "SELLER_PRODUCT_SUBMITTED",
		"audience": "Admin",
		"category": "Orders",
		"priority": "Normal",
		"deeplink_route": "/adminPendingProducts",
		"trigger_note": "Fires whenever an active seller submits a new product (always starts Pending).",
		"live_status": "Working",
		"title": "Product awaiting approval: {{ product_name }}",
		"body": "{{ student_name }} just listed a new product — review it before it goes live.",
		"description": "Fired from marketplace/engine.py::create_product.",
	},
	{
		"event_code": "SELLER_PRODUCT_APPROVED",
		"audience": "User",
		"category": "Marketplace",
		"priority": "High",
		"deeplink_route": "/sellerProducts",
		"trigger_note": "Fires when an admin approves a submitted product.",
		"live_status": "Working",
		"title": "Your product is live: {{ product_title }}",
		"body": "It's now visible on edenza.org — nice work!",
		"description": "Fired from marketplace/engine.py::approve_product.",
	},
	{
		"event_code": "SELLER_PRODUCT_REJECTED",
		"audience": "User",
		"category": "Marketplace",
		"priority": "Normal",
		"deeplink_route": "/sellerProducts",
		"trigger_note": "Fires when an admin rejects a submitted product.",
		"live_status": "Working",
		"title": "Your product needs changes: {{ product_title }}",
		"body": "An admin asked for some changes before this can go live. Check the note and resubmit.",
		"description": "Fired from marketplace/engine.py::reject_product.",
	},
	{
		"event_code": "SELLER_NEW_ORDER",
		"audience": "User",
		"category": "Marketplace",
		"priority": "High",
		"deeplink_route": "/sellerOrders",
		"trigger_note": "Instant, once the WooCommerce order webhook is registered · otherwise caught within a few hours by the hourly poll_recent_orders safety net.",
		"live_status": "Needs Setup",
		"title": "You made a sale! 🎉",
		"body": "{{ quantity }}x {{ product_title }} — order #{{ order_number }}.",
		"description": "Fired from marketplace/engine.py::sync_order_line_items, called from both api/shop_webhook.py and the hourly poll_recent_orders job.",
	},
	{
		"event_code": "SELLER_LOW_STOCK",
		"audience": "User",
		"category": "Marketplace",
		"priority": "Normal",
		"deeplink_route": "/sellerProducts",
		"trigger_note": "Daily scan · fires once per dip below threshold (cooldown clears once stock recovers).",
		"live_status": "Working",
		"title": "Low stock: {{ product_title }}",
		"body": "Only {{ stock_quantity }} left — restock soon so you don't miss out on sales.",
		"description": "Fired from marketplace/engine.py::check_low_stock.",
	},
]


# Starter library for the Daily Encouragement pool (notifications/
# encouragement.py) — deliberately gentle per this whole engine's existing
# tone rules (never implies failure, never claims to know someone's
# situation, always an invitation not a demand). Meant as a real starting
# set an admin can immediately use, then grow from the Encouragement
# Messages admin screen — adding a new one needs no code deploy.
_ENCOURAGEMENT_MESSAGES = [
	{
		"title": "You don't have to carry this alone",
		"body": "Jesus is right here with you. Whatever today has been, you don't have to face it by yourself.",
		"deeplink_route": "/todayVerse",
		"tag": "Comfort",
	},
	{
		"title": "Three words are enough to start",
		"body": "Just say, \"Jesus, help me.\" He's already listening.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Pray",
	},
	{
		"title": "Don't know how to pray?",
		"body": "There's no right way to begin. Tap here and we'll help you find the words.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Pray",
	},
	{
		"title": "Someone is listening",
		"body": "It might feel like no one has time for you today. Jesus does.",
		"deeplink_route": "/todayVerse",
		"tag": "Reassurance",
	},
	{
		"title": "He's ready to speak",
		"body": "Open today's verse — He has something for you in it.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Read",
	},
	{
		"title": "You're not forgotten",
		"body": "Whatever today has been, you're seen, you're loved, and you're not alone.",
		"deeplink_route": "/todayVerse",
		"tag": "Comfort",
	},
	{
		"title": "A quiet place for you",
		"body": "Step away for a moment. Bring whatever's on your heart to Him.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Pray",
	},
	{
		"title": "Still worth showing up",
		"body": "You don't need the right words or a good day to open His Word.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Read",
	},
	{
		"title": "Hope for today",
		"body": "Whatever's heavy right now, it doesn't get the final word.",
		"deeplink_route": "/todayVerse",
		"tag": "Hope",
	},
	{
		"title": "He already knows",
		"body": "You don't have to explain everything. He already understands.",
		"deeplink_route": "/todayVerse",
		"tag": "Reassurance",
	},
		{
		"title": "He knows your name",
		"body": "Not a number, not a stranger. He knows exactly who you are and what you're carrying.",
		"deeplink_route": "/todayVerse",
		"tag": "Reassurance",
	},
	{
		"title": "This moment counts",
		"body": "You don't need a perfect setting or a clear head. Right now is enough.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Pray",
	},
	{
		"title": "A word for right now",
		"body": "Today's verse was chosen for a moment just like this one.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Read",
	},
	{
		"title": "Tired is okay",
		"body": "You don't have to have it together to come to Him. Come as you are.",
		"deeplink_route": "/todayVerse",
		"tag": "Comfort",
	},
	{
		"title": "Small prayers still reach Him",
		"body": "It doesn't have to be long or eloquent. He hears the small ones too.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Pray",
	},
	{
		"title": "Not the end of the story",
		"body": "Whatever's unresolved today, it's still being written.",
		"deeplink_route": "/todayVerse",
		"tag": "Hope",
	},
	{
		"title": "Rest for a minute",
		"body": "You don't have to solve everything before you talk to Him. Just rest here for a moment.",
		"deeplink_route": "/todayVerse",
		"tag": "Comfort",
	},
	{
		"title": "Worth the pause",
		"body": "A minute with His Word can shift the rest of your day.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Read",
	},
	{
		"title": "He's not keeping score",
		"body": "However long it's been, He's not waiting to bring it up. He's just glad you're here.",
		"deeplink_route": "/todayVerse",
		"tag": "Reassurance",
	},
	{
		"title": "You're allowed to ask",
		"body": "For peace, for strength, for anything. He wants to hear it from you.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Pray",
	},
	{
		"title": "Even now, there's hope",
		"body": "Nothing you're facing today is bigger than what He can carry with you.",
		"deeplink_route": "/todayVerse",
		"tag": "Hope",
	},
	{
		"title": "A light in the noise",
		"body": "In everything pulling for your attention today, His Word is worth the pause.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Read",
	},
		{
		"title": "Jesus already knows",
		"body": "You don't have to explain the whole day. Jesus already understands it.",
		"deeplink_route": "/todayVerse",
		"tag": "Reassurance",
	},
	{
		"title": "Talk to Jesus about it",
		"body": "Whatever's on your mind right now, He wants to hear it from you.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Pray",
	},
	{
		"title": "Jesus isn't rushing you",
		"body": "Take your time. He's not going anywhere.",
		"deeplink_route": "/todayVerse",
		"tag": "Comfort",
	},
	{
		"title": "Jesus has something to say today",
		"body": "Open today's verse and see what He's speaking into your day.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Read",
	},
	{
		"title": "Jesus is still with you",
		"body": "However today has gone, He hasn't stepped away.",
		"deeplink_route": "/todayVerse",
		"tag": "Reassurance",
	},
	{
		"title": "Bring it to Jesus",
		"body": "You don't have to carry it alone. Bring it to Him, just as it is.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Pray",
	},
	{
		"title": "Jesus sees what today cost you",
		"body": "Even the parts no one else noticed. Come rest for a minute.",
		"deeplink_route": "/todayVerse",
		"tag": "Comfort",
	},
	{
		"title": "A minute with Jesus",
		"body": "That's all it takes to start. He'll meet you there.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Pray",
	},
	{
		"title": "Jesus is not keeping His distance",
		"body": "Whatever's between you and today, He's closer than you think.",
		"deeplink_route": "/todayVerse",
		"tag": "Reassurance",
	},
	{
		"title": "Jesus goes first",
		"body": "Before you find the words, He's already listening.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Pray",
	},
	{
		"title": "What Jesus is saying today",
		"body": "Today's verse carries something for exactly where you are.",
		"deeplink_route": "/todayVerse",
		"tag": "Invitation to Read",
	},
	{
		"title": "Jesus doesn't need a good day from you",
		"body": "Come as you are, hard day and all.",
		"deeplink_route": "/todayVerse",
		"tag": "Comfort",
	},
]


def seed_encouragement_messages():
	"""Create-only, matching `seed_notification_templates`' own reasoning —
	an admin's later edits (or a message they've disabled) must never be
	reset by a future migrate. Matched by `title` alone (this doctype has no
	natural unique key), so re-running never creates duplicates of the
	starter set."""
	for entry in _ENCOURAGEMENT_MESSAGES:
		if frappe.db.exists("TOB Encouragement Message", {"title": entry["title"]}):
			continue
		try:
			frappe.get_doc({"doctype": "TOB Encouragement Message", "enabled": 1, **entry}).insert(
				ignore_permissions=True
			)
			frappe.db.commit()
		except frappe.ValidationError:
			frappe.db.rollback()


# Starter library for the WhatsApp inbox's Quick Reply picker
# (communication/whatsapp.py, TOB WhatsApp Quick Reply) — a real starting
# set an admin can use immediately, then grow themselves from the
# conversation screen's quick-reply picker.
_WHATSAPP_QUICK_REPLIES = [
	{
		"title": "Welcome",
		"body": "Welcome to Truth of Bible! How can we help you today?",
	},
	{
		"title": "Prayer request received",
		"body": "Thank you for sharing this with us. We're praying for you.",
	},
	{
		"title": "We'll get back to you",
		"body": "Thank you for reaching out — we'll get back to you shortly.",
	},
	{
		"title": "Closing",
		"body": "God bless you! Feel free to message us anytime.",
	},
]


def seed_whatsapp_quick_replies():
	"""Create-only, matched by `title` (this doctype has no natural unique
	key) — same reasoning as `seed_encouragement_messages`: an admin's own
	edits or deletions must never be reset by a future migrate."""
	for entry in _WHATSAPP_QUICK_REPLIES:
		if frappe.db.exists("TOB WhatsApp Quick Reply", {"title": entry["title"]}):
			continue
		try:
			frappe.get_doc({"doctype": "TOB WhatsApp Quick Reply", "enabled": 1, **entry}).insert(
				ignore_permissions=True
			)
			frappe.db.commit()
		except frappe.ValidationError:
			frappe.db.rollback()


_OTP_EMAIL_TEMPLATE_NAME = "OTP Verification Email"
_OTP_EMAIL_SUBJECT = "Your Truth of Bible verification code"
_OTP_EMAIL_BODY = """
<div style="background:#f4f5f7;padding:32px 16px;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" style="max-width:480px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e7eb;">
    <tr>
      <td style="background:#f2a128;padding:24px 32px;text-align:center;">
        <span style="font-size:20px;font-weight:700;color:#ffffff;">Truth of Bible</span>
      </td>
    </tr>
    <tr>
      <td style="padding:32px;">
        <p style="margin:0 0 16px;font-size:15px;color:#1f2937;">Hello,</p>
        <p style="margin:0 0 24px;font-size:15px;color:#1f2937;line-height:1.5;">
          Use the verification code below to continue in the Truth of Bible app.
        </p>
        <div style="text-align:center;margin:0 0 24px;">
          <span style="display:inline-block;padding:14px 28px;background:#fff7e6;border:1px solid #f2a128;border-radius:10px;font-size:32px;font-weight:700;letter-spacing:10px;color:#92400e;">{{ otp }}</span>
        </div>
        <p style="margin:0 0 24px;font-size:14px;color:#4b5563;text-align:center;">
          This code expires in <strong>{{ minutes }} minutes</strong>.
        </p>
        <p style="margin:0 0 8px;font-size:13px;color:#6b7280;line-height:1.5;">
          For your security, never share this code with anyone — not even someone claiming to be from Truth of Bible. Our team will never ask you for it.
        </p>
        <p style="margin:0;font-size:13px;color:#6b7280;line-height:1.5;">
          If you didn't request this code, you can safely ignore this email.
        </p>
      </td>
    </tr>
    <tr>
      <td style="padding:20px 32px;background:#f9fafb;text-align:center;border-top:1px solid #e5e7eb;">
        <p style="margin:0;font-size:12px;color:#9ca3af;">Truth of Bible &middot; truthofbible.org</p>
      </td>
    </tr>
  </table>
</div>
"""


def seed_otp_email_template():
	"""Create-only, same as the other seed_* functions here — an admin's own
	edits to this template from the desk are never overwritten on a later
	migrate. `api/app_auth.py`'s `_send()` renders this with the OTP and
	falls back to a plain-text message if this record is ever deleted."""
	if frappe.db.exists("Email Template", _OTP_EMAIL_TEMPLATE_NAME):
		return
	frappe.get_doc(
		{
			"doctype": "Email Template",
			"name": _OTP_EMAIL_TEMPLATE_NAME,
			"subject": _OTP_EMAIL_SUBJECT,
			"response": _OTP_EMAIL_BODY,
			"use_html": 0,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()


_NOTIFICATION_EMAIL_TEMPLATE_NAME = "TOB Notification Email"
_NOTIFICATION_EMAIL_SUBJECT = "{{ title }}"
_NOTIFICATION_EMAIL_BODY = """
<div style="background:#f4f5f7;padding:32px 16px;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" style="max-width:480px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e7eb;">
    <tr>
      <td style="background:#f2a128;padding:24px 32px;text-align:center;">
        <span style="font-size:20px;font-weight:700;color:#ffffff;">Truth of Bible</span>
      </td>
    </tr>
    <tr>
      <td style="padding:32px;">
        <h1 style="margin:0 0 16px;font-size:19px;font-weight:700;color:#1f2937;">{{ title }}</h1>
        <p style="margin:0 0 24px;font-size:15px;color:#374151;line-height:1.6;white-space:pre-line;">{{ body }}</p>
        {% if cta_url %}
        <div style="text-align:center;margin:0 0 8px;">
          <a href="{{ cta_url }}" style="display:inline-block;padding:12px 28px;background:#f2a128;color:#ffffff;border-radius:8px;font-size:14px;font-weight:700;text-decoration:none;">{{ cta_label or "Open in App" }}</a>
        </div>
        {% endif %}
      </td>
    </tr>
    <tr>
      <td style="padding:20px 32px;background:#f9fafb;text-align:center;border-top:1px solid #e5e7eb;">
        <p style="margin:0;font-size:12px;color:#9ca3af;">Truth of Bible &middot; truthofbible.org</p>
      </td>
    </tr>
  </table>
</div>
"""


def seed_notification_email_template():
	"""Create-only, same as every other seed_* function here — an admin's own
	edits to this template from the desk are never overwritten on a later
	migrate. `notifications/email_delivery.py` renders this shell around
	whichever event's title/body just fired, so this is the ONE template that
	needs editing to change the look of every event email, rather than one
	template per event. Falls back to a plain-text email if this record is
	ever deleted."""
	if frappe.db.exists("Email Template", _NOTIFICATION_EMAIL_TEMPLATE_NAME):
		return
	frappe.get_doc(
		{
			"doctype": "Email Template",
			"name": _NOTIFICATION_EMAIL_TEMPLATE_NAME,
			"subject": _NOTIFICATION_EMAIL_SUBJECT,
			"response": _NOTIFICATION_EMAIL_BODY,
			"use_html": 0,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()


def seed_notification_templates():
	for entry in _NOTIFICATION_TEMPLATES:
		if frappe.db.exists("TOB Notification Template", entry["event_code"]):
			continue
		try:
			frappe.get_doc({"doctype": "TOB Notification Template", "enabled": 1, **entry}).insert(
				ignore_permissions=True
			)
			frappe.db.commit()
		except frappe.ValidationError:
			frappe.db.rollback()


def backfill_notification_template_metadata():
	"""`seed_notification_templates` above is create-only (by design, so an
	admin's own edits are never clobbered on the next migrate) — it never
	revisits a template that already exists, so a brand new field added to
	`_NOTIFICATION_TEMPLATES` (like `trigger_note`/`live_status` below) would
	otherwise never reach a row seeded before that field existed.

	Deliberately fills a field ONLY when it's currently blank — never
	overwrites a value that's already there, whether it got there from an
	earlier run of this same function or from an admin editing it directly
	in the app's Notification Templates screen (both `trigger_note` and
	`live_status` are admin-editable there: `live_status` in particular is
	meant to be flipped from "Needs Setup" to "Working" once an admin
	finishes a step like registering the WooCommerce/Discourse webhook —
	this function must never fight that by resetting it back). Safe to
	leave wired into after_install/after_migrate indefinitely on that basis.

	(The previous version of this function, `sync_notification_template_
	deeplinks`, force-corrected `deeplink_route`/`deeplink_id_field` for
	BIBLE_READING_CONTINUE/BIBLE_STUDY_SUGGESTION from the old `/todayVerse`
	placeholder to `/continueReading` — a one-time fix already applied to
	this site. It was removed rather than kept running because those two
	fields are now ALSO admin-editable in the app, and force-syncing them
	forever would have silently undone any admin's own edit on every
	future migrate.)
	"""
	for entry in _NOTIFICATION_TEMPLATES:
		fields_to_fill = {k: entry[k] for k in ("trigger_note", "live_status", "body") if entry.get(k)}
		if not fields_to_fill:
			continue
		current = frappe.db.get_value(
			"TOB Notification Template", entry["event_code"], list(fields_to_fill.keys()), as_dict=True
		)
		if not current:
			continue
		blank_only = {k: v for k, v in fields_to_fill.items() if not current.get(k)}
		if not blank_only:
			continue
		frappe.db.set_value("TOB Notification Template", entry["event_code"], blank_only)
	frappe.db.commit()


def ensure_social_worker_role():
	"""The outreach VPS worker's API user gets only this role — enough for
	social/blessing_automation.py's whitelisted methods, never System Manager.
	No desk access: the worker only calls the API."""
	if frappe.db.exists("Role", "TOB Social Worker"):
		return
	frappe.get_doc({"doctype": "Role", "role_name": "TOB Social Worker", "desk_access": 0}).insert(
		ignore_permissions=True
	)
	frappe.db.commit()


def ensure_sunday_school_role():
	"""A plain end-user role (no desk access, same shape as "LMS Student")
	an admin toggles on/off per user from the existing Manage User ->
	Profile -> Roles/Permissions checklist (generic Frappe Role/Has Role
	REST — see users_repository_impl.dart's assignRoles/getAllRoles).
	Having this role is what unlocks the "Student Dashboard" drawer entry
	client-side (main_drawer.dart's hasStudentAccess check) — no other
	backend permission is granted by this role; it's purely a client-side
	feature flag, not a data-access gate."""
	if frappe.db.exists("Role", "Sunday School Student"):
		return
	frappe.get_doc({"doctype": "Role", "role_name": "Sunday School Student", "desk_access": 0}).insert(
		ignore_permissions=True
	)
	frappe.db.commit()


def seed_social_content():
	"""Starter drafts for TOB Social Content (app features from the app's own
	navigation map, salvation prayers with exact KJV references), from
	social/seed_content.json. Added once per (type, title), never approved and
	never overwritten — approval is always a person checking every word."""
	import json
	from pathlib import Path

	path = Path(__file__).parent / "social" / "seed_content.json"
	for entry in json.loads(path.read_text(encoding="utf-8")):
		if frappe.db.exists("TOB Social Content", {"content_type": entry["content_type"], "title": entry["title"]}):
			continue
		try:
			frappe.get_doc({
				"doctype": "TOB Social Content",
				"source": "Import",
				**{k: entry.get(k) or "" for k in ("content_type", "title", "image_text", "image_footer", "caption",
					"how_to_find")},
			}).insert(ignore_permissions=True)
			frappe.db.commit()
		except frappe.ValidationError:
			frappe.db.rollback()


# Starter Bible Reading Plans — one per age tier plus one All Ages plan, each
# 7 days, so the Reading Plans hub has real, immediately usable content on a
# fresh install rather than an empty screen. book_id follows the app's fixed
# 1-66 canonical order (Genesis=1 ... Revelation=66, see
# bible_books_screen.dart on the Flutter side).
_READING_PLANS = [
	{
		"title": "Bible Stories for Little Hearts",
		"age_group": "Kids",
		"description": "Seven favorite Bible stories, told simply — perfect for reading together before bed.",
		"duration_days": 7,
		"difficulty": "Easy",
		"icon": "child_care",
		"accent_color": "Rose",
		"status": "Published",
		"sort_order": 1,
	},
	{
		"title": "Faith That Fits Your Life",
		"age_group": "Teens",
		"description": "A week of scripture on identity, love, peace, and handling the pressure of everyday life.",
		"duration_days": 7,
		"difficulty": "Easy",
		"icon": "school",
		"accent_color": "Blue",
		"status": "Published",
		"sort_order": 1,
	},
	{
		"title": "Foundations for the Real World",
		"age_group": "Young Adults",
		"description": "Seven passages on wisdom, hope, identity in Christ, and pressing on into what's next.",
		"duration_days": 7,
		"difficulty": "Moderate",
		"icon": "self_improvement",
		"accent_color": "Purple",
		"status": "Published",
		"sort_order": 1,
	},
	{
		"title": "Walking in Wisdom",
		"age_group": "Adults",
		"description": "A week in the wisdom books and the words of Jesus — for the steady, daily walk of faith.",
		"duration_days": 7,
		"difficulty": "Moderate",
		"icon": "menu_book",
		"accent_color": "Amber",
		"status": "Published",
		"sort_order": 1,
	},
	{
		"title": "A Faithful Legacy",
		"age_group": "Seniors",
		"description": "Seven passages of comfort, strength, and hope — for a lifetime of faith and the road ahead.",
		"duration_days": 7,
		"difficulty": "Easy",
		"icon": "favorite",
		"accent_color": "Teal",
		"status": "Published",
		"sort_order": 1,
	},
	{
		"title": "The Story of Jesus",
		"age_group": "All Ages",
		"description": "The life of Jesus in seven readings — from Bethlehem to the empty tomb. Read it together as a family.",
		"duration_days": 7,
		"difficulty": "Easy",
		"icon": "auto_stories",
		"accent_color": "Green",
		"status": "Published",
		"sort_order": 1,
	},
]

_READING_PLAN_DAYS = {
	"Bible Stories for Little Hearts": [
		{"day_number": 1, "title": "Creation Begins", "book_id": 1, "chapter_start": 1, "chapter_end": 1,
			"reference_label": "Genesis 1",
			"note": "In the beginning, God made everything — the sky, the sea, the animals, and you!"},
		{"day_number": 2, "title": "Noah's Big Boat", "book_id": 1, "chapter_start": 6, "chapter_end": 9,
			"reference_label": "Genesis 6-9",
			"note": "God asked Noah to build a huge boat, and Noah trusted Him — even when it didn't make sense yet."},
		{"day_number": 3, "title": "Baby Moses in the Basket", "book_id": 2, "chapter_start": 2, "chapter_end": 2,
			"reference_label": "Exodus 2",
			"note": "God watched over baby Moses and kept him safe, even in a scary time."},
		{"day_number": 4, "title": "David and the Giant", "book_id": 9, "chapter_start": 17, "chapter_end": 17,
			"reference_label": "1 Samuel 17",
			"note": "David was small, but he was brave because he trusted God to help him."},
		{"day_number": 5, "title": "Daniel and the Lions", "book_id": 27, "chapter_start": 6, "chapter_end": 6,
			"reference_label": "Daniel 6",
			"note": "Daniel kept praying even when it was dangerous, and God kept him safe."},
		{"day_number": 6, "title": "Jesus is Born", "book_id": 42, "chapter_start": 2, "chapter_end": 2,
			"reference_label": "Luke 2",
			"note": "On a starry night in Bethlehem, God's own Son came into the world as a baby."},
		{"day_number": 7, "title": "Jesus Loves the Children", "book_id": 41, "chapter_start": 10, "chapter_end": 10,
			"reference_label": "Mark 10",
			"note": "Jesus welcomed the children who came to Him — just like He welcomes you."},
	],
	"Faith That Fits Your Life": [
		{"day_number": 1, "title": "You Are Fearfully Made", "book_id": 19, "chapter_start": 139, "chapter_end": 139,
			"reference_label": "Psalm 139",
			"note": "Before anyone else had an opinion about you, God already knew and loved who you are."},
		{"day_number": 2, "title": "Trust Beyond Yourself", "book_id": 20, "chapter_start": 3, "chapter_end": 3,
			"reference_label": "Proverbs 3",
			"note": "You don't have to have it all figured out — trust doesn't mean having every answer."},
		{"day_number": 3, "title": "What Really Matters", "book_id": 40, "chapter_start": 5, "chapter_end": 5,
			"reference_label": "Matthew 5",
			"note": "Jesus flips the script on what it means to be \"blessed.\" It's not what you'd expect."},
		{"day_number": 4, "title": "Don't Copy the World", "book_id": 45, "chapter_start": 12, "chapter_end": 12,
			"reference_label": "Romans 12",
			"note": "You don't have to think, act, or scroll like everyone else. Let your mind be renewed."},
		{"day_number": 5, "title": "Love, Defined", "book_id": 46, "chapter_start": 13, "chapter_end": 13,
			"reference_label": "1 Corinthians 13",
			"note": "This is what real love actually looks like — not just the feeling, the practice."},
		{"day_number": 6, "title": "Don't Be Anxious", "book_id": 50, "chapter_start": 4, "chapter_end": 4,
			"reference_label": "Philippians 4",
			"note": "Whatever's stressing you out right now, you're invited to bring it to God directly."},
		{"day_number": 7, "title": "Trials Have a Purpose", "book_id": 59, "chapter_start": 1, "chapter_end": 1,
			"reference_label": "James 1",
			"note": "Hard seasons aren't wasted — they're building something in you."},
	],
	"Foundations for the Real World": [
		{"day_number": 1, "title": "Where Wisdom Begins", "book_id": 20, "chapter_start": 1, "chapter_end": 1,
			"reference_label": "Proverbs 1",
			"note": "Real wisdom starts with respect for God, not with having life figured out."},
		{"day_number": 2, "title": "Plans to Give You Hope", "book_id": 24, "chapter_start": 29, "chapter_end": 29,
			"reference_label": "Jeremiah 29",
			"note": "Even in an uncertain season, God says His plans for you are good."},
		{"day_number": 3, "title": "No Condemnation", "book_id": 45, "chapter_start": 8, "chapter_end": 8,
			"reference_label": "Romans 8",
			"note": "Whatever you carry from your past, it doesn't define how God sees you now."},
		{"day_number": 4, "title": "The Fruit That Lasts", "book_id": 48, "chapter_start": 5, "chapter_end": 5,
			"reference_label": "Galatians 5",
			"note": "Love, joy, peace, patience — this is what a Spirit-led life actually grows."},
		{"day_number": 5, "title": "Grow Up Into Him", "book_id": 49, "chapter_start": 4, "chapter_end": 4,
			"reference_label": "Ephesians 4",
			"note": "Maturity isn't about having it all together — it's about growing, together."},
		{"day_number": 6, "title": "Put On the New Self", "book_id": 51, "chapter_start": 3, "chapter_end": 3,
			"reference_label": "Colossians 3",
			"note": "Whoever you were before doesn't get the final say in who you're becoming."},
		{"day_number": 7, "title": "Press On", "book_id": 50, "chapter_start": 3, "chapter_end": 3,
			"reference_label": "Philippians 3",
			"note": "You don't have to have arrived. Keep pressing toward what's ahead."},
	],
	"Walking in Wisdom": [
		{"day_number": 1, "title": "Planted by the Water", "book_id": 19, "chapter_start": 1, "chapter_end": 1,
			"reference_label": "Psalm 1",
			"note": "A life rooted in God's word stays steady, whatever season comes."},
		{"day_number": 2, "title": "A Life Well Lived", "book_id": 20, "chapter_start": 31, "chapter_end": 31,
			"reference_label": "Proverbs 31",
			"note": "A picture of character, diligence, and strength worth reflecting on."},
		{"day_number": 3, "title": "A Time for Everything", "book_id": 21, "chapter_start": 3, "chapter_end": 3,
			"reference_label": "Ecclesiastes 3",
			"note": "Every season of life — the hard ones too — has its own purpose and place."},
		{"day_number": 4, "title": "Strength Renewed", "book_id": 23, "chapter_start": 40, "chapter_end": 40,
			"reference_label": "Isaiah 40",
			"note": "When you're weary, this is a promise worth returning to."},
		{"day_number": 5, "title": "What Matters Most", "book_id": 40, "chapter_start": 6, "chapter_end": 6,
			"reference_label": "Matthew 6",
			"note": "Jesus teaches on prayer, priorities, and where to put your trust."},
		{"day_number": 6, "title": "Wisdom From Above", "book_id": 59, "chapter_start": 3, "chapter_end": 3,
			"reference_label": "James 3",
			"note": "There's a kind of wisdom that's pure, peaceable, and worth asking God for."},
		{"day_number": 7, "title": "Set Your Mind Above", "book_id": 51, "chapter_start": 3, "chapter_end": 3,
			"reference_label": "Colossians 3",
			"note": "A short passage worth carrying into the rest of your week."},
	],
	"A Faithful Legacy": [
		{"day_number": 1, "title": "Do Not Forsake Me", "book_id": 19, "chapter_start": 71, "chapter_end": 71,
			"reference_label": "Psalm 71",
			"note": "A prayer of someone older in years, still trusting God as they always have."},
		{"day_number": 2, "title": "Teach Us to Number Our Days", "book_id": 19, "chapter_start": 90, "chapter_end": 90,
			"reference_label": "Psalm 90",
			"note": "A reflection on time, and on God's faithfulness across every one of our years."},
		{"day_number": 3, "title": "I Will Sustain You", "book_id": 23, "chapter_start": 46, "chapter_end": 46,
			"reference_label": "Isaiah 46",
			"note": "\"Even to your old age I am He... I will carry you.\" A promise worth holding onto."},
		{"day_number": 4, "title": "Be Strong and Courageous", "book_id": 6, "chapter_start": 1, "chapter_end": 1,
			"reference_label": "Joshua 1",
			"note": "God's charge to Joshua as he took on a new season — courage rooted in God's presence."},
		{"day_number": 5, "title": "The Lord is My Shepherd", "book_id": 19, "chapter_start": 23, "chapter_end": 23,
			"reference_label": "Psalm 23",
			"note": "A familiar, well-loved chapter — worth reading slowly today."},
		{"day_number": 6, "title": "I Have Finished the Race", "book_id": 55, "chapter_start": 4, "chapter_end": 4,
			"reference_label": "2 Timothy 4",
			"note": "Paul looks back on a life of faith with peace, not regret."},
		{"day_number": 7, "title": "He Will Wipe Every Tear", "book_id": 66, "chapter_start": 21, "chapter_end": 21,
			"reference_label": "Revelation 21",
			"note": "A picture of the hope that awaits — no more tears, no more pain."},
	],
	"The Story of Jesus": [
		{"day_number": 1, "title": "The Baby in Bethlehem", "book_id": 42, "chapter_start": 2, "chapter_end": 2,
			"reference_label": "Luke 2",
			"note": "The story of the night Jesus was born."},
		{"day_number": 2, "title": "Jesus is Baptized", "book_id": 40, "chapter_start": 3, "chapter_end": 3,
			"reference_label": "Matthew 3",
			"note": "The moment Jesus began His public ministry."},
		{"day_number": 3, "title": "Jesus Teaches on the Mountain", "book_id": 40, "chapter_start": 5, "chapter_end": 5,
			"reference_label": "Matthew 5",
			"note": "Some of Jesus' most famous teaching, given on a hillside to His followers."},
		{"day_number": 4, "title": "Jesus Calms the Storm", "book_id": 41, "chapter_start": 4, "chapter_end": 4,
			"reference_label": "Mark 4",
			"note": "A reminder that Jesus has power over even the scariest storms."},
		{"day_number": 5, "title": "The Last Supper", "book_id": 42, "chapter_start": 22, "chapter_end": 22,
			"reference_label": "Luke 22",
			"note": "Jesus' final meal with His disciples, the night before He was crucified."},
		{"day_number": 6, "title": "Jesus on the Cross", "book_id": 43, "chapter_start": 19, "chapter_end": 19,
			"reference_label": "John 19",
			"note": "The hardest day of the story — but not the end of it."},
		{"day_number": 7, "title": "He is Risen!", "book_id": 43, "chapter_start": 20, "chapter_end": 20,
			"reference_label": "John 20",
			"note": "The empty tomb, and the beginning of everything after."},
	],
}


def seed_reading_plans():
	"""Create-only by `title` (no natural unique key), same reasoning as
	`seed_encouragement_messages`/`seed_whatsapp_quick_replies` — an admin's
	own edits to a plan or its days must never be reset by a future migrate.
	A plan's days are only ever seeded at the moment the plan itself is first
	created; adding a day to a plan an admin has already customized needs a
	manual add through the app/Desk, not a code change here."""
	for entry in _READING_PLANS:
		if frappe.db.exists("TOB Reading Plan", {"title": entry["title"]}):
			continue
		try:
			plan_doc = frappe.get_doc({"doctype": "TOB Reading Plan", **entry})
			plan_doc.insert(ignore_permissions=True)
			frappe.db.commit()
		except frappe.ValidationError:
			frappe.db.rollback()
			continue

		for day in _READING_PLAN_DAYS.get(entry["title"], []):
			try:
				frappe.get_doc({"doctype": "TOB Reading Plan Day", "plan": plan_doc.name, **day}).insert(
					ignore_permissions=True
				)
				frappe.db.commit()
			except frappe.ValidationError:
				frappe.db.rollback()


_BIBLE_PLACES = [
	# --- Israel ---
	{"title": "Jerusalem", "category": "City", "region": "Israel", "latitude": 31.7683, "longitude": 35.2137,
		"primary_verse_ref": "Psalm 122:6",
		"description": "The City of David, site of Solomon's Temple, and where Jesus was crucified and rose again.",
		"facts": "Called the City of David\nSite of Solomon's Temple\nWhere Jesus was crucified, buried, and rose again\nWhere the Holy Spirit came at Pentecost",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/91/Temple_Mount_%28Aerial_view%2C_2007%29_07.jpg/330px-Temple_Mount_%28Aerial_view%2C_2007%29_07.jpg",
		"status": "Published", "sort_order": 1},
	{"title": "Bethlehem", "category": "City", "region": "Israel", "latitude": 31.7054, "longitude": 35.2024,
		"primary_verse_ref": "Luke 2:4-7",
		"description": "The small town where Jesus was born, fulfilling centuries-old prophecy.",
		"facts": "Also called the City of David (David's hometown)\nForetold by the prophet Micah 700 years earlier\nHome to the Church of the Nativity",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/61/Church_of_the_Nativity_%287703592746%29.jpg/330px-Church_of_the_Nativity_%287703592746%29.jpg",
		"status": "Published", "sort_order": 2},
	{"title": "Nazareth", "category": "City", "region": "Israel", "latitude": 32.6996, "longitude": 35.3035,
		"primary_verse_ref": "Luke 1:26-31",
		"description": "The town where Jesus grew up, and where the angel Gabriel appeared to Mary.",
		"facts": "Jesus lived here from early childhood until He began His ministry\nA small, unremarkable village in Jesus' day\nSite of the Annunciation",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/3e/Nazareth_Panorama_Dafna_Tal_IMOT_%2814532097313%29.jpg/330px-Nazareth_Panorama_Dafna_Tal_IMOT_%2814532097313%29.jpg",
		"status": "Published", "sort_order": 3},
	{"title": "Capernaum", "category": "City", "region": "Israel", "latitude": 32.8807, "longitude": 35.5753,
		"primary_verse_ref": "Matthew 4:13",
		"description": "A fishing town on the Sea of Galilee that became Jesus' ministry headquarters.",
		"facts": "Jesus called it 'his own city'\nHome to Peter, Andrew, James and John\nSite of a synagogue where Jesus taught and healed",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/fb/Sites_of_Christianity_in_the_Galillee_-_Ruins_of_the_ancient_Great_Synagogue_at_Capernaum_%28or_Kfar_Nahum%29_on_the_shore_of_the_Lake_of_Galilee%2C_Northern_Israel.jpg/330px-thumbnail.jpg",
		"status": "Published", "sort_order": 4},
	{"title": "Sea of Galilee", "category": "Sea", "region": "Israel", "latitude": 32.8000, "longitude": 35.5833,
		"primary_verse_ref": "Mark 4:39",
		"description": "The freshwater lake where Jesus called His first disciples, walked on water, and calmed the storm.",
		"facts": "Also called the Sea of Tiberias or Lake Kinneret\nSurrounded by many of Jesus' ministry towns\nSite of the miraculous catch of fish",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/f7/Kinneret_cropped.jpg/330px-Kinneret_cropped.jpg",
		"status": "Published", "sort_order": 5},
	{"title": "Jordan River", "category": "River", "region": "Israel", "latitude": 31.8467, "longitude": 35.5494,
		"primary_verse_ref": "Matthew 3:13-17",
		"description": "The river where John the Baptist baptized Jesus.",
		"facts": "Israel crossed it to enter the Promised Land\nNaaman was healed after washing in it\nStill a baptism site for pilgrims today",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/78/20100923_mer_morte13.JPG/330px-20100923_mer_morte13.JPG",
		"status": "Published", "sort_order": 6},
	{"title": "Jericho", "category": "City", "region": "Israel", "latitude": 31.8667, "longitude": 35.4500,
		"primary_verse_ref": "Joshua 6:20",
		"description": "One of the oldest continuously inhabited cities in the world, whose walls fell by faith.",
		"facts": "Called 'the city of palms'\nIts walls fell after Israel marched around it for seven days\nWhere Jesus healed blind Bartimaeus and met Zacchaeus",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/f4/Tell_es-sultan.jpg/330px-Tell_es-sultan.jpg",
		"status": "Published", "sort_order": 7},
	{"title": "Mount of Olives", "category": "Mountain", "region": "Israel", "latitude": 31.7784, "longitude": 35.2450,
		"primary_verse_ref": "Acts 1:9-12",
		"description": "The hill overlooking Jerusalem from which Jesus ascended into heaven.",
		"facts": "Jesus often taught and prayed here, including in Gethsemane\nSite of His agony the night before the crucifixion\nWhere He ascended, and where He is prophesied to return",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/4c/2013-Aerial-Mount_of_Olives.jpg/330px-2013-Aerial-Mount_of_Olives.jpg",
		"status": "Published", "sort_order": 8},
	{"title": "Bethany", "category": "City", "region": "Israel", "latitude": 31.7717, "longitude": 35.2603,
		"primary_verse_ref": "John 11:43-44",
		"description": "A village near Jerusalem, home to Jesus' close friends Mary, Martha, and Lazarus.",
		"facts": "Where Jesus raised Lazarus from the dead\nWhere Mary anointed Jesus' feet with perfume\nJesus' base near Jerusalem during His final week",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/3e/%D7%94%D7%A0%D7%95%D7%A3_%D7%9C%D7%9E%D7%AA%D7%97%D7%9D_%D7%90%D7%95%D7%92%D7%95%D7%A1%D7%98%D7%94_%D7%95%D7%99%D7%A7%D7%98%D7%95%D7%A8%D7%99%D7%94.jpg/330px-%D7%94%D7%A0%D7%95%D7%A3_%D7%9C%D7%9E%D7%AA%D7%97%D7%9D_%D7%90%D7%95%D7%92%D7%95%D7%A1%D7%98%D7%94_%D7%95%D7%99%D7%A7%D7%98%D7%95%D7%A8%D7%99%D7%94.jpg",
		"status": "Published", "sort_order": 9},
	{"title": "Cana", "category": "City", "region": "Israel", "latitude": 32.7492, "longitude": 35.3378,
		"primary_verse_ref": "John 2:1-11",
		"description": "The village where Jesus performed His first public miracle.",
		"facts": "Jesus turned water into wine at a wedding here\nHis first recorded miracle\nAlso where He healed an official's son from a distance",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/88/Cana_of_Galilee._90.Holy_land_photographed._Daniel_B._Shepp._1894-1.jpg/330px-Cana_of_Galilee._90.Holy_land_photographed._Daniel_B._Shepp._1894-1.jpg",
		"status": "Published", "sort_order": 10},
	{"title": "Hebron", "category": "City", "region": "Israel", "latitude": 31.5326, "longitude": 35.0998,
		"primary_verse_ref": "Genesis 23:19",
		"description": "One of the oldest cities in the world; where Abraham settled and is buried.",
		"facts": "Burial place of Abraham, Sarah, Isaac, Rebekah, Jacob, and Leah\nDavid reigned here for 7 years before ruling from Jerusalem\nAlso called Kiriath Arba",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/32/BTS_Hebron_Tour_280215_24.jpg/330px-BTS_Hebron_Tour_280215_24.jpg",
		"status": "Published", "sort_order": 11},
	{"title": "Beersheba", "category": "City", "region": "Israel", "latitude": 31.2589, "longitude": 34.7994,
		"primary_verse_ref": "Genesis 21:31",
		"description": "The southernmost city of ancient Israel, where Abraham made a covenant and dug a well.",
		"facts": "Its name means 'well of the oath'\nAssociated with Abraham, Isaac, and Jacob\n'From Dan to Beersheba' described the full extent of Israel",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8f/Beersheba_City_Hall_6.jpg/330px-Beersheba_City_Hall_6.jpg",
		"status": "Published", "sort_order": 12},
	{"title": "Mount Carmel", "category": "Mountain", "region": "Israel", "latitude": 32.7256, "longitude": 35.0472,
		"primary_verse_ref": "1 Kings 18:38-39",
		"description": "The mountain where Elijah defeated the prophets of Baal in a dramatic contest.",
		"facts": "Fire fell from heaven to consume Elijah's offering\nOverlooks the Jezreel Valley\nA symbol of God's power over false gods",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/5b/Caiobadner_-_mount_carmel.JPG/330px-Caiobadner_-_mount_carmel.JPG",
		"status": "Published", "sort_order": 13},
	# --- Jordan ---
	{"title": "Mount Nebo", "category": "Mountain", "region": "Jordan", "latitude": 31.7681, "longitude": 35.7256,
		"primary_verse_ref": "Deuteronomy 34:1-4",
		"description": "Where Moses viewed the Promised Land before he died, never entering it himself.",
		"facts": "Moses saw the whole land of Canaan from its summit\nHe died and was buried nearby, in an unknown location\nOffers sweeping views toward Jericho and the Dead Sea",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/07/Mount_Nebo_BW_6.JPG/330px-Mount_Nebo_BW_6.JPG",
		"status": "Published", "sort_order": 14},
	{"title": "Jerash", "category": "City", "region": "Jordan", "latitude": 32.2811, "longitude": 35.8994,
		"primary_verse_ref": "Mark 5:1-20",
		"description": "A Greco-Roman city (ancient Gerasa) where Jesus healed a man possessed by a legion of demons.",
		"facts": "One of the best-preserved Roman provincial cities anywhere\nPart of the Decapolis, ten Greco-Roman cities east of the Jordan\nSite of Jesus' healing of the Gerasene demoniac",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/51/Oval_Plaza_%28Forum_Romanum%2C_Gerasa_-_Jerash%2C_Jordan%29_-_%D8%B3%D8%A7%D8%AD%D8%A9_%D8%A7%D9%84%D9%86%D8%AF%D9%88%D8%A9%2C_%D8%AC%D8%B1%D8%B4.jpg/330px-Oval_Plaza_%28Forum_Romanum%2C_Gerasa_-_Jerash%2C_Jordan%29_-_%D8%B3%D8%A7%D8%AD%D8%A9_%D8%A7%D9%84%D9%86%D8%AF%D9%88%D8%A9%2C_%D8%AC%D8%B1%D8%B4.jpg",
		"status": "Published", "sort_order": 15},
	{"title": "Amman", "category": "City", "region": "Jordan", "latitude": 31.9552, "longitude": 35.9450,
		"primary_verse_ref": "2 Samuel 12:26",
		"description": "The ancient capital of the Ammonites (Rabbah), mentioned throughout the Old Testament.",
		"facts": "Capital of the Ammonites in Old Testament times\nDavid's general Joab besieged it\nKnown today as Jordan's capital, Amman",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/24/New_Abdali_2024.png/330px-New_Abdali_2024.png",
		"status": "Published", "sort_order": 16},
	# --- Asia Minor ---
	{"title": "Ephesus", "category": "City", "region": "Asia Minor", "latitude": 37.9394, "longitude": 27.3417,
		"primary_verse_ref": "Acts 19:10",
		"description": "A major city where Paul ministered for nearly three years; home to one of the seven churches of Revelation.",
		"facts": "Paul spent about 3 years here, his longest stay anywhere\nHome to the Temple of Artemis, a wonder of the ancient world\nFirst of the seven churches addressed in Revelation",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/84/Ephesus_Celsus_Library_Fa%C3%A7ade.jpg/330px-Ephesus_Celsus_Library_Fa%C3%A7ade.jpg",
		"status": "Published", "sort_order": 17},
	{"title": "Antioch", "category": "City", "region": "Asia Minor", "latitude": 36.2021, "longitude": 36.1603,
		"primary_verse_ref": "Acts 11:26",
		"description": "The city where followers of Jesus were first called Christians.",
		"facts": "Believers were first called 'Christians' here\nSent out Paul and Barnabas on their first missionary journey\nAn early center of Gentile Christianity",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/e2/Antakya_Views_from_hill_at_SE_in_1990%27s_05.jpg/330px-Antakya_Views_from_hill_at_SE_in_1990%27s_05.jpg",
		"status": "Published", "sort_order": 18},
	{"title": "Tarsus", "category": "City", "region": "Asia Minor", "latitude": 36.9081, "longitude": 34.8950,
		"primary_verse_ref": "Acts 22:3",
		"description": "The birthplace and hometown of the Apostle Paul.",
		"facts": "Paul's hometown, 'no ordinary city'\nA center of learning in the Roman world\nPaul was raised here before studying under Gamaliel",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2b/Old_Town_of_Tarsus%2C_Mersin.jpg/330px-Old_Town_of_Tarsus%2C_Mersin.jpg",
		"status": "Published", "sort_order": 19},
	{"title": "Colossae", "category": "City", "region": "Asia Minor", "latitude": 37.7833, "longitude": 29.3667,
		"primary_verse_ref": "Colossians 1:2",
		"description": "A city whose church received Paul's letter to the Colossians.",
		"facts": "Paul likely never visited in person\nEpaphras founded the church here\nRecipient of the letter warning against false teaching",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/4e/TR_Colossae_site_asv2020-02_img08.jpg/330px-TR_Colossae_site_asv2020-02_img08.jpg",
		"status": "Published", "sort_order": 20},
	{"title": "Laodicea", "category": "City", "region": "Asia Minor", "latitude": 37.8382, "longitude": 29.1081,
		"primary_verse_ref": "Revelation 3:15-16",
		"description": "One of the seven churches of Revelation, rebuked for being 'lukewarm.'",
		"facts": "Famously rebuked for being neither hot nor cold\nA wealthy banking and textile city\nLast of the seven churches addressed in Revelation",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/36/TR_Pamukkale_Laodicea_asv2020-02_img11.jpg/330px-TR_Pamukkale_Laodicea_asv2020-02_img11.jpg",
		"status": "Published", "sort_order": 21},
	# --- Greece ---
	{"title": "Athens", "category": "City", "region": "Greece", "latitude": 37.9838, "longitude": 23.7275,
		"primary_verse_ref": "Acts 17:22-31",
		"description": "Where Paul preached to philosophers at the Areopagus, reasoning from their own altar 'To an Unknown God.'",
		"facts": "Paul's famous sermon at the Areopagus (Mars Hill)\nCenter of Greek philosophy and idolatry in Paul's day\nFew converts, but a landmark moment for the gospel among Gentile intellectuals",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/68/Athens_Acropolis_at_Daybreak.jpg/330px-Athens_Acropolis_at_Daybreak.jpg",
		"status": "Published", "sort_order": 22},
	{"title": "Corinth", "category": "City", "region": "Greece", "latitude": 37.9060, "longitude": 22.8790,
		"primary_verse_ref": "Acts 18:1-11",
		"description": "A major trade city where Paul planted a church and stayed for 18 months.",
		"facts": "Paul lived and worked here as a tentmaker with Aquila and Priscilla\nRecipient of 1 and 2 Corinthians\nKnown for wealth, diversity, and moral compromise",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/41/Ravel_1008.2.jpg/330px-Ravel_1008.2.jpg",
		"status": "Published", "sort_order": 23},
	{"title": "Philippi", "category": "City", "region": "Greece", "latitude": 41.0138, "longitude": 24.2874,
		"primary_verse_ref": "Acts 16:12-15",
		"description": "The first church planted in Europe; where Paul and Silas were jailed and miraculously freed.",
		"facts": "First convert in Europe was Lydia, a seller of purple cloth\nPaul and Silas sang hymns in jail before an earthquake freed them\nRecipient of the joyful letter to the Philippians",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/5c/Philippi_city_center.jpg/330px-Philippi_city_center.jpg",
		"status": "Published", "sort_order": 24},
	{"title": "Thessalonica", "category": "City", "region": "Greece", "latitude": 40.6401, "longitude": 22.9444,
		"primary_verse_ref": "Acts 17:1-9",
		"description": "A busy port city where Paul planted a church amid fierce opposition.",
		"facts": "Paul preached in the synagogue for three Sabbaths\nRecipient of 1 and 2 Thessalonians\nStill a major city today, known as Thessaloniki",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/fa/Tessaloniki_BW_2017-10-05_18-22-47.jpg/330px-Tessaloniki_BW_2017-10-05_18-22-47.jpg",
		"status": "Published", "sort_order": 25},
	{"title": "Berea", "category": "City", "region": "Greece", "latitude": 40.5167, "longitude": 22.2000,
		"primary_verse_ref": "Acts 17:11",
		"description": "Praised for eagerly examining Scripture to test Paul's teaching.",
		"facts": "Its people 'searched the Scriptures daily' to verify Paul's message\nCalled 'more noble' than the Thessalonians for their openness\nA model for how believers should test what they're taught",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/3a/%CE%92%CE%AD%CF%81%CE%BF%CE%B9%CE%B1.jpg/330px-%CE%92%CE%AD%CF%81%CE%BF%CE%B9%CE%B1.jpg",
		"status": "Published", "sort_order": 26},
	{"title": "Patmos", "category": "Region", "region": "Greece", "latitude": 37.3000, "longitude": 26.5333,
		"primary_verse_ref": "Revelation 1:9-11",
		"description": "The small island where the apostle John received the vision recorded in Revelation.",
		"facts": "John was exiled here for his faith\nReceived the entire vision of the book of Revelation\nStill a pilgrimage site today",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a5/Chora-of-Patmos.JPG/330px-Chora-of-Patmos.JPG",
		"status": "Published", "sort_order": 27},
	# --- Rome ---
	{"title": "Rome", "category": "City", "region": "Rome", "latitude": 41.9028, "longitude": 12.4964,
		"primary_verse_ref": "Acts 28:16",
		"description": "The capital of the empire, where Paul was imprisoned and, by tradition, martyred.",
		"facts": "Paul was under house arrest here, still preaching freely\nTraditional site of both Paul's and Peter's martyrdom\nThe gospel reached 'the ends of the earth' as the book of Acts closes",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/7e/Trevi_Fountain%2C_Rome%2C_Italy_2_-_May_2007.jpg/330px-Trevi_Fountain%2C_Rome%2C_Italy_2_-_May_2007.jpg",
		"status": "Published", "sort_order": 28},
	{"title": "Puteoli", "category": "City", "region": "Rome", "latitude": 40.8236, "longitude": 14.1214,
		"primary_verse_ref": "Acts 28:13-14",
		"description": "The Italian port where Paul landed on his final journey toward Rome.",
		"facts": "Paul found fellow believers here and stayed a week\nA major port for grain ships from Egypt\nKnown today as Pozzuoli, near Naples",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/Pozzuoli_2010-by-RaBoe-23.jpg/330px-Pozzuoli_2010-by-RaBoe-23.jpg",
		"status": "Published", "sort_order": 29},
	# --- Mesopotamia, Sinai & other Old Testament settings ---
	{"title": "Ur", "category": "City", "region": "Mesopotamia", "latitude": 30.9625, "longitude": 46.1039,
		"primary_verse_ref": "Genesis 11:31",
		"description": "Abraham's hometown before God called him to leave everything and follow.",
		"facts": "A major Sumerian city in Abraham's day\nGod called Abram to leave here for a land he'd never seen\nOne of the earliest cities in recorded history",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8e/Urimki_inscription.jpg/330px-Urimki_inscription.jpg",
		"status": "Published", "sort_order": 30},
	{"title": "Haran", "category": "City", "region": "Mesopotamia", "latitude": 36.8636, "longitude": 39.0322,
		"primary_verse_ref": "Genesis 11:31",
		"description": "Where Abraham's family settled for a time on the journey toward Canaan.",
		"facts": "Abraham's father Terah died here\nGod renewed His call to Abraham here (Genesis 12:1)\nStill known for its distinctive beehive-shaped houses",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/22/Harran_2015.jpg/330px-Harran_2015.jpg",
		"status": "Published", "sort_order": 31},
	{"title": "Damascus", "category": "City", "region": "Syria", "latitude": 33.5138, "longitude": 36.2765,
		"primary_verse_ref": "Acts 9:3-9",
		"description": "Where Saul encountered the risen Jesus and was transformed into Paul.",
		"facts": "One of the oldest continuously inhabited cities in the world\nSaul was blinded by a light from heaven on the road here\nHe was baptized by Ananias in this city",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/53/Damascus%2C_Syria%2C_Panoramic_view_of_Damascus.jpg/330px-Damascus%2C_Syria%2C_Panoramic_view_of_Damascus.jpg",
		"status": "Published", "sort_order": 32},
	{"title": "Nineveh", "category": "City", "region": "Mesopotamia", "latitude": 36.3603, "longitude": 43.1189,
		"primary_verse_ref": "Jonah 3:5",
		"description": "The great city that repented at Jonah's preaching.",
		"facts": "Capital of the Assyrian Empire\nJonah initially fled rather than preach here\nThe entire city, from king to commoner, repented",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/27/Nineveh_-_Mashki_Gate.jpg/330px-Nineveh_-_Mashki_Gate.jpg",
		"status": "Published", "sort_order": 33},
	{"title": "Babylon", "category": "City", "region": "Mesopotamia", "latitude": 32.5364, "longitude": 44.4208,
		"primary_verse_ref": "Daniel 1:8",
		"description": "Where Judah was exiled, and where Daniel served faithfully in a foreign court.",
		"facts": "Judah was exiled here after Jerusalem's fall\nDaniel and his friends served in the royal court\nSite of the fiery furnace and the writing on the wall",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/e6/Ishtar_Gate.jpg/330px-Ishtar_Gate.jpg",
		"status": "Published", "sort_order": 34},
	{"title": "Mount Ararat", "category": "Mountain", "region": "Turkey", "latitude": 39.7019, "longitude": 44.2983,
		"primary_verse_ref": "Genesis 8:4",
		"description": "The traditional resting place of Noah's ark after the flood.",
		"facts": "The ark came to rest 'on the mountains of Ararat'\nThe highest peak in modern-day Turkey\nA lasting symbol of God's judgment and mercy",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/75/Mount_Ararat_and_the_Yerevan_skyline_in_spring_%2850mm%29.jpg/330px-Mount_Ararat_and_the_Yerevan_skyline_in_spring_%2850mm%29.jpg",
		"status": "Published", "sort_order": 35},
	{"title": "Mount Sinai", "category": "Mountain", "region": "Sinai", "latitude": 28.5392, "longitude": 33.9734,
		"primary_verse_ref": "Exodus 19:20",
		"description": "Where God gave Moses the Ten Commandments amid fire and thunder.",
		"facts": "Israel camped here for about a year after the Exodus\nGod gave the Ten Commandments and the Law here\nAlso called Horeb, 'the mountain of God'",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/36/Mount_Sinai_from_the_southwest.jpg/330px-Mount_Sinai_from_the_southwest.jpg",
		"status": "Published", "sort_order": 36},
	{"title": "Red Sea", "category": "Sea", "region": "Sinai", "latitude": 29.9668, "longitude": 32.5498,
		"primary_verse_ref": "Exodus 14:21-22",
		"description": "Where God parted the waters for Israel to cross on dry ground.",
		"facts": "God parted the sea so Israel could escape Pharaoh's army\nThe pursuing Egyptian army was destroyed when the waters returned\nCelebrated in the Song of Moses (Exodus 15)",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/78/EG-suez-20-bg-suez.jpg/330px-EG-suez-20-bg-suez.jpg",
		"status": "Published", "sort_order": 37},
	{"title": "Goshen", "category": "Region", "region": "Egypt", "latitude": 30.8000, "longitude": 31.9000,
		"primary_verse_ref": "Genesis 47:6",
		"description": "The fertile region where the Israelites lived during their centuries in Egypt.",
		"facts": "Given to Jacob's family by Joseph, then a ruler in Egypt\nWhere the Israelites multiplied over 400 years\nSpared several of the plagues that struck the rest of Egypt",
		"photo_url": "https://upload.wikimedia.org/wikipedia/commons/4/40/Gosen.jpg",
		"status": "Published", "sort_order": 38},
	# --- More places, added for a fuller set of guided journeys ---
	{"title": "Bethel", "category": "City", "region": "Israel", "latitude": 31.9308, "longitude": 35.2258,
		"primary_verse_ref": "Genesis 28:19",
		"description": "Where Jacob dreamed of a stairway to heaven and later returned to build an altar.",
		"facts": "Jacob named it 'Bethel' meaning 'house of God'\nSite of Jacob's ladder dream\nLater became a center of worship in the northern kingdom",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8e/COLOR_PHOTO_FROM_THE_LATE_19TH_CENTURY_TAKEN_BY_FRENCH_PHOTOGRAPHER%2C_BONFILS%2C_DEPICTING_THE_BET_EL_AREA_NEAR_JERUSALEM._%D7%A6%D7%99%D7%9C%D7%95%D7%9D_%D7%A6%D7%91%D7%A2_%D7%9E%D7%A1%D7%95%D7%A3_%D7%94%D7%9E%D7%90%D7%94_%D7%94_19_%D7%A4%D7%A8%D7%99_%D7%9E%D7%A6%D7%9C%D7%9E%D7%AA%D7%95_%D7%A9%D7%9C_%D7%94%D7%A6%D7%9C%D7%9D_%D7%94%D7%A6%D7%A8%D7%A4%D7%AA%D7%99_%D7%91%D7%95%D7%A0%D7%A4.jpg/330px-thumbnail.jpg",
		"status": "Published", "sort_order": 39},
	{"title": "Peniel", "category": "Region", "region": "Jordan", "latitude": 32.3833, "longitude": 35.5667,
		"primary_verse_ref": "Genesis 32:30",
		"description": "Where Jacob wrestled with God through the night and received the name Israel.",
		"facts": "Jacob wrestled with a man until daybreak\nHe was renamed 'Israel', meaning 'he struggles with God'\nJacob walked with a limp afterward",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/73/Landscape_of_Jordan.JPG/330px-Landscape_of_Jordan.JPG",
		"status": "Published", "sort_order": 40},
	{"title": "Shechem", "category": "City", "region": "Israel", "latitude": 32.2131, "longitude": 35.2761,
		"primary_verse_ref": "Genesis 33:18-20",
		"description": "An early stop of Abraham and Jacob in Canaan, and the site of Joshua's covenant renewal.",
		"facts": "Abraham built his first altar in Canaan here\nJacob bought land and dug a well here\nJoshua renewed Israel's covenant with God here",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/71/Tell_Balata.jpg/330px-Tell_Balata.jpg",
		"status": "Published", "sort_order": 41},
	{"title": "Dothan", "category": "City", "region": "Israel", "latitude": 32.4189, "longitude": 35.2725,
		"primary_verse_ref": "Genesis 37:17",
		"description": "Where Joseph's brothers sold him into slavery.",
		"facts": "Joseph found his brothers here while checking on the flocks\nHe was thrown into a pit, then sold to traders bound for Egypt\nLater the site of Elisha's vision of horses and chariots of fire (2 Kings 6)",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/ec/Tel_Dotan3.jpg/330px-Tel_Dotan3.jpg",
		"status": "Published", "sort_order": 42},
	{"title": "Ai", "category": "City", "region": "Israel", "latitude": 31.9294, "longitude": 35.2664,
		"primary_verse_ref": "Joshua 8:1",
		"description": "A Canaanite city Israel conquered after learning from an earlier defeat.",
		"facts": "Israel's first attack failed because of Achan's sin\nJoshua then led Israel to a decisive victory here\nNear Bethel, on the road into the hill country",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/96/049.Joshua_Burns_the_Town_of_Ai.jpg/330px-049.Joshua_Burns_the_Town_of_Ai.jpg",
		"status": "Published", "sort_order": 43},
	{"title": "Gibeon", "category": "City", "region": "Israel", "latitude": 31.8497, "longitude": 35.1811,
		"primary_verse_ref": "Joshua 10:12-13",
		"description": "Where the sun stood still at Joshua's command during Israel's battle for the Gibeonites.",
		"facts": "The Gibeonites tricked Israel into a treaty of peace\nJoshua prayed for the sun and moon to stand still here\nLater the site of Solomon's dream of wisdom (1 Kings 3)",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/25/Gibeon.png/330px-Gibeon.png",
		"status": "Published", "sort_order": 44},
	{"title": "Hazor", "category": "City", "region": "Israel", "latitude": 33.0167, "longitude": 35.5667,
		"primary_verse_ref": "Joshua 11:10",
		"description": "The largest Canaanite city of its day, conquered and burned by Joshua.",
		"facts": "Called 'the head of all those kingdoms' (Joshua 11:10)\nJoshua defeated its king and burned the city\nLater rebuilt and fortified by Solomon",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/e9/Hatzor-HouseofPillars.jpg/330px-Hatzor-HouseofPillars.jpg",
		"status": "Published", "sort_order": 45},
	{"title": "Joppa", "category": "City", "region": "Israel", "latitude": 32.0533, "longitude": 34.7514,
		"primary_verse_ref": "Jonah 1:3",
		"description": "The port city where Jonah fled by ship, and where Peter received his vision to preach to the Gentiles.",
		"facts": "Jonah boarded a ship here to flee to Tarshish\nPeter raised Tabitha (Dorcas) from the dead here\nPeter's rooftop vision here led him to Cornelius, and the gospel to the Gentiles",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a3/ISR-2013-Aerial-Jaffa-Port_of_Jaffa.jpg/330px-ISR-2013-Aerial-Jaffa-Port_of_Jaffa.jpg",
		"status": "Published", "sort_order": 46},
	{"title": "Susa", "category": "City", "region": "Persia", "latitude": 32.1889, "longitude": 48.2544,
		"primary_verse_ref": "Esther 1:2",
		"description": "The Persian capital where Esther became queen and Nehemiah served in the royal court.",
		"facts": "Setting of the book of Esther\nNehemiah served as cupbearer to King Artaxerxes here\nDaniel received one of his visions here (Daniel 8:2)",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8b/History_of_Egypt%2C_Chaldea%2C_Syria%2C_Babylonia_and_Assyria_%281903%29_%2814584070300%29.jpg/330px-History_of_Egypt%2C_Chaldea%2C_Syria%2C_Babylonia_and_Assyria_%281903%29_%2814584070300%29.jpg",
		"status": "Published", "sort_order": 47},
	{"title": "Smyrna", "category": "City", "region": "Asia Minor", "latitude": 38.4237, "longitude": 27.1428,
		"primary_verse_ref": "Revelation 2:8-11",
		"description": "One of the seven churches of Revelation, commended for enduring persecution and poverty.",
		"facts": "The only one of the seven churches with no rebuke from Jesus\nEncouraged to 'be faithful unto death'\nKnown today as İzmir, Turkey",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/90/Agora_of_Smyrna%2C_built_during_the_Hellenistic_era_at_the_base_of_Pagos_Hill_and_totally_rebuilt_under_Marcus_Aurelius_after_the_destructive_178_AD_earthquake%2C_Izmir%2C_Turkey_%2818702047681%29.jpg/330px-thumbnail.jpg",
		"status": "Published", "sort_order": 48},
	{"title": "Pergamum", "category": "City", "region": "Asia Minor", "latitude": 39.1325, "longitude": 27.1848,
		"primary_verse_ref": "Revelation 2:12-13",
		"description": "One of the seven churches of Revelation, called 'where Satan's throne is.'",
		"facts": "Home to a great altar of Zeus and emperor worship\nAntipas, a faithful martyr, was killed here\nA major center of pagan religion in Asia Minor",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/41/Acropolis_-_Bergama_%28Pergamon%29_-_Turkey_-_10_%285747249729%29.jpg/330px-Acropolis_-_Bergama_%28Pergamon%29_-_Turkey_-_10_%285747249729%29.jpg",
		"status": "Published", "sort_order": 49},
	{"title": "Thyatira", "category": "City", "region": "Asia Minor", "latitude": 38.9169, "longitude": 27.8386,
		"primary_verse_ref": "Revelation 2:18-19",
		"description": "One of the seven churches of Revelation; hometown of Lydia, the seller of purple cloth.",
		"facts": "Lydia, Paul's first European convert, was from here (Acts 16:14)\nKnown for its trade guilds, including dyers of purple cloth\nRebuked for tolerating false teaching",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a7/Columns_of_Thiatira.jpg/330px-Columns_of_Thiatira.jpg",
		"status": "Published", "sort_order": 50},
	{"title": "Sardis", "category": "City", "region": "Asia Minor", "latitude": 38.4877, "longitude": 28.0402,
		"primary_verse_ref": "Revelation 3:1-3",
		"description": "One of the seven churches of Revelation, rebuked for being spiritually dead despite its reputation.",
		"facts": "Once the wealthy capital of ancient Lydia\nJesus said it had 'a reputation of being alive, but you are dead'\nCalled to wake up and strengthen what remained",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/e5/The_Bath-Gymnasium_complex_at_Sardis%2C_late_2nd_-_early_3rd_century_AD%2C_Sardis%2C_Turkey_%2817098680002%29.jpg/330px-The_Bath-Gymnasium_complex_at_Sardis%2C_late_2nd_-_early_3rd_century_AD%2C_Sardis%2C_Turkey_%2817098680002%29.jpg",
		"status": "Published", "sort_order": 51},
	{"title": "Philadelphia", "category": "City", "region": "Asia Minor", "latitude": 38.3465, "longitude": 28.5223,
		"primary_verse_ref": "Revelation 3:7-8",
		"description": "One of the seven churches of Revelation, praised for its faithfulness despite little strength.",
		"facts": "Given an 'open door' no one could shut\nCommended for keeping God's word and not denying His name\nKnown today as Alaşehir, Turkey",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/eb/Biblical_Philadelphia%2C_Ala%C5%9Fehir%2C_Turkey_%28%E2%80%9CSeven_Churches_of_Revelation%E2%80%9D%29_%2851966166907%29.jpg/330px-Biblical_Philadelphia%2C_Ala%C5%9Fehir%2C_Turkey_%28%E2%80%9CSeven_Churches_of_Revelation%E2%80%9D%29_%2851966166907%29.jpg",
		"status": "Published", "sort_order": 52},
	{"title": "Persia", "category": "Region", "region": "Persia", "latitude": 29.9345, "longitude": 52.8916,
		"primary_verse_ref": "Matthew 2:1-2",
		"description": "The eastern lands the Magi are traditionally believed to have traveled from to worship the newborn Jesus.",
		"facts": "Traditional homeland of the 'wise men from the East'\nPersian astronomers and scholars would have studied the stars\nCapital of the Persian Empire, home to Susa, Persepolis, and Ecbatana",
		"photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/5c/2018-09-21_Iran%2C_Persepolis%2C_Tachara_%28from_the_southeast%29.jpg/330px-2018-09-21_Iran%2C_Persepolis%2C_Tachara_%28from_the_southeast%29.jpg",
		"status": "Published", "sort_order": 53},
]

_BIBLE_JOURNEYS = [
	{"title": "Jesus' Ministry", "description": "Walk the road of Jesus' earthly ministry — from a humble birth in Bethlehem to His ascension from the Mount of Olives.",
		"icon": "auto_stories", "accent_color": "Blue", "status": "Published", "sort_order": 1},
	{"title": "Paul's Missionary Journeys", "description": "Follow the apostle Paul from his hometown, through conversion, and across the ancient world spreading the gospel to Rome.",
		"icon": "route", "accent_color": "Purple", "status": "Published", "sort_order": 2},
	{"title": "Exodus Journey", "description": "Trace Israel's journey from slavery in Egypt to the edge of the Promised Land.",
		"icon": "hiking", "accent_color": "Amber", "status": "Published", "sort_order": 3},
	{"title": "David's Kingdom", "description": "Follow David from shepherd boy to anointed king, and the kingdom he built.",
		"icon": "flag", "accent_color": "Rose", "status": "Published", "sort_order": 4},
	{"title": "Abraham's Journey", "description": "Follow Abraham's journey of faith, from his homeland to the land God promised him.",
		"icon": "public", "accent_color": "Green", "status": "Published", "sort_order": 5},
	{"title": "Jacob's Journey", "description": "Follow Jacob from fleeing his brother's anger to becoming Israel, father of twelve tribes.",
		"icon": "hiking", "accent_color": "Amber", "status": "Published", "sort_order": 6},
	{"title": "Joseph in Egypt", "description": "From a pit in Dothan to the palace of Pharaoh — Joseph's rise from slavery to saving a nation.",
		"icon": "route", "accent_color": "Blue", "status": "Published", "sort_order": 7},
	{"title": "The Conquest of Canaan", "description": "Follow Joshua's campaign to bring Israel into the land God had promised.",
		"icon": "flag", "accent_color": "Rose", "status": "Published", "sort_order": 8},
	{"title": "Elijah's Journey", "description": "Follow the prophet Elijah from a dramatic showdown to a whisper on the mountain of God.",
		"icon": "volunteer_activism", "accent_color": "Purple", "status": "Published", "sort_order": 9},
	{"title": "Jonah's Journey", "description": "A prophet who ran from God's call — and the city that repented when he finally obeyed.",
		"icon": "explore", "accent_color": "Teal", "status": "Published", "sort_order": 10},
	{"title": "Exile and Return", "description": "From the fall of Jerusalem to the rebuilding of its walls — Judah's exile and return home.",
		"icon": "public", "accent_color": "Green", "status": "Published", "sort_order": 11},
	{"title": "Peter's Ministry", "description": "Follow Peter from a rooftop vision in Joppa to the gospel reaching the Gentile world.",
		"icon": "flag", "accent_color": "Blue", "status": "Published", "sort_order": 12},
	{"title": "The Seven Churches of Revelation", "description": "John's vision named seven real churches in Asia Minor, each given its own message from Jesus.",
		"icon": "temple_buddhist", "accent_color": "Purple", "status": "Published", "sort_order": 13},
	{"title": "The Magi's Journey", "description": "Wise men followed a star from a distant land to worship the newborn King.",
		"icon": "explore", "accent_color": "Amber", "status": "Published", "sort_order": 14},
	{"title": "Flight to Egypt", "description": "Joseph and Mary fled with the infant Jesus to escape Herod's murderous decree.",
		"icon": "route", "accent_color": "Green", "status": "Published", "sort_order": 15},
]

_BIBLE_JOURNEY_STOPS = {
	"Jesus' Ministry": [
		{"stop_number": 1, "place": "Bethlehem", "note": "Where it all began: God became flesh in a manger."},
		{"stop_number": 2, "place": "Nazareth", "note": "Jesus grew up here in obscurity, in an ordinary carpenter's home."},
		{"stop_number": 3, "place": "Jordan River", "note": "Jesus was baptized here, and the Father's voice confirmed Him as His beloved Son."},
		{"stop_number": 4, "place": "Cana", "note": "His first miracle — turning water into wine — happened at a wedding here."},
		{"stop_number": 5, "place": "Capernaum", "note": "Jesus made this fishing town His ministry headquarters in Galilee."},
		{"stop_number": 6, "place": "Sea of Galilee", "note": "He calmed a raging storm and walked on these very waters."},
		{"stop_number": 7, "place": "Bethany", "note": "He raised His friend Lazarus from the dead here, days before His own death."},
		{"stop_number": 8, "place": "Jerusalem", "note": "He was betrayed, crucified, buried — and rose again on the third day."},
		{"stop_number": 9, "place": "Mount of Olives", "note": "From this hill, the risen Jesus ascended into heaven before His disciples' eyes."},
	],
	"Paul's Missionary Journeys": [
		{"stop_number": 1, "place": "Tarsus", "note": "Paul's hometown, where he was born a Roman citizen and trained as a Pharisee."},
		{"stop_number": 2, "place": "Damascus", "note": "On the road here, the risen Jesus confronted Saul and changed his life forever."},
		{"stop_number": 3, "place": "Antioch", "note": "The church here first called believers 'Christians,' and sent Paul out to preach."},
		{"stop_number": 4, "place": "Ephesus", "note": "Paul stayed nearly three years, his longest ministry stop anywhere."},
		{"stop_number": 5, "place": "Philippi", "note": "The first church in Europe began here, after Paul and Silas were jailed and freed."},
		{"stop_number": 6, "place": "Thessalonica", "note": "Paul preached boldly here despite fierce opposition from the synagogue."},
		{"stop_number": 7, "place": "Berea", "note": "Its people searched the Scriptures daily to test everything Paul taught them."},
		{"stop_number": 8, "place": "Athens", "note": "Paul reasoned with philosophers at the Areopagus about the 'unknown God.'"},
		{"stop_number": 9, "place": "Corinth", "note": "He stayed 18 months, working as a tentmaker while planting a thriving church."},
		{"stop_number": 10, "place": "Puteoli", "note": "After a shipwreck and long voyage, Paul finally landed in Italy here."},
		{"stop_number": 11, "place": "Rome", "note": "Under house arrest, Paul kept preaching freely until the very end of Acts."},
	],
	"Exodus Journey": [
		{"stop_number": 1, "place": "Goshen", "note": "Israel's home in Egypt, where their cries for freedom reached God's ears."},
		{"stop_number": 2, "place": "Red Sea", "note": "God parted the waters, and Israel walked to freedom on dry ground."},
		{"stop_number": 3, "place": "Mount Sinai", "note": "Here God gave Moses the Ten Commandments and the Law for His people."},
		{"stop_number": 4, "place": "Mount Nebo", "note": "Moses climbed this mountain to see the Promised Land he would never enter."},
		{"stop_number": 5, "place": "Jericho", "note": "Israel finally crossed into Canaan, and its walls fell at God's command."},
	],
	"David's Kingdom": [
		{"stop_number": 1, "place": "Bethlehem", "note": "David was born and anointed king here as a young shepherd boy."},
		{"stop_number": 2, "place": "Hebron", "note": "David reigned here for seven years before uniting the kingdom."},
		{"stop_number": 3, "place": "Jerusalem", "note": "David captured this city and made it his capital — the City of David."},
		{"stop_number": 4, "place": "Beersheba", "note": "The southern edge of David's kingdom — 'from Dan to Beersheba.'"},
	],
	"Abraham's Journey": [
		{"stop_number": 1, "place": "Ur", "note": "Abraham's hometown, which he left behind at God's call, not knowing where he was going."},
		{"stop_number": 2, "place": "Haran", "note": "His family settled here for a time before God renewed His call to move on."},
		{"stop_number": 3, "place": "Hebron", "note": "Abraham finally settled in this land, and was buried here alongside Sarah."},
		{"stop_number": 4, "place": "Beersheba", "note": "Here Abraham made a covenant and dug a well that gave the city its name."},
	],
	"Jacob's Journey": [
		{"stop_number": 1, "place": "Beersheba", "note": "Jacob left his home here, fleeing his brother Esau's anger, with only a promise from God."},
		{"stop_number": 2, "place": "Bethel", "note": "God appeared to him in a dream of a stairway to heaven, and Jacob vowed to follow the Lord."},
		{"stop_number": 3, "place": "Haran", "note": "He worked for his uncle Laban here for twenty years, and married Leah and Rachel."},
		{"stop_number": 4, "place": "Peniel", "note": "On his way home, Jacob wrestled with God all night and was renamed Israel."},
		{"stop_number": 5, "place": "Shechem", "note": "He settled here for a time and bought land, building an altar to God."},
		{"stop_number": 6, "place": "Hebron", "note": "Jacob finally returned to his father Isaac's home, completing the journey full circle."},
	],
	"Joseph in Egypt": [
		{"stop_number": 1, "place": "Hebron", "note": "Joseph's father Jacob sent him from home to check on his brothers and their flocks."},
		{"stop_number": 2, "place": "Shechem", "note": "He searched for his brothers here before being redirected to Dothan."},
		{"stop_number": 3, "place": "Dothan", "note": "His brothers seized him, threw him in a pit, and sold him to traders bound for Egypt."},
		{"stop_number": 4, "place": "Goshen", "note": "Years later, as Egypt's second-in-command, Joseph welcomed his whole family to settle here."},
	],
	"The Conquest of Canaan": [
		{"stop_number": 1, "place": "Jordan River", "note": "Israel crossed the river on dry ground, just as their parents had crossed the Red Sea."},
		{"stop_number": 2, "place": "Jericho", "note": "The first city to fall, its walls collapsing after seven days of marching in faith."},
		{"stop_number": 3, "place": "Ai", "note": "After an early defeat exposed hidden sin, Israel returned and won a decisive victory."},
		{"stop_number": 4, "place": "Gibeon", "note": "Joshua prayed for the sun to stand still, and God answered in an unmatched miracle."},
		{"stop_number": 5, "place": "Hazor", "note": "The largest and most powerful Canaanite city fell last, completing the northern campaign."},
	],
	"Elijah's Journey": [
		{"stop_number": 1, "place": "Mount Carmel", "note": "Elijah stood alone against 450 prophets of Baal, and God answered with fire from heaven."},
		{"stop_number": 2, "place": "Beersheba", "note": "Exhausted and afraid after Jezebel's threats, Elijah fled here and prayed to die."},
		{"stop_number": 3, "place": "Mount Sinai", "note": "He walked forty days to this mountain, where God spoke to him in a gentle whisper."},
		{"stop_number": 4, "place": "Damascus", "note": "God sent Elijah here to anoint Hazael as king over Aram."},
	],
	"Jonah's Journey": [
		{"stop_number": 1, "place": "Joppa", "note": "Jonah boarded a ship here, running from God's call to preach to Nineveh."},
		{"stop_number": 2, "place": "Nineveh", "note": "After three days in a great fish, Jonah finally preached — and the whole city repented."},
	],
	"Exile and Return": [
		{"stop_number": 1, "place": "Jerusalem", "note": "The city fell to Babylon, its Temple destroyed, and its people carried into exile."},
		{"stop_number": 2, "place": "Babylon", "note": "Judah's exiles lived here for seventy years — including Daniel and his three friends."},
		{"stop_number": 3, "place": "Susa", "note": "Esther became queen here, and Nehemiah served as cupbearer before returning to rebuild Jerusalem."},
		{"stop_number": 4, "place": "Jerusalem", "note": "Under Ezra and Nehemiah, the exiles returned and rebuilt the city and its walls."},
	],
	"Peter's Ministry": [
		{"stop_number": 1, "place": "Jerusalem", "note": "Peter preached boldly here at Pentecost, and the church was born."},
		{"stop_number": 2, "place": "Joppa", "note": "On a rooftop here, God gave Peter a vision that the gospel was for all people, not Jews only."},
		{"stop_number": 3, "place": "Antioch", "note": "Peter ministered here, in the city where believers were first called Christians."},
	],
	"The Seven Churches of Revelation": [
		{"stop_number": 1, "place": "Ephesus", "note": "Commended for perseverance, but called to return to its first love."},
		{"stop_number": 2, "place": "Smyrna", "note": "Encouraged to remain faithful through persecution, even unto death."},
		{"stop_number": 3, "place": "Pergamum", "note": "Warned about compromise despite standing firm where 'Satan's throne' was."},
		{"stop_number": 4, "place": "Thyatira", "note": "Praised for love and faith, but rebuked for tolerating false teaching."},
		{"stop_number": 5, "place": "Sardis", "note": "Warned to wake up — its reputation for life masked spiritual deadness."},
		{"stop_number": 6, "place": "Philadelphia", "note": "Given an open door no one could shut, for keeping God's word faithfully."},
		{"stop_number": 7, "place": "Laodicea", "note": "Famously rebuked for being lukewarm — neither hot nor cold."},
	],
	"The Magi's Journey": [
		{"stop_number": 1, "place": "Persia", "note": "From the East, Persian astronomers studied the skies and saw a sign of a promised King."},
		{"stop_number": 2, "place": "Jerusalem", "note": "They first came here, asking Herod where the King of the Jews had been born."},
		{"stop_number": 3, "place": "Bethlehem", "note": "The star led them to the child Jesus, and they worshiped Him with gifts fit for a king."},
	],
	"Flight to Egypt": [
		{"stop_number": 1, "place": "Bethlehem", "note": "Warned in a dream of Herod's plot, Joseph took Mary and the child and fled by night."},
		{"stop_number": 2, "place": "Goshen", "note": "The Holy Family found refuge in Egypt until it was safe to return."},
		{"stop_number": 3, "place": "Nazareth", "note": "After Herod's death, the family returned and settled in Nazareth, where Jesus grew up."},
	],
}


def seed_bible_places():
	"""Create-only by `title`, same idempotent shape as `seed_reading_plans`.
	Places are seeded first (and their name looked up by title) so journeys
	seeded right after can link TOB Bible Journey Stop rows to them. An
	admin's own edits to a place, journey, or its stops must never be reset
	by a future migrate."""
	place_names_by_title = {}
	for entry in _BIBLE_PLACES:
		existing = frappe.db.get_value("TOB Bible Place", {"title": entry["title"]}, "name")
		if existing:
			place_names_by_title[entry["title"]] = existing
			continue
		try:
			place_doc = frappe.get_doc({"doctype": "TOB Bible Place", **entry})
			place_doc.insert(ignore_permissions=True)
			frappe.db.commit()
			place_names_by_title[entry["title"]] = place_doc.name
		except frappe.ValidationError:
			frappe.db.rollback()

	for entry in _BIBLE_JOURNEYS:
		if frappe.db.exists("TOB Bible Journey", {"title": entry["title"]}):
			continue
		try:
			journey_doc = frappe.get_doc({"doctype": "TOB Bible Journey", **entry})
			journey_doc.insert(ignore_permissions=True)
			frappe.db.commit()
		except frappe.ValidationError:
			frappe.db.rollback()
			continue

		for stop in _BIBLE_JOURNEY_STOPS.get(entry["title"], []):
			place_name = place_names_by_title.get(stop["place"])
			if not place_name:
				continue
			try:
				frappe.get_doc(
					{
						"doctype": "TOB Bible Journey Stop",
						"journey": journey_doc.name,
						"stop_number": stop["stop_number"],
						"place": place_name,
						"note": stop["note"],
					}
				).insert(ignore_permissions=True)
				frappe.db.commit()
			except frappe.ValidationError:
				frappe.db.rollback()


# Initial dataset for the three new "static-data search suggestion"
# content types (search hub's Characters/Events/Themes categories — see
# truth_of_bible/api/bible_characters.py, bible_events.py, bible_themes.py).
# Same create-only-by-title, idempotent shape as `seed_bible_places` above —
# an admin's own edits here must never be reset by a future migrate. This is
# a meaningful starting set, not literal full coverage — worth continuing
# to grow in future passes, same as `_BIBLE_BATTLE_QUESTIONS`.
_BIBLE_CHARACTERS = [
	# Old Testament
	{"title": "Adam", "testament": "Old Testament", "role": "The first man, formed by God from the dust of the ground.",
	 "relevant_passages": "Genesis 2:7\nGenesis 3:6\nRomans 5:12", "status": "Published", "sort_order": 10},
	{"title": "Eve", "testament": "Old Testament", "role": "The first woman, mother of all the living.",
	 "relevant_passages": "Genesis 2:22\nGenesis 3:6\nGenesis 3:20", "status": "Published", "sort_order": 20},
	{"title": "Noah", "testament": "Old Testament", "role": "A righteous man who built an ark to save his family from the flood.",
	 "relevant_passages": "Genesis 6:14\nGenesis 7:17\nGenesis 9:13", "status": "Published", "sort_order": 30},
	{"title": "Abraham", "testament": "Old Testament", "role": "Father of many nations, called the friend of God.",
	 "relevant_passages": "Genesis 12:1-3\nGenesis 15:6\nGenesis 22:2", "status": "Published", "sort_order": 40},
	{"title": "Isaac", "testament": "Old Testament", "role": "The promised son of Abraham and Sarah, later father of Jacob and Esau.",
	 "relevant_passages": "Genesis 21:3\nGenesis 22:9\nGenesis 25:24-26", "status": "Published", "sort_order": 50},
	{"title": "Jacob", "testament": "Old Testament", "role": "Renamed Israel after wrestling with God, father of the twelve tribes.",
	 "relevant_passages": "Genesis 28:12\nGenesis 32:28", "status": "Published", "sort_order": 60},
	{"title": "Joseph", "testament": "Old Testament", "role": "Sold into slavery, he rose to save his family from famine.",
	 "relevant_passages": "Genesis 37:28\nGenesis 45:5\nGenesis 50:20", "status": "Published", "sort_order": 70},
	{"title": "Moses", "testament": "Old Testament", "role": "Led Israel out of Egypt and received the Ten Commandments.",
	 "relevant_passages": "Exodus 3:10\nExodus 14:21\nExodus 20:1", "status": "Published", "sort_order": 80},
	{"title": "Deborah", "testament": "Old Testament", "role": "A prophetess and the only female judge of Israel.",
	 "relevant_passages": "Judges 4:4\nJudges 4:14", "status": "Published", "sort_order": 90},
	{"title": "Gideon", "testament": "Old Testament", "role": "A judge who defeated a Midianite army with just 300 men.",
	 "relevant_passages": "Judges 6:12\nJudges 7:7", "status": "Published", "sort_order": 100},
	{"title": "Samson", "testament": "Old Testament", "role": "A judge of Israel whose great strength was tied to his Nazirite vow.",
	 "relevant_passages": "Judges 13:5\nJudges 16:17\nJudges 16:30", "status": "Published", "sort_order": 110},
	{"title": "Ruth", "testament": "Old Testament", "role": "A Moabite woman remembered for her loyalty and faith.",
	 "relevant_passages": "Ruth 1:16\nRuth 4:17", "status": "Published", "sort_order": 120},
	{"title": "Samuel", "testament": "Old Testament", "role": "A prophet who anointed Israel's first two kings.",
	 "relevant_passages": "1 Samuel 3:10\n1 Samuel 10:1\n1 Samuel 16:13", "status": "Published", "sort_order": 130},
	{"title": "David", "testament": "Old Testament", "role": "A shepherd boy who became Israel's greatest king.",
	 "relevant_passages": "1 Samuel 16:13\n1 Samuel 17:49\nPsalm 23:1", "status": "Published", "sort_order": 140},
	{"title": "Solomon", "testament": "Old Testament", "role": "King renowned for his wisdom and the temple he built.",
	 "relevant_passages": "1 Kings 3:12\n1 Kings 6:1\nProverbs 1:1", "status": "Published", "sort_order": 150},
	{"title": "Elijah", "testament": "Old Testament", "role": "A prophet who confronted false gods with fire from heaven.",
	 "relevant_passages": "1 Kings 18:38\n2 Kings 2:11", "status": "Published", "sort_order": 160},
	{"title": "Isaiah", "testament": "Old Testament", "role": "A major prophet who foretold the coming Messiah.",
	 "relevant_passages": "Isaiah 6:8\nIsaiah 9:6\nIsaiah 53:5", "status": "Published", "sort_order": 170},
	{"title": "Job", "testament": "Old Testament", "role": "A righteous man tested by great suffering who never cursed God.",
	 "relevant_passages": "Job 1:21\nJob 42:10", "status": "Published", "sort_order": 180},
	{"title": "Jonah", "testament": "Old Testament", "role": "A reluctant prophet swallowed by a great fish.",
	 "relevant_passages": "Jonah 1:17\nJonah 3:4\nJonah 4:11", "status": "Published", "sort_order": 190},
	{"title": "Daniel", "testament": "Old Testament", "role": "A faithful exile who survived the lions' den.",
	 "relevant_passages": "Daniel 1:8\nDaniel 6:22", "status": "Published", "sort_order": 200},
	{"title": "Esther", "testament": "Old Testament", "role": "A queen who risked her life to save her people.",
	 "relevant_passages": "Esther 4:14\nEsther 7:3", "status": "Published", "sort_order": 210},
	{"title": "Nehemiah", "testament": "Old Testament", "role": "Rebuilt the walls of Jerusalem after the exile.",
	 "relevant_passages": "Nehemiah 2:17\nNehemiah 6:15", "status": "Published", "sort_order": 220},
	# New Testament
	{"title": "Mary", "testament": "New Testament", "role": "The mother of Jesus, chosen to bear the Messiah.",
	 "relevant_passages": "Luke 1:38\nLuke 2:7\nJohn 19:26-27", "status": "Published", "sort_order": 230},
	{"title": "John the Baptist", "testament": "New Testament", "role": "The forerunner who prepared the way for Jesus.",
	 "relevant_passages": "Matthew 3:3\nMatthew 3:13-14\nJohn 1:29", "status": "Published", "sort_order": 240},
	{"title": "Peter", "testament": "New Testament", "role": "A fisherman who became a leader of the early church.",
	 "relevant_passages": "Matthew 16:18\nJohn 21:17\nActs 2:14", "status": "Published", "sort_order": 250},
	{"title": "John", "testament": "New Testament", "role": "The \"beloved disciple\" who wrote a Gospel, three letters, and Revelation.",
	 "relevant_passages": "John 13:23\nJohn 21:20\nRevelation 1:9", "status": "Published", "sort_order": 260},
	{"title": "Thomas", "testament": "New Testament", "role": "A disciple remembered for doubting the resurrection.",
	 "relevant_passages": "John 11:16\nJohn 20:28", "status": "Published", "sort_order": 270},
	{"title": "Mary Magdalene", "testament": "New Testament", "role": "The first witness of Jesus' resurrection.",
	 "relevant_passages": "Luke 8:2\nJohn 20:16\nJohn 20:18", "status": "Published", "sort_order": 280},
	{"title": "Stephen", "testament": "New Testament", "role": "The first Christian martyr, stoned for his faith.",
	 "relevant_passages": "Acts 6:5\nActs 7:59-60", "status": "Published", "sort_order": 290},
	{"title": "Barnabas", "testament": "New Testament", "role": "An encourager who partnered with Paul on his first missionary journey.",
	 "relevant_passages": "Acts 4:36\nActs 11:24\nActs 13:2", "status": "Published", "sort_order": 300},
	{"title": "Paul", "testament": "New Testament", "role": "A former persecutor who became the apostle to the Gentiles.",
	 "relevant_passages": "Acts 9:15\nActs 13:2\nRomans 1:1\nGalatians 1:15-16", "status": "Published", "sort_order": 310},
	{"title": "Timothy", "testament": "New Testament", "role": "A young pastor mentored by the apostle Paul.",
	 "relevant_passages": "Acts 16:1-3\n1 Timothy 4:12\n2 Timothy 1:5", "status": "Published", "sort_order": 320},
]


def seed_bible_characters():
	"""Create-only by `title`, same idempotent shape as `seed_bible_places`."""
	for entry in _BIBLE_CHARACTERS:
		if frappe.db.exists("TOB Bible Character", {"title": entry["title"]}):
			continue
		try:
			frappe.get_doc({"doctype": "TOB Bible Character", **entry}).insert(ignore_permissions=True)
			frappe.db.commit()
		except frappe.ValidationError:
			frappe.db.rollback()


_BIBLE_EVENTS = [
	# Creation & Patriarchs
	{"title": "The Creation", "era": "Creation & Patriarchs", "description": "God created the heavens, the earth, and all living things.",
	 "relevant_passages": "Genesis 1:1\nGenesis 1:31", "status": "Published", "sort_order": 10},
	{"title": "The Flood", "era": "Creation & Patriarchs", "description": "God judged the earth's corruption and saved Noah's family.",
	 "relevant_passages": "Genesis 7:17\nGenesis 9:13", "status": "Published", "sort_order": 20},
	{"title": "The Tower of Babel", "era": "Creation & Patriarchs", "description": "Humanity's languages were confused after an act of prideful defiance.",
	 "relevant_passages": "Genesis 11:7-9", "status": "Published", "sort_order": 30},
	{"title": "The Call of Abraham", "era": "Creation & Patriarchs", "description": "God called Abraham to become the father of a great nation.",
	 "relevant_passages": "Genesis 12:1-3", "status": "Published", "sort_order": 40},
	{"title": "Jacob's Ladder", "era": "Creation & Patriarchs", "description": "Jacob dreamed of a stairway to heaven and renewed God's covenant promise.",
	 "relevant_passages": "Genesis 28:12-15", "status": "Published", "sort_order": 50},
	{"title": "Joseph Sold into Slavery", "era": "Creation & Patriarchs", "description": "Joseph's jealous brothers sold him into slavery in Egypt.",
	 "relevant_passages": "Genesis 37:28", "status": "Published", "sort_order": 60},
	# Exodus & Wilderness
	{"title": "The Ten Plagues", "era": "Exodus & Wilderness", "description": "God struck Egypt to compel Pharaoh to free Israel.",
	 "relevant_passages": "Exodus 7:14\nExodus 11:1", "status": "Published", "sort_order": 70},
	{"title": "Crossing the Red Sea", "era": "Exodus & Wilderness", "description": "God parted the sea so Israel could escape Egypt's army.",
	 "relevant_passages": "Exodus 14:21-22", "status": "Published", "sort_order": 80},
	{"title": "The Ten Commandments", "era": "Exodus & Wilderness", "description": "God gave Israel His law at Mount Sinai.",
	 "relevant_passages": "Exodus 20:1\nExodus 31:18", "status": "Published", "sort_order": 90},
	{"title": "Manna from Heaven", "era": "Exodus & Wilderness", "description": "God fed Israel with bread from heaven during their wilderness years.",
	 "relevant_passages": "Exodus 16:4\nExodus 16:35", "status": "Published", "sort_order": 100},
	{"title": "The Fall of Jericho", "era": "Exodus & Wilderness", "description": "Israel's walls-down victory marked their entrance into the Promised Land.",
	 "relevant_passages": "Joshua 6:20", "status": "Published", "sort_order": 110},
	# Kings & Prophets
	{"title": "David and Goliath", "era": "Kings & Prophets", "description": "A shepherd boy defeated a giant with faith and a sling.",
	 "relevant_passages": "1 Samuel 17:50", "status": "Published", "sort_order": 120},
	{"title": "The Dedication of Solomon's Temple", "era": "Kings & Prophets", "description": "Solomon completed and dedicated the first Temple in Jerusalem.",
	 "relevant_passages": "1 Kings 8:10-11", "status": "Published", "sort_order": 130},
	{"title": "Elijah on Mount Carmel", "era": "Kings & Prophets", "description": "Elijah proved the Lord is God before the prophets of Baal.",
	 "relevant_passages": "1 Kings 18:38", "status": "Published", "sort_order": 140},
	{"title": "Elijah's Ascension", "era": "Kings & Prophets", "description": "Elijah was taken up to heaven in a whirlwind.",
	 "relevant_passages": "2 Kings 2:11", "status": "Published", "sort_order": 150},
	{"title": "Esther Saves Her People", "era": "Kings & Prophets", "description": "Esther risked her life to expose a plot to destroy the Jewish people.",
	 "relevant_passages": "Esther 7:3", "status": "Published", "sort_order": 160},
	{"title": "Daniel in the Lions' Den", "era": "Kings & Prophets", "description": "Daniel's faith preserved him from the lions overnight.",
	 "relevant_passages": "Daniel 6:22", "status": "Published", "sort_order": 170},
	# Life of Jesus
	{"title": "The Nativity", "era": "Life of Jesus", "description": "Jesus Christ was born in Bethlehem as promised.",
	 "relevant_passages": "Luke 2:7\nMatthew 1:23", "status": "Published", "sort_order": 180},
	{"title": "The Baptism of Jesus", "era": "Life of Jesus", "description": "Jesus was baptized by John, and the Spirit descended like a dove.",
	 "relevant_passages": "Matthew 3:16-17", "status": "Published", "sort_order": 190},
	{"title": "The Sermon on the Mount", "era": "Life of Jesus", "description": "Jesus taught the Beatitudes and the core ethics of the kingdom of God.",
	 "relevant_passages": "Matthew 5:1-12", "status": "Published", "sort_order": 200},
	{"title": "The Transfiguration", "era": "Life of Jesus", "description": "Jesus was transfigured in glory before Peter, James, and John.",
	 "relevant_passages": "Matthew 17:1-2", "status": "Published", "sort_order": 210},
	{"title": "The Crucifixion", "era": "Life of Jesus", "description": "Jesus died on the cross for the sins of the world.",
	 "relevant_passages": "Matthew 27:35\nJohn 19:30", "status": "Published", "sort_order": 220},
	{"title": "The Resurrection", "era": "Life of Jesus", "description": "Jesus rose from the dead, conquering sin and death.",
	 "relevant_passages": "Matthew 28:6\n1 Corinthians 15:4", "status": "Published", "sort_order": 230},
	# Early Church
	{"title": "Pentecost", "era": "Early Church", "description": "The Holy Spirit came upon the disciples, birthing the church.",
	 "relevant_passages": "Acts 2:4", "status": "Published", "sort_order": 240},
	{"title": "The Conversion of Paul", "era": "Early Church", "description": "Saul the persecutor became Paul, the apostle to the Gentiles.",
	 "relevant_passages": "Acts 9:3-4", "status": "Published", "sort_order": 250},
	{"title": "The Council of Jerusalem", "era": "Early Church", "description": "Church leaders resolved how Gentile believers should live.",
	 "relevant_passages": "Acts 15:6", "status": "Published", "sort_order": 260},
	{"title": "Paul's Missionary Journeys", "era": "Early Church", "description": "Paul spread the gospel across the Roman world on three major journeys.",
	 "relevant_passages": "Acts 13:2-3\nActs 18:23", "status": "Published", "sort_order": 270},
]


def seed_bible_events():
	"""Create-only by `title`, same idempotent shape as `seed_bible_places`."""
	for entry in _BIBLE_EVENTS:
		if frappe.db.exists("TOB Bible Event", {"title": entry["title"]}):
			continue
		try:
			frappe.get_doc({"doctype": "TOB Bible Event", **entry}).insert(ignore_permissions=True)
			frappe.db.commit()
		except frappe.ValidationError:
			frappe.db.rollback()


_BIBLE_THEMES = [
	{"title": "Faith", "weight": "Large", "description": "Trusting God and His promises, even without seeing the outcome.",
	 "relevant_passages": "Hebrews 11:1\nRomans 10:17", "status": "Published", "sort_order": 10},
	{"title": "Grace", "weight": "Large", "description": "God's unearned favor and kindness toward sinners.",
	 "relevant_passages": "Ephesians 2:8-9\nRomans 5:8", "status": "Published", "sort_order": 20},
	{"title": "Love", "weight": "Large", "description": "God's self-giving love for humanity, and the love He calls His people to show.",
	 "relevant_passages": "John 3:16\n1 Corinthians 13:4-7", "status": "Published", "sort_order": 30},
	{"title": "Hope", "weight": "Medium", "description": "Confident expectation in God's promises for the future.",
	 "relevant_passages": "Romans 15:13\nJeremiah 29:11", "status": "Published", "sort_order": 40},
	{"title": "Covenant", "weight": "Medium", "description": "God's binding promises to His people throughout Scripture.",
	 "relevant_passages": "Genesis 9:13\nJeremiah 31:33", "status": "Published", "sort_order": 50},
	{"title": "Redemption", "weight": "Large", "description": "Being bought back and set free from sin through Christ.",
	 "relevant_passages": "Ephesians 1:7\nGalatians 3:13", "status": "Published", "sort_order": 60},
	{"title": "Sin", "weight": "Small", "description": "Falling short of God's standard, separating humanity from God.",
	 "relevant_passages": "Romans 3:23\nRomans 6:23", "status": "Published", "sort_order": 70},
	{"title": "Forgiveness", "weight": "Medium", "description": "Being released from guilt, and extending that same release to others.",
	 "relevant_passages": "1 John 1:9\nMatthew 6:14", "status": "Published", "sort_order": 80},
	{"title": "Righteousness", "weight": "Small", "description": "Right standing with God, given through faith in Christ.",
	 "relevant_passages": "2 Corinthians 5:21\nRomans 1:17", "status": "Published", "sort_order": 90},
	{"title": "Mercy", "weight": "Medium", "description": "God withholding the judgment sinners deserve.",
	 "relevant_passages": "Lamentations 3:22-23\nTitus 3:5", "status": "Published", "sort_order": 100},
	{"title": "Wisdom", "weight": "Medium", "description": "Skillful, godly living that starts with the fear of the Lord.",
	 "relevant_passages": "Proverbs 9:10\nJames 1:5", "status": "Published", "sort_order": 110},
	{"title": "Obedience", "weight": "Small", "description": "Faithfully following God's commands out of love and trust.",
	 "relevant_passages": "John 14:15\n1 Samuel 15:22", "status": "Published", "sort_order": 120},
	{"title": "Justice", "weight": "Small", "description": "God's righteous standard, and His call for His people to act justly.",
	 "relevant_passages": "Micah 6:8\nIsaiah 1:17", "status": "Published", "sort_order": 130},
	{"title": "Holiness", "weight": "Medium", "description": "Being set apart for God, reflecting His purity in character and conduct.",
	 "relevant_passages": "1 Peter 1:16\nLeviticus 20:26", "status": "Published", "sort_order": 140},
	{"title": "Peace", "weight": "Medium", "description": "Wholeness and rest with God and others through Christ.",
	 "relevant_passages": "John 14:27\nPhilippians 4:7", "status": "Published", "sort_order": 150},
	{"title": "Joy", "weight": "Small", "description": "A deep gladness rooted in God, not circumstances.",
	 "relevant_passages": "Nehemiah 8:10\nJohn 15:11", "status": "Published", "sort_order": 160},
	{"title": "Humility", "weight": "Small", "description": "A modest view of self, esteeming others and submitting to God.",
	 "relevant_passages": "Philippians 2:3-4\nJames 4:6", "status": "Published", "sort_order": 170},
	{"title": "Perseverance", "weight": "Small", "description": "Enduring trials faithfully without giving up.",
	 "relevant_passages": "James 1:2-4\nHebrews 12:1", "status": "Published", "sort_order": 180},
	{"title": "Truth", "weight": "Medium", "description": "God's unchanging reality and Word, in contrast to falsehood.",
	 "relevant_passages": "John 14:6\nJohn 8:32", "status": "Published", "sort_order": 190},
	{"title": "Sacrifice", "weight": "Small", "description": "Giving something valuable for God or others, ultimately fulfilled in Christ.",
	 "relevant_passages": "Hebrews 9:26\nRomans 12:1", "status": "Published", "sort_order": 200},
	{"title": "Freedom", "weight": "Small", "description": "Liberation from sin's bondage through Christ.",
	 "relevant_passages": "Galatians 5:1\nJohn 8:36", "status": "Published", "sort_order": 210},
	{"title": "Trust", "weight": "Small", "description": "Relying fully on God's character and faithfulness.",
	 "relevant_passages": "Proverbs 3:5-6\nPsalm 56:3", "status": "Published", "sort_order": 220},
	{"title": "Compassion", "weight": "Small", "description": "Tender concern for the suffering, modeled by Christ.",
	 "relevant_passages": "Matthew 9:36\nColossians 3:12", "status": "Published", "sort_order": 230},
	{"title": "Gratitude", "weight": "Small", "description": "A thankful heart toward God for His goodness.",
	 "relevant_passages": "1 Thessalonians 5:18\nPsalm 100:4", "status": "Published", "sort_order": 240},
	{"title": "Courage", "weight": "Small", "description": "Bold faithfulness to God in the face of fear.",
	 "relevant_passages": "Joshua 1:9\n1 Corinthians 16:13", "status": "Published", "sort_order": 250},
	{"title": "Prayer", "weight": "Large", "description": "Communicating with God — praise, confession, request, and thanksgiving.",
	 "relevant_passages": "Philippians 4:6\nMatthew 6:9-13\n1 Thessalonians 5:17", "status": "Published", "sort_order": 260},
	{"title": "Worship", "weight": "Medium", "description": "Honoring and adoring God with heart, voice, and life.",
	 "relevant_passages": "John 4:24\nPsalm 95:6", "status": "Published", "sort_order": 270},
	{"title": "Repentance", "weight": "Medium", "description": "Turning away from sin and back toward God.",
	 "relevant_passages": "Acts 3:19\n2 Corinthians 7:10", "status": "Published", "sort_order": 280},
	{"title": "Discipleship", "weight": "Medium", "description": "Following Jesus and growing to be more like Him.",
	 "relevant_passages": "Matthew 28:19-20\nLuke 9:23", "status": "Published", "sort_order": 290},
	{"title": "Service", "weight": "Small", "description": "Using one's gifts and time to serve God and others.",
	 "relevant_passages": "Mark 10:45\nGalatians 5:13", "status": "Published", "sort_order": 300},
	{"title": "Patience", "weight": "Small", "description": "Bearing with difficulty and delay without losing faith.",
	 "relevant_passages": "Romans 12:12\nJames 5:7-8", "status": "Published", "sort_order": 310},
	{"title": "Generosity", "weight": "Small", "description": "Freely giving of one's resources, following God's own generosity.",
	 "relevant_passages": "2 Corinthians 9:7\nProverbs 11:25", "status": "Published", "sort_order": 320},
	{"title": "Unity", "weight": "Small", "description": "Oneness among believers in Christ despite differences.",
	 "relevant_passages": "Ephesians 4:3\nPsalm 133:1", "status": "Published", "sort_order": 330},
	{"title": "Suffering", "weight": "Medium", "description": "Enduring hardship in a fallen world while trusting God's purposes.",
	 "relevant_passages": "Romans 8:18\n1 Peter 4:12-13", "status": "Published", "sort_order": 340},
	{"title": "Eternal Life", "weight": "Medium", "description": "Everlasting life with God, promised to those who trust in Christ.",
	 "relevant_passages": "John 3:16\nJohn 11:25-26", "status": "Published", "sort_order": 350},
]


def seed_bible_themes():
	"""Create-only by `title`, same idempotent shape as `seed_bible_places`."""
	for entry in _BIBLE_THEMES:
		if frappe.db.exists("TOB Bible Theme", {"title": entry["title"]}):
			continue
		try:
			frappe.get_doc({"doctype": "TOB Bible Theme", **entry}).insert(ignore_permissions=True)
			frappe.db.commit()
		except frappe.ValidationError:
			frappe.db.rollback()
