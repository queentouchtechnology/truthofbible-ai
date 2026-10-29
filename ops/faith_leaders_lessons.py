"""Faith Leaders (chapters 1-24): add the three lessons every Life of Jesus chapter has -
"Read: <passage>", "Short Lesson (Adults)" and "Brief Lesson (All Ages)" - in the same Editor.js shape.

The new lessons go first in each chapter; the chapter's existing lessons (videos, Tamil stories, memory
verses, questions) are never edited or deleted and stay after them. Safe to re-run: a chapter that
already has a "Short Lesson (Adults)" is skipped (1-15 were added first, 16-24 afterwards).

Run inside the Frappe container:
    cd /home/frappe/frappe-bench/sites && ../env/bin/python faith_leaders_lessons.py          # dry run
    cd /home/frappe/frappe-bench/sites && ../env/bin/python faith_leaders_lessons.py --apply
"""
import json
import random
import string
import sys
import time

COURSE = "faith-leaders-learning-faith-through-bible-heroes"
SITE = "learn.truthofbible.org"
LAST_CHAPTER = 24

# (chapter title, passage, watch-for, background note, short-lesson paragraphs, brief-lesson sentences)
LESSONS = [
    ("1. Hannah", "1 Samuel 1:1-28",
     "Hannah's yearly grief and Peninnah's taunts; her silent prayer at Shiloh and her vow; Eli mistaking her for drunk and her gentle reply; her face no longer sad before any answer came; and Samuel's birth — and Hannah keeping her promise.",
     "Hannah's song of praise follows in 1 Samuel 2:1–10. In 2:19–21 she makes Samuel a little coat every year, and God gives her three more sons and two daughters — “them that honour me I will honour” (2:30).",
     ["For years Hannah carried a sorrow she couldn't fix. She had no child, and her rival Peninnah made sure she felt it “year by year,” until Hannah wept and would not eat. What stands out is where she took that pain. She didn't fight back, and she didn't give up on God; she went to the house of the Lord and poured out her soul.",
      "Her prayer was so heartfelt that only her lips moved, and Eli the priest thought she was drunk. Hannah could have been offended. Instead she answered gently: “I am a woman of a sorrowful spirit… I have poured out my soul before the Lord.” Her reaction to being misunderstood showed the quality of her faith as much as her prayer did.",
      "Then something quiet but remarkable happens: before anything had changed, “her countenance was no more sad.” God gave her peace before he gave her the answer. When Samuel was born she named him “asked of God,” and — hardest of all — she kept her vow and gave him back to serve the Lord.",
      "Hannah's story isn't about getting what you want by praying hard enough. It's about bringing real pain to God, trusting him while the answer is still delayed, and honouring him even when obedience costs something. And God honoured her in return, with more children and a son who would lead a nation."],
     ["Hannah was very sad because she had no children, and someone kept teasing her about it.",
      "Instead of fighting back, she went to God's house and prayed with all her heart, and God gave her peace.",
      "God gave her a baby boy named Samuel, and Hannah kept her promise by letting him grow up serving God."]),

    ("2. Ruth", "Ruth 1:1-22",
     "a famine and three funerals; Naomi urging her daughters-in-law to go home; Orpah's goodbye kiss and Ruth clinging to Naomi; “thy people shall be my people, and thy God my God”; and Naomi's bitter arrival in Bethlehem — “call me Mara.”",
     "The story continues in Ruth 2–4: Ruth gleaning in Boaz's field (2:2–12), Boaz as kinsman-redeemer (chapters 3–4), and the birth of Obed, the grandfather of King David (4:13–17).",
     ["Ruth's life fell apart in a few verses. Her husband died, her father-in-law and brother-in-law died, and she was left a widow in a home with no income and no future in sight. Being a good person hadn't protected her from loss — the Bible is honest that the righteous face many troubles.",
      "At the crossroads Naomi urged both daughters-in-law to go back to their own families, where they would be safe and could marry again. Orpah kissed her and went. Ruth clung to her: “Whither thou goest, I will go… thy people shall be my people, and thy God my God.” It was a choice of faith over comfort — leaving the familiar for a God she was still coming to know.",
      "In Bethlehem she was a foreigner, poor and easily overlooked. She went out to glean the leftover grain, quietly and faithfully doing the small work in front of her. No one seemed to be watching — but God was, and so was Boaz, who blessed her: “The Lord recompense thy work.”",
      "In time Boaz redeemed the family land and married Ruth, and their son Obed became the grandfather of King David — placing a forgotten widow from Moab in the family line of Jesus. Ruth's story reminds us that what people overlook, God remembers, and that faithfulness in small things is never small to him."],
     ["Ruth's husband died, and she was left sad and alone with her mother-in-law Naomi.",
      "Ruth chose to stay with Naomi and follow her God, and she worked hard collecting grain in the fields.",
      "God saw her kindness: a good man named Boaz married her, and her great-grandson became King David."]),

    ("3. Esther", "Esther 4:1-17",
     "Mordecai in sackcloth at the king's gate; the law that anyone who came to the king uninvited could die; Mordecai's challenge, “who knoweth whether thou art come to the kingdom for such a time as this?”; Esther's call to fast for three days; and her decision, “if I perish, I perish.”",
     "Esther's rise is told in chapter 2: an orphan raised by her cousin Mordecai, chosen as queen after a long time of preparation. The king receives her and grants her request in 5:1–3, and her people are saved in chapters 7–8.",
     ["Esther started with very little: an orphan, raised by her cousin Mordecai, one of many young women taken to the Persian palace. To everyone around her she was ordinary. Yet she found favour, and after a long season of preparation she became queen — and stayed humble, still listening to Mordecai's counsel.",
      "Then came the crisis. A decree had gone out to destroy her people, and the only way to stop it was to approach the king without being called — an act that could cost her life. Esther was afraid, and she said so honestly. Mordecai's reply went straight to the heart: “Who knoweth whether thou art come to the kingdom for such a time as this?”",
      "Esther didn't answer with bravado. She asked her people to fast for three days, and then she decided: “I will go in unto the king… and if I perish, I perish.” It wasn't perfect confidence; it was real faith — courage that begins where comfort ends.",
      "When she stood in the court, the king held out his golden sceptre and granted her request, and her people were saved. Esther's story shows that God can use an ordinary life for an extraordinary purpose, and that the waiting seasons are often training for the moment he has prepared."],
     ["Esther was an orphan girl who became queen of a great kingdom.",
      "When a wicked plan put her people in danger, she was scared, but she prayed and fasted and bravely went to the king.",
      "The king listened to her, and God used Esther to save her whole nation."]),

    ("4. Samson", "Judges 16:4-31",
     "the Philistine lords offering Delilah eleven hundred pieces of silver each; three false answers and then the true one; the sad line “he wist not that the Lord was departed from him”; his blindness, the mill, and the boy who led him by the hand; and his last prayer, “remember me… strengthen me.”",
     "Samson's calling before birth is in Judges 13. The first betrayal and the burned fields (14:20–15:6) and the night in Gaza (16:1–3) lead up to this chapter. “By mercy and truth iniquity is purged” (Proverbs 16:6).",
     ["Samson had everything a calling could offer: chosen before he was born, filled with strength, set apart to begin delivering Israel. But a calling is not the same as obedience, and his story is a slow lesson in what happens when someone keeps walking away from God's plan.",
      "The first betrayal — his wife given to another man — produced anger, not repentance. He burned the Philistines' fields, and in revenge they burned his wife and her father. Grief followed grief. Instead of running to God, Samson ran to comfort in the wrong places: a prostitute in Gaza, then Delilah, a relationship God never led him into. Sin promised relief and delivered more trouble.",
      "Delilah sold him for silver. Step by step he lost his strength, then his eyes, then his dignity — mocked as entertainment and led around by a small boy. The saddest line in the chapter is that “he wist not that the Lord was departed from him.” Sin always takes more than it promises.",
      "And yet the story ends with grace. Blind and broken, Samson remembered his calling and prayed: “Remember me, I pray thee, and strengthen me, I pray thee, only this once.” God answered. Grace was real — but so much sorrow could have been avoided. The invitation for us is to turn back early, while it is still easy."],
     ["God gave Samson amazing strength to help his people.",
      "But Samson kept making wrong choices, and he lost his strength, his eyesight and his freedom.",
      "At the end he turned back and prayed, and God helped him one last time — teaching us to obey God early."]),

    ("5. Job", "Job 1:1-22",
     "God's own description of Job; Satan's claim that Job only serves God because he is blessed; four messengers arriving one after another; Job falling to the ground and worshipping; and his words, “the Lord gave, and the Lord hath taken away; blessed be the name of the Lord.”",
     "Job's friends sit with him in silence for seven days (2:13). His question about the wicked prospering is in 21:7–12. God speaks from the whirlwind in chapters 38–41, and restores Job in 42:10–15.",
     ["Before any of the suffering begins, God himself describes Job: “a perfect and an upright man, one that feareth God, and escheweth evil.” Job's trial didn't come because he was doing badly — it came because his faith was real, and God allowed it to be tested. A good life is not the same as a trouble-free life.",
      "In a single day Job lost his wealth and all his children, and soon afterwards his health. When his friends came, they sat with him in silence for seven days. When Job finally spoke, he cursed the day he was born — he was honest about his pain and confusion. But he never cursed God, which is exactly what Satan expected him to do.",
      "The hardest part of Job's test wasn't only the loss. It was looking around and seeing people who rejected God living long, comfortable lives, their homes safe and their children dancing (Job 21:7–12). “Why?” burned in his heart, and God seemed silent for a long time.",
      "When God finally spoke, he didn't explain everything; he reminded Job who holds the world together, and Job humbled himself. Then God said Job had spoken what was right about him, and restored him with more than before. Faith isn't pretending life is fair — it's staying with God when it isn't, trusting that he never forgets faithfulness."],
     ["Job loved God, but one day he lost his animals, his children and his health.",
      "He was very sad and didn't understand why, but he never turned against God.",
      "In the end God spoke to Job and blessed him with even more than he had before."]),

    ("6. Moses / Hezekiah", "Deuteronomy 34:1-12; Isaiah 38:1-8",
     "Moses on Mount Nebo, seeing the land he would not enter; the Lord himself burying Moses; Hezekiah's illness and the message “set thine house in order”; his tears and the fifteen years God added; and the shadow going back on the sundial.",
     "Moses had asked to enter the land and accepted God's “no” (Deuteronomy 3:25–26). God told him beforehand what Israel would do after his death (31:16–17). Hezekiah's visit from Babylon and its cost are in Isaiah 39 and 2 Kings 20:12–18. “The righteous is taken away from the evil to come. He shall enter into peace” (Isaiah 57:1–2).",
     ["This lesson sets two endings side by side. Moses wanted badly to cross the Jordan into the Promised Land, and he asked God for it. God said no. Moses accepted it — and instead of bitterness, his last view was from Mount Nebo, with God himself showing him the whole land before he died in God's presence.",
      "King Hezekiah received a different message: “Set thine house in order; for thou shalt die.” He wept bitterly and pleaded, and God added fifteen years to his life. It looks like the happier ending, but the extra years brought new problems. Envoys came from Babylon, and Hezekiah proudly showed them every treasure he had — and Isaiah told him that one day all of it, and some of his own descendants, would be carried away to Babylon.",
      "Meanwhile God had shown Moses what Israel would do after his death: turn to other gods and face judgment. Moses was spared from living to see it. Isaiah 57 says the righteous are sometimes taken away “from the evil to come” and “enter into peace.”",
      "The point isn't that we shouldn't pray for healing or long life — Scripture invites us to bring every request to God. It's that God's timing, and even his “no,” can be acts of love we don't yet understand. Moses trusted God's decision, and his ending was peaceful, unashamed, and safe in God's hands."],
     ["Moses asked God to let him into the Promised Land, but God said no, and Moses trusted Him.",
      "King Hezekiah was sick and begged for more years, and God gave him fifteen more.",
      "But in those extra years Hezekiah became proud and made a big mistake — which teaches us that God's plan is always best."]),

    ("7. Saul", "1 Samuel 15:10-26",
     "God grieving that he made Saul king; Saul insisting “I have performed the commandment of the Lord”; Samuel's question about the bleating of the sheep; “to obey is better than sacrifice”; and Saul blaming the people.",
     "Saul's humble beginnings are in 1 Samuel 9:21 and 10:6–10. His jealousy of David starts in 18:7–9, his visit to the medium at Endor is in chapter 28, and 1 Chronicles 10:13–14 sums up why he died.",
     ["Saul's story begins in an unlikely place. “Am not I a Benjamite, of the smallest of the tribes of Israel? and my family the least?” he asked when Samuel singled him out. He was out looking for his father's lost donkeys, and God was preparing him to be king. When the Spirit of God came on him, he was “turned into another man.”",
      "The fall started with partial obedience. God gave a clear command about the Amalekites, and Saul kept the best of what God had told him to destroy. When Samuel arrived, Saul greeted him with “I have performed the commandment of the Lord” — while the animals bleated in the background. “To obey is better than sacrifice,” Samuel told him.",
      "Pride made the rest worse. When the women sang that Saul had slain his thousands and David his ten thousands, “Saul eyed David from that day and forward.” And in the end, after removing mediums from the land himself, he secretly went to one. 1 Chronicles 10:13–14 sums it up: he died for his unfaithfulness, for not keeping the word of the Lord, and for seeking a medium instead of the Lord.",
      "Saul didn't lack opportunity or ability. He started low, God made him great, and disobedience slowly undid it. God can lift anyone from a small beginning — but only humility and obedience keep us there."],
     ["Saul came from a small, ordinary family, but God chose him to be Israel's first king.",
      "Later Saul stopped fully obeying God and became jealous of David.",
      "Because Saul kept disobeying, he lost his kingdom — showing us that obeying God keeps us blessed."]),

    ("8. Gideon", "Judges 7:1-22",
     "32,000 men cut down to 300; God's reason, “lest Israel vaunt themselves against me”; Gideon and his servant Phurah creeping down to the enemy camp; the dream of the barley loaf; and the trumpets, jars and torches — “The sword of the Lord, and of Gideon.”",
     "Gideon's call in the winepress — “The Lord is with thee, thou mighty man of valour” — is in Judges 6:11–16. The altar of Baal and the second bullock “of seven years old” are in 6:25–27, and the fleece in 6:36–40.",
     ["When the angel found Gideon, he was threshing wheat in a winepress — hiding his food from the Midianite raiders. “My family is poor in Manasseh, and I am the least in my father's house,” he said. Yet the greeting was “The Lord is with thee, thou mighty man of valour.” God saw who Gideon could become, not just who he was that day.",
      "God's instructions were strikingly specific: take your father's young bullock, “the second bullock of seven years old,” and pull down the altar of Baal. Later he told Gideon to take “Phurah thy servant” down to the enemy camp. God knew the details of Gideon's life down to an animal's age and a servant's name — and he knows ours. Gideon obeyed the first command at night because he was afraid, but he obeyed.",
      "Then God did something that makes no military sense: he cut an army of 32,000 down to 300, “lest Israel vaunt themselves against me, saying, Mine own hand hath saved me.” Armed with trumpets, empty jars and torches, the 300 surrounded the camp and shouted “The sword of the Lord, and of Gideon,” and the Midianites turned on each other.",
      "Gideon's strength was never his skill or experience. It was learning to trust God's word more than his own fear. “Go in this thy might,” God told him — and the same God still makes weak people strong, so that everyone can see the power is his."],
     ["Gideon was hiding and scared, but God called him a mighty warrior.",
      "God made his army very small — only 300 men — so everyone would know God gave the victory.",
      "With trumpets, jars and torches, Gideon's tiny army won, because God was with them."]),

    ("9. Joshua", "Joshua 1:1-9",
     "“Moses my servant is dead; now therefore arise”; the promise “I will not fail thee, nor forsake thee”; the call to “be strong and of a good courage,” repeated three times; and the book of the law that must not depart from his mouth, meditated on day and night.",
     "Joshua first appears as Moses' minister (Exodus 24:13). After this charge come the Jordan crossing (3:7–17; 4:14), the fall of Jericho (6:20) and the day the sun stood still (10:12–13).",
     ["Joshua didn't have Moses' extraordinary background — no rescue from the Nile, no palace upbringing. For years he was simply “his minister Joshua,” Moses' assistant. But God was watching his faithfulness in that hidden role, and when Moses died, God turned to the assistant and said, “Arise, go over this Jordan.”",
      "Leading a whole nation into an unknown land would have frightened anyone, so God gave Joshua one key instruction: “This book of the law shall not depart out of thy mouth; but thou shalt meditate therein day and night… for then thou shalt make thy way prosperous.” God's word on his lips, and God's word in his thoughts — speaking it, thinking on it, and planning his life by it.",
      "Then God began to lift him up: “This day will I begin to magnify thee in the sight of all Israel.” The priests stepped into a flooded Jordan and the water stopped. Israel marched around Jericho for seven days and shouted, and the walls fell. In one battle Joshua even prayed, “Sun, stand thou still,” and the day was lengthened. Joshua didn't promote himself; God promoted him.",
      "Joshua's life shows that the difference between an ordinary life and a powerful one is not talent but obedience to God's word. Young people today hear many voices — but Joshua's choice is still open to us: “As for me and my house, we will serve the Lord.”"],
     ["Joshua was Moses' helper, and when Moses died God chose him to lead Israel.",
      "God told Joshua to keep His word in his mouth and think about it day and night.",
      "Joshua obeyed, and God did amazing things — the river stopped, Jericho's walls fell, and Israel won."]),

    ("10. Jeremiah", "Jeremiah 37:11-21",
     "Jeremiah leaving Jerusalem for the land of Benjamin; his arrest at the gate; the beating and the dungeon; his plea to the king, “lest I die there”; and the king moving him to the prison court with a piece of bread every day.",
     "God's promise at his calling is in 1:18–19: “they shall fight against thee; but they shall not prevail.” God hides him in 36:26. His bold word to the king is in 38:14–24, and Nebuchadnezzar's order to look after him in 39:11–12.",
     ["At his calling, God made Jeremiah a promise: “I have made thee this day a defenced city, and an iron pillar, and brasen walls… they shall fight against thee; but they shall not prevail.” Opposition was guaranteed — defeat was not. And early on God proved it: when the king ordered Jeremiah's arrest, “the Lord hid them.”",
      "But even prophets get afraid. In chapter 37, Jeremiah tried to slip out of Jerusalem to his home region of Benjamin. He was caught at the gate, accused, beaten and thrown into a dungeon for many days. When the king finally sent for him, Jeremiah begged not to be sent back “lest I die there.” Fear made him forget what God had already told him, and step by step things got worse.",
      "God didn't abandon him. The king moved him to the prison courtyard and gave him bread daily — a small relief, and another chance. And Jeremiah's faith grew. When the same king questioned him again, the frightened man was gone: he told the king plainly what God said — obey, “and thy soul shall live.” Now it was the king who was afraid, asking him to keep the conversation secret.",
      "In the end, when Jerusalem fell, Nebuchadnezzar himself ordered that Jeremiah be looked after and given whatever he asked. Faith, Jeremiah learned, isn't the absence of fear — it's choosing to trust God while you still feel it. Fear may come, but faith must win."],
     ["God promised Jeremiah that He would protect him from his enemies.",
      "Once Jeremiah got scared and tried to run away, and he ended up in prison.",
      "But God gave him another chance, Jeremiah became brave, and God kept him safe."]),

    ("11. Jacob", "Genesis 28:10-22",
     "Jacob alone on the road with a stone for a pillow; the ladder and the angels; God's promise, “I will not leave thee, until I have done that which I have spoken to thee of”; Jacob waking to say “Surely the Lord is in this place; and I knew it not”; and his vow.",
     "Why he fled: Esau's threat and Rebekah's “tarry with him a few days” (27:41–45). His twenty years with Laban are in chapters 29–31, and his blessing of his sons — including the sceptre for Judah — is in Genesis 49.",
     ["Jacob left home in a hurry. His brother Esau had sworn to kill him, and his mother Rebekah told him to stay with her brother Laban “a few days, until thy brother's fury turn away.” Neither word came true: Esau never killed him, and those few days became twenty years. People's words depend on circumstances; only what God spoke came to pass.",
      "On that first lonely night, with a stone for a pillow, God met him in a dream and promised, “I will not leave thee, until I have done that which I have spoken to thee of.” Jacob woke saying, “Surely the Lord is in this place; and I knew it not.” The loneliest road of his life was the place he first truly met God.",
      "The uncle his parents trusted turned out not to be trustworthy. Laban deceived Jacob and changed his wages ten times, keeping him for his own benefit. Some people's true nature only becomes clear in seasons of separation. But where people failed, God kept working: he protected Jacob, prospered him, and sent him home with a large family.",
      "Even then Jacob's heart still felt weak at times — when Joseph was gone and Benjamin was taken to Egypt. And at the end of his life he saw clearly that God's purpose would run through Judah, from whom “the sceptre shall not depart.” When God leads us down a lonely path, he is separating, revealing, and preparing us for something greater."],
     ["Jacob had to run away from home all alone, and he was scared.",
      "That night God met him in a dream and promised never to leave him.",
      "Even when his uncle cheated him, God took care of Jacob and gave him a big family."]),

    ("12. Jonah", "Jonah 1:1-2:10",
     "Jonah paying the fare to Tarshish, the opposite direction; the great wind and the frightened sailors; “take me up, and cast me forth into the sea”; the great fish; and Jonah's prayer from the depths — “I remembered the Lord.”",
     "God calls Jonah a second time in 3:1–3; the king and the whole city repent in 3:6–10; and 4:11 speaks of more than 120,000 people God cared about. This week's key verse is Luke 5:20 — Jesus saw their faith and forgave.",
     ["God told Jonah to go to Nineveh, and Jonah went the other way. He found a ship to Tarshish, “paid the fare thereof,” and went down into it. Every step of that plan cost him something — money, effort, distance — and none of it took him anywhere God wanted him to go. Decisions made outside God's will end in loss.",
      "Then “the Lord sent out a great wind.” Jonah's disobedience didn't only affect Jonah; the sailors around him were terrified and threw their cargo overboard. When the storm wouldn't stop, Jonah said, “Take me up, and cast me forth into the sea.” Perhaps he thought he would either escape or be rescued at the last moment. God did neither — he prepared a great fish, a place where Jonah could neither live freely nor die.",
      "Inside the fish Jonah describes it plainly: the waters surrounded him, the depths closed in, “the weeds were wrapped about my head.” Life breaks down step by step when we run from God. Then came the turning point: “When my soul fainted within me I remembered the Lord.” And he saw clearly that “they that observe lying vanities forsake their own mercy.”",
      "God gave Jonah a second chance. “The word of the Lord came unto Jonah the second time,” and this time he went. The king of Nineveh and the whole city repented, and more than 120,000 people were spared. When we stop running and trust God, our lives become a blessing to many."],
     ["God asked Jonah to go to Nineveh, but Jonah ran away on a ship.",
      "A big storm came, Jonah was thrown into the sea, and a huge fish swallowed him.",
      "Inside the fish Jonah prayed, God gave him another chance, and a whole city turned to God."]),

    ("13. David / Solomon", "1 Kings 2:1-4; 1 Kings 3:5-14",
     "David's last charge to Solomon — “be thou strong therefore, and shew thyself a man”; the promise that keeping God's ways leads to prospering; God's offer at Gibeon, “Ask what I shall give thee”; Solomon calling himself “but a little child”; and God giving him what he didn't ask for as well.",
     "David's own story runs from the shepherd boy anointed by Samuel (1 Samuel 16) and the fight with Goliath (17) to his sin and repentance (2 Samuel 11–12; Psalm 51). 1 Kings 11:1–11 records how Solomon's heart turned away in his old age.",
     ["David had been a shepherd boy, a giant-killer, a fugitive and a king — and a man who failed badly and repented deeply. At the end of his life he called Solomon in and handed on what mattered most: “Be thou strong therefore, and shew thyself a man; and keep the charge of the Lord thy God, to walk in his ways… that thou mayest prosper in all that thou doest.”",
      "Soon afterwards God appeared to young Solomon at Gibeon with an extraordinary offer: “Ask what I shall give thee.” Solomon didn't ask for wealth, long life or victory over his enemies. He said, “I am but a little child… Give therefore thy servant an understanding heart.” He knew the task was bigger than he was.",
      "God was pleased, and gave him wisdom — and also the riches and honour he hadn't asked for. Seeking God's wisdom first put everything else in its proper place. Solomon's wisdom became famous, and Israel enjoyed peace in his days.",
      "But the story carries a warning too. In his old age Solomon's heart was turned away after other gods, and “his heart was not perfect with the Lord his God, as was the heart of David his father” (1 Kings 11:4). A good start isn't enough; faith leaders finish well by keeping the charge — walking in God's ways every day, not only at the beginning."],
     ["King David told his son Solomon to always obey God.",
      "When God asked Solomon what he wanted, Solomon asked for wisdom to lead God's people well.",
      "God was happy and gave him wisdom, riches and honour — reminding us to keep following God our whole life."]),

    ("14. John the Baptist", "Luke 3:1-20",
     "the word of God coming to John in the wilderness; “Prepare ye the way of the Lord”; his plain answers to the crowds, the tax collectors and the soldiers; “one mightier than I cometh”; and his rebuke of Herod, which led to prison.",
     "John's birth is told in Luke 1. In John 3:27–30 he says, “He must increase, but I must decrease,” and Jesus speaks of him in Luke 7:24–28 and Matthew 11:7–11.",
     ["The word of God came to John not in a palace or the temple but “in the wilderness.” The first verses of Luke 3 name an emperor, governors and high priests, yet God's message went to a man living plainly by the Jordan. John's whole life was about one assignment: “Prepare ye the way of the Lord.”",
      "His preaching was direct. When the crowds asked, “What shall we do then?” he gave practical answers: share your coat and your food; tax collectors, take no more than is right; soldiers, don't extort or accuse falsely. Repentance, for John, showed up in ordinary honesty and generosity — “fruits worthy of repentance.”",
      "People wondered whether he was the Christ, and John could easily have taken the attention. Instead he pointed away from himself: “One mightier than I cometh, the latchet of whose shoes I am not worthy to unloose.” Later, when his followers worried that the crowds were going to Jesus, he said, “He must increase, but I must decrease.”",
      "John's courage cost him. He rebuked Herod for his sin and was shut up in prison. But Jesus said that among those born of women there was no greater prophet. A faith leader, John shows us, isn't someone who gathers followers for himself, but someone who speaks the truth boldly and points every eye to Jesus."],
     ["John the Baptist lived in the desert and told people to get ready for Jesus.",
      "He taught them to turn back to God, share with others and be honest.",
      "When people praised him, John said, “Jesus must become greater, and I must become less.”"]),

    ("15. Judah", "Genesis 44:18-34",
     "Judah stepping forward to speak to the governor of Egypt; his description of their father's love for Benjamin; “how shall I go up to my father, and the lad be not with me?”; and his offer to stay as a slave in Benjamin's place.",
     "Judah was the one who said “let us sell him” about Joseph (37:26–27), and he later confessed about Tamar, “She hath been more righteous than I” (38:26). He pledged himself for Benjamin in 43:8–9. Jacob's blessing says “The sceptre shall not depart from Judah” (49:8–10) — the line of David and of Jesus.",
     ["Judah's story doesn't start well. When his brothers wanted Joseph dead, it was Judah who said, “Come, and let us sell him” — profit instead of murder, but betrayal all the same. Later, with his daughter-in-law Tamar, he acted shamefully until he was confronted and admitted, “She hath been more righteous than I.” That confession was the first sign of a changing heart.",
      "Years later, famine drove the brothers to Egypt, and the governor — Joseph, though they didn't know it — demanded to see Benjamin. Jacob refused to let him go, and Judah stepped forward: “I will be surety for him; of my hand shalt thou require him.” The brother who once sold a brother now offered his own life as a guarantee.",
      "When the silver cup was found in Benjamin's sack, Judah didn't run. He came near and pleaded, telling of his father's grief and ending with an offer: “Let thy servant abide instead of the lad a bondman to my lord… for how shall I go up to my father, and the lad be not with me?” That was the moment Joseph could no longer hold back his tears.",
      "Judah shows that God can transform a person's character. At the end of Genesis, Jacob declared that “the sceptre shall not depart from Judah” — the line of King David and, in time, of Jesus, who gave his life in our place. Leadership in God's kingdom grows out of repentance and a willingness to stand in the gap for others."],
     ["Judah once helped sell his brother Joseph, which was very wrong.",
      "Years later he changed, and when his little brother Benjamin was in trouble, Judah offered to take his place.",
      "God made Judah's family the family of King David and of Jesus."]),

    # 16-24: written from the chapters' own Tamil lessons, which stay in place after these three.
    ("16. Nehemiah", "Nehemiah 1:1-2:8",
     "Nehemiah serving as the king's cupbearer in Shushan; the news that Jerusalem's walls were broken down; his weeping, fasting and praying “day and night”; the king noticing his sad face — he had never been sad in his presence before; and his request, “send me unto Judah.”",
     "This week's verse is Matthew 25:13 — “Watch therefore, for ye know neither the day nor the hour.” Nehemiah rebuilds the wall in 2:17–6:15, serves as governor for twelve years (5:14), and feeds a hundred and fifty at his table (5:17).",
     ["Jesus told his disciples, “Watch therefore, for ye know neither the day nor the hour.” To watch is more than staying physically awake. A person who is awake works, notices what is happening around them, and responds. To be spiritually awake is to pray, to keep a clear mind, to serve one master, and to keep God's purposes in front of our own comfort.",
      "Nehemiah is a picture of that kind of wakefulness. He had a secure, respected job as the king's cupbearer, and he did it faithfully — so faithfully that he could say he had never been sad in the king's presence. Life was comfortable. Then a report came that Jerusalem's walls were broken down and its people were in great trouble and reproach.",
      "That news woke something in him. He wept, fasted and prayed for days, confessing the sins of his people and asking God for favour. When the king noticed his sad face, Nehemiah prayed silently and then asked boldly: “Send me unto Judah… that I may build it.” He put God's work ahead of his own position and ease.",
      "God honoured that. The walls he had grieved over were rebuilt, and the cupbearer became governor of Judah for twelve years, with a hundred and fifty people eating at his table. “He is thy life, and the length of thy days” (Deuteronomy 30:20). God lifts up and gives meaning to the lives of those who stay awake to him."],
     ["Nehemiah had a good job serving the king, far away from Jerusalem.",
      "When he heard that Jerusalem's walls were broken, he cried, prayed and asked the king to let him go and help.",
      "God helped Nehemiah rebuild the walls, and he became the leader of his people."]),

    ("17. Ezekiel", "Ezekiel 3:16-27",
     "God making Ezekiel “a watchman unto the house of Israel”; the responsibility to warn both the wicked and the righteous; Ezekiel's tongue held silent; and God's rule, “when I speak with thee, I will open thy mouth.”",
     "This week's verse is Matthew 25:29 — “unto every one that hath shall be given.” Ezekiel was among the captives by the river Chebar (1:1). His hard signs are in 4:4–6 (390 and 40 days), 5:1–3 (shaving his head and beard) and 24:15–18 (the death of his wife); 14:22–23 shows the comfort that followed.",
     ["Jesus ended the parable of the talents with a surprising line: “Unto every one that hath shall be given, and he shall have abundance: but from him that hath not shall be taken away even that which he hath.” The one who “has” isn't the person with the most money or talent. It's the servant who was faithful and responsible with what he was given — “thou hast been faithful over a few things.” The one who “has not” is the servant who said, in effect, “What do I have? I can't do anything,” and hid it.",
      "Ezekiel shows what faithfulness looks like when circumstances are hard. He wasn't serving in comfort; he was a captive in Babylon. There God made him a watchman over Israel, with one rule: speak only what I tell you. And the assignments were heavy. He lay on one side for 390 days and on the other for 40, bearing a picture of his people's sin. He shaved his head and beard — a sign of shame in that culture — to show what was coming on Jerusalem.",
      "The hardest came in chapter 24. God told him that “the desire of thine eyes” — his wife — would be taken, and that he was not to mourn openly, as a sign to the people. That evening she died, and Ezekiel writes, “I did in the morning as I was commanded.” He didn't complain, didn't try to escape, and didn't demand to know why.",
      "In the end the people were comforted, and they understood that God had not done “without cause” all that he did (Ezekiel 14:22–23). Faithfulness in hard seasons isn't wasted. To the faithful servant Jesus says, “Enter thou into the joy of thy lord” — and God promises a covenant of peace and his presence among his people for ever (Ezekiel 37:26)."],
     ["God made Ezekiel a watchman, to tell the people God's message.",
      "Ezekiel had to do some very hard things, even when he was sad, but he always obeyed God.",
      "Because Ezekiel was faithful, the people were comforted and learned that God is always fair."]),

    ("18. Mordecai", "Esther 3:1-15",
     "Haman promoted above all the princes; Mordecai refusing to bow; Haman's anger turning against all the Jews; the lot cast and the decree sent to every province; and the city of Shushan left “perplexed.”",
     "This week's verses are Galatians 5:14–16 — love your neighbour as yourself, and “walk in the Spirit.” Mordecai's grief and his message to Esther follow in 4:1–8; Esther's call to fast is in 4:16, and Mordecai does “according to all that Esther had commanded him” (4:17).",
     ["“Thou shalt love thy neighbour as thyself.” We know how we want to be treated: we want people to tell us the truth, to be fair with us, not to plot harm against us, not to deceive us, and to live at peace with us. Loving others means giving them the same — speaking truth, judging fairly, refusing to imagine evil against them in our hearts (Zechariah 8:16–17), and making peace.",
      "Paul warns what happens otherwise: “If ye bite and devour one another, take heed that ye be not consumed one of another.” A life without love ends in destruction. The way out is to “walk in the Spirit” — to listen to the Holy Spirit and follow where he leads, rather than our own desires. His fruit is “in all goodness and righteousness and truth,” and he usually speaks to us through Scripture and through words that agree with it (John 6:63). Sometimes his leading will look different from what seems right to us, and then we have to give way to it.",
      "Mordecai's story shows the turn. He refused to bow to Haman, the king's favourite, and Scripture doesn't tell us whether he sought God's guidance first. What followed was a decree to destroy all the Jews. Mordecai tore his clothes, put on sackcloth and ashes, and cried out loudly — he saw the destruction that had begun.",
      "Then he urged Esther to go to the king. Esther answered with a call to seek God first: “Go, gather together all the Jews… and fast ye for me.” Mordecai listened and did all that she asked. The destruction was stopped, the Jews were saved, and God's plan went forward. When we let go of the lust of the eyes, the lust of the flesh and the pride of life (1 John 2:16) and make room for the Spirit's leading, we are kept from destruction and receive God's blessing."],
     ["Mordecai would not bow to proud Haman, and Haman became very angry with all the Jews.",
      "Mordecai was very sad, and Queen Esther asked everyone to pray and fast first.",
      "Mordecai listened, they turned to God together, and God saved His people."]),

    ("19. Noah", "Genesis 6:1-22",
     "the sons of God drawn by beauty and the mighty “men of renown”; the wickedness of every imagination of the heart; “But Noah found grace in the eyes of the Lord”; “Noah walked with God”; and Noah doing all that God commanded.",
     "This week's verse is John 6:35 — “I am the bread of life: he that cometh to me shall never hunger.” Noah's family is kept safe through the flood (chapters 7–8); God blesses them in 9:1, and Noah lives three hundred and fifty years after the flood (9:28). See also Revelation 22:17 and Ephesians 5:14.",
     ["“I am the bread of life: he that cometh to me shall never hunger; and he that believeth on me shall never thirst.” Jesus isn't talking about the body's hunger and thirst. He means the inner craving for the things of this world — its attractions, and the satisfaction we keep looking for in them. The one who receives Jesus stops searching the world for what only he can give.",
      "Think of a full stomach. Your favourite food can be right in front of you, but if you have already eaten well, you don't want it. In the same way, when our minds and hearts are full of Jesus and God's word, the world's attractions lose their pull. That is why Jesus invites, “Come unto me” — and Revelation 22:17 says, “let him that is athirst come. And whosoever will, let him take the water of life freely.”",
      "Noah lived surrounded by a world that had turned from God. People were drawn by beauty, proud of their strength and reputation, and followed their own desires; “every imagination of the thoughts of his heart was only evil continually.” While everyone else looked at the world, Noah looked to God. While others followed the flesh, Noah obeyed God's word. Scripture sums him up in four words: “Noah walked with God.”",
      "God kept Noah and his family safe through the destruction, blessed them, and gave Noah three hundred and fifty more years of life. So ask yourself: what am I full of — God's word, or the world's desires? “Awake thou that sleepest… and Christ shall give thee light” (Ephesians 5:14)."],
     ["Everyone around Noah had stopped loving God, but Noah kept walking with God.",
      "God told Noah to build a big ark, and Noah obeyed everything God said.",
      "God kept Noah's family safe in the flood and blessed them with a long life."]),

    ("20. The Shunammite Woman", "2 Kings 4:8-37",
     "the woman who made a small room for Elisha; the promised son; the boy's sudden death in the field; her words “It shall be well”; her ride to Mount Carmel without stopping; her refusal to leave Elisha — “I will not leave thee”; and the child sneezing seven times and opening his eyes.",
     "This week's verse is Luke 19:10 — “the Son of man is come to seek and to save that which was lost.” Deuteronomy 4:25–31 explains who must seek the Lord, and how: “if thou seek him with all thy heart and with all thy soul.”",
     ["Jesus came “to seek and to save that which was lost.” In Scripture we see two kinds of people: some the Lord goes out to find, and some who must go and seek the Lord. Moses warned Israel that people who corrupted themselves, provoked God and drifted far from him through sin would have to turn back and seek him.",
      "And seeking God is not a casual effort. “If from thence thou shalt seek the Lord thy God, thou shalt find him, if thou seek him with all thy heart and with all thy soul.” Those who seek him that way find that he will not forsake them, will not destroy them, and will not forget his covenant.",
      "The Shunammite woman shows what that kind of seeking looks like. When her only son died in her arms, she laid him on the prophet's bed and set out at once for Elisha. She told her servant to drive hard and not slow down. She didn't stop to explain her grief to everyone she met; to her husband and to Gehazi she simply said, “It is well.” Her one aim was to reach the man of God.",
      "When Elisha tried to send his servant ahead with his staff, she refused: “As the Lord liveth… I will not leave thee.” She wouldn't accept a substitute. The staff did nothing; Elisha himself came, prayed, and the boy came back to life. Seek God first, don't take your problem to everyone else, don't look for other answers in his place — and hold on to him with all your heart and soul."],
     ["A kind woman's son became very sick and died.",
      "She didn't give up; she went straight to God's prophet Elisha and would not leave without him.",
      "Elisha came and prayed, and God brought her son back to life."]),

    ("21. Samuel", "1 Samuel 3:1-21",
     "the word of the Lord being rare in those days; the boy Samuel hearing his name in the night; Eli's advice, “Speak, Lord; for thy servant heareth”; the hard message for Eli's house; and God letting none of Samuel's words fall to the ground.",
     "This week's verses are John 5:14 and John 8:12 — “he that followeth me shall not walk in darkness, but shall have the light of life.” After the ark is lost (chapter 4), Samuel goes largely unsought for about twenty years (7:2) until the people come asking him to pray (7:8; 9:11). Isaiah 65:1 and 9:2–5 describe what God does for such people.",
     ["Jesus told the man he had healed, “Sin no more, lest a worse thing come unto thee,” and he promised, “He that followeth me shall not walk in darkness, but shall have the light of life.” That light of life is God's reward for those who follow him and trust him alone. Whatever their situation, Isaiah 9 says God multiplies them, increases their joy, and breaks the yoke of war.",
      "Samuel is a picture of that. As a boy he heard God call his name, and answered, “Speak; for thy servant heareth.” God was with him and let none of his words fall to the ground, and all Israel knew he was a prophet of the Lord. But when Israel faced the Philistines, they put their trust in carrying the ark into battle, and there is no record that they sought Samuel's counsel. The battle was lost, the ark was taken, Eli and his sons died, and “the glory is departed from Israel.”",
      "For about twenty years afterwards Samuel was largely overlooked. Yet God had a promise for people like him: “I am sought of them that asked not for me; I am found of them that sought me not” (Isaiah 65:1). In time the whole nation came looking for him. They asked him, “Cease not to cry unto the Lord our God for us,” and even strangers searching for lost donkeys asked, “Is the seer here?”",
      "Through Samuel's prayer and counsel God turned the tide: the cities the Philistines had taken were restored, and there was peace. The one who had been forgotten was honoured, sought after, filled with joy and given peaceful days. When we keep following God in the hidden years, he brings us into the light in his time."],
     ["Samuel was a boy who listened to God and said, “Speak, Lord, I am listening.”",
      "For many years people forgot about him, but Samuel kept following God.",
      "Later the whole nation came to Samuel for help, and God gave them peace through his prayers."]),

    ("22. Joseph", "Genesis 39:1-23",
     "Joseph sold to Potiphar; the Lord making all he did prosper; everything in the house placed in his hand; the daily pressure from Potiphar's wife; his answer, “how then can I do this great wickedness, and sin against God?”; his flight; and the Lord being with him even in prison.",
     "This week's verse is Psalm 147:3 — “He healeth the broken in heart, and bindeth up their wounds.” Joseph's early years are in Genesis 37:2–11; Isaiah 57:15 and 1 Corinthians 6:17–20 describe the God who lives with the contrite and the call to flee impurity.",
     ["“He healeth the broken in heart, and bindeth up their wounds.” Some wounds in life — disappointment, rejection, betrayal, loneliness — people cannot heal. Only the Spirit of the Lord can heal them completely. He does it by dwelling in us: God says he lives “with him also that is of a contrite and humble spirit, to revive the spirit of the humble, and to revive the heart of the contrite ones” (Isaiah 57:15). When he dwells in us, the broken heart comes alive, wounds begin to close, and his peace fills our life.",
      "For the Spirit to dwell in us, we are to be joined to the Lord: “he that is joined unto the Lord is one spirit” (1 Corinthians 6:17). That means living by his will, choosing what pleases him and keeping our lives holy — fleeing impurity rather than wrestling with it, and glorifying God “in your body, and in your spirit.” And keeping that up takes a firm decision that doesn't change when circumstances or people change.",
      "Joseph made that decision young. At seventeen, while his brothers did wrong, he didn't join them. When he shared the dreams God gave him, his father rebuked him and his brothers hated him, but he didn't deny what God had shown him. Later, in Potiphar's house, he had authority, trust and freedom — “there is none greater in this house than I” — and no one watching. When Potiphar's wife pressed him day after day, he said, “How then can I do this great wickedness, and sin against God?” and ran. It wasn't fear of his master; it was the fear of God.",
      "Because Joseph stayed joined to the Lord, God was with him through betrayal, slavery and prison, healed his broken heart, turned it all to blessing, and in the end made him a great leader. A life joined to the Lord is the life in which God heals a broken heart and lifts us up."],
     ["Joseph's brothers were jealous and sold him far away, and his heart was hurt.",
      "Even when no one was watching, Joseph chose to obey God and ran away from doing wrong.",
      "God was with Joseph, healed his heart, and made him a great leader in Egypt."]),

    ("23. Deborah", "Judges 4:1-16",
     "Deborah judging Israel under the palm tree; God's command to Barak and the promise to deliver Sisera into his hand; Barak's condition, “If thou wilt go with me, then I will go”; Deborah's answer that the honour would go to a woman; and her call, “Up; for this is the day.”",
     "This week's verse is Mark 9:23 — “If thou canst believe, all things are possible to him that believeth.” Before Deborah, God used ordinary people: Ehud (Judges 3:15–30) and Shamgar with an ox goad (3:31). After Deborah's victory, “the land had rest forty years” (5:31).",
     ["Jesus said these words to a father whose son had suffered “of a child” — since childhood. He had brought the boy to the disciples, and “they could not.” People who had succeeded at many things had tried and failed. So the father's question was natural: can this really change? And Jesus answered, “If thou canst believe, all things are possible to him that believeth.” Don't decide that God can't, just because people couldn't. The father cried out, “Lord, I believe; help thou mine unbelief.”",
      "In the time of the judges, God kept using ordinary people to do extraordinary things. Ehud was left-handed — something people saw as a weakness — yet he went alone into the private room of Eglon, the king who had oppressed Israel for eighteen years, and came out again past the guards. The land had rest for eighty years. Shamgar had no great weapon, only an ox goad, and with it he struck down six hundred Philistines.",
      "Then God told Barak to go out against Sisera, promising to deliver him into his hand. Barak came from a people who “jeoparded their lives unto the death,” yet he couldn't believe the word God had given him. “If thou wilt go with me, then I will go: but if thou wilt not go with me, then I will not go.” Where Barak couldn't believe, Deborah did. She looked not at her own strength but at God's word: “Up; for this is the day in which the Lord hath delivered Sisera into thine hand.”",
      "God brought the victory, and Israel had rest for forty years. Faith isn't telling ourselves that the impossible is possible. It's looking straight at what seems impossible and saying, “My God can.” What others can't believe, you can — and God works through those who do."],
     ["God told Barak to fight Israel's enemy, but Barak was afraid to go alone.",
      "Deborah believed what God had said and bravely went with him.",
      "God gave Israel the victory, and the land had peace for forty years."]),

    ("24. Jehoshaphat", "2 Chronicles 20:1-22",
     "a great army coming against Judah; Jehoshaphat proclaiming a fast and praying before all the people; his confession, “we have no might against this great company… but our eyes are upon thee”; the answer, “the battle is not yours, but God's”; and the singers going out ahead of the army.",
     "This week's verses are John 11:25 and 11:42 — “I knew that thou hearest me always.” God had already made the kingdoms around Judah afraid to fight Jehoshaphat (17:10), and he answered Jehoshaphat's cry in battle (18:31). The moral verse is 19:7: “there is no iniquity with the Lord our God, nor respect of persons, nor taking of gifts.”",
     ["“I am the resurrection, and the life: he that believeth in me, though he were dead, yet shall he live.” This doesn't mean believers never die in this world — they do. The deeper truth is that God is able to hear and act at any moment, in any situation. At Lazarus's tomb Jesus prayed, “I knew that thou hearest me always.”",
      "Jehoshaphat's life shows God hearing him in very different moments. First, God acted before he even asked: “the fear of the Lord fell upon all the kingdoms… so that they made no war against Jehoshaphat.” He never went to those kings asking for peace; God gave him peaceful years. God knows what we need before we ask.",
      "Later, in a battle alongside Ahab, the enemy chariot commanders surrounded Jehoshaphat, thinking he was the king of Israel. There was no way out. He cried out, “and the Lord helped him; and God moved them to depart from him,” and he came home safely. However bad our situation, our cry reaches God's ear.",
      "Then a vast army came against Judah, and Jehoshaphat didn't trust his own strength. He prayed, “We have no might against this great company… neither know we what to do: but our eyes are upon thee.” God answered, “The battle is not yours, but God's.” They went out singing, and God fought for them. There is no moment when God cannot hear — so in every situation, let us call on him."],
     ["When a huge army came against King Jehoshaphat, he was afraid and didn't know what to do.",
      "He gathered everyone to pray and said, “God, our eyes are on You.”",
      "God said, “The battle is Mine,” and He won the battle for them while they sang."]),
]


def _id():
    return "".join(random.choices(string.ascii_letters + string.digits, k=10))


def _content(blocks):
    return json.dumps({"time": int(time.time() * 1000),
                       "blocks": [{"id": _id(), **b} for b in blocks], "version": "2.31.0"})


def _h(text, level=2):
    return {"type": "header", "data": {"text": text, "level": level}}


def _p(text):
    return {"type": "paragraph", "data": {"text": text}}


def lessons_for(passage, watch, note, short, brief):
    return [
        (f"Read: {passage}", [
            _h(f"\U0001F4D6 Read: {passage}"),
            _p(f"Before this lesson, take a few minutes to read {passage} in your own Bible (tap the reference "
               f"above to preview it instantly). As you read, watch for: {watch}"),
            _h("Background", 3), _p(note)]),
        ("Short Lesson (Adults)", [_h("Short Lesson")] + [_p(t) for t in short]),
        ("Brief Lesson (All Ages)", [_h("Brief Lesson")] + [_p(t) for t in brief]),
    ]


def main(apply):
    import frappe
    frappe.init(site=SITE, sites_path=".")
    frappe.connect()
    frappe.set_user("Administrator")
    order = {r.chapter: r.idx for r in frappe.get_all(
        "Chapter Reference", filters={"parent": COURSE}, fields=["chapter", "idx"])}
    for title, passage, watch, note, short, brief in LESSONS:
        name = frappe.db.get_value("Course Chapter", {"course": COURSE, "title": title})
        if not name or order.get(name, 99) > LAST_CHAPTER:
            print(f"SKIP {title}: chapter not found in 1-{LAST_CHAPTER}")
            continue
        chapter = frappe.get_doc("Course Chapter", name)
        existing = [r.lesson for r in chapter.lessons]
        if any(frappe.db.get_value("Course Lesson", l, "title") == "Short Lesson (Adults)" for l in existing):
            print(f"SKIP {title}: already has the three lessons")
            continue
        planned = lessons_for(passage, watch, note, short, brief)
        print(f"{'ADD ' if apply else 'WOULD ADD'} {title}: {[t for t, _ in planned]} before {len(existing)} existing")
        if not apply:
            continue
        new = [frappe.get_doc({"doctype": "Course Lesson", "title": t, "chapter": name, "course": COURSE,
                               "content": _content(b), "include_in_preview": 0}).insert(ignore_permissions=True).name
               for t, b in planned]
        # Keep the existing link rows themselves (only their position changes) and put the new ones first.
        chapter.reload()
        old_rows = [r for r in chapter.lessons if r.lesson not in new]
        chapter.lessons = []
        for lesson in new:
            chapter.append("lessons", {"lesson": lesson})
        chapter.lessons.extend(old_rows)
        for i, row in enumerate(chapter.lessons, 1):
            row.idx = i
        chapter.save(ignore_permissions=True)
        frappe.db.commit()
    frappe.destroy()


if __name__ == "__main__":
    main("--apply" in sys.argv)
