from decimal import Decimal

import pytest

from collector.attributes import (
    COUNT,
    VOLUME,
    WEIGHT,
    Size,
    attributes_of,
    brand_of,
    fat_from_name,
    free_of_from_name,
    size_from_fields,
    size_from_name,
)

D = Decimal


# Names written the way the chains write them (the first two are from a real Shufersal file).
@pytest.mark.parametrize(
    ("name", "fat"),
    [
        ("חלב בקרטון 3% שומן 1 ל", D(3)),
        ("חלב 3% מהדרין שקית 1 ל", D(3)),
        ("קוטג' תנובה 5% 250 גרם", D(5)),
        ("גבינה לבנה 9% 500 גרם", D(9)),
        ('שמנת מתוקה 38% 250 מ"ל', D(38)),
        ("יוגורט טבעי 1.5% שומן 200 גרם", D("1.5")),
        ("יוגורט 0% 150 גרם", D(0)),
        ("חלב דל לקטוז 1% 1 ליטר", D(1)),
        ("גבינה צהובה עמק 28% פרוסות 400 גרם", D(28)),
        ("בשר בקר טחון טרי 20% שומן", D(20)),
        ("גבינה לבנה ללא שומן 250 גרם", D(0)),
        ("שמנת לבישול 15%", D(15)),
        ("חלב 10% שומן", D(10)),  # 10, not 1E+1
        # Real Shufersal names (checked on the full file): cheeses, often abbreviated.
        ("גב.עיזים5% למריחה 250 גר", D(5)),
        ("גב.צפתית במים 5% במשקל", D(5)),
        ("גב.סקי 5% 125 גרם", D(5)),
        ("גאודה גוסט 30%במשקל", D(30)),
        ("גבי.נפולאון24%+זיתים225ג", D(24)),
        ("קצוטה צאן30% כ150ג א", D(30)),
        ("גאוד.בקר כמהין150גוש32%", D(32)),
        ("יוג.יווני 10% 150 גרם", D(10)),
    ],
)
def test_fat_percent(name, fat):
    assert fat_from_name(name) == fat
    assert str(fat_from_name(name)) == str(fat)


@pytest.mark.parametrize(
    "name",
    [
        "שוקולד מריר 70% קקאו 100 גרם",
        "שוקולד חלב 30% קקאו",
        "מיץ תפוזים 100% טבעי 1 ליטר",
        "קפה טחון 100% ערביקה 200 גרם",
        "יין אדום 13% אלכוהול 750 מל",
        "חלב שקדים בטעם וניל 1 ליטר",  # no percentage
        "גבינה עם שומן מופחת",  # "reduced fat", no number
        # Real Shufersal names: a percentage that is not fat, found on the full file.
        "יוג.יווני6.5% חלבון600גד",  # protein
        "שוק.חלב 37% מקס ברנר90ג",  # "שוק." is שוקולד: 37% cocoa
        "100% קבב 440ג טיבון ויל",  # 100% is purity
        "שוקולד מריר60%",
        "מיץ רימונים100%",
        "רסק עגבניות28%פרי",  # fruit content
        "חלבון 20% פרוטאין",  # protein written before the number
        "גבינה 20% חלבון",  # protein, even on a cheese
    ],
)
def test_percentages_that_are_not_fat(name):
    assert fat_from_name(name) is None


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("חלב בקרטון 3% שומן 1 ל", Size(D(1000), VOLUME)),
        ("חלב 3% מהדרין שקית 1 ליטר", Size(D(1000), VOLUME)),
        ("מיץ תפוזים 1.5 ליטר", Size(D(1500), VOLUME)),
        ("מיץ ענבים 1,5 ל'", Size(D(1500), VOLUME)),
        ('שמן זית כתית 750 מ"ל', Size(D(750), VOLUME)),
        ("שמן קנולה 750 מל", Size(D(750), VOLUME)),
        ("שמן זית 750 מ״ל", Size(D(750), VOLUME)),  # typographic quote
        ("קולה זירו 330 ML", Size(D(330), VOLUME)),
        ('אורז בסמטי 1 ק"ג', Size(D(1000), WEIGHT)),
        ("קמח לבן 1 קג", Size(D(1000), WEIGHT)),
        ("קמח תופח 0.5 ק״ג", Size(D(500), WEIGHT)),
        ("פסטה ספגטי 500 גרם", Size(D(500), WEIGHT)),
        ("גבינת עמק פרוסות 400 ג'", Size(D(400), WEIGHT)),
        ("טונה בשמן 160 גר", Size(D(160), WEIGHT)),
        ("מים מינרליים 6*1.5 ליטר", Size(D(9000), VOLUME)),
        ("קולה 6X330 מל", Size(D(1980), VOLUME)),
        ('בירה 12 * 330 מ"ל', Size(D(3960), VOLUME)),
        ("ביצים L 12 יחידות", Size(D(12), COUNT)),
        ("שקיות אשפה 30 יח'", Size(D(30), COUNT)),
        ("קפה נמס 200 גרם 2 יח'", Size(D(200), WEIGHT)),  # weight or volume wins over a count
    ],
)
def test_size_from_name_is_normalised(name, size):
    found = size_from_name(name)
    assert found == size
    assert str(found.amount) == str(size.amount)


@pytest.mark.parametrize(
    "name",
    ["חלב בקר", "לחם אחיד פרוס", "3% שומן", "עוגת שוקולד לבן", "משקה 1 לימון", "סבון 2 בלי ריח"],
)
def test_no_size_when_the_name_gives_none(name):
    assert size_from_name(name) is None


def test_size_from_the_chains_own_fields():
    assert size_from_fields(D("1.00"), "ליטר") == Size(D(1000), VOLUME)
    assert size_from_fields(D("500"), "גרם") == Size(D(500), WEIGHT)
    assert size_from_fields(D("1"), 'ק"ג') == Size(D(1000), WEIGHT)
    assert size_from_fields(D("6"), "יחידות") == Size(D(6), COUNT)
    assert size_from_fields(None, "ליטר") is None
    assert size_from_fields(D("0"), "ליטר") is None
    assert size_from_fields(D("1"), "מטר") is None  # a unit we do not know


def test_the_name_wins_over_the_fields_and_fields_fill_the_gap():
    # a 750 ml bottle published as "1 unit"
    bottle = attributes_of("שמן זית 750 מל", quantity=D("1.00"), unit="יחידה")
    assert bottle.size == Size(D(750), VOLUME)
    no_size = attributes_of("חלב טרי", quantity=D("1.00"), unit="ליטר")
    assert no_size.size == Size(D(1000), VOLUME)


def test_weighted_items_are_priced_per_kilo():
    tomato = attributes_of("עגבניה שרי", is_weighted=True, quantity=D("1"), unit="יחידה")
    assert tomato.size == Size(D(1000), WEIGHT)


@pytest.mark.parametrize(
    ("name", "free"),
    [
        ("חלב ללא לקטוז 3% 1 ליטר", ("lactose",)),
        ("גבינה לבנה נטולת לקטוז", ("lactose",)),
        ("פסטה ללא גלוטן 500 גרם", ("gluten",)),
        ("לחם נטול גלוטן פרוס", ("gluten",)),
        ("שוקולד מריר ללא סוכר 100 גרם", ("sugar",)),
        ("קוקה קולה זירו 1.5 ליטר", ("sugar",)),
        ("מיץ תפוזים ללא תוספת סוכר 1 ליטר", ("added_sugar",)),
        ("עוגיות ללא גלוטן וללא סוכר", ("gluten", "sugar")),
        ("חלב דל לקטוז 1 ליטר", ()),  # low in lactose is not lactose free
        ("חלב 3% תנובה", ()),
    ],
)
def test_free_of(name, free):
    assert free_of_from_name(name) == free


@pytest.mark.parametrize(
    ("name", "maker", "brand"),
    [
        ("קוטג' תנובה 5% 250 גרם", "", "תנובה"),
        ("חלב בקרטון 3% שומן 1 ל", 'תנובה מרכז שיתופי לשיווק תוצרת חקלאית בע"מ', "תנובה"),
        ("יוגורט טבעי 3% 200 גרם", 'שטראוס מחלבות בע"מ', "שטראוס"),
        ("שוקולד חלב ויסוצקי 100 גרם", "", "וויסוצקי"),
        ("קוקה-קולה זירו 1.5 ליטר", "", "קוקה קולה"),
        ("חלב 3% 1 ליטר", "", ""),
        ("קמח תנובתי", "", ""),  # only whole words count
    ],
)
def test_brand(name, maker, brand):
    assert brand_of(name, maker) == brand


def test_everything_together():
    found = attributes_of("חלב דל לקטוז 1% תנובה 1 ליטר", "---", quantity=D("1.00"), unit="ליטר")
    assert found.fat_percent == D(1)
    assert found.size == Size(D(1000), VOLUME)
    assert found.free_of == ()
    assert found.brand == "תנובה"
