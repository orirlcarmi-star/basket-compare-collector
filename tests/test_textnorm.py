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
    ("חלב שוק עוף", "חלב שוק עופ"),  # a bare "שוק" is a thigh, not chocolate
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
