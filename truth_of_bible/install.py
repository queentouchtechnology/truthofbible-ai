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
	for entry in _BIBLE_BATTLE_QUESTIONS:
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
					"language": "en",
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
