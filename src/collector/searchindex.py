"""A search index in small files, split by the first two letters of each word (task B3).

The website cannot download every product name to search them, so the names are indexed:

  s/<file>.json   {"<word>": ["<barcode>", ...], ...}   words that begin with the same two letters

The file name is the two letters as four hex digits of each ("חל" -> "05d705dc"), so any letter
is safe in a URL. Words and queries are written in the normal form of `collector.textnorm`
(no vowel points or apostrophes, plain final letters, abbreviations such as "גב." spelled out).

To search: normalise the query into words; for each word read the file of its first two letters
and take the barcodes of every word that STARTS with it (typing "גבינ" finds גבינה, גבינות);
keep the barcodes found for all the query words. `search` below does exactly that and is the
reference for the website. A query word of one letter cannot be searched.
"""

import json
from collections.abc import Mapping
from pathlib import Path

from collector.textnorm import words

PREFIX = 2


def file_name(word: str) -> str:
    """ "חל..." -> "05d705dc.json" """
    return "".join(f"{ord(c):04x}" for c in word[:PREFIX]) + ".json"


def build_index(names: Mapping[str, str]) -> dict[str, dict[str, list[str]]]:
    """barcode -> product name  ->  {file name: {word: [barcodes]}}."""
    postings: dict[str, set[str]] = {}
    for code, name in names.items():
        for word in set(words(name)):
            postings.setdefault(word, set()).add(code)
    files: dict[str, dict[str, list[str]]] = {}
    for word in sorted(postings):
        files.setdefault(file_name(word), {})[word] = sorted(postings[word])
    return files


def write_index(index: Mapping[str, Mapping[str, list[str]]], folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in index.items():
        path = folder / name
        path.write_text(json.dumps(content, ensure_ascii=False, separators=(",", ":")), "utf-8")
        written.append(path)
    return written


def search(folder: Path, query: str) -> set[str] | None:
    """Barcodes of products having every word of the query (None: nothing to search for)."""
    query_words = words(query)
    if not query_words:
        return None
    found: set[str] | None = None
    for word in query_words:
        path = folder / file_name(word)
        content = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        matches = {code for w, codes in content.items() if w.startswith(word) for code in codes}
        found = matches if found is None else found & matches
    return found
