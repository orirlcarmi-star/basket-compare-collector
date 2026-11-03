import json

import pytest

from collector.locate import (
    apply_manual,
    city_name,
    clean_address,
    distance_km,
    load_manual,
    load_settlements,
    other_spellings,
    place_of,
    settlement_in,
    street_only,
    update_locations,
)

SETTLEMENTS = {"2530": "באר יעקב", "5000": "תל אביב -יפו", "70": "אשדוד"}
TEL_AVIV = (32.08, 34.78)
FAR_AWAY = (29.55, 34.95)  # Eilat


def store(sid="1", name="שלי", address="הבנים 46", city="5000", online=False):
    return {"store_id": sid, "name": name, "address": address, "city": city, "is_online": online}


def test_settlements_from_official_list():
    rows = {"result": {"records": [{"סמל_ישוב": "2530 ", "שם_ישוב": "באר  יעקב "}]}}
    assert load_settlements(lambda url: rows) == {"2530": "באר יעקב"}


def test_city_code_becomes_a_name():
    assert city_name("2530", SETTLEMENTS) == "באר יעקב"
    assert city_name("070", SETTLEMENTS) == "אשדוד"
    assert city_name("חיפה", SETTLEMENTS) == "חיפה"


def test_without_a_city_the_store_name_names_the_place():
    places = {"1": "חדרה", "2": "נתניה", "3": "תל אביב -יפו", "4": "ראשון לציון"}
    assert place_of(store(name="יוחננוף חדרה", address="unknown", city="0"), places) == (
        "",
        "חדרה",
        True,
    )
    assert place_of(store(name="נתניה הדרים", address="", city="0"), places) == (
        "הדרים",
        "נתניה",
        True,
    )
    assert place_of(store(name='ת"א - אחד העם', address="unknown", city="0"), places) == (
        "אחד העם",
        "תל אביב -יפו",
        True,
    )
    assert place_of(store(name="ראשלצ רמת אליהו", address="משורר השואה 15", city="0"), places)[
        :2
    ] == ("משורר השואה 15", "ראשון לציון")
    # A settlement name inside a longer word does not count.
    assert place_of(store(name="מפוח", address="", city="0"), {"1": "פוח"})[1] == "מפוח"


def test_clean_address_drops_noise():
    assert clean_address("רח' מקס ברוד34") == "מקס ברוד34"
    assert clean_address("עמק איילון פינת התרשיש") == "עמק איילון"
    assert clean_address("קניון הצפון , אירית 2") == "קניון הצפון"
    assert clean_address("אדום 24 פארק התעשיות כנות") == "אדום 24"
    assert clean_address("17 יצחק שמיר") == "17 יצחק שמיר"
    assert street_only('המסגר 22 אזה"ת הצפוני') == "המסגר"


def test_distance():
    assert 53 < distance_km((31.7683, 35.2137), (32.0853, 34.7818)) < 55  # Jerusalem-Tel Aviv


def fake_lookup(answers):
    asked = []

    def lookup(query):
        asked.append(query)
        return answers.get(query)

    return lookup, asked


def test_address_found_near_its_city():
    lookup, _ = fake_lookup({"תל אביב -יפו": TEL_AVIV, "הבנים 46, תל אביב -יפו": (32.09, 34.79)})
    located, missing = update_locations([store()], {}, SETTLEMENTS, lookup)
    assert located["1"]["precision"] == "address"
    assert missing == []


def test_same_street_name_in_another_city_falls_back_to_city_centre():
    lookup, _ = fake_lookup({"תל אביב -יפו": TEL_AVIV, "הבנים 46, תל אביב -יפו": FAR_AWAY})
    located, _ = update_locations([store()], {}, SETTLEMENTS, lookup)
    assert located["1"]["precision"] == "city"
    assert (located["1"]["lat"], located["1"]["lon"]) == TEL_AVIV


def test_known_location_is_reused_and_online_store_skipped():
    known = {
        "1": {
            "lat": 1,
            "lon": 2,
            "precision": "address",
            "address": "הבנים 46",
            "city": "תל אביב -יפו",
        }
    }
    lookup, asked = fake_lookup({})
    stores = [store(), store(sid="2", online=True)]
    located, _ = update_locations(stores, known, SETTLEMENTS, lookup)
    assert located == known
    assert asked == []


def test_nothing_found_is_reported():
    lookup, _ = fake_lookup({})
    located, missing = update_locations([store()], {}, SETTLEMENTS, lookup)
    assert located == {}
    assert len(missing) == 1


def test_street_without_number_as_last_resort():
    lookup, _ = fake_lookup({"תל אביב -יפו": TEL_AVIV, "הבנים, תל אביב -יפו": (32.09, 34.79)})
    located, _ = update_locations([store()], {}, SETTLEMENTS, lookup)
    assert located["1"]["precision"] == "street"


def test_chain_name_in_the_city_before_the_city_centre():
    lookup, _ = fake_lookup({"תל אביב -יפו": TEL_AVIV, "רמי לוי, תל אביב -יפו": (32.07, 34.77)})
    located, _ = update_locations([store()], {}, SETTLEMENTS, lookup, "רמי לוי")
    assert located["1"]["precision"] == "store name"


def test_one_name_point_for_several_stores_falls_back_to_city_centre():
    lookup, _ = fake_lookup({"תל אביב -יפו": TEL_AVIV, "רמי לוי, תל אביב -יפו": (32.07, 34.77)})
    stores = [store(sid="1"), store(sid="2", address="הרצל 5")]
    located, _ = update_locations(stores, {}, SETTLEMENTS, lookup, "רמי לוי")
    assert {loc["precision"] for loc in located.values()} == {"city"}


# Addresses that were left at "city" precision in locations/*.json before.
def test_other_spellings_of_addresses_the_map_did_not_know():
    assert other_spellings("רח.המלאכה 2") == ["המלאכה 2"]
    assert other_spellings("ד.ויצמן 1") == ["ויצמן 1"]
    assert other_spellings("רח משה יתום  46") == []  # cleaning already handles this one
    assert other_spellings("א.ת באר טוביה") == ["אזור התעשייה באר טוביה"]
    assert other_spellings("א.ת שילת") == ["אזור התעשייה שילת"]
    assert other_spellings("מרכז מסחרי מטה בנמין") == ["מטה בנמין"]
    assert other_spellings("1 אחי מאיר") == ["אחי מאיר 1"]
    assert other_spellings("24 פנחס רוזן") == ["פנחס רוזן 24"]
    assert other_spellings("הבנים 46") == []


def test_other_spellings_are_tried_after_the_usual_ones_and_keep_the_house_number():
    lookup, asked = fake_lookup(
        {"תל אביב -יפו": TEL_AVIV, "אחי מאיר 1, תל אביב -יפו": (32.09, 34.79)}
    )
    located, _ = update_locations([store(address="1 אחי מאיר")], {}, SETTLEMENTS, lookup)
    assert located["1"]["precision"] == "address"  # the number is there, so still an address
    assert asked.index("1 אחי מאיר, תל אביב -יפו") < asked.index("אחי מאיר 1, תל אביב -יפו")

    lookup, _ = fake_lookup(
        {"תל אביב -יפו": TEL_AVIV, "אזור התעשייה שילת, תל אביב -יפו": (32.09, 34.79)}
    )
    located, _ = update_locations([store(address="א.ת שילת")], {}, SETTLEMENTS, lookup)
    assert located["1"]["precision"] == "street"  # an area, not an exact address


def test_a_street_word_is_not_taken_for_the_city():
    places = {"1": "רחוב", "2": "אזור", "3": "אלון", "4": "אשדוד"}
    assert settlement_in("יוחננוף רחוב אחד העם 19", places) == ""
    assert settlement_in("אזור התעשיה יגאל אלון 57", places) == ""
    assert settlement_in("יוחננוף אשדוד רחוב הרצל", places) == "אשדוד"


def write_manual(tmp_path, content):
    path = tmp_path / "shufersal.manual.json"
    path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return path


def test_manual_correction_beats_the_search(tmp_path):
    manual = load_manual(
        write_manual(tmp_path, {"_help": "x", "007": {"lat": 32.07, "lon": 34.78, "city": "חיפה"}})
    )
    assert list(manual) == ["7"]  # leading zeros dropped, comments skipped
    assert manual["7"]["precision"] == "address"

    lookup, asked = fake_lookup({"תל אביב -יפו": TEL_AVIV})
    located, missing = update_locations([store(sid="007")], {}, SETTLEMENTS, lookup, manual=manual)
    assert located == {} and missing == [] and asked == []  # not searched, not "missing"

    searched = {"007": {"lat": 1.0, "lon": 2.0, "precision": "city", "address": "", "city": "x"}}
    merged = apply_manual(searched, manual)
    assert merged["7"]["lat"] == 32.07
    assert merged["7"]["city"] == "חיפה"


def test_manual_correction_without_a_city_keeps_the_searched_city(tmp_path):
    manual = load_manual(write_manual(tmp_path, {"7": {"lat": 32.07, "lon": 34.78}}))
    searched = {"7": {"lat": 1.0, "lon": 2.0, "precision": "city", "address": "", "city": "חיפה"}}
    assert apply_manual(searched, manual)["7"]["city"] == "חיפה"
    assert apply_manual({}, manual)["7"]["city"] == ""  # a store the search never found


def test_no_manual_file_means_no_corrections(tmp_path):
    assert load_manual(tmp_path / "missing.json") == {}


@pytest.mark.parametrize(
    "entry",
    [
        {"lat": 48.1, "lon": 34.78},  # latitude of Munich
        {"lat": 32.07, "lon": 3.478},  # a digit lost
        {"lat": "בערך", "lon": 34.78},
        {"lon": 34.78},
        {"lat": 32.07, "lon": 34.78, "precision": "exact"},
    ],
)
def test_a_wrong_manual_correction_is_refused_loudly(tmp_path, entry):
    with pytest.raises(ValueError, match="store 413"):
        load_manual(write_manual(tmp_path, {"413": entry}))
