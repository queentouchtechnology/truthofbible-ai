"""Build the English "Lesson from <leader>" lessons for Faith Leaders chapters 1-15, in the style of the
chapters' own Tamil lessons (16-24): a key verse, question headings, each reference quoted, the leader as
the example, what we learn, and a memory verse.

Every quotation is taken from the KJV in the site's Bible database, so a quote can never drift from the
text; a quoted fragment that is not in the verse stops the build.

    python ops/faith_leaders_build.py path/to/tob_bible_web.db out.json
Then faith_leaders_apply.py publishes out.json.
"""
import json
import random
import re
import sqlite3
import string
import sys
import time

BOOK_ALIASES = {"Psalm": "Psalms"}

# Each lesson: (chapter title, lesson title, [blocks]).
#   ("key", ref, part)  key verse: heading with the reference, then the quotation
#   ("rq", ref, part)   📖 reference with its quotation
#   ("r", ref)          📖 reference only
#   ("h2"|"h3"|"p", text), ("ul", [items])
#   ("mem", ref, part)  memory verse
# part=None quotes the whole verse(s); otherwise it must be an exact fragment of them.
LESSONS = [
    ("1. Hannah", "Lesson from Hannah", [
        ("key2", "Luke 1:45", None),
        ("h2", "What does “blessed is she that believed” mean?"),
        ("p", "When we believe, we don't wait to see the answer first. We trust God's word even while nothing has changed yet. That is why Elizabeth called Mary blessed — she believed before she saw."),
        ("p", "In the same way, God calls us to believe Him while we are still waiting, not only after the answer comes."),
        ("h3", "One who believes like this:"),
        ("ul", ["trusts God even when the answer is delayed", "takes the pain to God, not to people", "keeps the promise made to God"]),
        ("p", "So “blessed is she that believed” means: blessed is the one who trusts God before seeing what He will do."),
        ("h2", "Example: Hannah – a woman who believed before she saw"),
        ("p", "A great example of this is Hannah."),
        ("q", "1 Samuel 1:6", None),
        ("p", "Why was she so troubled?"),
        ("p", "She had no child, and Peninnah, her husband's other wife, mocked her for it — not once, but year after year. Hannah wept and would not eat. (📖 1 Samuel 1:7)"),
        ("p", "Yet she did not fight back, and she did not complain against God."),
        ("p", "So what did she do with her pain?"),
        ("h3", "1️⃣ She took her pain to God"),
        ("q", "1 Samuel 1:10", None),
        ("p", "She did not pour out her heart to people; she went to the house of the Lord and poured it out before God. She even made a vow: if God gave her a son, she would give him back to the Lord. (📖 1 Samuel 1:11)"),
        ("p", "This is faith. She trusted God before she saw anything change."),
        ("h3", "2️⃣ She stayed gentle when she was misunderstood"),
        ("p", "Eli the priest saw her lips moving without a sound and thought she was drunk. (📖 1 Samuel 1:13–14)"),
        ("p", "How would we have answered? Hannah did not argue and did not get angry. She answered gently:"),
        ("q", "1 Samuel 1:15", "I am a woman of a sorrowful spirit"),
        ("q", "Proverbs 15:1", "A soft answer turneth away wrath"),
        ("h3", "3️⃣ She received peace before the answer"),
        ("q", "1 Samuel 1:18", "and her countenance was no more sad"),
        ("p", "Nothing had changed yet — she still had no child. But her face changed, because she had left her burden with God. God often gives peace before He gives the answer. (📖 Philippians 4:7)"),
        ("h3", "What was the result?"),
        ("p", "God remembered Hannah."),
        ("q", "1 Samuel 1:20", None),
        ("p", "And Hannah kept her promise. When the boy was old enough, she brought him to the house of the Lord:"),
        ("q", "1 Samuel 1:28", "Therefore also I have lent him to the LORD; as long as he liveth he shall be lent to the LORD"),
        ("p", "It was not easy — she had waited so long. But she chose obedience over her feelings, and every year she made him a little coat and brought it to him. (📖 1 Samuel 2:19)"),
        ("p", "God did not forget her faithfulness."),
        ("q", "1 Samuel 2:21", None),
        ("p", "The woman who was once mocked for having no child now had six children — and her firstborn, Samuel, became the prophet who led all Israel."),
        ("h3", "What do we learn?"),
        ("ul", ["One who believes takes the pain to God first", "stays gentle when misunderstood", "receives God's peace before the answer comes", "keeps the promise made to God"]),
        ("p", "God honours those who honour Him."),
        ("mem", "1 Samuel 2:30", "for them that honour me I will honour"),
    ]),
    ("1. Hannah (previous)", "unused", [
        ("key", "Luke 1:45", None),
        ("h3", "What does “blessed is she that believed” mean?"),
        ("p", "Faith does not wait to see the answer before it trusts God. It believes first. Long before Mary, a woman named Hannah lived this way."),
        ("ul", ["Faith trusts God even when the answer is delayed.", "Faith takes its pain to God, not to people.", "Faith keeps its promise to God after the answer comes."]),
        ("h2", "The best example — Hannah"),
        ("h3", "What was Hannah's pain?"),
        ("r", "1 Samuel 1:5-7"),
        ("ul", ["She had no child.", "Her rival Peninnah provoked her year after year.", "She wept and would not eat."]),
        ("p", "Yet she did not complain and she did not fight back."),
        ("h3", "Where did she take her pain?"),
        ("rq", "1 Samuel 1:10", None),
        ("ul", ["She went to the house of the Lord.", "She poured out her heart in prayer.", "She made a vow to God (1 Samuel 1:11)."]),
        ("p", "She trusted God before she saw the answer."),
        ("h3", "How did she answer when she was misunderstood?"),
        ("r", "1 Samuel 1:13-16"),
        ("p", "Eli the priest thought she was drunk. Hannah did not argue and did not get angry. She answered gently:"),
        ("rq", "1 Samuel 1:15", "I am a woman of a sorrowful spirit"),
        ("rq", "Proverbs 15:1", "A soft answer turneth away wrath"),
        ("h3", "What happened after she prayed?"),
        ("rq", "1 Samuel 1:18", "and her countenance was no more sad"),
        ("p", "Her face changed before the answer came. God often gives peace before He gives the answer."),
        ("rq", "Philippians 4:7", None),
        ("h2", "What did God do?"),
        ("rq", "1 Samuel 1:20", None),
        ("p", "God remembered Hannah and gave her a son, Samuel — “asked of the Lord.”"),
        ("h2", "Did Hannah keep her promise?"),
        ("rq", "1 Samuel 1:27-28", None),
        ("p", "It was hard, and she had waited so long, but she chose obedience over her feelings. Every year she made Samuel a little coat and brought it to him (1 Samuel 2:19)."),
        ("h2", "What was the result?"),
        ("rq", "1 Samuel 2:21", None),
        ("ul", ["God gave her three more sons and two daughters.", "God blessed her family.", "Samuel grew before the Lord."]),
        ("h2", "What we learn"),
        ("ul", ["Take your pain to God, not to people.", "Believe before you see.", "Answer gently when you are misunderstood.", "Keep the promises you make to God.", "God honours those who honour Him."]),
        ("mem", "1 Samuel 2:30", "for them that honour me I will honour"),
    ]),
    ("2. Ruth", "Lesson from Ruth", [
        ("key", "Matthew 6:4", "and thy Father which seeth in secret himself shall reward thee openly"),
        ("h3", "Whom does the Father reward?"),
        ("p", "Not the people everyone notices, but the people who stay faithful when no one is watching."),
        ("ul", ["Those who choose God over comfort.", "Those who are faithful in small things.", "Those who obey quietly."]),
        ("h2", "The best example — Ruth"),
        ("h3", "What happened in Ruth's life?"),
        ("r", "Ruth 1:3-5"),
        ("ul", ["Her husband died.", "Her security was gone.", "Her future looked empty."]),
        ("p", "Being good does not mean life will always be easy."),
        ("rq", "John 16:33", "In the world ye shall have tribulation: but be of good cheer; I have overcome the world"),
        ("h3", "What did Ruth choose?"),
        ("p", "Naomi told both her daughters-in-law to go back home. Orpah went back (Ruth 1:14). Ruth stayed:"),
        ("rq", "Ruth 1:16", None),
        ("p", "She chose God over comfort."),
        ("rq", "Joshua 24:15", "choose you this day whom ye will serve"),
        ("h3", "How did she live in a strange land?"),
        ("r", "Ruth 2:2-3"),
        ("ul", ["Quietly", "Humbly", "Faithfully — gleaning in the fields"]),
        ("p", "No one noticed her. But God did — and so did Boaz:"),
        ("rq", "Ruth 2:12", None),
        ("h2", "What did God do?"),
        ("r", "Ruth 4:13-17"),
        ("ul", ["She received a loving husband, Boaz.", "Her life was restored.", "Her sorrow turned into joy."]),
        ("rq", "Joel 2:25", "I will restore to you the years that the locust hath eaten"),
        ("h2", "How big was God's plan?"),
        ("rq", "Matthew 1:5", None),
        ("p", "From a forgotten widow from Moab to the great-grandmother of King David and a part of the family line of Jesus."),
        ("h2", "What we learn"),
        ("ul", ["What people overlook, God remembers.", "Small acts of faithfulness are never small to God.", "What you lose, God can restore."]),
        ("mem", "Ruth 2:12", None),
    ]),
    ("3. Esther", "Lesson from Esther", [
        ("key", "Luke 1:52", None),
        ("h3", "Whom does God lift up?"),
        ("ul", ["Those of low degree.", "Those who stay humble.", "Those who are willing to trust Him."]),
        ("h2", "The best example — Esther"),
        ("h3", "Who was Esther?"),
        ("rq", "Esther 2:7", "for she had neither father nor mother"),
        ("ul", ["An orphan.", "Raised by her cousin Mordecai.", "Ordinary in the eyes of people."]),
        ("h3", "How did God lift her?"),
        ("p", "She was one among many young women brought to the palace (Esther 2:8). But God's favour was on her."),
        ("rq", "Esther 2:17", "and she obtained grace and favour in his sight more than all the virgins"),
        ("h3", "What did the waiting time teach her?"),
        ("r", "Esther 2:12"),
        ("p", "Months of preparation came before the crown. Delay is not denial — it is preparation."),
        ("rq", "Isaiah 40:31", "they that wait upon the LORD shall renew their strength"),
        ("h3", "Did success change her?"),
        ("rq", "Esther 2:20", "for Esther did the commandment of Mordecai, like as when she was brought up with him"),
        ("p", "She became queen, but she stayed humble and obedient."),
        ("h2", "But a danger came"),
        ("r", "Esther 3:13; 4:11"),
        ("ul", ["Her people were to be destroyed.", "She could not go to the king without being called.", "Going in could cost her life."]),
        ("rq", "Esther 4:14", "who knoweth whether thou art come to the kingdom for such a time as this?"),
        ("h2", "What did she do?"),
        ("rq", "Esther 4:16", "and so will I go in unto the king, which is not according to the law: and if I perish, I perish"),
        ("p", "She fasted first, then she went. This was not perfect confidence — it was real faith."),
        ("h2", "What was the result?"),
        ("rq", "Esther 5:2", "she obtained favour in his sight: and the king held out to Esther the golden sceptre"),
        ("p", "The king granted her request, and her people were saved (Esther 8)."),
        ("h2", "What we learn"),
        ("ul", ["God sees your future, not just your present.", "Waiting time is training time.", "Courage begins where comfort ends.", "God can use an ordinary life for an extraordinary purpose."]),
        ("mem", "Esther 4:14", "who knoweth whether thou art come to the kingdom for such a time as this?"),
    ]),
    ("4. Samson", "Lesson from Samson", [
        ("key", "Matthew 1:21", None),
        ("h3", "Why did Jesus come?"),
        ("p", "To save us from our sins — because sin always takes more than it promises. Samson's life shows us why."),
        ("h2", "The best example — Samson"),
        ("h3", "What did God give Samson?"),
        ("rq", "Judges 13:5", "the child shall be a Nazarite unto God from the womb: and he shall begin to deliver Israel"),
        ("ul", ["A calling", "Power", "Purpose"]),
        ("p", "But a calling alone is not enough. Obedience is needed."),
        ("h3", "What happened after the first betrayal?"),
        ("r", "Judges 14:20; 15:4-6"),
        ("ul", ["His wife was given to another man.", "He answered with anger, not repentance.", "He burned the Philistines' fields.", "In revenge they burned his wife and her father."]),
        ("h3", "Where did he go in his sorrow?"),
        ("r", "Judges 16:1-3"),
        ("p", "Instead of running to God, he ran to a harlot in Gaza. He found no peace there — only men waiting to kill him. Sin cannot heal pain."),
        ("h3", "Why did Delilah betray him?"),
        ("rq", "Judges 16:5", "and we will give thee every one of us eleven hundred pieces of silver"),
        ("ul", ["The love of money.", "The influence of powerful men."]),
        ("h2", "What did continuous sin cost him?"),
        ("rq", "Judges 16:20", "And he wist not that the LORD was departed from him"),
        ("ul", ["He lost his strength.", "He lost his eyes (Judges 16:21).", "He was made a sport for his enemies (Judges 16:25).", "He needed a small boy to lead him (Judges 16:26)."]),
        ("p", "The strongest man became the weakest."),
        ("h2", "But grace came"),
        ("rq", "Judges 16:28", "O Lord GOD, remember me, I pray thee, and strengthen me, I pray thee, only this once"),
        ("p", "In his brokenness he remembered God's calling, prayed and asked for strength, and God answered by grace. He had judged Israel twenty years (Judges 16:31)."),
        ("rq", "Proverbs 16:6", "By mercy and truth iniquity is purged"),
        ("h2", "What we learn"),
        ("p", "If Samson had turned from sin earlier, he could have lived longer, avoided betrayal, and spared the people he loved from so much sorrow."),
        ("ul", ["Sin starts small.", "Sin grows silently.", "Sin rewards destruction.", "Turn back to God's way now — don't delay."]),
        ("mem", "Proverbs 16:6", None),
    ]),
    ("5. Job", "Lesson from Job", [
        ("key", "Luke 1:79", None),
        ("h3", "Whom does God guide into the way of peace?"),
        ("p", "Those who sit in darkness — even those whose life feels unfair and whose prayers seem unanswered."),
        ("h2", "The best example — Job"),
        ("h3", "What did God say about Job?"),
        ("rq", "Job 1:8", "a perfect and an upright man, one that feareth God, and escheweth evil"),
        ("p", "God allowed a test — not to destroy Job, but to show the depth of his faith. A good life is not a trouble-free life."),
        ("h3", "What did Job lose?"),
        ("r", "Job 1:13-19; 2:7"),
        ("ul", ["His wealth", "His children", "His health"]),
        ("rq", "Job 1:21", "the LORD gave, and the LORD hath taken away; blessed be the name of the LORD"),
        ("h3", "How did he respond?"),
        ("r", "Job 2:13; 3:1"),
        ("p", "For seven days he sat in silence. When he spoke, he cursed the day he was born — but he never cursed God, even though Satan expected it (Job 2:5)."),
        ("h3", "What was his hardest test?"),
        ("rq", "Job 21:7", None),
        ("ul", ["Their houses were safe (Job 21:9).", "Their children danced (Job 21:11).", "Music filled their homes (Job 21:12)."]),
        ("p", "The hardest test of faith is watching the unfaithful succeed while you suffer."),
        ("h2", "Did God answer?"),
        ("r", "Job 38:1; 42:6"),
        ("p", "God spoke out of the whirlwind — not to explain everything, but to remind Job who is in control. Job humbled himself."),
        ("h2", "What was the result?"),
        ("rq", "Job 42:7", "for ye have not spoken of me the thing that is right, as my servant Job hath"),
        ("rq", "Job 42:10", "also the LORD gave Job twice as much as he had before"),
        ("ul", ["His relationships were restored.", "People brought him money and gold (Job 42:11).", "He received beautiful daughters (Job 42:15)."]),
        ("h2", "What we learn"),
        ("ul", ["Don't measure God by today's situation.", "Real faith stays even when answers are slow.", "God may allow delay, but He never forgets faithfulness."]),
        ("mem", "Psalm 109:31", None),
    ]),
    ("6. Moses / Hezekiah", "Lesson from Moses and Hezekiah", [
        ("key", "Luke 2:29", None),
        ("h3", "When can a servant depart in peace?"),
        ("p", "When God's word is fulfilled in his life, and he accepts God's will for his ending."),
        ("h2", "What happens to the faithful?"),
        ("rq", "Isaiah 57:1", "the righteous is taken away from the evil to come"),
        ("rq", "Isaiah 57:2", "He shall enter into peace"),
        ("rq", "Job 3:17", None),
        ("h3", "What is that peaceful place?"),
        ("rq", "Luke 16:22", "the beggar died, and was carried by the angels into Abraham's bosom"),
        ("ul", ["A place under God's care", "A place of comfort", "A place of safety", "No more suffering (Luke 16:25)"]),
        ("h2", "The first example — King Hezekiah"),
        ("h3", "What did he do?"),
        ("rq", "Isaiah 38:1", "Set thine house in order: for thou shalt die, and not live"),
        ("r", "Isaiah 38:2-5"),
        ("p", "He wept and pleaded, and God added fifteen years to his life. Not every answered prayer leads to blessing."),
        ("h3", "What came in those extra years?"),
        ("rq", "Isaiah 39:2", "and shewed them the house of his precious things"),
        ("rq", "2 Kings 20:18", "they shall be eunuchs in the palace of the king of Babylon"),
        ("p", "His pride brought consequences on his family, fulfilled later (2 Kings 24:12)."),
        ("h2", "The second example — Moses"),
        ("h3", "What did Moses ask, and what did God say?"),
        ("r", "Deuteronomy 3:25-26"),
        ("rq", "Deuteronomy 3:26", "Let it suffice thee; speak no more unto me of this matter"),
        ("p", "Moses accepted God's “no.”"),
        ("h3", "What was he spared from?"),
        ("rq", "Deuteronomy 31:16", "this people will rise up, and go a whoring after the gods of the strangers of the land"),
        ("rq", "Deuteronomy 31:27", "while I am yet alive with you this day, ye have been rebellious against the LORD"),
        ("h3", "How did his life end?"),
        ("rq", "Deuteronomy 34:5", None),
        ("rq", "Deuteronomy 33:3", "all his saints are in thy hand"),
        ("ul", ["In God's presence", "In peace", "Without shame", "Without fear"]),
        ("h2", "What we learn"),
        ("ul", ["Allow God's will, even when it is hard.", "Trust God's timing more than your feelings.", "A life surrendered to God ends safely in His hands."]),
        ("mem", "Isaiah 57:2", None),
    ]),
    ("7. Saul", "Lesson from Saul", [
        ("key", "Luke 3:9", "every tree therefore which bringeth not forth good fruit is hewn down, and cast into the fire"),
        ("h3", "What does God look for?"),
        ("p", "Good fruit — a life that obeys Him, not only a life that starts well."),
        ("h2", "The best example — Saul"),
        ("h3", "Where did Saul come from?"),
        ("rq", "1 Samuel 9:21", "Am not I a Benjamite, of the smallest of the tribes of Israel?"),
        ("p", "He was out looking for his father's lost donkeys (1 Samuel 9:3) when God was preparing him to be king."),
        ("h3", "What changed his life?"),
        ("rq", "1 Samuel 10:6", "and shalt be turned into another man"),
        ("ul", ["Not education", "Not wealth", "Not influence", "God's Spirit"]),
        ("h2", "But... where did the fall begin?"),
        ("rq", "1 Samuel 15:14", "What meaneth then this bleating of the sheep in mine ears"),
        ("rq", "1 Samuel 15:22", "to obey is better than sacrifice"),
        ("p", "Partial obedience is still disobedience."),
        ("h3", "What entered his heart?"),
        ("rq", "1 Samuel 18:9", None),
        ("p", "Pride cannot bear to see someone else honoured."),
        ("h3", "Where did he go when God did not answer?"),
        ("r", "1 Samuel 28:3, 6-8"),
        ("p", "He had once put mediums out of the land — and then he secretly went to one himself."),
        ("rq", "Leviticus 20:6", None),
        ("h2", "What was the result?"),
        ("rq", "1 Chronicles 10:13", None),
        ("p", "He lost God's presence, his peace, his direction and his throne, and the kingdom was given to David (1 Chronicles 10:14)."),
        ("h2", "What we learn"),
        ("ul", ["God can lift anyone from a small beginning.", "Only humility and obedience keep us there.", "Guard your heart from jealousy.", "Seek God alone."]),
        ("mem", "Leviticus 20:6", None),
    ]),
    ("8. Gideon", "Lesson from Gideon", [
        ("key", "Luke 4:4", "That man shall not live by bread alone, but by every word of God"),
        ("h3", "What makes a person strong?"),
        ("p", "Not their own strength, but God's word and God's presence."),
        ("h2", "The best example — Gideon"),
        ("h3", "Where was Gideon when God called him?"),
        ("rq", "Judges 6:11", "his son Gideon threshed wheat by the winepress, to hide it from the Midianites"),
        ("rq", "Judges 6:12", "The LORD is with thee, thou mighty man of valour"),
        ("rq", "Judges 6:15", "my family is poor in Manasseh, and I am the least in my father's house"),
        ("p", "God saw who Gideon could become, not just who he was."),
        ("h3", "Does God know the details of our life?"),
        ("rq", "Judges 6:25", "even the second bullock of seven years old"),
        ("rq", "Judges 7:10", "go thou with Phurah thy servant down to the host"),
        ("p", "God knew his father's bull, its age, and his servant's name."),
        ("rq", "Matthew 10:30", None),
        ("h3", "Whose strength did he go in?"),
        ("rq", "Judges 6:14", "Go in this thy might"),
        ("rq", "2 Corinthians 12:9", "for my strength is made perfect in weakness"),
        ("h3", "How did he obey first?"),
        ("r", "Judges 6:27"),
        ("p", "He pulled down his father's altar of Baal by night, because he was afraid — but he obeyed."),
        ("rq", "Luke 16:10", "He that is faithful in that which is least is faithful also in much"),
        ("h2", "Why did God make the army smaller?"),
        ("rq", "Judges 7:2", "lest Israel vaunt themselves against me, saying, Mine own hand hath saved me"),
        ("p", "From 32,000 men to just 300 (Judges 7:3, 7)."),
        ("h2", "How did the victory come?"),
        ("rq", "Judges 7:20", "The sword of the LORD, and of Gideon"),
        ("p", "With trumpets, jars and torches, the enemy was thrown into confusion and fought one another (Judges 7:22)."),
        ("rq", "Zechariah 4:6", "Not by might, nor by power, but by my spirit, saith the LORD of hosts"),
        ("h2", "What we learn"),
        ("ul", ["Don't say “I am too small.”", "Obey even when you are afraid.", "Depend on God's strength.", "God knows every detail about you (Psalm 139:16)."]),
        ("mem", "2 Chronicles 14:11", "it is nothing with thee to help, whether with many, or with them that have no power"),
    ]),
    ("9. Joshua", "Lesson from Joshua", [
        ("key", "John 1:9", None),
        ("h3", "What does this mean?"),
        ("p", "God's light shines on every person. But those who walk by His word experience His guidance, power and favour."),
        ("rq", "James 1:22", "But be ye doers of the word, and not hearers only"),
        ("h2", "The best example — Joshua"),
        ("h3", "Who was Joshua?"),
        ("rq", "Exodus 24:13", "And Moses rose up, and his minister Joshua"),
        ("p", "He wasn't raised in a palace like Moses. He was simply Moses' assistant — but faithful and obedient. God prepares leaders in hidden places before public places."),
        ("h3", "What was God's secret for his success?"),
        ("rq", "Joshua 1:8", None),
        ("ul", ["Keep God's word on your lips — speak it, teach it, declare it.", "Keep God's word in your thoughts — think on it, meditate on it, live by it."]),
        ("rq", "Psalm 1:3", "And he shall be like a tree planted by the rivers of water"),
        ("h3", "Who promoted Joshua?"),
        ("rq", "Joshua 3:7", "This day will I begin to magnify thee in the sight of all Israel"),
        ("rq", "Psalm 75:6", None),
        ("h2", "What did God do through his obedience?"),
        ("h3", "The Jordan stopped"),
        ("rq", "Joshua 3:17", "and all the Israelites passed over on dry ground"),
        ("h3", "Jericho fell"),
        ("rq", "Joshua 6:20", "the wall fell down flat"),
        ("h3", "The sun stood still"),
        ("rq", "Joshua 10:12", "Sun, stand thou still upon Gibeon"),
        ("h2", "What was the result?"),
        ("rq", "Joshua 4:14", "On that day the LORD magnified Joshua in the sight of all Israel"),
        ("h2", "What we learn"),
        ("ul", ["God does not look for famous people — He looks for faithful people.", "Speak God's word, think on God's word, live by God's word.", "Promotion from God is stronger than promotion from people."]),
        ("rq", "Joshua 24:15", "but as for me and my house, we will serve the LORD"),
        ("mem", "Joshua 1:8", "This book of the law shall not depart out of thy mouth; but thou shalt meditate therein day and night"),
    ]),
    ("10. Jeremiah", "Lesson from Jeremiah", [
        ("key", "Mark 4:40", None),
        ("h3", "Can fear and faith lead together?"),
        ("p", "Faith is not the absence of fear. Faith is choosing to trust God even while you feel afraid."),
        ("h2", "The best example — Jeremiah"),
        ("h3", "What did God promise him?"),
        ("rq", "Jeremiah 1:18", "I have made thee this day a defenced city, and an iron pillar, and brasen walls"),
        ("rq", "Jeremiah 1:19", None),
        ("p", "Opposition would come — but defeat would not."),
        ("h3", "How did God protect him?"),
        ("rq", "Jeremiah 36:26", "but the LORD hid them"),
        ("h2", "But... fear came"),
        ("r", "Jeremiah 37:12-13"),
        ("p", "He tried to leave Jerusalem for his own land of Benjamin, and was caught at the gate."),
        ("h3", "What did fear bring?"),
        ("r", "Jeremiah 37:15-16"),
        ("ul", ["He was beaten.", "He was put in prison.", "He was thrown into a dungeon for many days."]),
        ("rq", "Jeremiah 37:20", "lest I die there"),
        ("rq", "Proverbs 29:25", "The fear of man bringeth a snare"),
        ("h3", "Did God leave him?"),
        ("rq", "Jeremiah 37:21", "and that they should give him daily a piece of bread out of the bakers' street"),
        ("rq", "Isaiah 42:3", "A bruised reed shall he not break"),
        ("h2", "How did his faith grow?"),
        ("p", "Before the same king, the frightened man now spoke boldly what God said:"),
        ("rq", "Jeremiah 38:20", "so it shall be well unto thee, and thy soul shall live"),
        ("rq", "Jeremiah 38:24", "Let no man know of these words"),
        ("p", "Now it was the king who was afraid."),
        ("h2", "What was the result?"),
        ("rq", "Jeremiah 39:12", "Take him, and look well to him, and do him no harm"),
        ("p", "Others were in chains, but Jeremiah was set free in the same city (Jeremiah 40:4)."),
        ("h2", "What we learn"),
        ("ul", ["Don't run because of fear.", "Go back to what God already told you.", "Failure is not the end — God gives second chances.", "When you fear God, you will not fear people."]),
        ("mem", "Isaiah 42:3", None),
    ]),
    ("11. Jacob", "Lesson from Jacob", [
        ("key", "Mark 6:50", "Be of good cheer: it is I; be not afraid"),
        ("h3", "Who speaks to us when we are alone and afraid?"),
        ("p", "Jesus Himself. And God does special things on a lonely path."),
        ("h2", "The best example — Jacob"),
        ("h3", "Whose words came true?"),
        ("r", "Genesis 27:41-45"),
        ("ul", ["His brother said, “I will kill Jacob” — it never happened.", "His mother said, “Tarry with him a few days” — it never happened."]),
        ("rq", "Genesis 28:15", None),
        ("p", "People's words depend on situations. God's word controls situations."),
        ("h3", "What did the lonely road show him?"),
        ("rq", "Genesis 28:16", "Surely the LORD is in this place; and I knew it not"),
        ("p", "Laban, whom his parents trusted, used him and cheated him:"),
        ("rq", "Genesis 31:7", "changed my wages ten times; but God suffered him not to hurt me"),
        ("p", "Some people's true nature is revealed only in separation."),
        ("h3", "What did God do where people failed?"),
        ("rq", "Genesis 31:42", "surely thou hadst sent me away now empty"),
        ("p", "People stay with you for their benefit; God stays with you for your good."),
        ("h2", "What was the result?"),
        ("rq", "Genesis 32:10", "for with my staff I passed over this Jordan; and now I am become two bands"),
        ("p", "He began alone, afraid and running, and ended with a great family, wealth and a new identity."),
        ("h2", "But..."),
        ("rq", "Genesis 42:36", "Joseph is not, and Simeon is not, and ye will take Benjamin away"),
        ("p", "Even after many experiences, the heart can still feel weak."),
        ("h3", "What did Jacob finally understand?"),
        ("rq", "Genesis 49:10", "The sceptre shall not depart from Judah"),
        ("p", "Not everyone who looks strong is chosen for authority; God's chosen line alone remains."),
        ("h2", "What we learn"),
        ("ul", ["On a lonely path, God separates the people who are not meant to stay.", "Where people fail, God shows how good He is.", "God blesses beyond what you imagine."]),
        ("mem", "Genesis 28:15", "for I will not leave thee, until I have done that which I have spoken to thee of"),
    ]),
    ("12. Jonah", "Lesson from Jonah", [
        ("key", "Luke 5:20", None),
        ("h3", "What happens when our sins are forgiven?"),
        ("r", "Luke 5:25-26"),
        ("ul", ["We are raised up.", "Our situation changes.", "Others glorify God because of our life."]),
        ("h3", "And what happens when we do not trust God?"),
        ("h2", "The best example — Jonah"),
        ("h3", "Where did he go?"),
        ("rq", "Jonah 1:3", "so he paid the fare thereof, and went down into it"),
        ("ul", ["The ship — wasted", "The money — wasted", "The effort — wasted"]),
        ("p", "Every decision outside God's will ends in loss."),
        ("h3", "What came next?"),
        ("rq", "Jonah 1:4", "But the LORD sent out a great wind into the sea"),
        ("p", "Disobedience doesn't only affect us; it affects the people around us."),
        ("h3", "What if we think we can handle it ourselves?"),
        ("rq", "Jonah 1:12", "Take me up, and cast me forth into the sea"),
        ("rq", "Jonah 1:17", "Now the LORD had prepared a great fish to swallow up Jonah"),
        ("p", "In the fish he could neither live freely nor die."),
        ("h3", "How deep can trouble go?"),
        ("rq", "Jonah 2:5", "the weeds were wrapped about my head"),
        ("rq", "Psalm 69:8", None),
        ("rq", "Psalm 69:20", "I looked for some to take pity, but there was none; and for comforters, but I found none"),
        ("h2", "The turning point"),
        ("rq", "Jonah 2:7", "When my soul fainted within me I remembered the LORD"),
        ("rq", "Jonah 2:8", None),
        ("rq", "Psalm 71:7", "but thou art my strong refuge"),
        ("h2", "What happens when we return?"),
        ("rq", "Psalm 71:20", "shalt quicken me again, and shalt bring me up again from the depths of the earth"),
        ("rq", "Jonah 3:1", "And the word of the LORD came unto Jonah the second time"),
        ("p", "The king and the whole city repented (Jonah 3:6-10), and more than 120,000 people were spared:"),
        ("rq", "Jonah 4:11", "more than sixscore thousand persons"),
        ("h2", "What we learn"),
        ("ul", ["Don't run from God.", "Don't wait to lose everything before turning to Him.", "God gives second chances.", "When you walk in God's will, your life blesses thousands."]),
        ("mem", "Psalm 71:21", None),
    ]),
    ("13. David / Solomon", "Lesson from David and Solomon", [
        ("key", "Matthew 6:33", None),
        ("h3", "What does it mean to seek God first?"),
        ("p", "To put God's ways ahead of everything else — and to trust Him to add what we need."),
        ("h2", "The example — David and Solomon"),
        ("h3", "What did David tell Solomon?"),
        ("rq", "1 Kings 2:2", "be thou strong therefore, and shew thyself a man"),
        ("rq", "1 Kings 2:3", "that thou mayest prosper in all that thou doest"),
        ("h3", "What did Solomon ask for?"),
        ("rq", "1 Kings 3:5", "Ask what I shall give thee"),
        ("rq", "1 Kings 3:7", "I am but a little child"),
        ("rq", "1 Kings 3:9", "Give therefore thy servant an understanding heart"),
        ("h3", "What did God give him?"),
        ("rq", "1 Kings 3:13", "And I have also given thee that which thou hast not asked, both riches, and honour"),
        ("p", "He sought wisdom first, and God added the rest."),
        ("h2", "But..."),
        ("rq", "1 Kings 11:4", "his heart was not perfect with the LORD his God, as was the heart of David his father"),
        ("p", "A good start is not enough. David also failed — but he repented:"),
        ("rq", "2 Samuel 12:13", "I have sinned against the LORD"),
        ("rq", "Psalm 51:10", None),
        ("h2", "What we learn"),
        ("ul", ["Start with God.", "Ask God for wisdom.", "When you fall, repent quickly.", "Finish well — keep walking in God's ways to the end."]),
        ("rq", "James 1:5", "If any of you lack wisdom, let him ask of God"),
        ("mem", "1 Kings 3:9", "Give therefore thy servant an understanding heart"),
    ]),
    ("14. John the Baptist", "Lesson from John the Baptist", [
        ("key", "John 3:30", None),
        ("h3", "What does this mean?"),
        ("p", "A faith leader does not gather people to himself. He points every eye to Jesus."),
        ("h2", "The example — John the Baptist"),
        ("h3", "Where did God's word come to him?"),
        ("rq", "Luke 3:2", "the word of God came unto John the son of Zacharias in the wilderness"),
        ("rq", "Luke 3:4", "Prepare ye the way of the Lord, make his paths straight"),
        ("h3", "What did he teach?"),
        ("rq", "Luke 3:8", "Bring forth therefore fruits worthy of repentance"),
        ("r", "Luke 3:10-14"),
        ("ul", ["Share your coat and your food.", "Take no more than what is right.", "Do no violence, accuse no one falsely, and be content."]),
        ("h3", "Whom did he point to?"),
        ("rq", "Luke 3:16", "but one mightier than I cometh, the latchet of whose shoes I am not worthy to unloose"),
        ("rq", "John 1:29", "Behold the Lamb of God, which taketh away the sin of the world"),
        ("h2", "What did his courage cost?"),
        ("r", "Luke 3:19-20"),
        ("p", "He rebuked Herod for his sin and was shut up in prison."),
        ("h2", "What did Jesus say about him?"),
        ("rq", "Luke 7:28", "Among those that are born of women there is not a greater prophet than John the Baptist"),
        ("h2", "What we learn"),
        ("ul", ["Speak the truth boldly.", "Let repentance show in honest, generous living.", "Make Jesus greater, not yourself."]),
        ("mem", "Isaiah 40:3", "Prepare ye the way of the LORD"),
    ]),
    ("15. Judah", "Lesson from Judah", [
        ("key", "John 15:13", None),
        ("h3", "What is the greatest love?"),
        ("p", "To give yourself for others. Judah learned it slowly — and Jesus, from the tribe of Judah, showed it fully."),
        ("h2", "The example — Judah"),
        ("h3", "How did his story begin?"),
        ("rq", "Genesis 37:26", "What profit is it if we slay our brother"),
        ("rq", "Genesis 37:27", "Come, and let us sell him to the Ishmeelites"),
        ("h3", "Where did his heart begin to change?"),
        ("rq", "Genesis 38:26", "She hath been more righteous than I"),
        ("rq", "Proverbs 28:13", "but whoso confesseth and forsaketh them shall have mercy"),
        ("h3", "What did he promise his father?"),
        ("rq", "Genesis 43:9", "I will be surety for him; of my hand shalt thou require him"),
        ("h2", "What did he do when Benjamin was in danger?"),
        ("r", "Genesis 44:16-34"),
        ("rq", "Genesis 44:33", "let thy servant abide instead of the lad a bondman to my lord"),
        ("rq", "Genesis 44:34", "For how shall I go up to my father, and the lad be not with me?"),
        ("rq", "Genesis 45:1", "Then Joseph could not refrain himself"),
        ("p", "The brother who once sold a brother now offered himself in his place."),
        ("h2", "What was the result?"),
        ("rq", "Genesis 49:10", "The sceptre shall not depart from Judah"),
        ("rq", "Revelation 5:5", "the Lion of the tribe of Juda"),
        ("p", "From Judah came King David — and Jesus, who gave His life in our place."),
        ("h2", "What we learn"),
        ("ul", ["A bad start does not have to be the end of your story.", "Confession is the first step of change.", "Real leaders stand in the gap for others."]),
        ("mem", "Genesis 49:10", "The sceptre shall not depart from Judah"),
    ]),
]


class Bible:
    def __init__(self, path):
        self.con = sqlite3.connect(path)
        self.books = {n: b for b, n in self.con.execute("select book, name from book_names where version='KJV'")}

    def text(self, ref):
        m = re.fullmatch(r"(.+?) (\d+):(\d+)(?:-(\d+))?", ref.replace("–", "-"))
        if not m:
            raise ValueError(f"cannot quote {ref!r}")
        book, chapter, first, last = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4) or m.group(3))
        book = self.books[BOOK_ALIASES.get(book, book)]
        rows = self.con.execute("select text from verses where version='KJV' and book=? and chapter=? and verse between ? and ? "
                                "order by verse", (book, chapter, first, last)).fetchall()
        if len(rows) != last - first + 1:
            raise ValueError(f"missing verses for {ref}")
        return re.sub(r"\s+", " ", " ".join(r[0] for r in rows).replace("¶", "")).strip()

    def quote(self, ref, part):
        full = self.text(ref)
        if part is None:
            return f"“{full}”"
        if part not in full:
            raise ValueError(f"{ref}: {part!r} is not in “{full}”")
        start, end = full.index(part), full.index(part) + len(part)
        lead = "" if start == 0 else "…"
        tail = "" if end >= len(full.rstrip(".;:,")) else "…"
        return f"“{lead}{part}{tail}”"


def _id():
    return "".join(random.choices(string.ascii_letters + string.digits, k=10))


def build(bible, spec):
    out = []

    def add(kind, data):
        out.append({"id": _id(), "type": kind, "data": data})

    for item in spec:
        kind = item[0]
        if kind == "key":
            add("header", {"text": item[1], "level": 2})
            add("header", {"text": bible.quote(item[1], item[2]), "level": 2})
        elif kind == "key2":  # as in the Tamil lessons: “reference” heading, the verse as a paragraph
            add("header", {"text": f"“{item[1]}”", "level": 2})
            add("paragraph", {"text": bible.quote(item[1], item[2])})
        elif kind == "q":  # reference and quotation on one line: 📖 Ref “…”
            add("paragraph", {"text": f"📖 {item[1]} {bible.quote(item[1], item[2])}"})
        elif kind == "rq":
            add("paragraph", {"text": f"📖 <b>{item[1]}</b>"})
            add("paragraph", {"text": bible.quote(item[1], item[2])})
        elif kind == "r":
            add("paragraph", {"text": f"📖 {item[1]}"})
        elif kind in ("h2", "h3"):
            add("header", {"text": item[1], "level": int(kind[1])})
        elif kind == "p":
            add("paragraph", {"text": item[1]})
        elif kind == "ul":
            # One 👉 line per point, as in the teaching notes, rather than a bulleted list block.
            for t in item[1]:
                add("paragraph", {"text": f"👉 {t}"})
        elif kind == "mem":
            add("header", {"text": "📖 Memory Verse", "level": 2})
            add("paragraph", {"text": bible.quote(item[1], item[2])})
            add("paragraph", {"text": f"— {item[1]}"})
        else:
            raise ValueError(kind)
    return json.dumps({"time": int(time.time() * 1000), "blocks": out, "version": "2.31.0"}, ensure_ascii=False)


def main(db, out):
    bible = Bible(db)
    result = [{"chapter": c, "title": t, "content": build(bible, spec)} for c, t, spec in LESSONS]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"built {len(result)} lessons, {sum(len(json.loads(r['content'])['blocks']) for r in result)} blocks -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
