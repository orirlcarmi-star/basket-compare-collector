"""Choose the clearest name when chains disagree about one barcode (build task 5).

The same barcode is "חלב 3%" at one chain and "חלב טרה 3% בקרטון 1 ליטר" at another; the site
should show the second. A name scores higher when it is whole (not cut off, not a code or
all capitals), has Hebrew letters, says more (words, plus a size and a brand when they can
be read), and is not absurdly long (promotion text pasted into the name). A tie keeps the
name already chosen, so the result does not depend on luck, only on the order of the chains.
"""

import re

from collector.attributes import _clean, brand_in, size_from_name

_HEBREW = re.compile(r"[א-ת]")
_WORD = re.compile(r"[\w'\"%]{2,}")
_ONLY_SYMBOLS_OR_DIGITS = re.compile(r"[\d\W_]+")
_CUT_OFF = re.compile(r"\.\.|…|[-,/*+]$")
_STRAY = re.compile(r"[#_*|<>{}\\]")
_TOO_LONG = 70


def name_score(name: str) -> tuple[int, int, int]:
    """Higher is better; compares as (fewer faults, more information, more length)."""
    text = _clean(name)
    if not text:
        return (-99, 0, 0)
    faults = 0
    if _ONLY_SYMBOLS_OR_DIGITS.fullmatch(text):
        faults += 5
    if _CUT_OFF.search(text):
        faults += 2  # "בקבוק קולה 1.5 לי..." was cut at the chain's field length
    if _STRAY.search(text):
        faults += 1
    if not _HEBREW.search(text):
        faults += 1
    if text.upper() == text and re.search(r"[A-Z]{3,}", text):
        faults += 1  # SHOUTED, usually an unedited system name
    if len(text) > _TOO_LONG:
        faults += 1
    information = len({w.lower() for w in _WORD.findall(text)})
    information += 2 * (size_from_name(text) is not None) + (brand_in(text) != "")
    return (-faults, information, min(len(text), _TOO_LONG))


def better_name(current: str, candidate: str) -> str:
    """`candidate` only when it clearly scores higher; otherwise `current` stays."""
    return candidate if name_score(candidate) > name_score(current) else current
