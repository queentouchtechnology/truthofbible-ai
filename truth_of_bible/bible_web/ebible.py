"""Turns an eBible.org translation into the app's module format (<code>.db with <code>_books and
<code>_verses), so build.py reads it like every other version.

Text comes from eBible's verse-per-line file, book names from the USFM headers (\\h). The Indian
Revised Version prints cross references inline — "(इब्रा. 1:10, इब्रा. 11:3)" — which are removed,
as in the Tamil IRV the app already has; the version's attribution says so (CC BY-SA asks for it).

    python ebible.py DIR hin2017:HINIRV tel2017:TELIRV ...
"""

import io
import re
import sqlite3
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

USFM = [
	"GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA", "1KI", "2KI", "1CH", "2CH", "EZR", "NEH",
	"EST", "JOB", "PSA", "PRO", "ECC", "SNG", "ISA", "JER", "LAM", "EZK", "DAN", "HOS", "JOL", "AMO", "OBA", "JON",
	"MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL", "MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL",
	"EPH", "PHP", "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM", "HEB", "JAS", "1PE", "2PE", "1JN", "2JN", "3JN",
	"JUD", "REV",
]
BASE = "https://ebible.org/Scriptures/"
# a parenthesis holding a reference: (इब्रा. 1:10, इब्रा. 11:3), (मत्ती 5:3)
_XREF = re.compile(r"\s*\([^()]*\d+\s*[:.]\s*\d+[^()]*\)")
_VERSE = re.compile(r'<v b="(\w+)" c="(\d+)" v="(\d+)[^"]*">(.*?)</v>', re.S)


def _get(url: str) -> bytes:
	for attempt in range(5):
		try:
			req = urllib.request.Request(url, headers={"User-Agent": "truthofbible.org Bible builder (+https://truthofbible.org)"})
			return urllib.request.urlopen(req, timeout=300).read()
		except Exception as e:
			print(f"  retry {attempt + 1}: {e}")
			time.sleep(5 * (attempt + 1))
	raise RuntimeError(f"could not download {url}")


def book_names(eid: str) -> dict[int, str]:
	z = zipfile.ZipFile(io.BytesIO(_get(f"{BASE}{eid}_usfm.zip")))
	names = {}
	for n in z.namelist():
		if not n.lower().endswith((".usfm", ".sfm")):
			continue
		text = z.read(n).decode("utf-8-sig", "replace")
		code = re.search(r"\\id\s+(\w+)", text)
		if not code or code.group(1).upper() not in USFM:
			continue
		name = re.search(r"\\h\s+(.+)", text) or re.search(r"\\toc2\s+(.+)", text) or re.search(r"\\toc1\s+(.+)", text)
		if name:
			names[USFM.index(code.group(1).upper()) + 1] = name.group(1).strip()
	return names


def convert(eid: str, code: str, folder: Path) -> Path:
	"""Download eBible translation `eid` and write <folder>/<code>.db."""
	folder.mkdir(parents=True, exist_ok=True)
	print(f"ebible {eid} -> {code}")
	z = zipfile.ZipFile(io.BytesIO(_get(f"{BASE}{eid}_vpl.zip")))
	xml = z.read(next(n for n in z.namelist() if n.endswith("_vpl.xml"))).decode("utf-8-sig")
	names = book_names(eid)
	rows = []
	for b, c, v, text in _VERSE.findall(xml):
		if b not in USFM:
			continue  # deuterocanon / extra material
		text = re.sub(r"\s+", " ", _XREF.sub("", re.sub(r"<[^>]+>", "", text))).strip()
		if text:
			rows.append((USFM.index(b) + 1, int(c), int(v), text))
	tmp = folder / f"{code}.db.part"
	tmp.unlink(missing_ok=True)
	db = sqlite3.connect(tmp)
	db.executescript(f"""
		CREATE TABLE {code}_books(id INTEGER PRIMARY KEY, name TEXT);
		CREATE TABLE {code}_verses(id INTEGER PRIMARY KEY, book_id INT, chapter INT, verse INT, text TEXT);
	""")
	db.executemany(f"INSERT INTO {code}_books VALUES (?,?)", sorted(names.items()))
	db.executemany(f"INSERT INTO {code}_verses(book_id, chapter, verse, text) VALUES (?,?,?,?)", rows)
	db.commit()
	db.close()
	out = folder / f"{code}.db"
	tmp.replace(out)
	print(f"  {len(rows)} verses, {len(names)} book names")
	return out


if __name__ == "__main__":
	folder = Path(sys.argv[1])
	for pair in sys.argv[2:]:
		eid, code = pair.split(":")
		convert(eid, code, folder)
