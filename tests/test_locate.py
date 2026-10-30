from collector.locate import (
    city_name,
    clean_address,
    distance_km,
    load_settlements,
    place_of,
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
    assert place_of(store(name="יוחננוף חדרה", address="unknown", city="0"), {}) == ("", "חדרה")


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
