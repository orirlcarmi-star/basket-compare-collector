import pytest

from collector.textnorm import normalize, words

# What the website's copy must produce for the same input.
REFERENCE = [
    ("קוטג' תנובה 5%", "קוטג תנובה 5"),
    ("גב.צפתית במים 5% במשקל", "גבינה צפתית במימ 5 במשקל"),
    ("יוג.יווני6.5% חלבון600גד", "יוגורט יווני 6 5 חלבונ 600 גד"),
    ("שוק.חלב 37% מקס ברנר90ג", "שוקולד חלב 37 מקס ברנר 90 ג"),
    ('ק"ג עגבניות שרי', "קג עגבניות שרי"),
    ("חָלָב מִן הַחוּץ", "חלב מנ החוצ"),  # vowel points removed, final letters made plain
    ("מים-מינרליים Evian 1.5L", "מימ מינרליימ evian 1 5 l"),
    ("חלב שוק עוף", "חלב שוק עופ"),
    ("שוקו.חלב אוורירי100ג פפה", "שוקולד חלב אוורירי 100 ג פפה"),
    ("שו.חלב לוז לגרנד150לינדט", "שוקולד חלב לוז לגרנד 150 לינדט"),
    ("ש.חלב עם פיסטוק קלוי100ג", "שוקולד חלב עמ פיסטוק קלוי 100 ג"),
    ("שו.מריר 70% 100 גרם", "שוקולד מריר 70 100 גרמ"),
    ("שוקו בשקית", "שוקו בשקית"),  # no dot: the chocolate milk drink, unchanged
    ("ש.זית כתית", "ש זית כתית"),  # a dot after one letter is not chocolate unless a kind follows
]


@pytest.mark.parametrize(("text", "normal"), REFERENCE)
def test_reference_vectors(text, normal):
    assert normalize(text) == normal


def test_normalising_twice_changes_nothing():
    for text, _ in REFERENCE:
        assert normalize(normalize(text)) == normalize(text)


def test_a_word_is_the_same_at_the_end_of_a_phrase_and_in_the_middle():
    assert normalize("לחם עוף") == "לחמ עופ"
    assert normalize("עוף לחם") == "עופ לחמ"
    assert words("עוף לחם") == ["עופ", "לחמ"]


def test_search_words_drop_numbers_stop_words_and_single_letters():
    assert words("חלב של עם 3% 1 ל 250 גרם") == ["חלב", "גרמ"]
    assert words("גב.סקי 5% 125 גרם") == ["גבינה", "סקי", "גרמ"]
    assert words("") == []


def test_the_of_form_of_a_few_nouns_is_searched_as_the_plain_noun():
    assert words("גבינת עמק") == ["גבינה", "עמק"]
    assert words("עוגת גבינה") == ["עוגה", "גבינה"]
    assert normalize("גבינת עמק") == "גבינת עמק"  # only the search words change
