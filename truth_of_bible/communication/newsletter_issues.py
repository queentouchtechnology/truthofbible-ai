"""The first newsletter series, "7 Daily Activities to Stay Close to God" — seeded once into TOB Newsletter
Issue (newsletter.seed_issues) and edited in the desk from then on. Verses are KJV, checked against
truthofbible.org/bible/kjv/. `app_route` is one of the app's deep-link routes (lib/src/config/deep_link_routes.dart)."""

ACTIVITIES = [
	("📖", "Bible Reading", "Read God's Word every day.", "Psalm 119:105"),
	("🙏", "Personal Prayer", "Talk with God sincerely every day.", "1 Thessalonians 5:17"),
	("🎵", "Worship & Praise", "Praise God through songs and thanksgiving.", "Psalm 100:2"),
	("❤️", "Meditate on God's Word", "Think deeply about Scripture and apply it to your life.", "Joshua 1:8"),
	("🕊️", "Walk in the Holy Spirit", "Allow the Holy Spirit to guide your thoughts, words and actions.", "Galatians 5:16"),
	("✝️", "Obey God's Word", "Put God's teachings into practice.", "John 14:15"),
	("🤝", "Love & Serve Others", "Forgive, help, encourage and show kindness to others.", "Galatians 5:13"),
]

_LIST = "<ol>" + "".join(f"<li><b>{e} {name}</b> – {what} <i>({ref})</i></li>" for e, name, what, ref in ACTIVITIES) + "</ol>"

ISSUES = [
	{
		"title": "7 Daily Activities to Stay Close to God",
		"subject": "7 simple ways to stay close to God every day",
		"preheader": "A short series for the next few weeks — one step at a time.",
		"verse_ref": "John 15:4",
		"verse_text": "Abide in me, and I in you.",
		"body_html": "<p>Over the next few weeks we'll walk through seven simple daily habits that help us stay close "
		"to God — one each week, with a verse and one small step to try.</p>" + _LIST + "<p>The goal isn't to tick "
		"off spiritual activities. It's to grow a closer relationship with Jesus Christ, every day.</p>",
		"action": "Choose one of the seven and do it every day this week. Next week we start with the first.",
		"app_route": "/dashboard",
		"app_button": "Open the app",
		"push_title": "7 daily ways to stay close to God",
		"push_body": "A new weekly series starts today. \"Abide in me, and I in you.\" — John 15:4",
	},
	{
		"title": "📖 Bible Reading — a lamp for the next step",
		"subject": "Read God's Word every day 📖",
		"preheader": "Activity 1 of 7: Bible Reading.",
		"verse_ref": "Psalm 119:105",
		"verse_text": "Thy word is a lamp unto my feet, and a light unto my path.",
		"body_html": "<p>A lamp doesn't light up the whole road at once — just the next few steps. That's how God's Word "
		"works in our lives. A few verses each day give us light for today: comfort, direction and truth.</p>"
		"<p>You don't need to read a lot. You need to read often. Little and daily beats long and rare.</p>",
		"action": "Read one chapter each day this week. Not sure where to start? Begin with the Gospel of John.",
		"app_route": "/readingPlans",
		"app_button": "Choose a reading plan",
		"push_title": "📖 Activity 1: Read God's Word daily",
		"push_body": "\"Thy word is a lamp unto my feet.\" Pick a reading plan and read one chapter today.",
	},
	{
		"title": "🙏 Personal Prayer — talk with God today",
		"subject": "Talk with God sincerely every day 🙏",
		"preheader": "Activity 2 of 7: Personal Prayer.",
		"verse_ref": "1 Thessalonians 5:17",
		"verse_text": "Pray without ceasing.",
		"body_html": "<p>Prayer is simply talking with God — honestly, as you are. He isn't waiting for perfect words; "
		"He wants your heart.</p><p>\"Pray without ceasing\" doesn't mean saying words all day. It means living "
		"close enough to God that you can turn to Him at any moment.</p>",
		"action": "Set a time — morning or before sleep — and talk to God for five minutes. Tell Him what's on your "
		"heart, and thank Him for one thing.",
		"app_route": "/prayer",
		"app_button": "Pray in the app",
		"push_title": "🙏 Activity 2: Talk with God today",
		"push_body": "\"Pray without ceasing.\" Take five quiet minutes with God today.",
	},
	{
		"title": "🎵 Worship & Praise — come before Him with singing",
		"subject": "Praise God through songs and thanksgiving 🎵",
		"preheader": "Activity 3 of 7: Worship & Praise.",
		"verse_ref": "Psalm 100:2",
		"verse_text": "Serve the LORD with gladness: come before his presence with singing.",
		"body_html": "<p>Worship turns our eyes from our problems to the God who is bigger than all of them. A song of "
		"praise or a simple \"thank You, Lord\" can change the whole feeling of a day.</p><p>Thanksgiving is worship "
		"too — every good thing we name is a reason to praise Him.</p>",
		"action": "Start or end each day with one song of praise, and name three things you're thankful for.",
		"app_route": "/dashboard",
		"app_button": "Open the app",
		"push_title": "🎵 Activity 3: Praise God today",
		"push_body": "\"Come before his presence with singing.\" One song and three thank-yous today.",
	},
	{
		"title": "❤️ Meditate on God's Word — let it sink in",
		"subject": "Think deeply about Scripture ❤️",
		"preheader": "Activity 4 of 7: Meditate on God's Word.",
		"verse_ref": "Joshua 1:8",
		"verse_text": "This book of the law shall not depart out of thy mouth; but thou shalt meditate therein day and "
		"night, that thou mayest observe to do according to all that is written therein: for then thou shalt make "
		"thy way prosperous, and then thou shalt have good success.",
		"body_html": "<p>Reading takes God's Word in; meditating lets it sink deep. To meditate is to slow down, think "
		"about a verse, and let it shape how we live.</p><p>One verse carried through the day can do more than many "
		"chapters read quickly and forgotten.</p>",
		"action": "Take today's verse, read it slowly three times, and ask: What does this show me about God? What "
		"should I do?",
		"app_route": "/todayVerse",
		"app_button": "Open today's verse",
		"push_title": "❤️ Activity 4: Meditate on God's Word",
		"push_body": "Read today's verse slowly three times. What is God showing you?",
	},
	{
		"title": "🕊️ Walk in the Holy Spirit — let Him lead",
		"subject": "Let the Holy Spirit guide you today 🕊️",
		"preheader": "Activity 5 of 7: Walk in the Holy Spirit.",
		"verse_ref": "Galatians 5:16",
		"verse_text": "This I say then, Walk in the Spirit, and ye shall not fulfil the lust of the flesh.",
		"body_html": "<p>We don't have to live the Christian life in our own strength. God gives us His Holy Spirit to "
		"guide our thoughts, our words and our choices.</p><p>Walking in the Spirit is step by step: listening, "
		"following, and turning back quickly when we go our own way.</p>",
		"action": "Before you speak or decide something today, pause and pray: \"Holy Spirit, lead me.\"",
		"app_route": "/prayer",
		"app_button": "Pray in the app",
		"push_title": "🕊️ Activity 5: Walk in the Spirit",
		"push_body": "Before you speak or decide today, pause and pray: \"Holy Spirit, lead me.\"",
	},
	{
		"title": "✝️ Obey God's Word — love in action",
		"subject": "Put God's teachings into practice ✝️",
		"preheader": "Activity 6 of 7: Obey God's Word.",
		"verse_ref": "John 14:15",
		"verse_text": "If ye love me, keep my commandments.",
		"body_html": "<p>Jesus connects love and obedience. Obeying God isn't about earning His love — we already have "
		"it. It's how we show our love back to Him.</p><p>Every time we do what His Word says, our faith grows "
		"stronger and more real.</p>",
		"action": "Ask yourself: what is one thing God has already shown me to do? Do it this week.",
		"app_route": "/courseList",
		"app_button": "Continue a Bible course",
		"push_title": "✝️ Activity 6: Put God's Word into practice",
		"push_body": "\"If ye love me, keep my commandments.\" What is one thing God has shown you to do?",
	},
	{
		"title": "🤝 Love & Serve Others — faith you can see",
		"subject": "Forgive, help and encourage someone this week 🤝",
		"preheader": "Activity 7 of 7: Love & Serve Others.",
		"verse_ref": "Galatians 5:13",
		"verse_text": "For, brethren, ye have been called unto liberty; only use not liberty for an occasion to the "
		"flesh, but by love serve one another.",
		"body_html": "<p>Our love for God shows in how we treat people. Forgiving, helping, encouraging and being kind "
		"are all ways of serving Christ through others.</p><p>Small acts matter: a kind word, a phone call, a prayer "
		"for someone who is struggling.</p>",
		"action": "This week, forgive someone, help someone and encourage someone — and pray for someone on the "
		"Prayer Wall.",
		"app_route": "/prayerWall",
		"app_button": "Visit the Prayer Wall",
		"push_title": "🤝 Activity 7: Love & serve others",
		"push_body": "\"By love serve one another.\" Pray for someone on the Prayer Wall today.",
	},
	{
		"title": "🌿 Abide in Me — the heart of it all",
		"subject": "Abide in Him — the heart of all seven 🌿",
		"preheader": "The ultimate goal: a closer relationship with Jesus every day.",
		"verse_ref": "John 15:4",
		"verse_text": "Abide in me, and I in you. As the branch cannot bear fruit of itself, except it abide in the "
		"vine; no more can ye, except ye abide in me.",
		"body_html": "<p>Over these weeks we've looked at seven daily activities:</p>" + _LIST + "<p>But the ultimate "
		"goal isn't just doing spiritual activities. It's developing a closer relationship with Jesus Christ every "
		"day. A branch bears fruit by staying joined to the vine — and we grow by staying close to Him.</p>",
		"action": "Look back over the seven. Which one helped you most? Keep it going — and add one more.",
		"app_route": "/readingPlans",
		"app_button": "Start a reading plan",
		"push_title": "🌿 Abide in Me",
		"push_body": "\"Abide in me, and I in you.\" The heart of all seven daily activities.",
	},
]
