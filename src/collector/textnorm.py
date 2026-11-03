"""One way of writing Hebrew product text, for searching and for sorting into categories.

The same rules must be used by whoever types a search, so the website has a copy of this
(`REFERENCE` in tests/test_textnorm.py pins down what it must produce):

1. Chains' abbreviations written with a dot are spelled out: "גב." -> גבינה, "יוג." -> יוגורט,
   "שוק." -> שוקולד (see ABBREVIATIONS; a bare "שוק" is a chicken thigh and is left alone).
2. Vowel points and cantillation marks are removed.
3. Apostrophes, geresh and gershayim are removed: "קוטג'" -> קוטג, "ק\"ג" -> קג.
4. Final letters become ordinary letters: ך ם ן ף ץ -> כ מ נ פ צ (so a word is the same
   typed in the middle of a phrase or at its end, and spelling variants meet).
5. Latin letters become lower case.
6. Anything that is not a letter or digit separates words, and so does the place where
   letters meet digits: "חלבון600גד" -> חלבונ 600 גד, "נפולאון24" -> נפולאון 24.
"""

import re

ABBREVIATIONS = {
    "גב.": "גבינה",
    "גבי.": "גבינה",
    "גאוד.": "גאודה",
    "יוג.": "יוגורט",
    "שוק.": "שוקולד",
}
_ABBREVIATION = re.compile(
    "(?<![א-ת])("
    + "|".join(re.escape(a) for a in sorted(ABBREVIATIONS, key=len, reverse=True))
    + ")"
)
_POINTS = re.compile("[֑-ׇ]")  # cantillation, vowel points, maqaf is handled below
_APOSTROPHES = re.compile("[\"'`׳״’‘“”]")
_FINAL = str.maketrans("ךםןףץ", "כמנפצ")
_WORD = re.compile(r"[א-תa-z0-9]+")
_LETTER_DIGIT = re.compile(r"(?<=[א-תa-z])(?=\d)|(?<=\d)(?=[א-תa-z])")
# "גבינת עמק" is a cheese too: whoever searches "גבינה" should find it. The few nouns whose
# "of" form (ending in ת) is common in product names are searched in their plain form.
CONSTRUCT_FORMS = {
    "גבינת": "גבינה",
    "עוגת": "עוגה",
    "גלידת": "גלידה",
    "חמאת": "חמאה",
    "ביצת": "ביצה",
}
STOP_WORDS = {w.translate(_FINAL) for w in ("של", "עם", "את", "או", "על", "מן")}  # as normalised
MIN_WORD = 2  # a one-letter word cannot be placed in the two-letter search files


def normalize(text: str) -> str:
    """The text in normal form: words of letters and digits separated by single spaces."""
    text = _ABBREVIATION.sub(lambda m: f" {ABBREVIATIONS[m[1]]} ", text)
    text = _POINTS.sub("", text.replace("־", " "))
    text = _APOSTROPHES.sub("", text)
    return _LETTER_DIGIT.sub(" ", " ".join(_WORD.findall(text.translate(_FINAL).lower())))


def words(text: str) -> list[str]:
    """Searchable words in order: no stop words, no one-letter words, no bare numbers, and the
    "of" form of a few nouns (גבינת) in its plain form (גבינה)."""
    return [
        CONSTRUCT_FORMS.get(w, w)
        for w in normalize(text).split()
        if len(w) >= MIN_WORD and not w.isdigit() and w not in STOP_WORDS
    ]
