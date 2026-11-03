"""Sort products into 13 general categories by the words in their names (build task B).

A rule is a list of words or phrases. A trailing * lets the word continue ("גבינ*" matches
גבינה, גבינת, גבינות). Words are compared in the normal form of collector.textnorm, so
"קוטג'", vowel points, final letters and abbreviations such as "גב." (גבינה) are handled.

How a category is chosen:
1. Strong words decide wherever they stand: "קפוא*" (frozen), baby words. "עוף קפוא" is
   frozen, not meat; "מגבוני לחות לתינוק" is for babies, not hygiene.
2. Otherwise the word that comes first wins, because Israeli names start with the thing
   itself: "מיץ תפוזים" is a drink (not fruit), "חטיף בטעם גבינה" a snack (not dairy),
   "עוגת גבינה" a pastry. When two rules match at the same place, the one listed first wins,
   so a more specific phrase ("סבון כלים") is listed before its general word ("סבון").
3. Nothing matches: no category (None). Those names go to a list for a person to read, and
   the rules are completed from it. A wrong category is worse than none, so a rule is only
   added for words that mean one thing.

Run `python -m collector.categories <chain> --data data` for the share classified and the
names that were not.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from collector.textnorm import normalize


@dataclass(frozen=True)
class Category:
    id: str
    name: str


CATEGORIES = (
    Category("dairy", "חלב וביצים"),
    Category("meat", "בשר ועוף"),
    Category("fish", "דגים"),
    Category("produce", "ירקות ופירות"),
    Category("bakery", "לחם ומאפים"),
    Category("pantry", "יבשים ושימורים"),
    Category("snacks", "ממתקים וחטיפים"),
    Category("drinks", "שתייה"),
    Category("frozen", "קפואים"),
    Category("cleaning", "ניקיון"),
    Category("hygiene", "היגיינה וטיפוח"),
    Category("baby", "תינוקות"),
    Category("home", "בית"),
)

# --- 1. words that decide wherever they stand -------------------------------------------

STRONG: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "frozen",
        (
            "קפוא*",
            "מוקפא*",
            "גלידה",
            "גלידת",
            "גלידות",
            "קרטיב*",
            "שלגון*",
            "ארטיק*",
            "ג'לאטו",
            "סורבה",
        ),
    ),  # fmt: skip
    (
        "baby",
        (
            "חיתול*",
            "חיתולי*",
            "מטרנה",
            "סימילאק",
            "נוטרילון",
            "תמל",
            "תחליף חלב אם",
            "תינוק*",
            "לתינוק*",  # "for the baby": the letter ל is part of the word
            "פעוט*",
            "לפעוט*",
            "מוצץ",
            "מוצצים",
            "פורמולה",
            "האגיס",
            "פמפרס",
            "גרבר",
            "מחית פירות",
            "מחית ירקות",
        ),
    ),  # fmt: skip
)

# --- 2. the first word wins; on a tie the earlier line wins -----------------------------

RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # specific phrases first, so that they beat the general word that begins them
    (
        "hygiene",
        (
            "מרכך שיער",
            "סבון גוף",
            "סבון ידיים",
            "סבון נוזלי",
            "קרם ידיים",
            "קרם גוף",
            "קרם פנים",
            "קרם הגנה",
            "קרם לחות",
            "קרם גילוח",
        ),
    ),  # fmt: skip
    ("cleaning", ("סבון כלים", "מרכך כביסה", "מרכך*", "נוזל כלים", "נוזל לכלים")),
    (
        "pantry",
        (
            "מרק*",
            "ממרח*",
            "חומוס*",
            "טחינה",
            "אבקת אפיה",
            "אבקת אפייה",
            "אבקת פודינג",
            "קורנפלקס",
            "דגנ*",
            "שמן",
            "שמנים",
            "רוטב*",
            "קמח*",
            "סוכר",
            "מלח",
            "אורז*",
            "פסטה",
            "ספגטי",
            "פנה",
            "פוסילי",
            "מקרוני",
            "אטריות",
            "קוסקוס",
            "פתיתים",
            "בורגול",
            "קינואה",
            "גרנולה",
            "קוואקר",
            "שיבולת*",
            "עדשים",
            "שעועית",
            "חומץ",
            "קטשופ",
            "מיונז",
            "חרדל",
            "ריבה",
            "דבש",
            "סילאן",
            "שימורי*",
            "שימורים",
            "תירס",
            "אפונה",
            "זיתים",
            "חמוצים",
            "מלפפונים חמוצים",
            "טונה",
            "סרדינ*",
            "פולי",
            "רסק*",
            "תבלין*",
            "תבלינים",
            "פפריקה",
            "כמון",
            "קינמון",
            "אגוז*",
            "שקדים",
            "קשיו",
            "פקאן",
            "צימוקים",
            "פירות יבשים",
            "תמרים",
            "שמרים",
            "וניל",
            "פודינג",
            "ג'לי",
            "עמילן",
            "פירורי לחם",
            "פירורי",
            "קרקר*",
            "טורטיות",
            "ממתיק",
            "סוכרזית",
            "קטניות",
            "גרגרי חומוס",
            "קוקוס",
            "פלפל שחור",
            "פלפל לבן",
            "חמאת בוטנים",
        ),
    ),  # fmt: skip
    (
        "snacks",
        (
            "שוקולד*",
            "ממתק*",
            "ממתקים",
            "סוכריות",
            "סוכריה",
            "מסטיק",
            "חטיף*",
            "ציפס",
            "תפוציפס",
            "במבה",
            "ביסלי",
            "דוריטוס",
            "פופקורן",
            "פרלינים",
            "פרליני",
            "וופל*",
            "עוגיות",
            "עוגיית",
            "ביסקוויט*",
            "חלווה",
            "מרציפן",
            "גומי",
            "מרשמלו",
            "נשנושי*",
            "בוטנים",
            "גרעינים",
            "פיסטוק",
            "פתי בר",
            "קליק",
            "מקופלת",
            "לוקשים",
            "אבקת שוקולד",
            "בייגלה",
            "קראנץ",
            "קינדר",
            "טופי",
            "קרמל",
            "סוכריות על מקל",
        ),
    ),  # fmt: skip
    (
        "dairy",
        (
            "חלב",
            "גבינ*",
            "קוטג",
            "שמנת",
            "יוגורט*",
            "לבן",
            "לבנה",
            "אשל",
            "קפיר",
            "חמאה",
            "מרגרינה",
            "ביצים",
            "ביצה",
            "מוצרלה",
            "עמק",
            "צהובה",
            "בולגרית",
            "פטה",
            "ריקוטה",
            "קממבר",
            "גאודה",
            "פרמזן",
            "מעדן*",
            "מילקי",
            "שוקו",
            "צפתית",
            "קצוטה",
            "נפולאון",
            "ברי",
            "מסקרפונה",
            "אמנטל",
            "חלומי",
            "לאבנה",
            "סקי",
        ),
    ),  # fmt: skip
    (
        "meat",
        (
            "עוף",
            "חזה",
            "כנפיים",
            "שוק",
            "פרגית",
            "פרגיות",
            "שניצל*",
            "נקניק*",
            "נקניקיות",
            "קבב",
            "המבורגר*",
            "בקר",
            "בשר",
            "סטייק*",
            "אנטריקוט",
            "צלי",
            "כבד",
            "לבבות",
            "הודו",
            "אווז",
            "ברווז",
            "כבש",
            "טלה",
            "סינטה",
            "אסאדו",
            "שייטל",
            "קציצות",
            "פסטרמה",
            "סלמי",
            "שווארמה",
            "קורנביף",
            "טחון",
            "צוואר",
            "צלעות",
            "אונטריב",
            "נתחי",
            "פרגיות",
            "קבבים",
            "המבורגרים",
            "מדליוני",
        ),
    ),  # fmt: skip
    (
        "fish",
        (
            "דג",
            "דגים",
            "סלמון",
            "פורל",
            "אמנון",
            "מושט",
            "לוקוס",
            "דניס",
            "קרפיון",
            "הרינג",
            "פילה דג",
            "נסיכת הנילוס",
            "אינטיאס",
            "טונה טרייה",
        ),
    ),  # fmt: skip
    (
        "produce",
        (
            "ירק*",
            "ירקות",
            "פירות",
            "פרי",
            "תפוח*",
            "תפוז*",
            "בננה",
            "בננות",
            "עגבני*",
            "מלפפון*",
            "גזר",
            "בצל*",
            "שום",
            "תפוד",
            "פלפל*",
            "חסה",
            "כרוב*",
            "ברוקולי",
            "אבוקדו",
            "לימון*",
            "אשכולית*",
            "ענבים",
            "אבטיח",
            "מלון",
            "תות*",
            "אפרסק*",
            "שזיף*",
            "נקטרינה",
            "קישוא*",
            "חציל*",
            "דלעת",
            "בטטה",
            "פטרוזיליה",
            "כוסברה",
            "נענע",
            "שמיר",
            "פטריות",
            "שרי",
            "אגס*",
            "קלמנטינה",
            "מנדרינה",
            "רימון*",
            "אננס",
            "מנגו",
            "פפאיה",
            "קיווי",
            "סלק",
            "צנון",
            "צנונית",
            "קולורבי",
            "כרובית",
            "עירית",
            "תרד",
            "עלי חסה",
            "עלי תרד",
            "עלי גפן",
            "פומלה",
            "פומלית",
            "תאנים",
            "דובדבנים",
            "משמש",
            "אפרסמון",
            "שסק",
            "תמר*",
            "ג'ינג'ר",
            "זנגביל",
            "נבטים",
            "חמניות טריות",
        ),
    ),  # fmt: skip
    (
        "bakery",
        (
            "לחם",
            "לחמנייה",
            "לחמניות",
            "פיתה",
            "פיתות",
            "חלה",
            "חלות",
            "בגט",
            "באגט",
            "בייגל",
            "טורטייה",
            "לאפה",
            "עוגה",
            "עוגת",
            "בורקס*",
            "מאפה",
            "מאפים",
            "קרואסון",
            "רוגלך",
            "מאפינס",
            "דונאט",
            "פיצה",
            "בצק*",
            "כיכר",
            "טוסט",
            "פוקצ'ה",
            "פרוסות לחם",
            "קמח תופח",
        ),
    ),  # fmt: skip
    (
        "drinks",
        (
            "מים",
            "מינרל*",
            "סודה",
            "מיץ",
            "מיצים",
            "משקה",
            "משקאות",
            "קולה",
            "פפסי",
            "ספרייט",
            "פאנטה",
            "שוופס",
            "בירה",
            "יין",
            "וודקה",
            "ויסקי",
            "ערק",
            "ליקר",
            "שמפניה",
            "ברנדי",
            "קפה",
            "תה",
            "נס",
            "אספרסו",
            "קפסולות",
            "קקאו",
            "לימונדה",
            "אייס טי",
            "אנרג'י",
            "תרכיז",
            "סירופ",
            "חליטה",
            "חליטות",
            "נקטר",
            "משקה אנרגיה",
            "סיידר",
            "ג'ין",
            "רום",
            "טקילה",
            "אלכוהול",
            "וויסקי",
        ),
    ),  # fmt: skip
    (
        "cleaning",
        (
            "כביסה",
            "אקונומיקה",
            "מנקה*",
            "ניקוי",
            "חומר ניקוי",
            "מסיר*",
            "מטהר*",
            "מבשם",
            "מדיח*",
            "דטרגנט",
            "אבקת כביסה",
            "ג'ל כביסה",
            "מסיר שומנים",
            "פיירי",
            "סנו",
            "מי כלור",
            "כלור",
            "חומצה",
            "אבקת ניקוי",
            "ספריי ניקוי",
        ),
    ),  # fmt: skip
    (
        "hygiene",
        (
            "שמפו",
            "סבון*",
            "משחת שיניים",
            "משחה לשיניים",
            "מברשת שיניים",
            "דאודורנט*",
            "ג'ל רחצה",
            "מי פה",
            "חוט דנטלי",
            "גילוח",
            "סכיני גילוח",
            "קצף גילוח",
            "אפטרשייב",
            "בושם",
            "מגבונים*",
            "מגבוני*",
            "פלסטרים",
            "פלסטר",
            "קוטנפס",
            "ספוגיות",
            "מקלוני אוזניים",
            "צמר גפן",
            "תחליב",
            "שמן גוף",
            "ג'ל לשיער",
            "ג'ל לחות",
        ),
    ),  # fmt: skip
    (
        "home",
        (
            "נייר טואלט",
            "נייר מגבת",
            "מגבות נייר",
            "מפיות",
            "שקיות אשפה",
            "שקיות",
            "נייר אפייה",
            "נייר אפיה",
            "נייר כסף",
            "אלומיניום",
            "ניילון",
            "נרות",
            "נר",
            "סוללות",
            "סוללה",
            "נורה",
            "נורות",
            "צלחות",
            "כוסות",
            'סכו"ם',
            "סכום",
            "קשיות",
            "מטליות",
            "מטלית",
            "ספוג*",
            "סקוטש",
            "מטאטא",
            "מגב",
            "גפרורים",
            "מצית",
            "כפפות",
            "מחבת",
            "סיר",
            "קופסאות",
            "קופסה",
            "אשפה",
            "מכסה",
            "תבנית",
            "תבניות",
            "חד פעמי",
            "חד פעמיים",
        ),
    ),  # fmt: skip
)

OTHER = "לא מסווג"


@dataclass(frozen=True)
class _Pattern:
    words: tuple[str, ...]
    prefix: bool  # the last word may continue


def _compile(spec: str) -> _Pattern:
    star = spec.endswith("*")
    return _Pattern(tuple(normalize(spec.rstrip("*")).split()), star)


_STRONG = tuple((cat, tuple(_compile(s) for s in specs)) for cat, specs in STRONG)
_RULES = tuple((cat, tuple(_compile(s) for s in specs)) for cat, specs in RULES)


def _first_match(tokens: list[str], pattern: _Pattern) -> int | None:
    n = len(pattern.words)
    for start in range(len(tokens) - n + 1):
        window = tokens[start : start + n]
        if window[:-1] == list(pattern.words[:-1]) and (
            window[-1].startswith(pattern.words[-1])
            if pattern.prefix
            else window[-1] == pattern.words[-1]
        ):
            return start
    return None


def categorize(name: str) -> str | None:
    """The category id for a product name, or None when no rule is sure."""
    tokens = normalize(name).split()
    if not tokens:
        return None
    for category, patterns in _STRONG:
        if any(_first_match(tokens, p) is not None for p in patterns):
            return category
    # (position of the match, fewer words last, order of the rule): the earliest word wins; at
    # the same place a longer phrase beats a single word, then the rule listed first.
    candidates = []
    order = 0
    for category, patterns in _RULES:
        for pattern in patterns:
            order += 1
            position = _first_match(tokens, pattern)
            if position is not None:
                candidates.append((position, -len(pattern.words), order, category))
    return min(candidates)[-1] if candidates else None


def category_name(category_id: str | None) -> str:
    return next((c.name for c in CATEGORIES if c.id == category_id), OTHER)


def coverage(names: Iterable[str]) -> tuple[Counter[str], list[str]]:
    """How many names fall in each category, and the names that fell in none."""
    counts: Counter[str] = Counter()
    unclassified: list[str] = []
    for name in names:
        category = categorize(name)
        counts[category or "none"] += 1
        if category is None:
            unclassified.append(name)
    return counts, unclassified


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chain")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--show", type=int, default=40, help="how many unclassified names to print")
    args = parser.parse_args(argv)
    path = args.data / args.chain / "ready" / "products.json"
    products = json.loads(path.read_text(encoding="utf-8"))
    counts, unclassified = coverage(p["name"] for p in products.values())
    total = sum(counts.values())
    print(f"{args.chain}: {total:,} products, {1 - counts['none'] / total:.1%} classified")
    for category in CATEGORIES:
        print(f"  {category.name}: {counts[category.id]:,}")
    print(f"  {OTHER}: {counts['none']:,}")
    for name in unclassified[: args.show]:
        print(f"    ? {' '.join(name.split())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
