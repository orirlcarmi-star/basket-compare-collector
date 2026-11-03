"""Facts read out of a product's name (build task 3): fat percentage, package size,
"free of" labels and brand.

Chains write names by hand ("חלב בקרטון 3% שומן 1 ל", "קוטג' תנובה 5% 250 גרם"), so everything
here is a careful guess from the text and returns nothing when the text is unclear:
a missing value is always better than a wrong one on a shopper's screen.

- Fat: "3% שומן", "שומן 3%", or a percentage on a dairy or ground-meat product
  ("קוטג' 5%"). "ללא שומן" is 0. A percentage on chocolate, juice or alcohol is not fat.
- Size, normalised to one base unit per kind: volume in millilitres (1 ליטר = 1000),
  weight in grams (1 ק"ג = 1000), or a count of units. The name wins over the chain's
  Quantity/UnitQty fields, which are often wrong (a 750 ml bottle published as "1 יחידה");
  the fields are used when the name has no size. "6*1.5 ליטר" is 9 litres. Items sold by
  weight are priced per kilo, so their size is 1 kg.
- Free of: "lactose", "gluten", "sugar" (ללא סוכר, זירו) and "added_sugar" (ללא תוספת סוכר,
  which is not the same thing: a juice without added sugar still has sugar). "דל לקטוז"
  (low in lactose) is deliberately not "lactose free".
- Brand: a known brand written in the name, or in the manufacturer field. The list is
  short and meant to grow: add a line to BRANDS.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

VOLUME, WEIGHT, COUNT = "volume", "weight", "count"


@dataclass(frozen=True)
class Size:
    amount: Decimal  # millilitres, grams or units, by kind
    kind: str  # "volume", "weight" or "count"


@dataclass(frozen=True)
class Attributes:
    fat_percent: Decimal | None
    size: Size | None
    free_of: tuple[str, ...]  # sorted subset of: added_sugar, gluten, lactose, sugar
    brand: str  # "" when unknown


_QUOTES = str.maketrans({"״": '"', "”": '"', "“": '"', "׳": "'", "’": "'", "‘": "'", "`": "'"})


def _clean(text: str) -> str:
    """One spelling for quotes and spaces, so "ק״ג", "ק''ג" and 'ק"ג' read alike."""
    text = text.translate(_QUOTES).replace("''", '"')
    return " ".join(text.split())


# ----------------------------------------------------------------------------- size

_NUMBER = r"\d+(?:[.,]\d+)?"
# (spelling after the number, kind, how many base units one of it is). Longest first:
# the alternation must try "ליטר" before "ל".
_UNITS = {
    'ק"ג': (WEIGHT, 1000),
    "ק'ג": (WEIGHT, 1000),
    "קג": (WEIGHT, 1000),
    "קילוגרם": (WEIGHT, 1000),
    "קילו": (WEIGHT, 1000),
    "kg": (WEIGHT, 1000),
    "גרמים": (WEIGHT, 1),
    "גרם": (WEIGHT, 1),
    "גר'": (WEIGHT, 1),
    "גר": (WEIGHT, 1),
    "ג'": (WEIGHT, 1),
    "gr": (WEIGHT, 1),
    "g": (WEIGHT, 1),
    "ג": (WEIGHT, 1),
    "ליטרים": (VOLUME, 1000),
    "ליטר": (VOLUME, 1000),
    "ל'": (VOLUME, 1000),
    "lt": (VOLUME, 1000),
    "l": (VOLUME, 1000),
    "ל": (VOLUME, 1000),
    "מיליליטר": (VOLUME, 1),
    'מ"ל': (VOLUME, 1),
    "מ'ל": (VOLUME, 1),
    "מל": (VOLUME, 1),
    "ml": (VOLUME, 1),
    'סמ"ק': (VOLUME, 1),
    "יחידות": (COUNT, 1),
    "יחידה": (COUNT, 1),
    "יח'": (COUNT, 1),
    "יח": (COUNT, 1),
}
_UNIT_PATTERN = "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
# A unit counts only when the word ends there: "1 ל" yes, "1 לבן" no.
_AFTER = r"(?![\w\"'])"
_QUANTITY = re.compile(rf"(?<![\d.,])({_NUMBER})\s*({_UNIT_PATTERN}){_AFTER}", re.IGNORECASE)
_MULTIPACK = re.compile(
    rf"(?<![\d.,])(\d+)\s*[*xX×]\s*({_NUMBER})\s*({_UNIT_PATTERN}){_AFTER}", re.IGNORECASE
)


def _number(text: str) -> Decimal:
    return Decimal(text.replace(",", "."))


def _tidy(value: Decimal) -> Decimal:
    """1500.0 -> 1500, 0.50 -> 0.5 (and never 1.5E+3)."""
    return Decimal(format(value.normalize(), "f"))


def _size(number: str, unit: str, times: int = 1) -> Size | None:
    kind, factor = _UNITS[unit.lower()]
    amount = _number(number) * factor * times
    return Size(_tidy(amount), kind) if amount > 0 else None


def size_from_name(name: str) -> Size | None:
    text = _clean(name)
    if match := _MULTIPACK.search(text):
        return _size(match[2], match[3], int(match[1]))
    weight_or_volume = None
    count = None
    for match in _QUANTITY.finditer(text):
        found = _size(match[1], match[2])
        if found is None:
            continue
        if found.kind == COUNT:
            count = count or found
        else:
            weight_or_volume = weight_or_volume or found
    return weight_or_volume or count


def size_from_fields(quantity: Decimal | None, unit: str) -> Size | None:
    """The chain's own Quantity and UnitQty, e.g. (1.00, "ליטר") or (500, "גרם")."""
    if quantity is None or quantity <= 0:
        return None
    text = _clean(unit).lower().strip(" .")
    for spelling in sorted(_UNITS, key=len, reverse=True):
        if text == spelling.lower().strip(" ."):
            return _size(str(quantity), spelling)
    return None


# ------------------------------------------------------------------------------ fat

_PERCENT = re.compile(rf"(?<![\d.,])({_NUMBER})\s*%")
_FAT_WORD = re.compile(r"שומן|שומנים")
_FAT_FREE = re.compile(r"(?:ללא|נטול|נטולת|אפס)\s+שומן")
_FATTY_FOODS = re.compile(
    r"חלב|גבינ|קוטג|שמנת|יוגורט|לבן|לבנה|מעדן|שוקו|חמאה|קפיר|ריקוטה|מוצרלה|עמק|צהובה|בולגרית"
    r"|פטה|קממבר|פרמזן|טחון|המבורגר|קבב|נקניק"
)
_NOT_FAT_PERCENT = re.compile(r"קקאו|מריר|שוקולד|מיץ|אלכוהול|בירה|יין|סבון|כביסה|ויסקי|וודקה|קפה")


def fat_from_name(name: str) -> Decimal | None:
    text = _clean(name)
    if _FAT_FREE.search(text):
        return Decimal(0)
    fat_foods = _FATTY_FOODS.search(text) and not _NOT_FAT_PERCENT.search(text)
    for match in _PERCENT.finditer(text):
        percent = _number(match[1])
        if not 0 <= percent <= 100:
            continue
        around = text[max(0, match.start() - 10) : match.end() + 10]
        if _FAT_WORD.search(around) or fat_foods:
            return _tidy(percent)
    return None


# ------------------------------------------------------------------------ free of

_NO = r"(?:ללא|נטול|נטולת|חף\s+מ|חסר|לא\s+מכיל)"
_FREE_OF = {
    "lactose": re.compile(rf"{_NO}[\s-]*לקטוז|0%\s*לקטוז|lactose[\s-]*free", re.IGNORECASE),
    "gluten": re.compile(rf"{_NO}[\s-]*גלוטן|gluten[\s-]*free", re.IGNORECASE),
    "sugar": re.compile(rf"(?:{_NO}|אפס)[\s-]*סוכר|(?<!\w)(?:זירו|zero)(?!\w)", re.IGNORECASE),
    "added_sugar": re.compile(
        rf"{_NO}[\s-]*תוספת[\s-]*סוכר|no[\s-]*added[\s-]*sugar", re.IGNORECASE
    ),
}


def free_of_from_name(name: str) -> tuple[str, ...]:
    text = _clean(name)
    return tuple(sorted(label for label, pattern in _FREE_OF.items() if pattern.search(text)))


# ---------------------------------------------------------------------------- brand

# Canonical name -> other spellings seen in names and manufacturer fields.
BRANDS: dict[str, tuple[str, ...]] = {
    "תנובה": (),
    "שטראוס": ("שטראוס מים", "שטראוס מחלבות"),
    "טרה": (),
    "יטבתה": (),
    "גד": ("מחלבות גד",),
    "אסם": (),
    "עלית": (),
    "נסטלה": (),
    "וויסוצקי": ("ויסוצקי",),
    "סוגת": (),
    "תלמה": (),
    "פריגת": (),
    "פרימור": (),
    "הרדוף": (),
    "יד מרדכי": (),
    "טבעול": (),
    "זוגלובק": (),
    "עוף טוב": (),
    "אחוה": ("אחוות",),
    "שמרית": (),
    "מילקה": ("milka",),
    "קוקה קולה": ("קוקה-קולה", "קוקה", "coca cola"),
    "פפסי": ("pepsi",),
    "נביעות": (),
    "מי עדן": (),
    "דנונה": ("danone",),
    "יופלה": (),
    "מולר": ("muller",),
    "אקטיביה": (),
    "קלוגס": ("kelloggs",),
    "לוטוס": ("lotus",),
    "סנו": (),
    "אריאל": ("ariel",),
    "דאב": ("dove",),
    "קרסט": (),
    "ברמן": ("מאפיות ברמן",),
    "גולן": ("יקבי הגולן",),
    "ליפטון": ("lipton",),
    "הלמנס": ("hellmanns",),
    "קנור": ("knorr",),
    "היינץ": ("heinz",),
}


def _bare(text: str) -> str:
    """Letters and digits only, one space between words, for matching names to brands."""
    return " ".join(re.sub(r"[^\w\s]", "", _clean(text).replace("-", " ")).lower().split())


_BRAND_SPELLINGS = sorted(
    (
        (_bare(spelling), brand)
        for brand, aliases in BRANDS.items()
        for spelling in (brand, *aliases)
    ),
    key=lambda pair: -len(pair[0]),
)


def brand_in(text: str) -> str:
    """The brand written first in the text (whole words only), or ''."""
    padded = f" {_bare(text)} "
    best: tuple[int, str] | None = None
    for spelling, brand in _BRAND_SPELLINGS:
        position = padded.find(f" {spelling} ")
        if position >= 0 and (best is None or position < best[0]):
            best = (position, brand)
    return best[1] if best else ""


def brand_of(name: str, manufacturer: str = "") -> str:
    return brand_in(name) or brand_in(manufacturer)


# --------------------------------------------------------------------------- all in one


def attributes_of(
    name: str,
    manufacturer: str = "",
    quantity: Decimal | None = None,
    unit: str = "",
    is_weighted: bool = False,
) -> Attributes:
    if is_weighted:
        size = Size(Decimal(1000), WEIGHT)  # priced per kilo
    else:
        size = size_from_name(name) or size_from_fields(quantity, unit)
    return Attributes(
        fat_percent=fat_from_name(name),
        size=size,
        free_of=free_of_from_name(name),
        brand=brand_of(name, manufacturer),
    )
