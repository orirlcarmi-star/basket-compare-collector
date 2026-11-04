"""A search index in small files, split by the first two letters of each word (tasks B3, B2).

The website cannot download every product name to search them, so the names are indexed:

  s/<file>.json   {"p": [[barcode, name, category?], ...], "w": {word: [position, ...], ...}}

`w` holds the words that begin with the same two letters; each word lists the positions, in `p`,
of the products that contain it. `p` holds those products: barcode, the short name the
shopper sees, and the category id (left out when the product has none). So one request per
word of the query is enough to show results: no product files are read until the shopper adds
something to the basket. (A product with several words is in several files; the name is
repeated, which is what makes the index about four times bigger than one with barcodes only.)

Facts for the narrowing buttons. A record may carry a fourth place: an object with the facts the
website needs to ask "which fat percent? which size?" without reading the product file —
  "f"  fat percent, as written in the product file ("3")
  "z"  what the package holds, [amount, "l" | "kg" | "unit"] (price / amount = unit price)
  "w"  true when the product is sold by weight (its price is per kilo)
Each is left out when it is not known, and the whole object is left out when none is: a record is
then exactly `[barcode, name, category?]` as before. Nothing in the first three places moves or
changes meaning, so a reader that knows only those keeps working; when a product has facts but
no category, the category place holds "" (the empty string: "no category") so that the facts
can stay in the fourth place. The values are the ones the product file holds (`a.f`, `z`, `w`),
the same names and shapes, computed by `collector.attributes` and `collector.unitprice`.

The file name is the two letters as four hex digits of each ("חל" -> "05d705dc"), so any letter
is safe in a URL. Words and queries are written in the normal form of `collector.textnorm`
(no vowel points or apostrophes, plain final letters, abbreviations such as "גב." spelled out).

To search: normalise the query into words; for each word read the file of its first two letters
and take the products of every word that STARTS with it (typing "גבינ" finds גבינה, גבינות);
keep the products found for all the query words (they are in every one of those files, so the
first file already holds what is needed to show them). `search` below does exactly that and is
the reference for the website. A query word of one letter cannot be searched.

Prefix letters. Names are written "בקרטון", "וחלב", "לתינוק", "מהדרין". Each such word is also
indexed without its first letter, so searching "קרטון", "חלב", "תינוק" finds them. This is
done only when it is safe, and always in addition to the word itself, never instead of it:
the first letter must be one of ו ב ל כ ש ה מ, what is left must be at least three letters,
and it must be a word the catalog really uses on its own ("בקר" is beef and is not "קר", cold;
"בננה" is not "ננה"; "כלב" is not "לב"). Words chains write only with a prefix, such as
"מהדרין", are listed in EXTRA_STEMS.
"""

import json
from collections.abc import Mapping
from pathlib import Path

from collector.textnorm import words

PREFIX = 2
PREFIX_LETTERS = "ובלכשהמ"
MIN_STEM = 3
# Stems that chains write with a prefix letter and rarely without one.
EXTRA_STEMS = {"הדרינ"}  # מהדרין, normal form (final letter plain)


def file_name(word: str) -> str:
    """ "חל..." -> "05d705dc.json" """
    return "".join(f"{ord(c):04x}" for c in word[:PREFIX]) + ".json"


def stems(word: str, vocabulary: set[str]) -> list[str]:
    """The word without its prefix letter, when that is safe (see the module text)."""
    if word[0] not in PREFIX_LETTERS:
        return []
    rest = word[1:]
    if len(rest) >= MIN_STEM and (rest in vocabulary or rest in EXTRA_STEMS):
        return [rest]
    return []


def search_facts(product: Mapping) -> dict:
    """The facts of a product that go into its search record (see the module text): the fat
    percent from `a.f`, the package contents `z`, and `w` when sold by weight. Left out when
    missing."""
    facts: dict = {}
    fat = (product.get("a") or {}).get("f")
    if fat:
        facts["f"] = fat
    if product.get("z"):
        facts["z"] = list(product["z"])
    if product.get("w"):
        facts["w"] = True
    return facts


def record(code: str, entry: tuple) -> list:
    """[barcode, name, category?, facts?] — the category place holds "" when only facts follow."""
    name, category, *rest = entry
    facts = rest[0] if rest else {}
    made: list = [code, name]
    if category or facts:
        made.append(category or "")
    if facts:
        made.append(dict(facts))
    return made


def build_index(products: Mapping[str, tuple]) -> dict[str, dict]:
    """barcode -> (name, category id or None[, facts])  ->  {file name: {"p": [...], "w": {...}}}.

    `facts` is optional (see `search_facts`); without it a record is [barcode, name, category?]."""
    searchable = {code: words(entry[0]) for code, entry in products.items()}
    vocabulary = {w for ws in searchable.values() for w in ws}
    postings: dict[str, set[str]] = {}
    for code, ws in searchable.items():
        for word in ws:
            for form in [word, *stems(word, vocabulary)]:
                postings.setdefault(form, set()).add(code)

    files: dict[str, dict] = {}
    positions: dict[str, dict[str, int]] = {}  # file -> barcode -> place in "p"
    for word in sorted(postings):
        name = file_name(word)
        content = files.setdefault(name, {"p": [], "w": {}})
        place = positions.setdefault(name, {})
        entry = []
        for code in sorted(postings[word]):
            if code not in place:
                place[code] = len(content["p"])
                content["p"].append(record(code, products[code]))
            entry.append(place[code])
        content["w"][word] = entry
    return files


def write_index(index: Mapping[str, Mapping], folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in index.items():
        path = folder / name
        path.write_text(json.dumps(content, ensure_ascii=False, separators=(",", ":")), "utf-8")
        written.append(path)
    return written


def search(folder: Path, query: str) -> dict[str, tuple[str, str | None]] | None:
    """barcode -> (name, category id or None) of the products having every word of the query
    (None: nothing to search for). The facts of the fourth place are not part of this answer;
    `facts_of` reads them from a record."""
    found: dict[str, tuple[str, str | None]] | None = None
    for word in words(query):
        path = folder / file_name(word)
        content = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"p": [], "w": {}}
        )
        matches = {
            content["p"][i][0]: (
                content["p"][i][1],
                (content["p"][i][2] if len(content["p"][i]) > 2 else None) or None,
            )
            for w, places in content["w"].items()
            if w.startswith(word)
            for i in places
        }
        found = matches if found is None else {c: v for c, v in found.items() if c in matches}
    return found


def facts_of(entry: list) -> dict:
    """The facts of a search record (empty when it has none)."""
    return entry[3] if len(entry) > 3 else {}
