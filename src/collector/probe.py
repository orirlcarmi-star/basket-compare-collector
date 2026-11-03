"""Check which public Cerberus usernames work, before a chain is added (build task 7).

The portal (url.publishedprices.co.il) serves many chains, one public username each, empty
password. Which username belongs to which chain is not written anywhere official, so a
guess must be tried. This logs in once per name, reads the file list, and says what it
found — nothing is downloaded, nothing is changed, and there are two seconds between names.

Usage: python -m collector.probe                # the candidates below
       python -m collector.probe TivTaam Keshet  # chosen names

A name that works is added to `USERNAMES` in collector/sources/cerberus.py (and its
Hebrew name to `CHAIN_NAMES` in collector/locate.py, and to the options of
.github/workflows/collect.yml); then `python -m collector.collect <chain> --limit 3` is the
first real test, after which `locate` and `build` as for the others.
"""

import re
import sys
import time
from collections import Counter

from collector.files import kind_of
from collector.sources import cerberus

# Names seen for other chains of the portal in public projects. Not verified: that is what
# this tool is for. Victory is listed because it was asked for, but it is thought to publish
# through another system (Matrix, laibcatalog.co.il) rather than this portal.
CANDIDATES = [
    "TivTaam",
    "Keshet",
    "Stop_Market",
    "politzer",
    "SalachD",
    "ZolVeBegadol",
    "Victory",
]
SECONDS_BETWEEN_NAMES = 2

_CHAIN_CODE = re.compile(r"[A-Za-z]+(\d{13})")


def describe(names: list[str]) -> str:
    """One line: how many files, of which kinds, which chain code, and whether a stores file
    and full price files exist (what `collect` needs)."""
    if not names:
        return "logged in, but the file list is empty"
    kinds = Counter(kind_of(n) for n in names)
    codes = sorted({m[1] for n in names if (m := _CHAIN_CODE.match(n))})
    has_stores = any(k in kinds for k in ("stores", "storesfull"))
    has_prices = "pricefull" in kinds
    top = ", ".join(f"{kind} {count}" for kind, count in kinds.most_common(5))
    stores, prices = ("yes" if has_stores else "NO"), ("yes" if has_prices else "NO")
    verdict = "" if has_stores and has_prices else "  <- cannot be collected as is"
    return (
        f"{len(names)} files ({top}); chain code {', '.join(codes) or '?'}; "
        f"stores file: {stores}; full prices: {prices}{verdict}"
    )


def main(argv: list[str] | None = None) -> int:
    names = (sys.argv[1:] if argv is None else argv) or CANDIDATES
    working = 0
    for number, username in enumerate(names):
        if number:
            time.sleep(SECONDS_BETWEEN_NAMES)
        try:
            files = [f.name for f in cerberus.Session(username).list_files()]
            print(f"{username}: {describe(files)}")
            working += bool(files)
        except Exception as error:  # a wrong name is an answer, not a crash
            print(f"{username}: does not work ({type(error).__name__}: {error})")
    return 0 if working else 1


if __name__ == "__main__":
    sys.exit(main())
