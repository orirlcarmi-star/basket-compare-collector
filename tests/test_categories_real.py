"""Category rules added from the unclassified list of the first real package (2026-11-04).

Every name below is a real product name, as the chains publish it (Rami Levy and Osher Ad cut
their names to 20 characters). Where a word has two meanings the case that must NOT change is
in the list too.
"""

import pytest

from collector.categories import categorize

CASES = [
    # Sunfrost sells frozen vegetables: the vegetable word no longer wins
    ("תרד מדליונים סנפרוסט", "frozen"),
    ("כרובית סנפרוסט 800 ג", "frozen"),
    ("פסטה וירקות סנפרוסט", "frozen"),
    ("אפונה עדינה סנפרוסט", "frozen"),
    ("גרעיני תירס סנפרוסט", "frozen"),
    ("קרחוני אבטיח 6 יח", "frozen"),
    # housewares: the first word says what it is, whatever fruit or drink follows
    ("כוס יין מהודרת שקוף", "home"),
    ("כוס קפה חרסינה", "home"),
    ('צלחת מלמין 8" דרדסים', "home"),
    ('קערת סלט עגולה 27 ס"', "home"),
    ("מגש אורון שחור-זהב 3", "home"),
    ("כף הגשה נירוסטה איכו", "home"),
    ("שטיח פירות אדום צהוב", "home"),
    ("סכין שף סנטוקו", "home"),
    ("קנקן לסינון מים 2.4ל", "home"),
    ("מאוורר עמוד 20 אינץ", "home"),
    ("מזגן נייד FUJIAIR", "home"),
    ("שמיכת חורף מפנקת גלי", "home"),
    ("מגבת פנים איכותית (9", "home"),
    ('סדין זוגי 200*160 ס"', "home"),
    ("קומקום חשמלי נירוסטה", "home"),
    ("מתקן כביסה טלסקופי", "home"),
    ("ארגז פלסטיק היינקן 5", "home"),
    ("מייבש שיער 5600 - זק", "home"),
    # ... but the same words inside a food or drink are not housewares
    ("כוס מיץ גזר קטן", "drinks"),
    ("כוס הפתעה שוקו וניל", "dairy"),
    ("תנובה חלב כוס 3%", "dairy"),
    ("בירה בקבוק גולדסטאר", "drinks"),
    ("שיפודי פרגית", "meat"),
    ("נתח סלמון פרימיום", "fish"),
    ("סכין גילוח חד פעמי ג", "hygiene"),
    ("דלי מגבונים פרימיום", "hygiene"),
    ("תחתית פאי אפויה קמח", "pantry"),
    ('צנצנת דבש 480 מ"ל -', "pantry"),
    # food words that stood first and found no rule
    ("זית סורי מבוקע 560 ג", "pantry"),
    ("זית ירוק גדול בני דר", "pantry"),
    ("שקד ספרדי קלוי במשקל", "pantry"),
    ("אגוז מלך גרוס 100 ג", "pantry"),
    ("שומשום מלא 150 גר", "pantry"),
    ("צימוק חום תפזורת", "pantry"),
    ("חמוציות חצויות מסוכר", "pantry"),
    ("סחוג ירוק דיפ דיפ 15", "pantry"),
    ("עלי דפנה מיה 10 גרם", "pantry"),
    ("מאסטר שף איטריות דקי", "pantry"),
    ("לבבות דקל שלמים 400", "pantry"),
    ("חזרת ללא סוכר ביסבס", "pantry"),
    ("קונפיטורה תות 778 34", "pantry"),
    ("בוטן אמריקאי 350 גרם", "snacks"),
    ("גרעין אבטיח קלוי תפז", "snacks"),
    ("גרעיני דלעת קלופים א", "snacks"),
    ("חלבה וניל 500 גרם", "snacks"),
    ("לקקן תות12 גרם 50 יח", "snacks"),
    ("טורטיה ציפס בטעם בר", "snacks"),
    ("ביצי שוקולד עם הפתעה", "snacks"),
    ("ביצי חופש 12יח L", "dairy"),
    ("ביצי דג בורי אדמחוט", "fish"),
    ("צ'דר אנגלי כתום", "dairy"),
    ("פרמזנו 200 גרם", "dairy"),
    ('תפו"א לבן ארוז', "produce"),
    ("עלי רוקולה שטופים 25", "produce"),
    ("אתרוג", "produce"),
    ("טורטיה מקמח תירס ללא", "bakery"),
    ("לחמניה אצבע קטן 75 ג", "bakery"),
    ('מלוואח חמסי 1 ק"ג', "bakery"),
    ("פילה מקרל נורווגי מע", "fish"),
    ("פילה בינתן 400 גר", "fish"),
    ("עצמות ברך לנדא", "meat"),
    ("קישקע 500ג קהילות", "meat"),
    ("שריר צרכני(בננה) בקר", "meat"),
    ("חליטת קמומיל דבש פומ", "drinks"),
    ("קפסולות קפה 07 יוחננ", "drinks"),
    ("קפסולות סטארבקס רוסט", "drinks"),
    ("לנור כדוריות 210 גרם", "cleaning"),
    ("כביסכל 2 ליטר רוז  B", "cleaning"),
    ("קפסולות ג'ל אריאל או", "cleaning"),
    ("אנטי קאלק נוזל לניקו", "cleaning"),
]


@pytest.mark.parametrize(("name", "category"), CASES)
def test_real_names(name, category):
    assert categorize(name) == category


@pytest.mark.parametrize(
    "name",
    [
        "צבע לשיער פאלטה בלונ",  # hair colour: never a sweet because of "שוקולד" in its shade
        "צבע לשיער חום שוקולד",
        "קולסטון קיט 4/0 חום",
        "בלדי",  # one word, meaning unknown
        "פול גדול 500 ג' רמי",  # could be fresh or canned
        "מארז WOW Z קרניבל בט",
        "סט מצעים מלא יחיד בז",
        'בקבוק טריטן 500מ"ל',  # a thermos, but "בקבוק" also starts beer and wine names
    ],
)
def test_doubtful_names_stay_unclassified(name):
    assert categorize(name) is None
