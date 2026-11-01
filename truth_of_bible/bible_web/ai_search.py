"""Search by meaning: "verse about not worrying", "kavalai padathe", "when did Jesus weep?".

The AI only names references (and why each fits); every verse's text comes from our own database, in the
reader's version, so it can't misquote Scripture, and references that don't exist are dropped. Answers
are keyed on the search alone, so one AI call serves every version and every later visitor."""

import json
import re

from truth_of_bible.bible_web import queries as Q

PROMPT = """You find Bible verses for a search typed on a Bible website.
The search may be English, Tamil, Tanglish (Tamil typed in English letters, e.g. "kavalai padathe"),
Hindi or another language, and may be a topic, a feeling, a situation, a question, or a half-remembered
verse.

Reply with JSON only, in exactly this shape:
{"topic": "<3 to 6 word English title>", "verses": [{"ref": "<reference>", "why": "<why it fits>"}]}

- 6 to 8 verses, the most relevant and best-known first.
- "ref": English book name, chapter:verse or chapter:verse-verse, from the 66-book Protestant Bible,
  e.g. "Philippians 4:6-7". Only references you are certain exist.
- "why": under 15 words, in the language of the search (Tamil script for Tamil or Tanglish searches).
- If the search isn't about the Bible, faith or life, or asks for anything harmful, reply
  {"topic": "", "verses": []}."""


def normalize(q: str) -> str:
	"""The cache key: case, spacing and punctuation don't change what's being asked."""
	return re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", (q or "").strip().lower()))[:120]


def ask(q: str, generate) -> dict:
	"""{"topic", "verses": [{"ref", "why"}]} for the search, from generate(system_prompt, user_text) -> str."""
	raw = generate(PROMPT, normalize(q))
	m = re.search(r"\{.*\}", raw or "", re.S)  # tolerate a code fence or a sentence around the JSON
	try:
		data = json.loads(m.group(0)) if m else {}
	except ValueError:
		data = {}
	verses = [v for v in data.get("verses") or [] if isinstance(v, dict) and isinstance(v.get("ref"), str)]
	return {"topic": str(data.get("topic") or "")[:80],
		"verses": [{"ref": v["ref"][:40], "why": str(v.get("why") or "")[:160]} for v in verses[:8]]}


def resolve(con, answer: dict, version: str) -> dict:
	"""The AI's references as verses in [version] (text from our database); unknown ones dropped."""
	names = {r[0]: r[1] for r in con.execute("SELECT book, name FROM book_names WHERE version=?", (version,))}
	out, seen = [], set()
	for v in answer["verses"]:
		refs = Q.parse_refs(con, v["ref"])
		if not refs or not refs[0]["verse"]:
			continue
		r = refs[0]
		r["end"] = min(r["end"], r["verse"] + 2) if r["end"] and r["end"] > r["verse"] else None
		span = {(r["book"], r["chapter"], n) for n in range(r["verse"], (r["end"] or r["verse"]) + 1)}
		if span & seen:  # John 11:33-35 after John 11:35: the same passage twice
			continue
		hit = Q._with_text(con, [r], version)[0]
		if not hit["text"]:  # no such verse (or not in this version)
			continue
		seen |= span
		out.append({**hit, "book_name": names.get(r["book"]), "why": v["why"]})
	return {"topic": answer["topic"], "version": version, "results": out}
