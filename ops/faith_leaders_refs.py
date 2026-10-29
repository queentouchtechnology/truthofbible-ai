"""Faith Leaders: drop the "Short Lesson (Adults)" lessons and give every "Brief Lesson (All Ages)" the
references from the teaching notes - each point with its passage, its Youth Truth and its cross references,
then the chapter's memory verses.

Only lessons this tooling created are changed (Short Lesson / Brief Lesson); the chapters' own lessons are
never edited or deleted. Safe to re-run: the references section is rebuilt, not appended twice.

Run inside the Frappe container:
    cd /home/frappe/frappe-bench/sites && ../env/bin/python faith_leaders_refs.py          # dry run
    cd /home/frappe/frappe-bench/sites && ../env/bin/python faith_leaders_refs.py --apply
"""
import json
import random
import string
import sys
import time

COURSE = "faith-leaders-learning-faith-through-bible-heroes"
SITE = "learn.truthofbible.org"
SECTION = "Key Truths & Bible References"

# chapter title -> ([(point, passage, youth truth, [cross references])], memory verses)
REFS = {
    "1. Hannah": ([
        ("Pain Did Not Stop Her Faith", "1 Samuel 1:5–7", "Pain should not push you away from God — it should push you closer to Him.",
         ["Psalm 34:18 – The Lord is close to the brokenhearted.", "Matthew 11:28 – Come to Me… I will give you rest."]),
        ("She Took Her Pain to God, Not People", "1 Samuel 1:10–11; Luke 1:45", "Real faith believes before it sees.",
         ["Hebrews 11:1 – Faith is the substance of things hoped for.", "Mark 11:24 – Believe that you receive."]),
        ("She Stayed Humble When Misunderstood", "1 Samuel 1:13–16", "Your reaction in misunderstanding reveals your character.",
         ["Proverbs 15:1 – A gentle answer turns away wrath.", "James 1:19 – Be slow to speak, slow to anger."]),
        ("She Received Peace Before the Answer", "1 Samuel 1:18", "God often gives peace before He gives the answer.",
         ["Philippians 4:6–7 – The peace of God guards your heart.", "John 14:27 – My peace I give to you."]),
        ("God Answered Her Prayer", "1 Samuel 1:19–20", "God never ignores sincere prayers.",
         ["Jeremiah 33:3 – Call to Me, and I will answer you.", "Psalm 65:2 – You who hear prayer."]),
        ("She Honored God Above Her Feelings", "1 Samuel 1:27–28", "True faith keeps promises even when it is hard.",
         ["Ecclesiastes 5:4 – Fulfil your vows to God.", "John 14:15 – If you love Me, keep My commandments."]),
        ("Faithfulness in Small Things Matters", "1 Samuel 2:19", "Faithfulness is shown in small, consistent actions.",
         ["Luke 16:10 – Faithful in little, faithful in much.", "Galatians 6:9 – Do not grow weary in doing good."]),
        ("God Honored Her Faithfulness", "1 Samuel 2:21, 30", "When you honor God, God will honor you.",
         ["Matthew 6:33 – Seek first the kingdom of God.", "Proverbs 3:9–10 – Honor the Lord… and He will bless you."]),
        ("The Great Lesson from Hannah", "", "Waiting is not wasting — it is God preparing something greater.",
         ["Isaiah 40:31 – Those who wait on the Lord will renew their strength.", "Romans 8:28 – God works all things for good."]),
    ], ""),
    "2. Ruth": ([
        ("Good People Still Face Hard Times", "Ruth 1:1–5", "Being good does not mean life will always be easy.",
         ["John 16:33 – In this world you will have trouble.", "Psalm 34:19 – The righteous face many troubles."]),
        ("When People Forget You, God Still Sees You", "Ruth 1:20–21", "You may feel forgotten by people — but you are never forgotten by God.",
         ["Isaiah 49:15 – I will not forget you.", "Psalm 139:7–10 – God is always with you."]),
        ("Faith Means Choosing God Over Comfort", "Ruth 1:16", "True faith chooses God, even when it is difficult.",
         ["Matthew 6:33 – Seek first the kingdom of God.", "Joshua 24:15 – Choose whom you will serve."]),
        ("Faithfulness in Small Things Matters", "Ruth 2:2–3", "Small acts of faithfulness are never small to God.",
         ["Luke 16:10 – Faithful in little, faithful in much.", "Galatians 6:9 – Do not grow weary in doing good."]),
        ("God Rewards Quiet Obedience", "Ruth 2:12", "God rewards those who obey Him — even in secret.",
         ["Matthew 6:4 – Your Father who sees in secret will reward you.", "Hebrews 11:6 – God rewards those who seek Him."]),
        ("God Turns Loss into Restoration", "Ruth 4:13–17", "God can restore what you have lost — and give you more.",
         ["Joel 2:25 – I will restore the years the locust has eaten.", "Psalm 30:5 – Joy comes in the morning."]),
        ("God's Plan Is Bigger Than You See", "Ruth 4:17", "Your present situation does not limit your future.",
         ["Romans 8:28 – God works all things for good.", "Jeremiah 29:11 – Plans to give you hope and a future."]),
        ("God Honors Faithful Hearts", "", "When you stay faithful, God will lift you at the right time.",
         ["1 Samuel 2:30 – Those who honor Me, I will honor.", "James 4:10 – Humble yourselves, and He will lift you up."]),
        ("The Great Lesson from Ruth", "", "God can turn your lowest moment into your greatest testimony.",
         ["2 Corinthians 5:7 – Walk by faith, not by sight.", "Isaiah 61:3 – Beauty for ashes."]),
    ], ""),
    "3. Esther": ([
        ("God Sees More Than What People See", "Esther 2:7", "God sees your future, not just your present.",
         ["1 Samuel 16:7 – God looks at the heart.", "Jeremiah 29:11 – God has a plan for your future."]),
        ("God Can Lift Anyone from Anywhere", "Esther 2:8", "You don't need to be the best — you need God's favor.",
         ["Psalm 75:6–7 – Promotion comes from God.", "James 4:10 – Humble yourself, and He will lift you up."]),
        ("Waiting Time Is Training Time", "Esther 2:12", "Delay is not denial — it is preparation.",
         ["Isaiah 40:31 – Those who wait on the Lord renew their strength.", "Romans 8:25 – Wait patiently."]),
        ("Stay Humble When God Lifts You", "Esther 2:17", "Success should not change your character.",
         ["Proverbs 22:4 – Humility brings honor.", "1 Peter 5:6 – God exalts the humble."]),
        ("Courage Begins Where Comfort Ends", "Esther 4:11", "Feeling afraid is normal — but staying silent is dangerous.",
         ["Isaiah 41:10 – Do not fear, I am with you.", "2 Timothy 1:7 – God has not given us a spirit of fear."]),
        ("Small Faith Can Do Great Things", "Esther 4:16", "Even small faith becomes powerful in God's hands.",
         ["Matthew 17:20 – Faith like a mustard seed.", "Mark 11:22 – Have faith in God."]),
        ("God Gives Favor at the Right Time", "Esther 5:2–3", "When you step out in faith, God releases favor.",
         ["Proverbs 3:5–6 – Trust in the Lord… He will direct your path.", "Psalm 5:12 – God surrounds us with favor like a shield."]),
        ("God Lifts the Humble to Great Places", "Esther 1:6–8", "God can lift your life beyond what you imagine.",
         ["Luke 1:52 – God lifts the humble.", "Ephesians 3:20 – God does more than we ask or imagine."]),
        ("The Great Lesson from Esther", "", "God uses ordinary people who are willing to trust Him.",
         ["Romans 8:28 – God works all things for good.", "Joshua 1:9 – Be strong and courageous."]),
    ], ""),
    "4. Samson": ([
        ("God Had a Plan for Samson", "Judges 13:5", "God's plan protects us — walking away from it exposes us.", []),
        ("First Betrayal → Anger → Destruction", "Judges 14:20; 15:5–6", "Anger instead of repentance only brings more loss.", []),
        ("Depression Led Him Away from God", "Judges 16:1", "When we avoid God in our pain, sin becomes our false comfort.", []),
        ("No Peace — Only More Trouble", "Judges 16:2–3", "Sin promises peace, but it delivers trouble.", []),
        ("Final Love, Final Betrayal", "Judges 16:4–5", "When love is not led by God, it can lead to destruction.", []),
        ("The Downward Fall of Sin", "Judges 16:21, 25–26", "Sin always takes more than it promises.", []),
        ("Repentance & God's Grace", "Judges 16:28", "By mercy and truth iniquity is purged.", ["Proverbs 16:6 – By mercy and truth iniquity is purged."]),
        ("Jesus Came for This Reason", "Matthew 1:21", "Grace was given — but many sorrows could have been avoided.",
         ["Matthew 1:21 – He shall save his people from their sins."]),
        ("Final Warning to Youth", "", "Sin starts small, grows silently, and rewards destruction — turn back now.", []),
    ], "Proverbs 16:6 · Life of Jesus: Matthew 1:21"),
    "5. Job": ([
        ("God Called Job Faithful — Before the Trial", "Job 1:1, 8", "A good life does not mean a trouble-free life.", []),
        ("Everything Was Taken — But Faith Was Not", "Job 1–2", "Silence before God is better than rebellion against God.", ["Job 2:13 – They sat with him seven days and seven nights."]),
        ("When Job Spoke — He Hated Himself, Not God", "Job 3:1; 2:5", "You can question life and still remain faithful.", []),
        ("The Most Difficult Test: Life Looked Unfair", "Job 21:7–12", "The hardest test of faith is watching the unfaithful succeed while you suffer.", []),
        ("Still Faithful — Even When God Felt Silent", "Job 21–37", "Real faith stays even when answers don't come quickly.", []),
        ("God Spoke — And Faith Was Vindicated", "Job 38–41", "Faith grows when we trust God's wisdom over our understanding.", []),
        ("God Publicly Honored Job's Faithfulness", "Job 42:7", "God notices faith that survives confusion.", []),
        ("Restoration Came After Faithfulness", "Job 42:10–15", "God may allow delay — but He never forgets faithfulness.", []),
    ], "Psalm 109:31 · Life of Jesus: Luke 1:79"),
    "6. Moses / Hezekiah": ([
        ("The Faithful Are Taken to Peace — Not Lost", "Isaiah 57:1–2", "Death for the faithful is not punishment — it is protection.", []),
        ("God Removes the Righteous to Escape Greater Trouble", "Job 3:17", "God sees dangers we cannot see.", []),
        ("What Is the “Peaceful Place”?", "Luke 16:22", "God does not abandon His faithful — He receives them.", []),
        ("No More Pain, Crying, or Earthly Burden", "Luke 16:25", "God defends His faithful — they don't need to defend themselves anymore.", []),
        ("When We Resist God's Will — Trouble Follows", "Isaiah 38:1–5, 15", "Not every answered prayer leads to blessing.", []),
        ("Extended Life Brought New Problems", "Isaiah 39:2", "Pride and foolish decisions can follow a long-awaited answer.", []),
        ("Consequences Fell on His Family", "2 Kings 20:18; 24:12", "Disobeying God can affect future generations.", []),
        ("He Asked Only for More Life — Not Wisdom", "", "God's timing is wiser than our emotions.", []),
        ("Moses Accepted God's Decision", "Deuteronomy 3:25–26", "True faith accepts God's “No” as well as His “Yes.”", []),
        ("Moses Was Spared Future Pain", "Deuteronomy 31:16–17, 27", "Sometimes God takes His servants early to protect their hearts.", []),
        ("God Personally Cared for Moses' Ending", "Deuteronomy 33:3", "A life surrendered to God ends safely in His hands.", []),
    ], "Isaiah 57:1–2 · Life of Jesus: Luke 2:29"),
    "7. Saul": ([
        ("From the Smallest Clan to God's Choice", "1 Samuel 9:21", "God does not look at your background — He looks at your heart.", []),
        ("God Lifted Him from Low to High", "1 Samuel 9:3; 10:6, 10, 16", "God's power can transform an ordinary life into an extraordinary one.", []),
        ("Disobedience Began the Fall", "1 Samuel 15:14, 19", "Partial obedience is still disobedience.", []),
        ("Jealousy Entered His Heart", "1 Samuel 17:56; 18:9", "Pride cannot tolerate someone else being honored.", []),
        ("From Trusting God to Seeking Darkness", "1 Samuel 28:8", "When we stop listening to God, we become vulnerable to wrong voices.",
         ["Exodus 22:18", "Leviticus 19:31", "Leviticus 20:6 – Do not seek mediums or fortune tellers."]),
        ("God Rejected Him as King", "1 Chronicles 10:13–14", "Disobedience does not destroy instantly — it destroys gradually.", []),
        ("The Tragic Contrast", "", "Your beginning does not determine your future — your choices do.", []),
    ], "Leviticus 20:6 · Life of Jesus: Luke 3:9"),
    "8. Gideon": ([
        ("From Fearful to Chosen", "Judges 6:11–12, 15", "God sees your future potential, not just your present weakness.",
         ["1 Samuel 16:7 – Man looks at the outward appearance, but the Lord looks at the heart.", "Jeremiah 1:5 – Before I formed you in the womb I knew you."]),
        ("God Knows Every Detail About Us", "Judges 6:25; 7:10–11", "God knows every detail about your life.",
         ["Psalm 139:1–4 – God knows our thoughts and words.", "Matthew 10:30 – Even the hairs of your head are numbered."]),
        ("God's Strength Works in Weak People", "Judges 6:14", "When God is with you, weakness becomes strength.",
         ["2 Chronicles 14:11 – It is nothing with Thee to help, whether with many or with them that have no power.",
          "2 Corinthians 12:9 – My power is made perfect in weakness.", "Philippians 4:13 – I can do all things through Christ who strengthens me."]),
        ("Gideon First Obeyed in Private", "Judges 6:25–27", "God prepares great leaders through small hidden acts of obedience.",
         ["Luke 16:10 – Faithful in little, faithful in much.", "James 1:22 – Be doers of the word, not hearers only."]),
        ("God Reduced the Army", "Judges 7:2", "God sometimes reduces our strength so His power can be seen.",
         ["Zechariah 4:6 – Not by might nor by power, but by My Spirit.", "Psalm 20:7 – Some trust in chariots… but we trust in the Lord."]),
        ("Victory Came Through Faith", "Judges 7:20–21", "Victory comes when we trust God's strategy, not human wisdom.",
         ["Proverbs 3:5 – Trust in the Lord with all your heart.", "1 Samuel 17:47 – The battle belongs to the Lord."]),
        ("The Real Strength of Gideon", "Luke 4:4", "True spiritual strength comes from living by God's Word.",
         ["Matthew 7:24 – The wise man builds on the rock.", "Joshua 1:8 – Meditate on the Word day and night."]),
        ("The Great Lesson from Gideon", "", "Fear cannot stop God's plan when we trust Him.",
         ["Isaiah 41:10 – Do not fear, I am with you.", "2 Timothy 1:7 – God has not given us a spirit of fear.",
          "Psalm 139:16 – All the days of our life are known to God."]),
    ], "2 Chronicles 14:11 · Life of Jesus: Luke 4:4"),
    "9. Joshua": ([
        ("Key Truth: God Can Glorify Any Person", "John 1:9", "God gives opportunity to everyone, but responsibility determines destiny.",
         ["Matthew 7:24 – Whoever hears these sayings of Mine and does them is like a wise man.", "James 1:22 – Be doers of the word, and not hearers only."]),
        ("God Chose Joshua — An Ordinary Man", "Exodus 24:13", "God does not look for famous people. He looks for faithful people — and prepares leaders in hidden places before public places.",
         ["1 Samuel 16:7 – The Lord looks at the heart.", "Luke 16:10 – Faithful in what is least, faithful also in much.",
          "Proverbs 22:29 – A man diligent in his work will stand before kings.", "1 Peter 5:6 – Humble yourselves… that He may exalt you in due time."]),
        ("God's Secret for Success", "Joshua 1:8", "Success in God's kingdom is not about talent — it is about obedience to His Word. Victory begins in the mind before it appears in life.",
         ["Psalm 1:2–3 – Like a tree planted by the rivers of water.", "Romans 12:2 – Be transformed by the renewing of your mind.",
          "Psalm 119:11 – Your word I have hidden in my heart.", "Colossians 3:16 – Let the word of Christ dwell in you richly."]),
        ("God Began to Glorify Joshua", "Joshua 3:7", "Promotion that comes from God is stronger than promotion from people.",
         ["Psalm 75:6–7 – Promotion comes neither from the east nor the west.", "1 Samuel 2:30 – Those who honor Me I will honor.",
          "Matthew 23:12 – Whoever humbles himself will be exalted."]),
        ("The Jordan River Miracle", "Joshua 3:16–17", "When we step forward in faith, God opens impossible paths.",
         ["Isaiah 43:16 – The Lord makes a way in the sea and a path through the mighty waters."]),
        ("The Fall of Jericho", "Joshua 6:20", "God's plans may not always make sense to us, but obedience brings victory.",
         ["Isaiah 55:8–9 – My ways are higher than your ways.", "1 Corinthians 1:25 – The foolishness of God is wiser than men.",
          "John 14:15 – If you love Me, keep My commandments.", "Proverbs 3:5–6 – He will direct your paths."]),
        ("The Day the Sun Stood Still", "Joshua 10:12–13", "Bold prayers often come from people who walk closely with God.",
         ["James 5:16 – The prayer of a righteous person is powerful and effective.", "Jeremiah 33:3 – Call to Me, and I will answer you.",
          "Mark 11:24 – Believe that you receive them."]),
        ("The Result of Joshua's Obedience", "Joshua 4:14", "Consistency in obedience produces lasting influence.",
         ["Galatians 6:9 – Let us not grow weary in doing good.", "Psalm 37:5 – Commit your way to the Lord."]),
        ("Final Call", "Joshua 24:15", "As for me and my house, we will serve the Lord.", []),
    ], "Joshua 1:8 · Life of Jesus: John 1:9"),
    "10. Jeremiah": ([
        ("God's Original Command", "Jeremiah 1:18–19", "If God is with you, opposition is normal — defeat is not.",
         ["Romans 8:31 – If God is for us, who can be against us?", "Isaiah 41:10 – Do not fear, I am with you."]),
        ("God's Invisible Protection", "Jeremiah 36:26", "When you are in God's will, no one can touch you unless God allows it.",
         ["Psalm 91:1 – He who dwells in God's shelter is safe.", "Isaiah 54:17 – No weapon formed against you shall prosper."]),
        ("Fear Can Shake Your Faith", "Jeremiah 37:12–13, 20; 38:5", "Fear makes you forget what God already told you.",
         ["2 Timothy 1:7 – God has not given us a spirit of fear.", "Proverbs 29:25 – The fear of man is a trap."]),
        ("Fear Brings Consequences", "Jeremiah 37:14–16", "When you follow fear, problems increase step by step.",
         ["Jonah 1:3 – Running from God leads to trouble.", "Galatians 6:7 – You reap what you sow."]),
        ("God Gives Another Chance", "Jeremiah 37:21", "Failure is not the end. God gives second chances.",
         ["Isaiah 42:3 – A bruised reed He will not break.", "Psalm 37:24 – Though he falls, he will not be cast down."]),
        ("Faith Begins to Grow", "Jeremiah 38:1–3", "Real faith speaks truth even in difficult places.",
         ["Acts 4:20 – We cannot stop speaking what we have seen.", "Romans 1:16 – Not ashamed of the Gospel."]),
        ("God Tests Him Again", "Jeremiah 38:14–18", "God will test you again to see if your faith has grown.",
         ["James 1:3 – Testing produces perseverance.", "1 Peter 1:7 – Faith is refined by trials."]),
        ("Fear Is Gone, Faith Is Strong", "Jeremiah 38:24", "When you fear God, you will not fear people.",
         ["Matthew 10:28 – Fear God, not man.", "Psalm 56:3 – When I am afraid, I trust in You."]),
        ("God Honors His Faith", "Jeremiah 39:11–12", "God can make your enemies favor you.",
         ["Proverbs 16:7 – God makes even enemies be at peace.", "Psalm 23:5 – A table before my enemies."]),
        ("Freedom in the Same Place", "Jeremiah 40:1–6", "God can give you peace and freedom even in the same situation others suffer in.",
         ["John 8:36 – Whom the Son sets free is free indeed.", "Philippians 4:7 – Peace that surpasses understanding."]),
        ("The Great Lesson from Jeremiah", "Mark 4:40", "Fear may come… but faith must win.",
         ["Romans 8:31 – If God is for us, who can be against us?", "Hebrews 11:6 – Without faith it is impossible to please God."]),
    ], "Isaiah 42:3 · Life of Jesus: Mark 4:40"),
    "11. Jacob": ([
        ("People's Words Fail — Only God's Word Stands", "Genesis 27:41–45; 28:15", "Human words depend on situations; God's Word controls situations.", []),
        ("Some People's True Nature Is Revealed in Separation", "Genesis 29:25; 31:7", "People may use you — but God will build you.", []),
        ("In Loneliness, God Shows How Good He Is", "Genesis 31:42", "People stay with you for benefit; God stays with you for your good.", []),
        ("In the End, God Multiplies Beyond Imagination", "Genesis 32:10", "God doesn't just protect you — He expands your life.", []),
        ("Final Understanding", "Genesis 49:10, 27", "Not everyone who looks strong is chosen for authority — God's chosen line alone will remain.", []),
    ], "Genesis 28:15 · Life of Jesus: Mark 6:50"),
    "12. Jonah": ([
        ("Key Truth: Faith Brings Forgiveness", "Luke 5:20", "Faith in God brings forgiveness; forgiveness transforms life.", []),
        ("What Happens When You Have Faith?", "Luke 5:25–26", "When you trust God, your life becomes a living testimony.", []),
        ("What Happens Without Faith?", "Jonah 1:1–3", "Every decision outside God's will leads to loss.", []),
        ("God's Hand Will Oppose Disobedience", "Jonah 1:4", "A disobedient life creates storms — for you and the people around you.", []),
        ("“I Can Handle It Myself”", "Jonah 1:12, 17", "You cannot escape when you run from God.", []),
        ("Deep Struggles & Pressure", "Jonah 2:5", "Life breaks down step by step when we leave God.",
         ["Psalm 69:7 – Shame in the family.", "Psalm 69:9 – Rejection from people.", "Psalm 69:12 – People talk against you.",
          "Psalm 69:20 – No one to comfort."]),
        ("The Turning Point", "Jonah 2:7–8", "Don't wait to lose everything before turning to God.",
         ["Psalm 71:7 – You are my strong refuge.", "Jonah 2:8 – Following false things forsakes God's mercy."]),
        ("What Happens When You Return?", "Psalm 71:20–21", "God revives you, lifts you again and comforts you.", []),
        ("Restoration & Purpose", "Jonah 3:1–3, 7", "God gives second chances.", []),
        ("Final Impact", "Jonah 4:11", "When you walk in God's will, your life blesses thousands.", []),
    ], "Luke 5:20"),
    "13. David / Solomon": ([
        ("David's Charge to Solomon", "1 Kings 2:1–4", "Strength for leadership comes from keeping God's ways.",
         ["Joshua 1:7–8 – Turn not from it to the right hand or to the left.", "Psalm 1:1–3 – Blessed is the man who delights in God's law."]),
        ("Solomon Asked for Wisdom", "1 Kings 3:5–9", "Knowing your need is the beginning of wisdom.",
         ["James 1:5 – If any of you lack wisdom, let him ask of God.", "Proverbs 2:6 – The Lord gives wisdom."]),
        ("God Gave More Than He Asked", "1 Kings 3:10–14", "Seek God first, and He adds the rest.", ["Matthew 6:33 – Seek first the kingdom of God."]),
        ("A Heart That Repents", "2 Samuel 12:13", "Failure doesn't have to be final when we truly repent.", ["Psalm 51:10 – Create in me a clean heart, O God."]),
        ("Finish Well", "1 Kings 11:4", "A good start isn't enough — keep walking in God's ways to the end.",
         ["2 Timothy 4:7 – I have finished my course, I have kept the faith.", "Hebrews 12:1–2 – Run with patience, looking unto Jesus."]),
    ], ""),
    "14. John the Baptist": ([
        ("Called in the Wilderness", "Luke 3:2–4", "God's word can reach you in any place.", ["Isaiah 40:3 – Prepare ye the way of the Lord."]),
        ("Fruits of Repentance", "Luke 3:8–14", "Repentance shows up in honesty and generosity.", []),
        ("Pointing Everyone to Jesus", "Luke 3:16", "Make Jesus greater, not yourself.",
         ["John 3:30 – He must increase, but I must decrease.", "John 1:29 – Behold the Lamb of God."]),
        ("Courage Before Kings", "Luke 3:19–20", "Truth may cost you, but God honours it.",
         ["Luke 7:28 – Among those born of women there is no greater prophet than John.", "Matthew 11:11"]),
    ], ""),
    "15. Judah": ([
        ("A Bad Start", "Genesis 37:26–27", "A wrong choice doesn't have to be the end of your story.", []),
        ("A Changing Heart", "Genesis 38:26", "Admitting our wrong is the first step of change.",
         ["1 John 1:9 – If we confess our sins, He is faithful to forgive.", "Proverbs 28:13 – Whoever confesses and forsakes his sins shall have mercy."]),
        ("He Pledged Himself", "Genesis 43:8–9", "Real leaders take responsibility for others.", []),
        ("He Stood in the Gap", "Genesis 44:18–34", "Leaders stand in the gap for others.",
         ["John 15:13 – Greater love has no one than this.", "Ezekiel 22:30 – I sought for a man… to stand in the gap."]),
        ("The Sceptre Shall Not Depart", "Genesis 49:8–10", "God can bring a royal line out of a changed life.",
         ["Revelation 5:5 – The Lion of the tribe of Judah.", "Matthew 1:3 – Judah in the family line of Jesus."]),
    ], ""),
    "16. Nehemiah": ([
        ("What Does “Watch” Mean?", "Matthew 25:13", "Being spiritually awake means doing God's work, staying alert, and living with God first.",
         ["Mark 13:33 – Take heed, watch and pray.", "1 Peter 4:7 – Be sober, and watch unto prayer.", "Matthew 6:24 – No one can serve two masters."]),
        ("What God Does for Those Who Watch", "Deuteronomy 30:20", "He is your life and the length of your days.", []),
        ("Faithful in His Work", "Nehemiah 1:11; 2:1", "Be faithful where God has placed you.", []),
        ("Awakened by the News", "Nehemiah 1:2–3", "Spiritual wakefulness begins when we feel what God feels.", []),
        ("He Prayed Day and Night", "Nehemiah 1:6", "Those who are awake pray.", []),
        ("God's Work Before His Comfort", "Nehemiah 2:5", "Put God's purpose ahead of your own ease.", []),
        ("He Built the Wall", "Nehemiah 2:17; 7:1", "With God's help, what grieves you can be rebuilt.", []),
        ("God Lifted Him Up", "Nehemiah 5:14, 17–18", "God lifts up and gives meaning to the lives of those who watch.", []),
    ], "Matthew 25:13"),
    "17. Ezekiel": ([
        ("Who Is the One Who “Has”?", "Matthew 25:29, 21", "Not the one with the most, but the one who is faithful and responsible with what God gave.", []),
        ("Who Is the One Who “Has Not”?", "Matthew 25:26, 30", "Laziness and a wrong view of God lose even what we have.", []),
        ("What the Faithful Receive", "Matthew 25:21", "Enter into the joy of your Lord.",
         ["Ezekiel 37:24–26 – A covenant of peace, and God's sanctuary among His people for ever."]),
        ("Faithful as a Watchman", "Ezekiel 3:17, 27", "Speak only what God gives you to speak.", ["Ezekiel 1:1 – Among the captives by the river Chebar."]),
        ("First Hardship – Restless Days", "Ezekiel 4:4–6", "Obey even when the assignment is heavy.", []),
        ("Second Hardship – A Sign of Shame", "Ezekiel 5:1–3, 14", "Faithfulness doesn't depend on how it looks to others.", []),
        ("Third Hardship – Losing His Wife", "Ezekiel 24:16–18, 25", "He did not complain, run, or demand to know why.", []),
        ("The Outcome", "Ezekiel 14:22–23", "God never acts without cause; He is righteous in all He does.",
         ["Nehemiah 9:33 – You are just in all that has come upon us; You have dealt faithfully."]),
    ], "Matthew 25:29"),
    "18. Mordecai": ([
        ("Love Your Neighbour as Yourself", "Galatians 5:14", "Treat others the way you want to be treated.",
         ["Zechariah 8:16 – Speak the truth to one another.", "Zechariah 8:17 – Do not plan evil in your heart against your neighbour."]),
        ("What Happens Without Love?", "Galatians 5:15", "A life without love ends in destruction.", []),
        ("Walk in the Spirit", "Galatians 5:16", "Follow the Spirit's leading, not the desires of the flesh.",
         ["Ephesians 5:9 – The fruit of the Spirit is in all goodness, righteousness and truth.",
          "John 6:63 – The words I speak to you are spirit and life.", "Deuteronomy 11:25–26 – A blessing and a curse set before you."]),
        ("Mordecai's Turning Point", "Esther 3:2–6; 4:1", "He saw the destruction that had begun.", []),
        ("Seek God First", "Esther 4:8, 16–17", "Make room for God's warning and guidance instead of holding on to our own way.", []),
        ("Lust of the Eyes, the Flesh, and Pride", "1 John 2:16", "Giving way to these begins destruction; giving way to the Spirit brings blessing.", []),
    ], "Galatians 5:14"),
    "19. Noah": ([
        ("Never Hungry, Never Thirsty", "John 6:35", "Those who come to Jesus stop looking to the world for satisfaction.", []),
        ("A Full Heart", "", "When we are full of God's word, the world's attractions lose their pull.", []),
        ("Who May Come to Jesus?", "Revelation 22:17", "Those who hear, those who thirst, and whoever is willing.", []),
        ("Noah – Shining in a Dark World", "Genesis 6:1–4, 8–9", "While others looked at the world, Noah walked with God.", []),
        ("Safe in the Midst of Destruction", "Genesis 7:1", "Walking with God brings protection.", []),
        ("God's Blessing", "Genesis 9:1", "God blessed Noah and his sons.", []),
        ("A Long Life", "Genesis 9:28", "Noah lived 350 years after the flood.", []),
        ("Wake Up", "Ephesians 5:14", "Awake, and Christ shall give you light.", []),
    ], "John 6:35"),
    "20. The Shunammite Woman": ([
        ("Jesus Came to Seek the Lost", "Luke 19:10", "Some the Lord seeks; some must seek the Lord.", []),
        ("Who Must Seek the Lord?", "Deuteronomy 4:25–30", "Those who have drifted from God must turn back to Him.", []),
        ("How to Seek Him", "Deuteronomy 4:29", "With all your heart and all your soul — and you will find Him.", []),
        ("She Took Her Problem to God First", "2 Kings 4:21", "When trouble comes, go to God first.", []),
        ("She Didn't Tell Everyone on the Way", "2 Kings 4:24", "We don't have to take our problem to everyone.", []),
        ("She Wanted No Other Answer", "2 Kings 4:29–30", "Hold on to God alone — not a substitute.", []),
    ], "Deuteronomy 4:29"),
    "21. Samuel": ([
        ("Sin No More", "John 5:14", "God speaks this to those who stand with Him and trust Him alone.", []),
        ("The Light of Life", "John 8:12", "Those who follow Jesus will not walk in darkness.", []),
        ("God's Promise", "Isaiah 9:2–5", "He multiplies, increases joy, and gives peaceful days.", []),
        ("Who Samuel Was", "1 Samuel 3:10, 19–21", "God spoke with him and let none of his words fall to the ground.", []),
        ("Overlooked", "1 Samuel 4:3, 13–18, 22; 7:2", "For about twenty years Samuel was forgotten by the people.", []),
        ("Sought by Those Who Did Not Ask", "Isaiah 65:1", "God makes the overlooked to be sought after.", []),
        ("Sought by All Israel", "1 Samuel 7:8, 14; 9:11", "Through his prayer and counsel, God restored what was lost.", []),
    ], "Isaiah 65:1"),
    "22. Joseph": ([
        ("Who Can Heal a Broken Heart?", "Psalm 147:3", "Only the Spirit of the Lord can heal it completely.", []),
        ("How the Spirit Heals", "Isaiah 57:15", "He dwells with the humble and revives the broken heart.", []),
        ("Be Joined to the Lord", "1 Corinthians 6:17", "Live by His will and choose what pleases Him.", []),
        ("Flee and Glorify God", "1 Corinthians 6:18, 20", "Run from impurity; glorify God in body and spirit.", []),
        ("Firm When Others Did Wrong", "Genesis 37:2–3", "Stay true to God even when everyone around you doesn't.", []),
        ("Firm When His Father Rebuked Him", "Genesis 37:10–11", "Don't deny what God has shown you.", []),
        ("Firm When He Had Power and Freedom", "Genesis 39:8–9", "Flee sin out of the fear of God, not the fear of man.", []),
    ], "Psalm 147:3"),
    "23. Deborah": ([
        ("If You Can Believe", "Mark 9:23; Luke 9:40", "Don't think God can't, just because people couldn't.", []),
        ("Changing What Has Been Since Childhood", "Mark 9:21, 24", "Believe God can change even a long-standing problem.", []),
        ("Ehud – An Ordinary Man", "Judges 3:15–30", "God used a left-handed man to free Israel; the land had rest 80 years.", []),
        ("Shamgar – An Ordinary Tool", "Judges 3:31", "God doesn't need great people — only people who believe Him.", []),
        ("Barak Could Not Believe", "Judges 4:7–8; 5:18", "Courage without faith in God's word holds back.", []),
        ("Deborah Believed and Led", "Judges 4:9, 14; 5:2, 31", "Where others can't believe, you can — and God gave 40 years of rest.", []),
    ], "Mark 9:23"),
    "24. Jehoshaphat": ([
        ("Resurrection and Life", "John 11:25, 42", "God hears and acts at any moment.", []),
        ("God Acted Before He Asked", "2 Chronicles 17:10", "God knows what we need before we ask.", []),
        ("God Heard Him Near Death", "2 Chronicles 18:31", "However bad the situation, our cry reaches God.", []),
        ("God Fought When He Couldn't", "2 Chronicles 20:12, 15", "The battle is not yours, but God's.", []),
    ], "2 Chronicles 19:7"),
}


def _id():
    return "".join(random.choices(string.ascii_letters + string.digits, k=10))


def _block(kind, data):
    return {"id": _id(), "type": kind, "data": data}


def refs_blocks(points, memory):
    blocks = [_block("header", {"text": SECTION, "level": 3})]
    for n, (title, passage, truth, xrefs) in enumerate(points, 1):
        head = f"<b>{n}. {title}</b>" + (f" — 📖 {passage}" if passage else "")
        blocks.append(_block("paragraph", {"text": head}))
        blocks.append(_block("paragraph", {"text": f"👉 <b>Youth Truth:</b> {truth}"}))
        if xrefs:
            blocks.append(_block("list", {"style": "unordered", "items": [{"content": x, "items": []} for x in xrefs]}))
    if memory:
        blocks.append(_block("paragraph", {"text": f"<b>📖 Memory verse:</b> {memory}"}))
    return blocks


def main(apply):
    import frappe
    frappe.init(site=SITE, sites_path=".")
    frappe.connect()
    frappe.set_user("Administrator")
    for title, (points, memory) in REFS.items():
        name = frappe.db.get_value("Course Chapter", {"course": COURSE, "title": title})
        chapter = frappe.get_doc("Course Chapter", name)
        by_title = {frappe.db.get_value("Course Lesson", r.lesson, "title"): r.lesson for r in chapter.lessons}
        brief, short = by_title.get("Brief Lesson (All Ages)"), by_title.get("Short Lesson (Adults)")
        if not brief:
            print(f"SKIP {title}: no Brief Lesson")
            continue
        n_x = sum(len(p[3]) for p in points)
        print(f"{'' if apply else 'WOULD '}{title}: {len(points)} points, {n_x} cross refs"
              + (f", remove {short}" if short else ""))
        if not apply:
            continue
        doc = frappe.get_doc("Course Lesson", brief)
        content = json.loads(doc.content)
        blocks = content["blocks"]
        cut = next((i for i, b in enumerate(blocks) if b["type"] == "header" and b["data"].get("text") == SECTION), len(blocks))
        content["blocks"] = blocks[:cut] + refs_blocks(points, memory)
        content["time"] = int(time.time() * 1000)
        doc.content = json.dumps(content)
        doc.save(ignore_permissions=True)
        if short:
            rows = [r for r in chapter.lessons if r.lesson != short]
            chapter.lessons = rows
            for i, row in enumerate(chapter.lessons, 1):
                row.idx = i
            chapter.save(ignore_permissions=True)
            frappe.delete_doc("Course Lesson", short, ignore_permissions=True)
        frappe.db.commit()
    frappe.destroy()


if __name__ == "__main__":
    main("--apply" in sys.argv)
