"""A search index in small files, split by the first two letters of each word (tasks B3, B2).

The website cannot download every product name to search them, so the names are indexed:

  s/<file>.json   {"p": [[barcode, name, category?, facets?], ...], "w": {word: [position, ...]}}

`w` holds the words that begin with the same two letters; each word lists the positions, in `p`,
of the products that contain it. `p` holds those products: barcode, the short name the
shopper sees, the category id (left out when the product has none) and, when there is
something to say, the facets (see below). So one request per
word of the query is enough to show results: no product files are read until the shopper adds
something to the basket. (A product with several words is in several files; the name is
repeated, which is what makes the index about four times bigger than one with barcodes only.)

Facets are an addition at the END of the record, for the website's narrowing buttons, so a
search does not have to read product files: `{"f": fat percent, "z": [amount, "l"|"kg"|"unit"],
"w": true}` — exactly the values the product file already carries as a.f, z and w, and only the
ones that exist (a product with none has no fourth place). The first three places never move
and never change meaning: a reader that knows only [barcode, name, category] keeps working. When
a product has facets but no category, the category place holds "" (an empty string).

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


def facets_of(product: Mapping) -> dict:
    """What the product file already says, for the narrowing buttons: fat percent (a.f), the
    package contents (z) and "sold by weight" (w). Only what exists; {} when nothing does."""
    found: dict = {}
    fat = (product.get("a") or {}).get("f")
    if fat:
        found["f"] = fat
    if product.get("z"):
        found["z"] = product["z"]
    if product.get("w"):
        found["w"] = True
    return found


def _record(code: str, entry: tuple) -> list:
    """One entry of "p": [barcode, name, category?, facets?]. The first three places keep their
    place and meaning; facets only ever come after them."""
    name, category = entry[0], entry[1]
    facets = entry[2] if len(entry) > 2 else None
    if facets:
        return [code, name, category or "", facets]
    return [code, name, category] if category else [code, name]


def build_index(products: Mapping[str, tuple]) -> dict[str, dict]:
    """barcode -> (name, category id or None[, facets]) -> {file name: {"p": [...], "w": {...}}}."""
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
                content["p"].append(_record(code, products[code]))
            entry.append(place[code])
        content["w"][word] = entry
    return files


def file_sizes(index: Mapping[str, Mapping]) -> list[int]:
    """Bytes each index file would take (what write_index writes)."""
    return [
        len(json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        for content in index.values()
    ]


def index_size(index: Mapping[str, Mapping]) -> int:
    """Bytes all the index files would take together."""
    return sum(file_sizes(index))


def write_index(index: Mapping[str, Mapping], folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in index.items():
        path = folder / name
        path.write_text(json.dumps(content, ensure_ascii=False, separators=(",", ":")), "utf-8")
        written.append(path)
    return written


def search_records(folder: Path, query: str) -> dict[str, list] | None:
    """barcode -> its whole record ([barcode, name, category?, facets?]) for every product having
    all the words of the query (None: nothing to search for)."""
    found: dict[str, list] | None = None
    for word in words(query):
        path = folder / file_name(word)
        content = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"p": [], "w": {}}
        )
        matches = {
            content["p"][i][0]: content["p"][i]
            for w, places in content["w"].items()
            if w.startswith(word)
            for i in places
        }
        found = matches if found is None else {c: v for c, v in found.items() if c in matches}
    return found


def search(folder: Path, query: str) -> dict[str, tuple[str, str | None]] | None:
    """barcode -> (name, category id or None) of the products having every word of the query
    (None: nothing to search for)."""
    found: dict[str, tuple[str, str | None]] | None = None
    for word in words(query):
        path = folder / file_name(word)
        content = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"p": [], "w": {}}
        )
        matches = {
            content["p"][i][0]: (
                content["p"][i][1],
                content["p"][i][2] if len(content["p"][i]) > 2 else None,
            )
            for w, places in content["w"].items()
            if w.startswith(word)
            for i in places
        }
        found = matches if found is None else {c: v for c, v in found.items() if c in matches}
    return found
