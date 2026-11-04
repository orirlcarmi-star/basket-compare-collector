import pytest

from collector.categories import CATEGORIES, categorize, category_name, coverage

# Names in the style the chains write them. The first group is real Shufersal names reported
# from the full file; the rest are written the same way (abbreviations, glued numbers).
NAMES = [
    # --- real names ---
    ("יוג.יווני6.5% חלבון600גד", "dairy"),
    ("שוק.חלב 37% מקס ברנר90ג", "snacks"),
    ("100% קבב 440ג טיבון ויל", "meat"),
    ("גב.עיזים5% למריחה 250 גר", "dairy"),
    ("גב.צפתית במים 5% במשקל", "dairy"),
    ("גב.סקי 5% 125 גרם", "dairy"),
    ("גאודה גוסט 30%במשקל", "dairy"),
    ("גבי.נפולאון24%+זיתים225ג", "dairy"),
    ("קצוטה צאן30% כ150ג א", "dairy"),
    ("שוקולד מריר60%", "snacks"),
    ("מיץ רימונים100%", "drinks"),
    ("רסק עגבניות28%פרי", "pantry"),
    ("חלב בקרטון 3% שומן 1 ל", "dairy"),
    ("חלב 3% מהדרין שקית 1 ל", "dairy"),
    # --- dairy and eggs ---
    ("קוטג' תנובה 5% 250 גרם", "dairy"),
    ("ביצים L 12 יחידות", "dairy"),
    ('שמנת מתוקה 38% 250 מ"ל', "dairy"),
    ("חמאה 200 גרם", "dairy"),
    ("לבן 1.5% 500 מל", "dairy"),
    ("שוקו בשקית 1 ליטר", "dairy"),
    ("גבינה צהובה עמק 28% פרוסות", "dairy"),
    ("מילקי שוקולד 4 יח'", "dairy"),
    # --- meat, poultry, fish ---
    ("חזה עוף טרי", "meat"),
    ("שניצל תירס 800 גרם", "meat"),
    ("נקניקיות הודו 400 גרם", "meat"),
    ("בשר בקר טחון טרי 20% שומן", "meat"),
    ("שוק עוף במשקל", "meat"),
    ("פילה סלמון נורבגי", "fish"),
    ("דג אמנון שלם", "fish"),
    ("טונה בשמן צמחי 160 גרם", "pantry"),
    # --- produce ---
    ("עגבניות שרי 500 גרם", "produce"),
    ("מלפפון בייבי במשקל", "produce"),
    ("תפוחי אדמה לבנים", "produce"),
    ("בננות", "produce"),
    ("לימון מובחר", "produce"),
    ("עלי חסה אורגני", "produce"),
    # --- bread and pastries ---
    ("לחם אחיד פרוס", "bakery"),
    ("פיתות 10 יחידות", "bakery"),
    ("עוגת גבינה", "bakery"),
    ("חלה לשבת", "bakery"),
    ("בצק עלים מגולגל", "bakery"),
    # --- pantry ---
    ('אורז בסמטי 1 ק"ג', "pantry"),
    ("פסטה ספגטי 500 גרם", "pantry"),
    ("שמן זית כתית מעולה 750 מל", "pantry"),
    ("קמח לבן 1 קג", "pantry"),
    ('סוכר לבן 1 ק"ג', "pantry"),
    ("קורנפלקס 750 גרם", "pantry"),
    ("תירס שימורים 3 יחידות", "pantry"),
    ("חומוס גרגרים מוכן 400 גרם", "pantry"),
    ("טחינה גולמית 500 גרם", "pantry"),
    ("חמאת בוטנים 340 גרם", "pantry"),
    ("פלפל שחור טחון 50 גרם", "pantry"),
    # --- sweets and snacks ---
    ("במבה אסם 80 גרם", "snacks"),
    ("חטיף חלבון בטעם גבינה", "snacks"),
    ("עוגיות שוקולד צ'יפס 200 גרם", "snacks"),
    ("סוכריות גומי דובונים", "snacks"),
    ("צ'יפס פיצה 50 גרם", "snacks"),
    ("עלית שוקולד חלב 100 גרם", "snacks"),
    # --- drinks ---
    ("קוקה קולה זירו 1.5 ליטר", "drinks"),
    ("מים מינרליים 6*1.5 ליטר", "drinks"),
    ("בירה גולדסטאר 6*330 מל", "drinks"),
    ("קפה נמס עלית 200 גרם", "drinks"),
    ("תה ירוק 25 שקיות", "drinks"),
    ("יין אדום קברנה 750 מל", "drinks"),
    ("סודה 1.5 ליטר", "drinks"),
    # --- frozen: wins wherever the word stands ---
    ("גלידה וניל 1 ליטר", "frozen"),
    ("עוף קפוא שלם", "frozen"),
    ("ירקות מוקפאים לאפייה", "frozen"),
    ("פיצה משפחתית קפואה", "frozen"),
    ("ארטיק קרח תות", "frozen"),
    # --- cleaning, hygiene, home, baby ---
    ('אבקת כביסה אריאל 3 ק"ג', "cleaning"),
    ("סבון כלים פיירי 750 מל", "cleaning"),
    ("מרכך כביסה סנו 2 ליטר", "cleaning"),
    ("אקונומיקה 4 ליטר", "cleaning"),
    ("שמפו הד אנד שולדרס 400 מל", "hygiene"),
    ("מרכך שיער דאב 250 מל", "hygiene"),
    ("משחת שיניים קולגייט 100 מל", "hygiene"),
    ("דאודורנט ספריי 150 מל", "hygiene"),
    ("סבון גוף נוזלי 500 מל", "hygiene"),
    ("נייר טואלט 24 גלילים", "home"),
    ("שקיות אשפה 50 יח'", "home"),
    ("סוללות AA 8 יחידות", "home"),
    ("נייר אפייה 20 מטר", "home"),
    ("חיתולים פמפרס מידה 4", "baby"),
    ("מטרנה שלב 2 400 גרם", "baby"),
    ("דייסה לתינוקות", "baby"),
    ("מגבונים לחים לתינוק", "baby"),
    # --- real Shufersal names that were filed wrongly or not at all (checked on the full file) ---
    ("פיזארו מוסקטו לבן 750מל", "drinks"),  # wine: was dairy because of "לבן"
    ("פאוץ לה קט סלמון85גר", "pets"),  # cat food: was fish because of "סלמון"
    ("לבבות קיסר יחידה", "produce"),  # romaine hearts: was meat
    ("קימל טחון מחיר לפי משקל", "pantry"),  # a spice: was meat because of "טחון"
    ('גרניה ספריי פרש 150מ"ל', "hygiene"),
    ("דאו רול BWC אלוורה 50 מל", "hygiene"),
    ("מסכה לשיער דרים לונג300מ", "hygiene"),
    ('דרמו רויטליפט לחות50 מ"ל', "hygiene"),
    # --- pets, wine and white things that are not dairy ---
    ('אוכל לכלבים בקר 2 ק"ג', "pets"),
    ("חול לחתולים 10 ליטר", "pets"),
    ("יין לבן שרדונה 750 מל", "drinks"),
    ("שוקולד לבן 100 גרם", "snacks"),
    ('אורז לבן 1 ק"ג', "pantry"),
    ("לבן 1.5% 500 מל", "dairy"),
    ("קיט קט 4 אצבעות", "snacks"),  # "קט" is not a pet word on its own
    ("שמן שמן זית", "pantry"),
    ("בשר טחון טרי", "meat"),
    ("קפה טחון 200 גרם", "drinks"),
    ("עוף טחון", "meat"),
    ("חלב קוקוס 400 מל", "pantry"),
    ("מי קוקוס 330 מל", "drinks"),
    # --- real Shufersal names that were still wrong or unclassified (6 stores, ~9,000 products) ---
    ("ספרינג מנגו בננה1.5 ליטר", "drinks"),  # fruit + a volume: a drink, not produce
    ("פריגת קליר בטעם אננס1.5ל", "drinks"),
    ("שוקו.חלב אוורירי100ג פפה", "snacks"),  # milk chocolate in short: was dairy
    ("שו.חלב לוז לגרנד150לינדט", "snacks"),
    ("ש.חלב עם פיסטוק קלוי100ג", "snacks"),
    ("סקיטלס בטעם פירות 152 גר", "snacks"),  # "flavoured with fruit" is not fruit
    ("אבקת הלבנה רן 350ג", "cleaning"),  # laundry whitener: was pantry
    ("קלינקס", "hygiene"),
    ("ניוטרוגינה", "hygiene"),
    ("פרינגלס", "snacks"),
    ("אורביט", "snacks"),
    ("אוכמניות", "produce"),
    ("שאבלי", "drinks"),
    ("חמאת בוטנים", "pantry"),
    # --- the same rules on neighbours: nothing that worked must break ---
    ("תפוח עץ אדום", "produce"),
    ('לימון 1 ק"ג', "produce"),  # a weight, not a volume: still fruit
    ("מיץ תפוזים 1 ליטר", "drinks"),
    ("שוקו בשקית 1 ליטר", "dairy"),  # a bare "שוקו" is the chocolate milk drink
    ("שוקולד חלב 100 גרם", "snacks"),
    ("יוגורט בטעם תות 200 גרם", "dairy"),  # flavoured yoghurt is yoghurt
    ("חטיף בטעם גבינה", "snacks"),
    ("גלידה בטעם וניל 1 ליטר", "frozen"),
    ("תה בטעם לימון 25 שקיות", "drinks"),
]

# Make-up, nail and lip products are kept out of every rule: whatever else the name says, it is
# "not classified" rather than something wrong ("שמן" is cooking oil, "מסיר" is a cleaner).
NOT_CLASSIFIED = [
    "שמן שפתיים למראה עסיסי11",
    "מסיר קוטיקולה נייל סטורי",
    "עפרון פלמפינג קוקוס",
    "מסקרה שחורה 10 מל",
    "טמפונים 16 יחידות",  # left unclassified, like the others in this list
    "או בה נורמל",
    "קרפרי",
]


@pytest.mark.parametrize(("name", "category"), NAMES)
def test_category_of_a_chain_style_name(name, category):
    assert categorize(name) == category


def test_unknown_words_get_no_category_not_a_wrong_one():
    for name in ["", "   ", "מארז מתנה", "מוצר 12345", "XYZ"]:
        assert categorize(name) is None


@pytest.mark.parametrize("name", NOT_CLASSIFIED)
def test_names_kept_out_of_the_rules_stay_unclassified(name):
    assert categorize(name) is None


def test_fourteen_categories():
    assert len(CATEGORIES) == 14
    assert len({c.id for c in CATEGORIES}) == 14
    assert category_name("pets") == "חיות מחמד"
    assert {c.name for c in CATEGORIES} >= {"חלב וביצים", "בשר ועוף", "דגים", "ירקות ופירות"}
    assert category_name("dairy") == "חלב וביצים"
    assert category_name(None) == "לא מסווג"


def test_every_category_is_used_by_the_examples():
    assert {c for _, c in NAMES} == {c.id for c in CATEGORIES}


def test_coverage_counts_and_lists_what_was_missed():
    counts, missed = coverage(["חלב 3%", "עוף טרי", "מארז מתנה", "חלב עיזים"])
    assert counts["dairy"] == 2 and counts["meat"] == 1 and counts["none"] == 1
    assert missed == ["מארז מתנה"]
