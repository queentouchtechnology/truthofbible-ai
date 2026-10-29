"""Writes catalogue.json — which Bible versions truthofbible.org may show, with their licences.

Licences were read from each module's own `translations` / `Details` / `info` table (2026-10-28).
web=False keeps a version app-only; flip it once a licence for web use is confirmed.

    python make_catalogue.py
"""
import json
from pathlib import Path

PD, CC0 = "Public Domain", "CC0"


def v(code, name, language, lang, license=PD, web=True, dir="ltr", note=None, attribution=None, ebible=None):
	d = {"code": code, "name": name, "language": language, "lang": lang, "dir": dir, "license": license, "web": web}
	if note:
		d["note"] = note
	if attribution:
		d["attribution"] = attribution
	if ebible:
		d["ebible"] = ebible  # not an app module: build.py fetches it from eBible.org (see ebible.py)
	return d


def irv(code, ebible, language, lang, dir="ltr", year="2019", by="Bridge Connectivity Solutions", script=""):
	"""Indian Revised Version (and like-licensed) Bibles from eBible.org, CC BY-SA 4.0."""
	title = "Indian Revised Version" if by.startswith("Bridge") else "Unlocked Literal Bible"
	return v(code, f"{title} — {language}{script} ({year})", language, lang, "CC BY-SA 4.0", dir=dir, ebible=ebible,
		attribution=f"{title} ({language}), {by}, CC BY-SA 4.0, via eBible.org. Inline cross-reference notes removed.")


VERSIONS = [
	v("KJV", "King James Version (1769)", "English", "en", "Public Domain (text); module GPL", note="Strong's numbers kept for word study"),
	v("KJVPCE", "King James Version — Pure Cambridge Edition", "English", "en"),
	v("KJVA", "King James Version with Apocrypha", "English", "en", "Public Domain (text); module GPL"),
	v("BSB", "Berean Standard Bible", "English", "en", CC0),
	v("ASV", "American Standard Version (1901)", "English", "en"),
	v("BBE", "Bible in Basic English", "English", "en"),
	v("NHEBJE", "New Heart English Bible (Jehovah Edition)", "English", "en"),
	v("NHEBME", "New Heart English Bible (Messianic Edition)", "English", "en"),
	v("OEB", "Open English Bible (US)", "English", "en", CC0),
	v("OEBcth", "Open English Bible (Commonwealth)", "English", "en", CC0),
	v("Darby", "Darby Bible (1889)", "English", "en"),
	v("YLT", "Young's Literal Translation (1898)", "English", "en"),
	v("Webster", "Webster Bible (1833)", "English", "en"),
	v("RWebster", "Revised Webster (1833)", "English", "en"),
	v("UKJV", "Updated King James Version", "English", "en"),
	v("Rotherham", "Rotherham Emphasized Bible", "English", "en"),
	v("Geneva1599", "Geneva Bible (1599)", "English", "en"),
	v("Tyndale", "Tyndale Bible (1525/1530)", "English", "en"),
	v("Wycliffe", "Wycliffe Bible (c.1395)", "English", "en", "CC BY-SA 4.0", attribution="Wycliffe Bible, CC BY-SA 4.0 (eBible.org)"),
	v("DRC", "Douay-Rheims, Challoner Revision", "English", "en"),
	v("Noyes", "Noyes Translation (1869)", "English", "en"),
	v("Twenty", "Twentieth Century New Testament", "English", "en"),
	v("Haweis", "Haweis New Testament (1795)", "English", "en"),
	v("Anderson", "Anderson New Testament (1864)", "English", "en"),
	v("tamil", "Tamil Bible (Union Version)", "Tamil", "ta", "Free for non-profit use",
	  attribution="Tamil Bible Unicode: Word of God Ministries (wordofgod.in)"),
	v("TAMIRV2019", "Indian Revised Version — Tamil (2019)", "Tamil", "ta", "CC BY-SA 4.0",
	  attribution="Indian Revised Version (IRV) Tamil, Bridge Connectivity Solutions, CC BY-SA 4.0"),
	v("Mal1910", "Sathyavedapusthakam (1910)", "Malayalam", "ml"),
	irv("MALIRV", "mal", "Malayalam", "ml"),
	irv("HINIRV", "hin2017", "Hindi", "hi"),
	irv("TELIRV", "tel2017", "Telugu", "te"),
	irv("KANIRV", "kanirv", "Kannada", "kn"),
	irv("BENIRV", "benirv", "Bengali", "bn"),
	irv("GUJIRV", "guj2017", "Gujarati", "gu"),
	irv("MARIRV", "mar", "Marathi", "mr"),
	irv("ORYIRV", "ory", "Odia", "or", year="2021"),
	irv("PANIRV", "pan", "Punjabi", "pa"),
	irv("ASMIRV", "asmfb", "Assamese", "as", year="2018"),
	irv("URDIRV", "urd", "Urdu", "ur", script=", Devanagari script"),  # eBible's Urdu IRV is printed in Devanagari
	irv("NPIULB", "npiulb", "Nepali", "ne", by="Door43 World Missions Community"),
	v("SpaRV", "Reina-Valera (1909)", "Spanish", "es"),
	v("SpaRV1865", "Reina-Valera (1865)", "Spanish", "es"),
	v("PorBLivre", "Bíblia Livre", "Portuguese", "pt", "CC BY 3.0", attribution="Bíblia Livre, CC BY 3.0"),
	v("FreCrampon", "Bible Crampon (1923)", "French", "fr"),
	v("FreJND", "Bible Darby (French)", "French", "fr"),
	v("FreSynodale1921", "Version Synodale (1921) — NT & Psaumes", "French", "fr"),
	v("GerElb1905", "Elberfelder (1905)", "German", "de"),
	v("GerMenge", "Menge-Bibel (1939)", "German", "de"),
	v("GerTextbibel", "Textbibel (1906)", "German", "de"),
	v("GerBoLut", "Luther 1545 (modern spelling)", "German", "de"),
	v("DutSVV", "Statenvertaling", "Dutch", "nl"),
	v("Swe1917", "Bibeln (1917)", "Swedish", "sv"),
	v("FinPR", "Pyhä Raamattu (1933/1938)", "Finnish", "fi"),
	v("CzeBKR", "Bible kralická", "Czech", "cs"),
	v("PolGdanska", "Biblia Gdańska (1881)", "Polish", "pl"),
	v("HunKar", "Károli Biblia (1908)", "Hungarian", "hu"),
	v("RusSynodal", "Синодальный перевод", "Russian", "ru"),
	v("UkrOgienko", "Біблія — переклад Огієнка", "Ukrainian", "uk"),
	v("Esperanto", "Londona Biblio", "Esperanto", "eo"),
	v("TagAngBiblia", "Ang Biblia (1905)", "Tagalog", "tl"),
	v("Viet", "Kinh Thánh (1934)", "Vietnamese", "vi"),
	v("ChiUn", "和合本 (繁體)", "Chinese", "zh-Hant"),
	v("ChiUnL", "文理和合", "Chinese", "zh-Hant"),
	v("JapKougo", "口語訳 (1955)", "Japanese", "ja"),
	v("KorRV", "개역성경", "Korean", "ko"),
	v("Vulgate", "Biblia Sacra Vulgata", "Latin", "la"),
	v("VulgClementine", "Vulgata Clementina", "Latin", "la"),
	v("WLC", "Westminster Leningrad Codex (Hebrew OT)", "Hebrew", "he", dir="rtl"),
	# App-only: the licence does not allow free web use, or is unknown.
	v("AKJV", "American King James Version", "English", "en", "Free non-commercial", web=False),
	v("NHEB", "New Heart English Bible", "English", "en", "Unknown (module)", web=False),
	v("Jubilee2000", "Jubilee Bible 2000", "English", "en", "Free non-commercial", web=False),
	v("GerSch", "Schlachter (1951)", "German", "de", "Free non-commercial", web=False),
	v("SpaRVG", "Reina Valera Gómez", "Spanish", "es", "CC BY-NC-ND 4.0", web=False),
	v("Byz", "Byzantine Textform (2013)", "Greek", "grc", "CC BY-NC-SA 4.0", web=False),
	v("TR", "Textus Receptus", "Greek", "grc", "CC BY-NC-SA 4.0", web=False),
	v("ERVTA", "Easy-to-Read Version — Tamil", "Tamil", "ta", "Copyrighted", web=False),
	v("taBCS", "Tamil Bible (Biblica)", "Tamil", "ta", "Copyrighted", web=False),
] + [
	# The app's Indian modules (checked 2026-10-29): Bengali, Gujarati, Marathi, Odia, Punjabi and Nepali are
	# the Easy-to-Read Version (copyrighted); Malayalam is the 1910 text (Mal1910 above); Hindi, Telugu and
	# Kannada are the Bible Society old versions. The IRV above covers these languages on the web.
	v(code, name, language, lang, "Unknown — confirm before web use", web=False)
	for code, name, language, lang in (
		("hindi", "Hindi Bible", "Hindi", "hi"),
		("telugu", "Telugu Bible", "Telugu", "te"),
		("malayalam", "Malayalam Bible", "Malayalam", "ml"),
		("kannada", "Kannada Bible", "Kannada", "kn"),
		("bengali", "Bengali Bible", "Bengali", "bn"),
		("gujarati", "Gujarati Bible", "Gujarati", "gu"),
		("marathi", "Marathi Bible", "Marathi", "mr"),
		("oriya", "Odia Bible", "Odia", "or"),
		("punjabi", "Punjabi Bible", "Punjabi", "pa"),
		("nepali", "Nepali Bible", "Nepali", "ne"),
	)
]

if __name__ == "__main__":
	out = Path(__file__).with_name("catalogue.json")
	out.write_text(json.dumps({"versions": VERSIONS}, ensure_ascii=False, indent=1), encoding="utf-8")
	print(f"{len(VERSIONS)} versions, {sum(x['web'] for x in VERSIONS)} on the web -> {out.name}")
