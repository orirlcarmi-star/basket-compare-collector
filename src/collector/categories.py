"""Sort products into 14 general categories by the words in their names (build task B).

A rule is a word or a phrase. A trailing * lets the word continue ("גבינ*" matches גבינה,
גבינת, גבינות); a leading ^ means "only as the first word" ("^לבן" is the dairy drink, not
"שוקולד לבן" or "יין לבן"). Words are compared in the normal form of collector.textnorm, so
"קוטג'", vowel points, final letters and abbreviations such as "גב." (גבינה) are handled.

How a category is chosen:
0. Words in NEVER make the whole name unclassified, whatever else it says.
1. Strong words decide wherever they stand: "קפוא*" (frozen), baby words, pet words.
   "עוף קפוא" is frozen, not meat; "פאוץ לה קט סלמון" is cat food, not fish.
2. Otherwise the word that comes first wins, because Israeli names start with the thing
   itself: "מיץ תפוזים" is a drink (not fruit), "חטיף בטעם גבינה" a snack (not dairy),
   "עוגת גבינה" a pastry. When two rules match at the same place, the longer phrase wins
   ("סבון כלים" over "סבון"), then the rule listed first.
3. "בטעם ..." (flavoured with) is not the product: everything from "בטעם" on is ignored
   ("סקיטלס בטעם פירות" is a sweet, not fruit; "יוגורט בטעם תות" is still dairy).
4. A fruit or vegetable named together with a volume (ליטר, מ"ל) is a drink, not produce:
   "ספרינג מנגו בננה 1.5 ליטר". Fresh produce is sold by weight or by the unit.
   But a fruit word never beats a cleaning, hygiene or household word anywhere in the name:
   "נוזל רצפה מלון 2 ל" is a cleaner with a melon scent, not a drink.
5. Nothing matches: no category (None). Those names go to a list for a person to read, and
   the rules are completed from it. A wrong category is worse than none: when a word can mean
   two things ("טחון" is ground meat, ground cumin, ground coffee) it is only used inside a
   phrase that says which ("בשר טחון").

Run `python -m collector.categories <chain> --data data` for the share classified and the
names that were not.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from collector.attributes import VOLUME, size_from_name
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
    Category("pets", "חיות מחמד"),
)


def _words(text: str) -> tuple[str, ...]:
    """Rules are written as comma-separated phrases: easy to read, one place to add a word."""
    return tuple(part.strip() for part in text.replace("\n", " ").split(",") if part.strip())


# --- 0. names that are never given a category ---------------------------------------------
# Words of make-up and nail products, and of lip products. They are kept out of every rule,
# so that a word like "שמן" or "מסיר" in such a name cannot send it to the wrong category.

NEVER = _words(
    """שפתיים, שפתון, קוטיקולה, נייל, לק, עפרון, מסקרה, איפור, מייקאפ, גלוס, סומק, אודם, ריסים"""
)

# --- 1. words that decide wherever they stand --------------------------------------------

STRONG: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "frozen",
        _words("""קפוא*, מוקפא*, גלידה, גלידת, גלידות, קרטיב*, שלגון*, ארטיק*, ג'לאטו, סורבה"""),
    ),
    (
        "baby",
        _words(
            """חיתול*, חיתולי*, מטרנה, סימילאק, נוטרילון, תמל, תחליף חלב אם, תינוק*, לתינוק*,
            פעוט*, לפעוט*, מוצץ, מוצצים, פורמולה, האגיס, פמפרס, גרבר, מחית פירות, מחית ירקות"""
        ),
    ),  # not "בייבי": there are baby carrots and baby spinach
    (
        "pets",
        _words(
            """לחתול*, לכלב*, חתולים, חתול, כלבים, כלב, לה קט, וויסקס, ויסקס, פדיגרי, שבא,
            פרוליין, פריסקיז, רויאל קנין, דוג, פט פוד, לחיות מחמד"""
        ),
    ),  # "קט" alone is also KitKat, so only the phrase "לה קט" counts
    # Teeth: toothpaste says "הלבנה" (whitening), which on its own is a laundry word.
    ("hygiene", _words("""שיניים, לשיניים""")),
)

# --- 2. the first word wins; the longer phrase wins a tie; then the rule listed first ----

RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Phrases first: they must beat the general word that begins them.
    (
        "hygiene",
        _words(
            """מרכך שיער, מסכה לשיער, מסכת שיער, שמן לשיער, שמן שיער, סבון גוף, סבון ידיים,
            סבון נוזלי, קרם ידיים, קרם גוף, קרם פנים, קרם הגנה, קרם לחות, קרם לילה, קרם יום,
            קרם עיניים, קרם רגליים, קרם גילוח, קרם שיזוף, ספריי לשיער, ג'ל לשיער, ג'ל רחצה,
            שמן גוף, שמן עיסוי, ג'ל לחות, משחת שיניים, משחה לשיניים, מברשת שיניים, חוט דנטלי,
            מי פה, צמר גפן, מקלוני אוזניים"""
        ),
    ),
    (
        "cleaning",
        _words(
            """סבון כלים, מרכך כביסה, מרכך*, נוזל כלים, נוזל לכלים, אבקת כביסה, נוזל כביסה,
            ג'ל כביסה, כדורי כביסה, מסיר שומנים, מסיר שומן, מסיר אבנית, מסיר כתמים,
            אבקת הלבנה, מלח למדיח, טבליות למדיח, נוזל רצפות, נוזל רצפה, נוזל פרקט,
            נוזל חלונות, מנקה*, מטהר אוויר, מטהרי אוויר"""
        ),
    ),
    (
        "pantry",
        _words(
            """אבקת*, מרק*, ממרח*, חומוס*, טחינה, קורנפלקס, דגנ*, שמן, שמנים, רוטב*, קמח*, סוכר,
            מלח, אורז*, פסטה, ספגטי, פנה, פוסילי, מקרוני, אטריות, נודלס, קוסקוס, פתיתים,
            בורגול, קינואה, כוסמת, סולת, פולנטה, גרנולה, קוואקר, שיבולת*, עדשים, שעועית,
            חומץ, קטשופ, מיונז, חרדל, ריבה, דבש, סילאן, מולסה, סירופ מייפל, שימורי*, שימורים,
            תירס, אפונה, זיתים, חמוצים, כבוש*, מלפפונים חמוצים, פלפלים חמוצים, טונה, סרדינ*,
            סלמון משומר, רסק*, תבלין*, תבלינים, פפריקה, כמון, קינמון, קימל, כורכום, קרדמום,
            אניס, זעפרן, אורגנו, טימין, פלפל שחור, פלפל לבן, אגוזים, אגוזי מלך, שקדים, קשיו,
            פקאן, צימוקים, פירות יבשים, תמרים, שמרים, וניל, פודינג, ג'לי, עמילן, פירורי*,
            טורטיות, ממתיק, סוכרזית, קטניות, גרגרי חומוס, קוקוס, חמאת בוטנים, חמאת שקדים,
            שוקולד למריחה, נוטלה, פסטו, סלסה, אצות, נורי, ווסאבי, טריאקי, סויה, רוטב סויה,
            סודה לשתייה, מיץ לימון, תערובת*, פירות משומרים, חלב קוקוס"""
        ),
    ),
    (
        "snacks",
        _words(
            """שוקולד*, ממתק*, ממתקים, ופל*, ופלים, נטיפים, סוכריות, סוכריה, מסטיק, חטיף*,
            חטיפי*, ציפס, תפוציפס, במבה, ביסלי, דוריטוס, צ'יטוס, פופקורן, פרלינים, פרליני,
            וופל*, עוגיות, עוגיית, ביסקוויט*, חלווה, מרציפן, גומי, מרשמלו, נשנושי*, בוטנים,
            גרעינים, פיסטוק, פתי בר, קליק, מקופלת, לוקשים, אבקת שוקולד, בייגלה, קראנץ, קינדר,
            טופי, קרמל, קרקר*, פריכיות, פריכית, לקריץ, אנרג'י בר, מילקה, לינדט, סניקרס,
            טוויקס, באונטי, אוראו, קיט קט, סקיטלס, מנטוס, טיק טק, אורביט, פרינגלס, פררו,
            רפאלו, טופיפי, פסק זמן, מארס"""
        ),
    ),
    (
        "dairy",
        _words(
            """חלב, גבינ*, קוטג, שמנת, יוגורט*, ^לבן, לבנה, אשל, קפיר, חמאה, מרגרינה, ביצים,
            ביצה, מוצרלה, עמק, צהובה, בולגרית, פטה, ריקוטה, קממבר, גאודה, פרמזן, מעדן*,
            מילקי, שוקו, צפתית, קצוטה, נפולאון, ברי, מסקרפונה, אמנטל, חלומי, לאבנה, סקי,
            קשקבל, דנונה, יופלה, מולר, אקטיביה"""
        ),
    ),
    (
        "meat",
        _words(
            """עוף, עופות, חזה, כנפיים, כנף, שוק, שוקיים, כרעיים, פרגית, פרגיות, שניצל*, נקניק*,
            נקניקיות, קבב, קבבים, המבורגר*, בקר, בשר, סטייק*, אנטריקוט, צלי, כבד, לבבות עוף,
            לבבות הודו, הודו, אווז, ברווז, כבש, טלה, סינטה, אסאדו, שייטל, קציצות, פסטרמה,
            סלמי, שווארמה, קורנביף, בשר טחון, עוף טחון, הודו טחון, צוואר, צלעות, אונטריב,
            נתחי, מדליוני, גולש"""
        ),
    ),
    (
        "fish",
        _words(
            """דג, דגים, סלמון, פורל, אמנון, מושט, לוקוס, דניס, קרפיון, הרינג, פילה דג,
            נסיכת הנילוס, אינטיאס, טונה טרייה, בקלה, לברק, קלמארי, שרימפס, פירות ים, סורימי,
            סרדינים טריים"""
        ),
    ),
    (
        "produce",
        _words(
            """ירק*, ירקות, פירות, פרי, תפוח*, תפוז*, בננה, בננות, עגבני*, מלפפון*, גזר, בצל*,
            שום, תפוד, פלפל*, חסה, חסות, לבבות קיסר, לבבות חסה, רוקט, כרוב*, ברוקולי, אבוקדו,
            לימון*, אשכולית*, ענבים, אבטיח, מלון, תות*, אפרסק*, שזיף*, נקטרינה, קישוא*,
            חציל*, דלעת, בטטה, פטרוזיליה, כוסברה, נענע, שמיר, פטריות, שרי, אגס*, קלמנטינה,
            מנדרינה, רימון*, אננס, מנגו, פפאיה, קיווי, סלק, צנון, צנונית, קולורבי, כרובית,
            עירית, תרד, סלרי, עלי חסה, עלי תרד, עלי גפן, פומלה, פומלית, תאנים, דובדבנים,
            משמש, אפרסמון, שסק, אוכמניות, אוכמנית, פטל, דומדמניות, תמר*, ג'ינג'ר, זנגביל,
            נבטים, בזיליקום, עשבי תיבול"""
        ),
    ),
    (
        "bakery",
        _words(
            """לחם, לחמנייה, לחמניות, פיתה, פיתות, חלה, חלות, בגט, באגט, בייגל, טורטייה, לאפה,
            עוגה, עוגת, בורקס*, מאפה, מאפים, קרואסון, רוגלך, מאפינס, דונאט, סופגנייה, פיצה,
            בצק*, כיכר, טוסט, פוקצ'ה, פרוסות לחם, קמח תופח"""
        ),
    ),
    (
        "drinks",
        _words(
            """מים, מינרל*, סודה, מיץ, מיצים, משקה, משקאות, קולה, פפסי, ספרייט, פאנטה, שוופס,
            בירה, יין, וודקה, ויסקי, ערק, ליקר, שמפניה, ברנדי, קפה, תה, נס, אספרסו,
            נספרסו, דולצ'ה גוסטו, קקאו, לימונדה, אייס טי, אנרג'י, תרכיז, סירופ, חליטה, חליטות, נקטר, סיידר,
            מי קוקוס, ג'ין, רום, טקילה, אלכוהול, וויסקי, קוניאק, קאווה, פרוסקו, מוסקטו,
            קברנה, מרלו, שרדונה, שאבלי, בורגונדי, קיאנטי, טמפרניו, ספרינג, פריגת, פרימור,
            סוביניון, רוזה, פינו, שיראז, מלבק, ריזלינג, יקב*, איזוטוני"""
        ),
    ),
    (
        "cleaning",
        _words(
            """כביסה, לכביסה, למדיח, קוואנטום, הלבנה, ריצפז, פיניש, פנטסטיק, לניקוי, רצפה, פרקט,
            אקונומיקה, ניקוי, חומר ניקוי, מטהר*, מבשם, מדיח*, דטרגנט, פיירי, סנו, סומו, פרסיל, כלור, חומצה,
            ספריי ניקוי, אסלה, שירותים, נוזל זכוכית, רצפות"""
        ),
    ),
    (
        "hygiene",
        _words(
            """שמפו, סבון*, דאודורנט*, מגבונים*, מגבוני*, פלסטר, פלסטרים, גילוח, סכיני גילוח,
            קצף גילוח, אפטרשייב, בושם, תחליב, גרניה, דאו, דאב, דרמו, ניוואה, פנטן,
            הד אנד שולדרס, האד אנד שולדרס, קולגייט, אורל בי, סנסודין, ליסטרין, ג'ילט,
            ספידסטיק, רקסונה, קלירסיל, קלינקס, טישו, ממחטות, ניוטרוגינה, לחות, רול און,
            רולון, טיפוח, קוסמטיקה"""
        ),
    ),
    (
        "home",
        _words(
            """נייר טואלט, נייר מגבת, מגבות נייר, מפיות, מפת שולחן, מפות שולחן, שקיות אשפה,
            שקיות, נייר אפייה, נייר אפיה, נייר כסף, אלומיניום, ניילון, נרות, נר, סוללות,
            סוללה, נורה, נורות, צלחות, כוסות, סכום, קשיות, מטליות, מטלית, ספוג*, סקוטש,
            מטאטא, מגב, גפרורים, מצית, כפפות, מחבת, סיר, קופסאות, קופסה, אשפה, מכסה, תבנית,
            תבניות, חד פעמי, חד פעמיים"""
        ),
    ),
)

OTHER = "לא מסווג"


@dataclass(frozen=True)
class _Pattern:
    words: tuple[str, ...]
    prefix: bool  # the last word may continue
    first: bool  # only as the first word of the name


def _compile(spec: str) -> _Pattern:
    first = spec.startswith("^")
    star = spec.endswith("*")
    return _Pattern(tuple(normalize(spec.strip("^*")).split()), star, first)


class _Index:
    """Patterns found by the words of a name, so that a name is only tried against the patterns
    that could match it (with ~600 patterns and 40,000 names the plain loop took half a minute).
    A pattern is filed under its first word; a single word that may continue ("גבינ*") cannot be
    looked up by that word, so those are tried against every name."""

    def __init__(self, entries: list[tuple[int, str, _Pattern]]) -> None:
        self._by_word: dict[str, list[tuple[int, str, _Pattern]]] = {}
        self._wild: list[tuple[int, str, _Pattern]] = []
        for entry in entries:
            pattern = entry[2]
            if pattern.prefix and len(pattern.words) == 1:
                self._wild.append(entry)
            else:
                self._by_word.setdefault(pattern.words[0], []).append(entry)

    def matches(self, tokens: list[str]) -> list[tuple[int, int, str, _Pattern]]:
        """(position, order, category, pattern) of every pattern that matches the tokens."""
        found = []
        seen = set()
        candidates = [e for t in set(tokens) for e in self._by_word.get(t, ())] + self._wild
        for order, category, pattern in candidates:
            if order in seen:
                continue
            seen.add(order)
            position = _first_match(tokens, pattern)
            if position is not None:
                found.append((position, order, category, pattern))
        return found


def _entries(groups) -> list[tuple[int, str, _Pattern]]:
    order = 0
    entries = []
    for category, specs in groups:
        for spec in specs:
            order += 1
            entries.append((order, category, _compile(spec)))
    return entries


_NEVER = _Index(_entries([("never", NEVER)]))
_STRONG = _Index(_entries(STRONG))
_RULES = _Index(_entries(RULES))


def _first_match(tokens: list[str], pattern: _Pattern) -> int | None:
    n = len(pattern.words)
    last_start = 0 if pattern.first else len(tokens) - n
    for start in range(last_start + 1):
        window = tokens[start : start + n]
        if (
            len(window) == n
            and window[:-1] == list(pattern.words[:-1])
            and (
                window[-1].startswith(pattern.words[-1])
                if pattern.prefix
                else window[-1] == pattern.words[-1]
            )
        ):
            return start
    return None


_OVER_PRODUCE = {"cleaning", "hygiene", "home"}


@lru_cache(maxsize=200_000)
def categorize(name: str) -> str | None:
    """The category id for a product name, or None when no rule is sure."""
    tokens = normalize(name).split()
    if "בטעמ" in tokens[1:]:  # "flavoured with": what follows is not the product
        tokens = tokens[: tokens.index("בטעמ", 1)]
    if not tokens or _NEVER.matches(tokens):
        return None
    strong = _STRONG.matches(tokens)
    if strong:
        return min(strong, key=lambda m: m[1])[2]  # the strong group listed first
    # (position of the match, fewer words last, order of the rule): the earliest word wins; at
    # the same place a longer phrase beats a single word, then the rule listed first.
    candidates = [(pos, -len(p.words), order, cat) for pos, order, cat, p in _RULES.matches(tokens)]
    if not candidates:
        return None
    category = min(candidates)[-1]
    if category == "produce":
        # A fruit word is often only the scent or flavour: any cleaning, hygiene or household word
        # in the name wins over it, wherever it stands.
        others = [c for c in candidates if c[3] in _OVER_PRODUCE]
        if others:
            return min(others)[-1]
        size = size_from_name(name)
        if size is not None and size.kind == VOLUME:
            return "drinks"  # fruit named with a volume: a juice or a soft drink
    return category


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
