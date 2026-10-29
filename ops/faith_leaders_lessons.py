"""Faith Leaders (chapters 1-15): add the three lessons every Life of Jesus chapter has -
"Read: <passage>", "Short Lesson (Adults)" and "Brief Lesson (All Ages)" - in the same Editor.js shape.

The new lessons go first in each chapter; the chapter's existing lessons (videos, Tamil stories, memory
verses, questions) stay after them. Chapters 16-24 are never touched. Safe to re-run: a chapter that
already has a "Short Lesson (Adults)" is skipped.

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
LAST_CHAPTER = 15

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
        chapter.reload()
        present = [r.lesson for r in chapter.lessons]
        keep = [l for l in existing if l in present] + [l for l in present if l not in new and l not in existing]
        chapter.set("lessons", [])
        for lesson in new + keep:
            chapter.append("lessons", {"lesson": lesson})
        chapter.save(ignore_permissions=True)
        frappe.db.commit()
    frappe.destroy()


if __name__ == "__main__":
    main("--apply" in sys.argv)
