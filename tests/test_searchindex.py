import json

import pytest

from collector.searchindex import (
    build_index,
    facts_of,
    file_name,
    search,
    search_facts,
    stems,
    write_index,
)

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


# --- facts for the narrowing buttons: an addition in the fourth place, nothing else moves ---


def records(index, word):
    return {e[0]: e for e in index[file_name(word)]["p"]}


def test_search_facts_are_the_product_files_own_values_and_only_those_that_exist():
    milk = {"a": {"f": "3", "b": "תנובה"}, "z": ["1", "l"], "w": False}
    assert search_facts(milk) == {"f": "3", "z": ["1", "l"]}  # no brand, no "free of", no w: false
    assert search_facts({"w": True}) == {"w": True}
    assert search_facts({"a": {"b": "תנובה", "d": ["lactose"]}}) == {}  # not asked for: left out
    assert search_facts({"a": {}, "z": [], "w": False}) == {} and search_facts({}) == {}


def test_a_record_with_facts_has_them_in_the_fourth_place_after_name_and_category():
    index = build_index({"1": ("חלב 3% 1 ליטר", "dairy", {"f": "3", "z": ["1", "l"]})})
    record = records(index, "חלב")["1"]
    assert record == ["1", "חלב 3% 1 ליטר", "dairy", {"f": "3", "z": ["1", "l"]}]
    assert facts_of(record) == {"f": "3", "z": ["1", "l"]}


def test_without_a_category_the_category_place_is_the_empty_string_so_the_facts_stay_fourth():
    index = build_index({"1": ("עגבניות", None, {"w": True})})
    assert records(index, "עגבניות")["1"] == ["1", "עגבניות", "", {"w": True}]


def test_a_product_without_facts_is_written_exactly_as_before():
    index = build_index(
        {"1": ("חלב", "dairy", {}), "2": ("חלב שקדים", None, {}), "3": ("חלב", None)}
    )
    found = records(index, "חלב")
    assert found["1"] == ["1", "חלב", "dairy"]
    assert found["2"] == ["2", "חלב שקדים"] and found["3"] == ["3", "חלב"]  # no extra places at all
    assert facts_of(found["3"]) == {}


def test_the_first_three_places_and_the_word_lists_do_not_change_when_facts_are_added():
    plain = {code: (name, category) for code, (name, category) in PRODUCTS.items()}
    with_facts = {
        code: (name, category, {"f": "3", "z": ["1", "l"], "w": True})
        for code, (name, category) in PRODUCTS.items()
    }
    before, after = build_index(plain), build_index(with_facts)
    assert before.keys() == after.keys()
    for name in before:
        assert before[name]["w"] == after[name]["w"]  # the same words, the same positions
        for old, new in zip(before[name]["p"], after[name]["p"], strict=True):
            assert new[:2] == old[:2]  # barcode and name
            assert (new[2] or None) == (old[2] if len(old) > 2 else None)  # category
            assert isinstance(new[3], dict)  # the only addition


def test_search_reads_a_category_less_record_with_facts_as_having_no_category(tmp_path):
    write_index(
        build_index({"1": ("עגבניות", None, {"w": True}), "2": ("חלב", "dairy", {"f": "3"})}),
        tmp_path,
    )
    assert search(tmp_path, "עגבניות") == {"1": ("עגבניות", None)}
    assert search(tmp_path, "חלב") == {"2": ("חלב", "dairy")}
