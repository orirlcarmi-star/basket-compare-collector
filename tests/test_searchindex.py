import json

import pytest

from collector.searchindex import build_index, file_name, search, stems, write_index

PRODUCTS = {
    "1": ("חלב בקרטון 3% שומן 1 ל", "dairy"),
    "2": ("גב.צפתית במים 5% במשקל", "dairy"),
    "3": ("גבינת עמק פרוסות 400 גרם", "dairy"),
    "4": ("קוטג' תנובה 5% 250 גרם", "dairy"),
    "5": ("גבינה לבנה 9% 500 גרם", "dairy"),
    "6": ("חלבון מיוחד", None),
    "7": ("יין אדום", "drinks"),
    "8": ("קרטון ביצים גדול", None),
    "9": ("וחלב מועשר לתינוק", "dairy"),
    "10": ("חלב מהדרין שקית", "dairy"),
    "11": ("בקר טחון לבישול", "meat"),
    "12": ("מי קר ומתוק", "drinks"),
    "13": ("בננה אורגנית", "produce"),
}


@pytest.fixture
def folder(tmp_path):
    write_index(build_index(PRODUCTS), tmp_path / "s")
    return tmp_path / "s"


def test_file_name_is_the_two_letters_as_hex():
    assert file_name("חלב") == "05d705dc.json"
    assert file_name("קוטג") == file_name("קוטגג")  # only the first two letters count
    assert file_name("evian") == "00650076.json"


def test_a_file_holds_the_products_with_name_and_category_and_the_words_pointing_to_them(folder):
    content = json.loads((folder / file_name("חלב")).read_text(encoding="utf-8"))
    names = {code: (name, rest) for code, name, *rest in content["p"]}
    assert names["1"] == ("חלב בקרטון 3% שומן 1 ל", ["dairy"])  # the short name, ready to show
    assert names["6"] == ("חלבון מיוחד", [])  # no category: the field is left out
    by_word = {w: [content["p"][i][0] for i in places] for w, places in content["w"].items()}
    assert by_word["חלב"] == ["1", "10", "9"]  # incl. "וחלב" (9) through its stem
    assert by_word["חלבונ"] == ["6"]  # normal form: plain final letters


def test_search_shows_results_from_one_file_per_query_word(folder):
    found = search(folder, "גבינה")
    assert set(found) == {"2", "3", "5"}  # incl. "גב." and "גבינת"
    assert found["3"] == ("גבינת עמק פרוסות 400 גרם", "dairy")
    assert search(folder, "קוטג'") == {"4": ("קוטג' תנובה 5% 250 גרם", "dairy")}


def test_search_by_the_start_of_a_word(folder):
    assert set(search(folder, "חלב")) == {"1", "6", "9", "10"}  # חלב and חלבון both start with it
    assert set(search(folder, "גבינ")) == {"2", "3", "5"}


def test_all_words_of_the_query_must_match(folder):
    assert set(search(folder, "גבינה לבנה")) == {"5"}
    assert search(folder, "גבינה חלב") == {}
    assert set(search(folder, "גב. עמק")) == {"3"}
    assert set(search(folder, "גבינת עמק")) == {"3"}


def test_nothing_to_search_for(folder):
    assert search(folder, "") is None
    assert search(folder, "ח 3 של") is None  # one letter, a number and a stop word
    assert search(folder, "מילה שלא קיימת") == {}


# --- prefix letters: found without the prefix, never by cutting a real word ---


@pytest.mark.parametrize(
    ("query", "found"),
    [
        ("קרטון", {"1", "8"}),  # בקרטון has the stem קרטון, which the catalog uses on its own
        ("חלב", {"1", "9", "10", "6"}),  # וחלב
        ("תינוק", {"9"}),  # לתינוק: a stem the catalog never uses alone is NOT cut...
        ("הדרין", {"10"}),  # ...except the listed ones (מהדרין)
    ],
)
def test_words_with_a_prefix_letter_are_also_found_without_it(folder, query, found):
    if query == "תינוק":
        found = set()  # "תינוק" stands alone nowhere in this catalog, so לתינוק is not cut
    assert set(search(folder, query)) == found


def test_a_prefix_is_cut_only_when_the_rest_is_a_word_the_catalog_uses():
    vocabulary = {"קרטונ", "חלב", "קר"}
    assert stems("בקרטונ", vocabulary) == ["קרטונ"]
    assert stems("וחלב", vocabulary) == ["חלב"]
    assert stems("בקר", vocabulary) == []  # beef is not "cold": the rest is too short
    assert stems("בננה", vocabulary) == []  # "ננה" is not a word of the catalog
    assert stems("מהדרינ", vocabulary) == ["הדרינ"]  # listed stem
    assert stems("חלב", vocabulary) == []  # not a prefix letter
    assert stems("לבנה", vocabulary) == []  # "בנה" is not a word of the catalog


def test_real_words_that_begin_with_a_prefix_letter_stay_whole(folder):
    # beef (11), and בקרטון (1) because it starts with the same letters; not "קר" (cold, 12)
    assert set(search(folder, "בקר")) == {"1", "11"}
    cold = set(search(folder, "קר"))
    assert "12" in cold and "11" not in cold  # beef is not found by "קר"
    assert set(search(folder, "בננה")) == {"13"} and search(folder, "ננה") == {}


def test_a_product_with_no_words_adds_nothing():
    assert build_index({"9": ("3% 1 ל", None)}) == {}


def test_the_index_is_deterministic():
    assert json.dumps(build_index(PRODUCTS)) == json.dumps(
        build_index(dict(reversed(PRODUCTS.items())))
    )
