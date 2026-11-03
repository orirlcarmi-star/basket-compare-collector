import json

import pytest

from collector.searchindex import build_index, file_name, search, write_index

NAMES = {
    "1": "חלב בקרטון 3% שומן 1 ל",
    "2": "גב.צפתית במים 5% במשקל",
    "3": "גבינת עמק פרוסות 400 גרם",
    "4": "קוטג' תנובה 5% 250 גרם",
    "5": "גבינה לבנה 9% 500 גרם",
    "6": "חלבון מיוחד",
    "7": "יין אדום",
}


@pytest.fixture
def folder(tmp_path):
    write_index(build_index(NAMES), tmp_path / "s")
    return tmp_path / "s"


def test_file_name_is_the_two_letters_as_hex():
    assert file_name("חלב") == "05d705dc.json"
    assert file_name("קוטג") == file_name("קוטגג")  # only the first two letters count
    assert file_name("evian") == "00650076.json"


def test_words_with_the_same_two_letters_share_a_file(folder):
    content = json.loads((folder / file_name("חלב")).read_text(encoding="utf-8"))
    assert content == {"חלב": ["1"], "חלבונ": ["6"]}  # normal form: plain final letters
    assert sorted(f.name for f in folder.iterdir()) == sorted(set(file_name(w) for w in
        ["חלב", "גבינה", "צפתית", "במימ", "במשקל", "עמק", "פרוסות", "קוטג", "תנובה",
         "גרמ", "לבנה", "שומנ", "בקרטונ", "מיוחד", "יינ", "אדומ"]))  # fmt: skip


def test_search_by_the_start_of_a_word(folder):
    assert search(folder, "חלב") == {"1", "6"}  # חלב and חלבון both start with it
    assert search(folder, "גבינ") == {"2", "3", "5"}  # גבינה (also from "גב."), גבינת
    assert search(folder, "קוטג'") == {"4"}  # the apostrophe does not matter


def test_all_words_of_the_query_must_match(folder):
    assert search(folder, "גבינה לבנה") == {"5"}
    assert search(folder, "גבינה חלב") == set()
    assert search(folder, "גב. עמק") == {"3"}  # the abbreviation is spelled out in the query too
    assert search(folder, "גבינת עמק") == {"3"}  # and "גבינת" is the same word as "גבינה"


def test_nothing_to_search_for(folder):
    assert search(folder, "") is None
    assert search(folder, "ח 3 של") is None  # one letter, a number and a stop word
    assert search(folder, "מילה שלא קיימת") == set()


def test_a_product_with_no_words_adds_nothing():
    assert build_index({"9": "3% 1 ל"}) == {}
