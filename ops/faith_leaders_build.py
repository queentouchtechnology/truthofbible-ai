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
        ("ul", ["When pain comes, take it to God first — not to people. (📖 1 Samuel 1:10)",
                "When you are misunderstood, answer gently instead of in anger. (📖 Proverbs 15:1)",
                "While you wait, trust God; His peace can come before His answer. (📖 Philippians 4:7)",
                "Keep the promises you make to God, even when it costs you something. (📖 1 Samuel 1:28)"]),
        ("p", "Hannah believed before she saw, and God turned her tears into a testimony. He does the same for everyone who trusts Him, because He has said:"),
        ("q", "1 Samuel 2:30", "for them that honour me I will honour"),
    ]),
    ("2. Ruth", "Lesson from Ruth", [
        ("key2", "Matthew 6:4", "and thy Father which seeth in secret himself shall reward thee openly"),
        ("h2", "What does “thy Father which seeth in secret” mean?"),
        ("p", "Many good things we do are never seen by people. No one claps, no one thanks us, no one even notices. But Jesus says our Father sees what is done in secret — and He Himself rewards it openly."),
        ("h3", "One whom the Father rewards like this:"),
        ("ul", ["chooses God even when it is not comfortable", "is faithful in small things that no one notices", "obeys quietly, without seeking attention"]),
        ("p", "So this verse means: nothing done faithfully for God is ever wasted, even if no one else sees it."),
        ("h2", "Example: Ruth – a woman whom God saw in secret"),
        ("p", "A great example of this is Ruth."),
        ("p", "Ruth was a young woman from Moab who married into a family from Bethlehem. Then, one after another, the men of the family died — her father-in-law, and then her husband and his brother. (📖 Ruth 1:3–5)"),
        ("p", "She was left a widow and poor, with no security and no future in sight. Why does this happen to good people?"),
        ("q", "John 16:33", "In the world ye shall have tribulation: but be of good cheer; I have overcome the world"),
        ("p", "Being good does not mean life will always be easy. So what did Ruth do in her loss?"),
        ("h3", "1️⃣ She chose God over comfort"),
        ("p", "Naomi told her daughters-in-law to go back to their own families. Orpah kissed her and went back. (📖 Ruth 1:14) But Ruth held on:"),
        ("q", "Ruth 1:16", None),
        ("p", "Going back would have been easier. Ruth chose to follow Naomi's God into a land she did not know."),
        ("h3", "2️⃣ She was faithful in small things"),
        ("p", "In Bethlehem she was a foreigner. She went out to the fields to glean — to pick up the leftover grain behind the reapers. (📖 Ruth 2:2–3)"),
        ("p", "It was humble, quiet work, and no one seemed to notice her. But God did — and so did Boaz, the owner of the field."),
        ("h3", "3️⃣ God rewarded her quiet obedience"),
        ("q", "Ruth 2:12", None),
        ("p", "Ruth did not ask for attention. She simply did what was right, and God made sure her faithfulness was seen."),
        ("h3", "What was the result?"),
        ("p", "Boaz redeemed the family land and took Ruth as his wife, and God gave them a son. (📖 Ruth 4:13–17)"),
        ("q", "Matthew 1:5", None),
        ("p", "The widow from Moab became the great-grandmother of King David — and part of the family line of Jesus."),
        ("h3", "What do we learn?"),
        ("ul", ["Being good does not mean life will be easy, but God never leaves His people. (📖 John 16:33)",
                "Choose God even when going back would be more comfortable. (📖 Ruth 1:16)",
                "Be faithful in small things, even when no one is watching. (📖 Ruth 2:2–3)",
                "God sees what others overlook, and He rewards it. (📖 Ruth 2:12)"]),
        ("p", "Ruth began with loss, pain and an uncertain future, and ended with blessing, honour and purpose. What you lose, God can restore:"),
        ("q", "Joel 2:25", "I will restore to you the years that the locust hath eaten"),
    ]),
    ("3. Esther", "Lesson from Esther", [
        ("key2", "Luke 1:52", None),
        ("h2", "What does “exalted them of low degree” mean?"),
        ("p", "People usually honour the rich, the famous and the powerful. God works differently. He can take someone from a small, unnoticed place and lift them to a place of great purpose."),
        ("h3", "One whom God lifts like this:"),
        ("ul", ["stays humble", "waits patiently for God's time", "steps out in faith when the moment comes"]),
        ("p", "So this verse means: your beginning does not limit what God can do with your life."),
        ("h2", "Example: Esther – an ordinary girl whom God lifted up"),
        ("p", "A great example of this is Esther."),
        ("q", "Esther 2:7", "for she had neither father nor mother"),
        ("p", "Esther was an orphan, raised by her cousin Mordecai. She was not rich or famous. To people she looked ordinary — but to God she was chosen."),
        ("h3", "1️⃣ God gave her favour"),
        ("p", "Many young women were brought to the king's palace, and Esther was just one among many. (📖 Esther 2:8) Yet God's favour was on her:"),
        ("q", "Esther 2:17", "and she obtained grace and favour in his sight more than all the virgins"),
        ("p", "She did not need to be the best. She needed God's favour."),
        ("h3", "2️⃣ She stayed humble when she was lifted up"),
        ("p", "Before she became queen there was a long time of preparation. (📖 Esther 2:12) And even after she wore the crown, she did not become proud:"),
        ("q", "Esther 2:20", "for Esther did the commandment of Mordecai, like as when she was brought up with him"),
        ("p", "Success did not change her character."),
        ("h3", "3️⃣ She found courage when danger came"),
        ("p", "A decree went out to destroy all her people. (📖 Esther 3:13) The only way to stop it was to go to the king without being called — and that could cost her life. (📖 Esther 4:11) Esther was afraid. Then Mordecai asked her:"),
        ("q", "Esther 4:14", "who knoweth whether thou art come to the kingdom for such a time as this?"),
        ("p", "What did she do? She asked all her people to fast with her for three days, and then she decided:"),
        ("q", "Esther 4:16", "and so will I go in unto the king, which is not according to the law: and if I perish, I perish"),
        ("p", "This was not perfect confidence — it was real faith."),
        ("h3", "What was the result?"),
        ("q", "Esther 5:2", "she obtained favour in his sight: and the king held out to Esther the golden sceptre"),
        ("p", "The king granted her request, and her people were saved. (📖 Esther 8) The orphan girl became a queen, a leader and a deliverer."),
        ("h3", "What do we learn?"),
        ("ul", ["God sees your future, not just your present. (📖 Esther 2:7)",
                "Waiting time is training time — delay is not denial. (📖 Esther 2:12)",
                "Stay humble when God lifts you up. (📖 Esther 2:20)",
                "Fear is normal, but staying silent is dangerous — step out in faith. (📖 Esther 4:16)"]),
        ("p", "God can take an ordinary life and turn it into an extraordinary purpose for those who wait on Him:"),
        ("q", "Isaiah 40:31", "they that wait upon the LORD shall renew their strength"),
    ]),
    ("4. Samson", "Lesson from Samson", [
        ("key2", "Matthew 1:21", None),
        ("h2", "Why did Jesus come?"),
        ("p", "Jesus came to save His people from their sins. Why does that matter so much? Because sin never stays small. It promises pleasure, comfort or relief, but it always takes more than it gives."),
        ("h3", "Sin, when we keep walking in it:"),
        ("ul", ["starts small", "grows silently", "ends in destruction"]),
        ("p", "So this verse is both a warning and a hope: sin is dangerous, but Jesus came to save us from it."),
        ("h2", "Example: Samson – the cost of walking away from God's plan"),
        ("p", "A clear example of this is Samson."),
        ("q", "Judges 13:5", "the child shall be a Nazarite unto God from the womb: and he shall begin to deliver Israel"),
        ("p", "Samson was chosen before he was born. He had a calling, great power and a purpose. But a calling alone is not enough — obedience is needed. So what went wrong?"),
        ("h3", "1️⃣ Betrayal led to anger, not repentance"),
        ("p", "His wife was given to another man. (📖 Judges 14:20) Instead of turning to God, Samson turned to anger. He burned the Philistines' fields, and in revenge they burned his wife and her father. (📖 Judges 15:4–6)"),
        ("h3", "2️⃣ Pain led him away from God"),
        ("p", "In his sorrow he did not run to God's presence. He went to a harlot in Gaza, trying to escape his pain. (📖 Judges 16:1) But he found no peace there — only men waiting to kill him. (📖 Judges 16:2–3) Sin cannot heal pain."),
        ("h3", "3️⃣ A love that God had not led him to"),
        ("p", "Then he loved Delilah — a relationship God had not led him into. Why did she betray him? For money, and under the pressure of powerful men:"),
        ("q", "Judges 16:5", "and we will give thee every one of us eleven hundred pieces of silver"),
        ("h3", "4️⃣ Continuous sin took everything"),
        ("q", "Judges 16:20", "And he wist not that the LORD was departed from him"),
        ("p", "He lost his strength, then his eyes. (📖 Judges 16:21) He was made a sport for his enemies (📖 Judges 16:25), and a little boy had to lead him by the hand. (📖 Judges 16:26) The strongest man had become the weakest."),
        ("h3", "What was the result?"),
        ("p", "In his brokenness and blindness, Samson remembered God's calling. He prayed, repented and asked for strength:"),
        ("q", "Judges 16:28", "O Lord GOD, remember me, I pray thee, and strengthen me, I pray thee, only this once"),
        ("p", "God answered by grace. But Samson died with his enemies, and so much sorrow could have been avoided if he had turned back earlier."),
        ("h3", "What do we learn?"),
        ("ul", ["A calling from God must be protected by obedience. (📖 Judges 13:5)",
                "When we are hurt, we must run to God, not to sin — sin cannot heal pain. (📖 Judges 16:1)",
                "Sin always takes more than it promises. (📖 Judges 16:20–21)",
                "It is never too late to cry out to God, but it is wiser to turn back early. (📖 Judges 16:28)"]),
        ("p", "Be careful with sin. Turn back now and seek God's way today — because God forgives:"),
        ("q", "Proverbs 16:6", None),
    ]),
    ("5. Job", "Lesson from Job", [
        ("key2", "Luke 1:79", None),
        ("h2", "What does “guide our feet into the way of peace” mean?"),
        ("p", "Some people sit in darkness — in pain, loss and confusion — and God feels far away. This verse says God's light visits even them, and leads their feet into peace."),
        ("h3", "One whom God leads into peace:"),
        ("ul", ["keeps trusting when life is unfair", "stays with God when answers are slow", "believes that God sees what others don't"]),
        ("p", "So this verse means: darkness is not the end of the story for those who keep walking with God."),
        ("h2", "Example: Job – faithful when life was unfair"),
        ("p", "A great example of this is Job."),
        ("q", "Job 1:8", "a perfect and an upright man, one that feareth God, and escheweth evil"),
        ("p", "God Himself said this about Job. So why did trouble come to such a man? Not to destroy him, but to show how deep his faith was. A good life is not always a trouble-free life."),
        ("h3", "1️⃣ He lost everything — but not his faith"),
        ("p", "In one day Job lost his wealth and his children, and soon afterwards his health. (📖 Job 1:13–19; 2:7) What did he say?"),
        ("q", "Job 1:21", "the LORD gave, and the LORD hath taken away; blessed be the name of the LORD"),
        ("p", "For seven days he sat in silence with his friends. (📖 Job 2:13) Silence before God is better than rebellion against God."),
        ("h3", "2️⃣ He was honest about his pain, but did not curse God"),
        ("p", "When Job finally spoke, he cursed the day he was born. (📖 Job 3:1) He was honest about his pain and confusion. Satan had expected him to curse God (📖 Job 2:5) — but Job never did."),
        ("h3", "3️⃣ He stayed faithful when life looked unfair"),
        ("p", "The hardest question for Job was this:"),
        ("q", "Job 21:7", None),
        ("p", "The wicked lived safely, their children danced, and music filled their homes. (📖 Job 21:9–12) Watching the unfaithful succeed while you suffer is one of the hardest tests of faith. Still, Job did not abandon God."),
        ("h3", "What was the result?"),
        ("p", "At last God spoke — not to explain everything, but to show Job who is in control — and Job humbled himself. (📖 Job 38:1; 42:6) Then God honoured him:"),
        ("q", "Job 42:7", "for ye have not spoken of me the thing that is right, as my servant Job hath"),
        ("q", "Job 42:10", "also the LORD gave Job twice as much as he had before"),
        ("h3", "What do we learn?"),
        ("ul", ["A good life is not always a trouble-free life. (📖 Job 1:8)",
                "Even in loss, we can bless the name of the Lord. (📖 Job 1:21)",
                "We can be honest with God about our pain and still stay faithful. (📖 Job 3:1)",
                "God may allow delay, but He never forgets faithfulness. (📖 Job 42:10)"]),
        ("p", "Don't measure God by today's situation. He stands beside those who suffer:"),
        ("q", "Psalm 109:31", None),
    ]),
    ("6. Moses / Hezekiah", "Lesson from Moses and Hezekiah", [
        ("key2", "Luke 2:29", None),
        ("h2", "When can a servant depart in peace?"),
        ("p", "Simeon said these words when he held the baby Jesus. God's promise to him had been fulfilled, so he was ready to go in peace. A life that accepts God's will has a peaceful ending."),
        ("h3", "One who accepts God's will:"),
        ("ul", ["trusts God's timing more than their own feelings", "accepts God's “no” as well as His “yes”", "ends life safe in God's hands"]),
        ("p", "This lesson shows two men — one who resisted God's decision, and one who accepted it."),
        ("h2", "What happens to the faithful?"),
        ("q", "Isaiah 57:1", "the righteous is taken away from the evil to come"),
        ("q", "Isaiah 57:2", "He shall enter into peace"),
        ("p", "Sometimes God takes His faithful children early to protect them from future trouble. What is that place of peace? Jesus described it: the poor man Lazarus was carried by the angels into Abraham's bosom (📖 Luke 16:22) — a place of comfort under God's care, where he suffered no more. (📖 Luke 16:25)"),
        ("h2", "First example: King Hezekiah – resisting God's decision"),
        ("q", "Isaiah 38:1", "Set thine house in order: for thou shalt die, and not live"),
        ("p", "What did Hezekiah do? He wept and pleaded, and God added fifteen years to his life. (📖 Isaiah 38:2–5) But not every answered prayer leads to blessing."),
        ("h3", "1️⃣ The extra years brought pride"),
        ("q", "Isaiah 39:2", "and shewed them the house of his precious things"),
        ("p", "He proudly showed everything he had to the messengers from Babylon."),
        ("h3", "2️⃣ The consequences fell on his family"),
        ("q", "2 Kings 20:18", "they shall be eunuchs in the palace of the king of Babylon"),
        ("p", "His descendants would be carried away — and later it happened. (📖 2 Kings 24:12) He had asked only for more life, not for wisdom."),
        ("h2", "Second example: Moses – accepting God's decision"),
        ("p", "Moses longed to enter the Promised Land, and he asked God for it. (📖 Deuteronomy 3:25) God said no:"),
        ("q", "Deuteronomy 3:26", "Let it suffice thee; speak no more unto me of this matter"),
        ("p", "And Moses accepted it."),
        ("h3", "1️⃣ He was spared from future sorrow"),
        ("q", "Deuteronomy 31:16", "this people will rise up, and go a whoring after the gods of the strangers of the land"),
        ("p", "God told Moses what Israel would do after his death, and Moses did not live to see it. He already knew how rebellious they were (📖 Deuteronomy 31:27), and God let him rest before the trouble came."),
        ("h3", "2️⃣ His ending was peaceful"),
        ("q", "Deuteronomy 34:5", None),
        ("p", "He died in God's presence, in peace, without shame and without fear — “all his saints are in thy hand.” (📖 Deuteronomy 33:3)"),
        ("h3", "What do we learn?"),
        ("ul", ["Not every answered prayer is a blessing; God's timing is wiser than our emotions. (📖 Isaiah 38:5)",
                "Pride after a blessing can bring trouble on the people we love. (📖 2 Kings 20:18)",
                "True faith accepts God's “no” as well as His “yes.” (📖 Deuteronomy 3:26)",
                "God sometimes takes His children early to protect them from what is coming. (📖 Isaiah 57:1)"]),
        ("p", "Don't fight God's plan for your life. When we accept His will, our ending will be peaceful:"),
        ("q", "Isaiah 57:2", None),
    ]),
    ("7. Saul", "Lesson from Saul", [
        ("key2", "Luke 3:9", "every tree therefore which bringeth not forth good fruit is hewn down, and cast into the fire"),
        ("h2", "What does “good fruit” mean?"),
        ("p", "A tree is known by its fruit. God does not only look at how our life starts; He looks at what our life produces. And the fruit He looks for is obedience."),
        ("h3", "One who bears good fruit:"),
        ("ul", ["stays humble after being lifted up", "obeys God fully, not partly", "guards the heart from jealousy", "seeks God alone"]),
        ("p", "So this verse is a warning: a good beginning is not enough without good fruit."),
        ("h2", "Example: Saul – from small beginnings to a fallen king"),
        ("p", "A sad example of this is Saul."),
        ("q", "1 Samuel 9:21", "Am not I a Benjamite, of the smallest of the tribes of Israel?"),
        ("p", "Saul came from the smallest tribe and the least family. He was out searching for his father's lost donkeys (📖 1 Samuel 9:3) when God was preparing him to be king. What changed his life? Not education, wealth or influence — but God's Spirit:"),
        ("q", "1 Samuel 10:6", "and shalt be turned into another man"),
        ("p", "So where did it go wrong?"),
        ("h3", "1️⃣ Partial obedience"),
        ("p", "God gave Saul a clear command, but he kept what God had told him to destroy. When Samuel came, he could hear the animals:"),
        ("q", "1 Samuel 15:14", "What meaneth then this bleating of the sheep in mine ears"),
        ("q", "1 Samuel 15:22", "to obey is better than sacrifice"),
        ("p", "Partial obedience is still disobedience."),
        ("h3", "2️⃣ Jealousy"),
        ("p", "When the people praised David more than Saul, jealousy entered his heart:"),
        ("q", "1 Samuel 18:9", None),
        ("p", "Pride cannot bear to see someone else honoured."),
        ("h3", "3️⃣ Seeking darkness"),
        ("p", "Saul had once put the mediums out of the land. (📖 1 Samuel 28:3) But when God did not answer him, he secretly went to one himself (📖 1 Samuel 28:6–8) — even though God had said:"),
        ("q", "Leviticus 20:6", None),
        ("h3", "What was the result?"),
        ("q", "1 Chronicles 10:13", None),
        ("p", "He lost God's presence, his peace, his direction and his throne, and the kingdom was given to David. (📖 1 Chronicles 10:14) Saul started low, became great, and ended in tragedy — not because he lacked opportunity or ability, but because he lacked obedience."),
        ("h3", "What do we learn?"),
        ("ul", ["God can lift anyone from a small beginning. (📖 1 Samuel 9:21)",
                "Partial obedience is still disobedience. (📖 1 Samuel 15:22)",
                "Jealousy grows when pride cannot bear someone else's honour. (📖 1 Samuel 18:9)",
                "When God seems silent, keep seeking Him — never the wrong voices. (📖 Leviticus 20:6)"]),
        ("p", "God can make you great, but only obedience keeps you there. Choose God's way today, stay close to Him, and you will bear good fruit:"),
        ("q", "John 15:5", "He that abideth in me, and I in him, the same bringeth forth much fruit"),
    ]),
    ("8. Gideon", "Lesson from Gideon", [
        ("key2", "Luke 4:4", "That man shall not live by bread alone, but by every word of God"),
        ("h2", "What does “by every word of God” mean?"),
        ("p", "Bread keeps the body alive, but it cannot make us strong inside. Jesus says real life and real strength come from every word of God. When we depend on God's word, even weak people become strong."),
        ("h3", "One who lives by God's word:"),
        ("ul", ["trusts God's strength more than their own", "obeys even when afraid", "remembers that God knows every detail of their life"]),
        ("p", "So this verse means: our strength is not in what we have, but in what God says."),
        ("h2", "Example: Gideon – from fear to faith"),
        ("p", "A great example of this is Gideon."),
        ("q", "Judges 6:11", "his son Gideon threshed wheat by the winepress, to hide it from the Midianites"),
        ("p", "Gideon was not a warrior. He was hiding his food from the enemy. And how did he see himself?"),
        ("q", "Judges 6:15", "my family is poor in Manasseh, and I am the least in my father's house"),
        ("p", "But how did God see him?"),
        ("q", "Judges 6:12", "The LORD is with thee, thou mighty man of valour"),
        ("p", "God saw who Gideon could become, not just who he was."),
        ("h3", "1️⃣ God knew every detail of his life"),
        ("p", "God told him to take “the second bullock of seven years old” (📖 Judges 6:25), and later to go down to the enemy camp with “Phurah thy servant.” (📖 Judges 7:10) God knew his father's animals, their age, and even his servant's name."),
        ("q", "Matthew 10:30", None),
        ("h3", "2️⃣ He went in God's strength, not his own"),
        ("q", "Judges 6:14", "Go in this thy might"),
        ("p", "Gideon felt unqualified, afraid and small. But God promised, “Surely I will be with thee.” (📖 Judges 6:16) When God is with you, weakness becomes strength."),
        ("h3", "3️⃣ He obeyed in private first"),
        ("p", "Before God used him publicly, God told him to pull down his father's altar of Baal. Gideon did it at night because he was afraid — but he obeyed. (📖 Judges 6:27)"),
        ("h3", "4️⃣ God made his army small"),
        ("q", "Judges 7:2", "lest Israel vaunt themselves against me, saying, Mine own hand hath saved me"),
        ("p", "From 32,000 men, God brought the army down to just 300 (📖 Judges 7:3, 7), so that everyone would know the victory was His."),
        ("h3", "What was the result?"),
        ("p", "With trumpets, clay jars and torches, the 300 surrounded the enemy camp and shouted:"),
        ("q", "Judges 7:20", "The sword of the LORD, and of Gideon"),
        ("p", "God threw the enemy into confusion, and they turned against each other. (📖 Judges 7:22) The fearful farmer became the deliverer of Israel."),
        ("h3", "What do we learn?"),
        ("ul", ["God sees who you can become, not only who you are today. (📖 Judges 6:12)",
                "God knows every detail of your life. (📖 Matthew 10:30)",
                "Go in God's strength, not your own. (📖 Judges 6:14)",
                "Obey in small, hidden things first; that is where God prepares leaders. (📖 Judges 6:27)"]),
        ("p", "Don't say, “I am too small” or “I am not strong enough.” God can turn fear into faith and weakness into victory, because:"),
        ("q", "2 Chronicles 14:11", "it is nothing with thee to help, whether with many, or with them that have no power"),
    ]),
    ("9. Joshua", "Lesson from Joshua", [
        ("key2", "John 1:9", None),
        ("h2", "What does “lighteth every man” mean?"),
        ("p", "God's light shines on every person — rich or poor, famous or unknown. Anyone can be used by God. But not everyone walks in that light. Those who obey His word experience His guidance, power and favour."),
        ("h3", "One who walks in that light:"),
        ("ul", ["hears God's word and does it", "is faithful in hidden places", "lets God do the promoting"]),
        ("p", "So this verse means: God gives the opportunity to everyone, but obedience to His word makes the difference."),
        ("q", "James 1:22", "But be ye doers of the word, and not hearers only"),
        ("h2", "Example: Joshua – the power of obedience"),
        ("p", "A great example of this is Joshua."),
        ("q", "Exodus 24:13", "And Moses rose up, and his minister Joshua"),
        ("p", "Joshua was not raised in a palace like Moses. He was simply Moses' assistant. Why did God choose him? Because God does not look for famous people; He looks for faithful people."),
        ("h3", "1️⃣ God gave him one secret for success"),
        ("p", "When Moses died, Joshua suddenly had to lead the whole nation. God gave him one instruction:"),
        ("q", "Joshua 1:8", None),
        ("p", "Keep God's word on your lips — speak it, teach it, declare it. Keep God's word in your thoughts — think on it, meditate on it, and plan your life by it. Success in God's kingdom is not about talent, but about obedience to His word."),
        ("h3", "2️⃣ God lifted him up"),
        ("q", "Joshua 3:7", "This day will I begin to magnify thee in the sight of all Israel"),
        ("p", "Joshua did not promote himself. God promoted him."),
        ("h3", "3️⃣ God did the impossible through him"),
        ("p", "When the priests stepped into the flooded Jordan, the water stopped, “and all the Israelites passed over on dry ground.” (📖 Joshua 3:17) When the people marched around Jericho and shouted, “the wall fell down flat.” (📖 Joshua 6:20) And in battle Joshua prayed, “Sun, stand thou still upon Gibeon.” (📖 Joshua 10:12)"),
        ("h3", "What was the result?"),
        ("q", "Joshua 4:14", "On that day the LORD magnified Joshua in the sight of all Israel"),
        ("p", "The assistant became the leader who brought Israel into the Promised Land."),
        ("h3", "What do we learn?"),
        ("ul", ["God looks for faithful people, not famous people. (📖 Exodus 24:13)",
                "Keep God's word on your lips and in your thoughts, day and night. (📖 Joshua 1:8)",
                "Promotion that comes from God is stronger than promotion from people. (📖 Joshua 3:7)",
                "When we step forward in obedience, God opens impossible paths. (📖 Joshua 3:17)"]),
        ("p", "Young people today hear many voices — social media, friends, culture and pressure — but God's voice is still the most important. Like Joshua, let us decide:"),
        ("q", "Joshua 24:15", "but as for me and my house, we will serve the LORD"),
    ]),
    ("10. Jeremiah", "Lesson from Jeremiah", [
        ("key2", "Mark 4:40", None),
        ("h2", "What does “why are ye so fearful?” mean?"),
        ("p", "Jesus said this to His disciples in a storm, while He was right there in the boat with them. Fear made them forget who was with them. Faith is not the absence of fear — it is choosing to trust God even while we feel afraid."),
        ("h3", "One who has faith:"),
        ("ul", ["remembers what God has already said", "does not run because of fear", "speaks the truth even in danger"]),
        ("p", "So this question is an invitation: let faith lead you, not fear."),
        ("h2", "Example: Jeremiah – from fear to faith"),
        ("p", "A great example of this is Jeremiah. At the very beginning, God gave him a promise:"),
        ("q", "Jeremiah 1:19", None),
        ("p", "Opposition would come — but defeat would not. And God kept His word: when the king ordered Jeremiah's arrest, “the LORD hid them.” (📖 Jeremiah 36:26)"),
        ("h3", "1️⃣ Fear shook his faith"),
        ("p", "But later Jeremiah became afraid. He tried to leave Jerusalem for his own land of Benjamin, and was caught at the gate. (📖 Jeremiah 37:12–13) He was beaten, imprisoned and thrown into a dungeon for many days. (📖 Jeremiah 37:15–16) When the king called for him, he begged:"),
        ("q", "Jeremiah 37:20", "lest I die there"),
        ("p", "Why did this happen? Fear made him forget what God had already told him."),
        ("q", "Proverbs 29:25", "The fear of man bringeth a snare"),
        ("h3", "2️⃣ God gave him another chance"),
        ("q", "Jeremiah 37:21", "and that they should give him daily a piece of bread out of the bakers' street"),
        ("p", "Even in his failure, God did not leave him. He was moved to the prison courtyard and given bread every day."),
        ("h3", "3️⃣ His faith grew"),
        ("p", "Before the same king, the frightened man now spoke boldly what God said:"),
        ("q", "Jeremiah 38:20", "so it shall be well unto thee, and thy soul shall live"),
        ("p", "And now it was the king who was afraid: “Let no man know of these words.” (📖 Jeremiah 38:24)"),
        ("h3", "What was the result?"),
        ("p", "When Jerusalem fell, even King Nebuchadnezzar gave an order about him:"),
        ("q", "Jeremiah 39:12", "Take him, and look well to him, and do him no harm"),
        ("p", "Others were in chains, but Jeremiah was set free in the same city. (📖 Jeremiah 40:4) The one who had been hunted was now honoured."),
        ("h3", "What do we learn?"),
        ("ul", ["When God is with you, opposition is normal, but defeat is not. (📖 Jeremiah 1:19)",
                "Fear makes us forget what God has already said. (📖 Proverbs 29:25)",
                "Failure is not the end; God gives second chances. (📖 Jeremiah 37:21)",
                "When you fear God, you will not fear people. (📖 Jeremiah 38:20)"]),
        ("p", "Fear may come, but faith must win. And God is gentle with those who fall:"),
        ("q", "Isaiah 42:3", "A bruised reed shall he not break"),
    ]),
    ("11. Jacob", "Lesson from Jacob", [
        ("key2", "Mark 6:50", "Be of good cheer: it is I; be not afraid"),
        ("h2", "What does “it is I; be not afraid” mean?"),
        ("p", "The disciples were alone on the sea at night, struggling against the wind, when Jesus came to them. In their loneliest and most frightening moment, He was there. A lonely path is never empty when God is on it."),
        ("h3", "On a lonely path, God:"),
        ("ul", ["shows that only His word stands", "reveals people's true nature", "shows how good He is", "blesses beyond what we imagine"]),
        ("h2", "Example: Jacob – what God does on a lonely path"),
        ("p", "A great example of this is Jacob. He had to run from home, alone and afraid. (📖 Genesis 27:41–45)"),
        ("h3", "1️⃣ Only God's word came true"),
        ("p", "His brother said, “I will slay my brother Jacob” — it never happened. His mother said, “tarry with him a few days” — it never happened. (📖 Genesis 27:41, 44) But on his first lonely night, God made him a promise:"),
        ("q", "Genesis 28:15", None),
        ("p", "People's words depend on situations. God's word controls situations."),
        ("h3", "2️⃣ People's true nature was revealed"),
        ("p", "Laban, whom his parents trusted, turned out not to be trustworthy. He used Jacob and cheated him again and again:"),
        ("q", "Genesis 31:7", "changed my wages ten times; but God suffered him not to hurt me"),
        ("p", "If Jacob had not walked this road, he would never have known who Laban really was. Some people's true nature is revealed only in separation."),
        ("h3", "3️⃣ God showed how good He is"),
        ("q", "Genesis 31:42", "surely thou hadst sent me away now empty"),
        ("p", "Laban kept Jacob for his own need, not out of love. People may stay with you for their benefit, but God stays with you for your good."),
        ("h3", "What was the result?"),
        ("q", "Genesis 32:10", "for with my staff I passed over this Jordan; and now I am become two bands"),
        ("p", "He left with nothing but a staff — alone, afraid and running. He returned with a great family, wealth and a new identity."),
        ("p", "Even then, his heart still felt weak at times: “Joseph is not, and Simeon is not, and ye will take Benjamin away.” (📖 Genesis 42:36) But at the end of his life he saw God's plan clearly: “The sceptre shall not depart from Judah.” (📖 Genesis 49:10)"),
        ("h3", "What do we learn?"),
        ("ul", ["People's words change with situations, but God's word stands. (📖 Genesis 28:15)",
                "On a lonely path, God separates the people who are not meant to stay. (📖 Genesis 31:7)",
                "Where people fail, God shows how good He is. (📖 Genesis 31:42)",
                "God blesses beyond what we can imagine. (📖 Genesis 32:10)"]),
        ("p", "Don't be afraid when people leave, and don't be broken when support fails. When God leads you into loneliness, He is separating, revealing and preparing you for something greater. He was with Jacob from the very first night:"),
        ("q", "Genesis 28:16", "Surely the LORD is in this place; and I knew it not"),
    ]),
    ("12. Jonah", "Lesson from Jonah", [
        ("key2", "Luke 5:20", None),
        ("h2", "What happens when Jesus sees faith?"),
        ("p", "Four men carried their paralysed friend to Jesus, even breaking open a roof to reach Him. When Jesus saw their faith, He forgave the man's sins — and the man got up, took his bed and went home glorifying God. (📖 Luke 5:25–26)"),
        ("h3", "When we trust God:"),
        ("ul", ["our sins are forgiven", "we are raised up", "our life becomes a testimony, and others glorify God"]),
        ("p", "But what happens when we do not trust God?"),
        ("h2", "Example: Jonah – from disobedience to destiny"),
        ("p", "God told Jonah to go to Nineveh. Jonah went the opposite way:"),
        ("q", "Jonah 1:3", "so he paid the fare thereof, and went down into it"),
        ("p", "The ship, the money, the effort — all of it was wasted, because none of it went where God had sent him. Every decision outside God's will ends in loss."),
        ("h3", "1️⃣ Disobedience brought a storm"),
        ("q", "Jonah 1:4", "But the LORD sent out a great wind into the sea"),
        ("p", "Disobedience does not affect only us. The sailors around Jonah were in danger too."),
        ("h3", "2️⃣ “I can handle it myself”"),
        ("q", "Jonah 1:12", "Take me up, and cast me forth into the sea"),
        ("p", "Perhaps Jonah thought he would either escape or be saved at the last moment. God did neither: “the LORD had prepared a great fish to swallow up Jonah.” (📖 Jonah 1:17) In the fish he could neither live freely nor die."),
        ("h3", "3️⃣ Life broke down step by step"),
        ("q", "Jonah 2:5", "the weeds were wrapped about my head"),
        ("p", "Pressure, deep wounds and shame closed in on him — just as the psalmist describes: “I am become a stranger unto my brethren” (📖 Psalm 69:8), and “I looked for some to take pity, but there was none.” (📖 Psalm 69:20)"),
        ("h3", "4️⃣ The turning point"),
        ("q", "Jonah 2:7", "When my soul fainted within me I remembered the LORD"),
        ("q", "Jonah 2:8", None),
        ("p", "Only then could Jonah say to God, “Thou art my strong refuge.” (📖 Psalm 71:7) We should not wait until we have lost everything to remember God."),
        ("h3", "What was the result?"),
        ("q", "Jonah 3:1", "And the word of the LORD came unto Jonah the second time"),
        ("p", "This time Jonah went. The king and the whole city repented (📖 Jonah 3:6–10), and “more than sixscore thousand persons” — over 120,000 people — were spared. (📖 Jonah 4:11) The man who ran away became a blessing to a whole city."),
        ("h3", "What do we learn?"),
        ("ul", ["Every decision outside God's will leads to loss. (📖 Jonah 1:3)",
                "Disobedience brings storms on us and on the people around us. (📖 Jonah 1:4)",
                "Don't wait to lose everything before turning to God. (📖 Jonah 2:7)",
                "God gives second chances, and an obedient life blesses thousands. (📖 Jonah 3:1)"]),
        ("p", "Don't run from God. Trust Him and walk in His path, and He will lift you again:"),
        ("q", "Psalm 71:20", "shalt quicken me again, and shalt bring me up again from the depths of the earth"),
    ]),
    ("13. David / Solomon", "Lesson from David and Solomon", [
        ("key2", "Matthew 6:33", None),
        ("h2", "What does it mean to “seek first”?"),
        ("p", "We all seek many things — success, money, security, a good name. Jesus says: put God's kingdom and His ways first, and He will add what we need."),
        ("h3", "One who seeks God first:"),
        ("ul", ["asks God for wisdom before anything else", "walks in God's ways every day", "repents quickly when they fall", "finishes well"]),
        ("h2", "Example: David and Solomon – a father's charge and a son's choice"),
        ("p", "A great example of this is David and his son Solomon. At the end of his life, David called Solomon and gave him his final charge:"),
        ("q", "1 Kings 2:2", "be thou strong therefore, and shew thyself a man"),
        ("q", "1 Kings 2:3", "that thou mayest prosper in all that thou doest"),
        ("p", "What would Solomon do with this charge?"),
        ("h3", "1️⃣ Solomon asked for wisdom first"),
        ("p", "God appeared to Solomon and said, “Ask what I shall give thee.” (📖 1 Kings 3:5) What would we have asked for? Solomon did not ask for money, long life or victory over his enemies. He said, “I am but a little child” (📖 1 Kings 3:7), and asked:"),
        ("q", "1 Kings 3:9", "Give therefore thy servant an understanding heart"),
        ("h3", "2️⃣ God added what he did not ask for"),
        ("q", "1 Kings 3:13", "And I have also given thee that which thou hast not asked, both riches, and honour"),
        ("p", "He sought God's wisdom first, and God added the rest — exactly as Jesus said."),
        ("h3", "3️⃣ But a good start is not enough"),
        ("q", "1 Kings 11:4", "his heart was not perfect with the LORD his God, as was the heart of David his father"),
        ("p", "In his old age Solomon's heart turned away to other gods. David had also failed badly in his life — but when he was confronted, he repented: “I have sinned against the LORD.” (📖 2 Samuel 12:13)"),
        ("q", "Psalm 51:10", None),
        ("h3", "What was the result?"),
        ("p", "David is remembered as a man after God's own heart (📖 1 Samuel 13:14), because he kept returning to God. Solomon's wisdom became famous, but because his heart turned away, the kingdom was torn apart after him. (📖 1 Kings 11:11)"),
        ("h3", "What do we learn?"),
        ("ul", ["Seek God's wisdom before anything else. (📖 1 Kings 3:9)",
                "When we put God first, He adds what we need. (📖 1 Kings 3:13)",
                "When you fall, repent quickly, as David did. (📖 Psalm 51:10)",
                "A good start is not enough — finish well. (📖 1 Kings 11:4)"]),
        ("p", "Start with God, stay with God and finish with God. And whenever you need wisdom, ask Him:"),
        ("q", "James 1:5", "If any of you lack wisdom, let him ask of God"),
    ]),
    ("14. John the Baptist", "Lesson from John the Baptist", [
        ("key2", "John 3:30", None),
        ("h2", "What does “he must increase, but I must decrease” mean?"),
        ("p", "John's followers were worried because people were leaving John and going to Jesus. John was not worried at all. His whole purpose was to make Jesus known, not himself."),
        ("h3", "One who lives like this:"),
        ("ul", ["speaks the truth boldly", "shows repentance in honest, generous living", "points people to Jesus, not to themselves"]),
        ("h2", "Example: John the Baptist – preparing the way"),
        ("p", "A great example of this is John himself."),
        ("q", "Luke 3:2", "the word of God came unto John the son of Zacharias in the wilderness"),
        ("p", "Why the wilderness? The first verses of Luke 3 name an emperor, governors and high priests — yet God's word came to a man living simply by the Jordan. He had one assignment:"),
        ("q", "Luke 3:4", "Prepare ye the way of the Lord, make his paths straight"),
        ("h3", "1️⃣ He called for real change"),
        ("q", "Luke 3:8", "Bring forth therefore fruits worthy of repentance"),
        ("p", "When the people asked, “What shall we do then?”, he gave simple answers: share your coat and your food; tax collectors, take no more than what is right; soldiers, do no violence, accuse no one falsely, and be content. (📖 Luke 3:10–14)"),
        ("h3", "2️⃣ He pointed to Jesus, not to himself"),
        ("p", "People wondered whether John was the Christ. He could have taken that honour. Instead he said:"),
        ("q", "Luke 3:16", "but one mightier than I cometh, the latchet of whose shoes I am not worthy to unloose"),
        ("p", "And when he saw Jesus, he said, “Behold the Lamb of God, which taketh away the sin of the world.” (📖 John 1:29)"),
        ("h3", "3️⃣ He spoke the truth even to a king"),
        ("p", "John rebuked Herod for his sin, and Herod shut him up in prison. (📖 Luke 3:19–20) The truth cost him his freedom, but he did not keep silent."),
        ("h3", "What was the result?"),
        ("q", "Luke 7:28", "Among those that are born of women there is not a greater prophet than John the Baptist"),
        ("p", "The man in the wilderness who made himself small was honoured by Jesus Himself."),
        ("h3", "What do we learn?"),
        ("ul", ["God's word can reach us in any place. (📖 Luke 3:2)",
                "Real repentance shows in honest, generous living. (📖 Luke 3:8–14)",
                "Make Jesus greater, not yourself. (📖 John 3:30)",
                "Speak the truth, even when it costs you. (📖 Luke 3:19–20)"]),
        ("p", "Like John, each of us can prepare the way for Jesus in the place where we live, just as the prophet said:"),
        ("q", "Isaiah 40:3", "Prepare ye the way of the LORD"),
    ]),
    ("15. Judah", "Lesson from Judah", [
        ("key2", "John 15:13", None),
        ("h2", "What is the greatest love?"),
        ("p", "Jesus says the greatest love is to lay down your life for others. This kind of love does not come naturally; God grows it in us as He changes our hearts."),
        ("h3", "One who loves like this:"),
        ("ul", ["confesses their own wrong", "takes responsibility for others", "stands in the gap when someone is in danger"]),
        ("h2", "Example: Judah – a changed heart"),
        ("p", "An example of this is Judah, one of Jacob's sons. But his story does not start well."),
        ("q", "Genesis 37:27", "Come, and let us sell him to the Ishmeelites"),
        ("p", "When his brothers wanted to kill Joseph, it was Judah who said, “What profit is it if we slay our brother” (📖 Genesis 37:26) — and suggested selling him instead. Profit instead of murder, but betrayal all the same. Can a person like this change?"),
        ("h3", "1️⃣ He confessed his wrong"),
        ("p", "Later Judah sinned with his daughter-in-law Tamar. When he was confronted, he did not hide it:"),
        ("q", "Genesis 38:26", "She hath been more righteous than I"),
        ("p", "That confession was the first sign of a changing heart."),
        ("q", "Proverbs 28:13", "but whoso confesseth and forsaketh them shall have mercy"),
        ("h3", "2️⃣ He took responsibility for his brother"),
        ("p", "Years later the brothers had to take Benjamin to Egypt, and their father was afraid to let him go. Judah said:"),
        ("q", "Genesis 43:9", "I will be surety for him; of my hand shalt thou require him"),
        ("h3", "3️⃣ He offered himself in his brother's place"),
        ("p", "When the silver cup was found in Benjamin's sack, Judah did not run. He came near to the governor and pleaded:"),
        ("q", "Genesis 44:33", "let thy servant abide instead of the lad a bondman to my lord"),
        ("q", "Genesis 44:34", "For how shall I go up to my father, and the lad be not with me?"),
        ("p", "The brother who once sold a brother now offered his own life for his brother. At that moment “Joseph could not refrain himself.” (📖 Genesis 45:1)"),
        ("h3", "What was the result?"),
        ("q", "Genesis 49:10", "The sceptre shall not depart from Judah"),
        ("p", "From Judah came King David — and Jesus, “the Lion of the tribe of Juda” (📖 Revelation 5:5), who laid down His life for us."),
        ("h3", "What do we learn?"),
        ("ul", ["A bad start does not have to be the end of your story. (📖 Genesis 37:27)",
                "Confessing our wrong is the first step of change. (📖 Genesis 38:26)",
                "Real leaders take responsibility for others. (📖 Genesis 43:9)",
                "The greatest love stands in the gap for others. (📖 Genesis 44:33)"]),
        ("p", "God can take a heart that once betrayed and make it a heart that lays down its life for others — just as Jesus did for us:"),
        ("q", "1 John 3:16", "Hereby perceive we the love of God, because he laid down his life for us"),
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
