"""The newsletter messages — seeded once into TOB Newsletter Issue (newsletter.seed) and edited in the desk from
then on. One topic per message, each standing on its own: a call to wake up to God, written for someone who may
be far from Him, ending with the part of the app that helps them take the step (Bible reading, prayer, worship
songs, the daily verse, the Holy Spirit, obeying God's Word, loving others).

Verses are KJV, checked against truthofbible.org/bible/kjv/. `app_route` is one of the app's deep-link routes
(lib/src/config/deep_link_routes.dart)."""

ISSUES = [
	{
		"title": "📖 Is your soul hungry?",
		"subject": "You feed your body every day. What about your soul?",
		"preheader": "There is a bread that gives real life.",
		"verse_ref": "Matthew 4:4",
		"verse_text": "But he answered and said, It is written, Man shall not live by bread alone, but by every word "
		"that proceedeth out of the mouth of God.",
		"body_html": "<p>We never forget to eat. Yet many of us go days, months, even years without feeding our souls, "
		"and we wonder why we feel empty, restless and tired inside.</p><p>Jesus said we don't live by bread alone. "
		"God's Word is food for the soul. It brings a dead heart back to life, gives light in the dark, and shows us "
		"the way home to the Father.</p><p>If you've been feeling empty, it may not be your life that's wrong. Your "
		"soul may simply be hungry for God.</p>",
		"action": "Open the Bible today and read one chapter. Start with the Gospel of John: it was written so that "
		"you might believe and have life.",
		"app_route": "/readingPlans",
		"app_button": "Start reading the Bible",
		"push_title": "📖 Is your soul hungry?",
		"push_body": "\"Man shall not live by bread alone, but by every word… of God.\" Read one chapter today.",
	},
	{
		"title": "🙏 God is waiting to hear from you",
		"subject": "When did you last talk to God?",
		"preheader": "He promised to answer.",
		"verse_ref": "Jeremiah 33:3",
		"verse_text": "Call unto me, and I will answer thee, and shew thee great and mighty things, which thou knowest "
		"not.",
		"body_html": "<p>Maybe it's been a long time. Maybe you've never really prayed. Maybe you feel you've gone too "
		"far from God for Him to listen.</p><p>But God isn't far away. He is calling: <i>\"Call unto me, and I will "
		"answer thee.\"</i> You don't need special words. Tell Him the truth: your fears, your failures, your "
		"questions. He already knows, and He still wants to hear it from you.</p><p>Prayer is where a sleeping "
		"heart begins to wake up.</p>",
		"action": "Find a quiet place today and talk to God for five minutes, honestly, as you are.",
		"app_route": "/prayer",
		"app_button": "Pray now",
		"push_title": "🙏 God is waiting to hear from you",
		"push_body": "\"Call unto me, and I will answer thee.\" Talk to Him today, just as you are.",
	},
	{
		"title": "🎵 You still have breath, so praise Him",
		"subject": "Every breath you take is a gift from God",
		"preheader": "Worship lifts your eyes above your troubles.",
		"verse_ref": "Psalm 150:6",
		"verse_text": "Let every thing that hath breath praise the LORD. Praise ye the LORD.",
		"body_html": "<p>You woke up today. You are breathing. That alone is a gift from the God who made you and "
		"still holds your life in His hands.</p><p>The world teaches us to complain. God invites us to praise. When "
		"we worship, our eyes are lifted from our problems to the One who is bigger than all of them, and a cold "
		"heart begins to feel His warmth again.</p><p>If you have breath, you have a reason to praise Him.</p>",
		"action": "Sing one song of praise to God today, and thank Him for three things.",
		"app_route": "/dashboard",
		"app_button": "Sing along in the app",
		"push_title": "🎵 You still have breath",
		"push_body": "\"Let every thing that hath breath praise the LORD.\" Sing one song to Him today.",
	},
	{
		"title": "❤️ Hide His Word in your heart",
		"subject": "One verse can change your whole day",
		"preheader": "Let God's Word stay with you.",
		"verse_ref": "Psalm 119:11",
		"verse_text": "Thy word have I hid in mine heart, that I might not sin against thee.",
		"body_html": "<p>Our minds are full all day: news, worries, noise. What we keep thinking about slowly shapes "
		"who we become.</p><p>God invites us to keep His Word in our hearts. One verse, carried through the day and "
		"thought about again and again, can guard us from sin, calm our fears, and remind us that God is near.</p>"
		"<p>The heart that holds God's Word is never truly alone.</p>",
		"action": "Read today's verse slowly three times. Carry it with you all day, and ask God what He is saying "
		"to you.",
		"app_route": "/todayVerse",
		"app_button": "Read today's verse",
		"push_title": "❤️ Hide His Word in your heart",
		"push_body": "\"Thy word have I hid in mine heart.\" Carry today's verse with you.",
	},
	{
		"title": "🕊️ Awake — the Spirit gives life",
		"subject": "Awake, you who sleep",
		"preheader": "God can bring a dead heart back to life.",
		"verse_ref": "John 6:63",
		"verse_text": "It is the spirit that quickeneth; the flesh profiteth nothing: the words that I speak unto you, "
		"they are spirit, and they are life.",
		"body_html": "<p>Many people are alive on the outside but asleep on the inside: busy, successful, yet empty "
		"before God. The Bible calls out to them: <i>\"Awake thou that sleepest, and arise from the dead, and Christ "
		"shall give thee light\"</i> (Ephesians 5:14).</p><p>We can't wake ourselves up. It is God's Holy Spirit who "
		"gives life. He opens our eyes to see our need, turns our hearts back to Jesus, and leads us day by day.</p>"
		"<p>If something in you is stirring as you read this, that may be Him calling you.</p>",
		"action": "Pray today: \"Holy Spirit, wake me up. Open my eyes to Jesus, and lead me.\"",
		"app_route": "/prayer",
		"app_button": "Pray in the app",
		"push_title": "🕊️ Awake, you who sleep",
		"push_body": "\"It is the spirit that quickeneth.\" Ask the Holy Spirit to wake your heart today.",
	},
	{
		"title": "✝️ Don't just hear it — live it",
		"subject": "Hearing God's Word is good. Doing it changes everything.",
		"preheader": "Faith becomes real when we obey.",
		"verse_ref": "James 1:22",
		"verse_text": "But be ye doers of the word, and not hearers only, deceiving your own selves.",
		"body_html": "<p>It's possible to hear sermons, read verses and still stay the same. The Bible says that's "
		"deceiving ourselves.</p><p>God's Word comes alive when we do what it says: when we forgive because He "
		"said forgive, when we stop what He told us to stop, when we trust Him enough to obey.</p><p>Obedience "
		"isn't how we earn God's love. It's how we show we've truly received it.</p>",
		"action": "Think of one thing God has already shown you to do, or to stop doing. Do it today.",
		"app_route": "/courseList",
		"app_button": "Grow with a Bible course",
		"push_title": "✝️ Don't just hear it — live it",
		"push_body": "\"Be ye doers of the word, and not hearers only.\" Do one thing God has shown you today.",
	},
	{
		"title": "🤝 From death to life — through love",
		"subject": "The proof that you've passed from death to life",
		"preheader": "Love is the sign of a heart God has awakened.",
		"verse_ref": "1 John 3:14",
		"verse_text": "We know that we have passed from death unto life, because we love the brethren. He that loveth "
		"not his brother abideth in death.",
		"body_html": "<p>How do we know a heart has truly come alive to God? The Bible gives a simple answer: love.</p>"
		"<p>A heart that holds bitterness and unforgiveness is still living in death. But when Christ makes us "
		"alive, He gives us His love for others: to forgive, to help, to encourage, to pray for those who are "
		"hurting.</p><p>Somebody near you needs that love today.</p>",
		"action": "Forgive someone, help someone, or pray for someone today. Start with a prayer request on the "
		"Prayer Wall.",
		"app_route": "/prayerWall",
		"app_button": "Pray for someone",
		"push_title": "🤝 From death to life",
		"push_body": "\"We have passed from death unto life, because we love.\" Pray for someone on the Prayer Wall.",
	},
]
