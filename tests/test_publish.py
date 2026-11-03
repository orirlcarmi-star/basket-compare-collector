from collector.publish import bucket_of, chain_products, chain_stores, finish_products

READY = {
    "groups": [{"id": "g1", "stores": ["1", "2"], "base": {"milk": "7.35", "tomato": "11.90"}}],
    "stores": {
        "1": {"group": "g1", "stock": ["milk", "tomato"], "exceptions": {}},
        "2": {"group": "g1", "stock": ["milk"], "exceptions": {"milk": "6.90"}},
    },
    "products": {
        "milk": {"name": "חלב 3%", "quantity": "1.00", "unit": "ליטר", "is_weighted": False}
    },
}


def test_bucket_matches_the_website():
    # Reference values from the website's bucketOf (experiments/basket-cpu/worker/src/calc.ts).
    assert [bucket_of(c) for c in ["7290000000015", "7290004131074", "10900302814", "1"]] == [
        3069,
        1645,
        4707,
        1820,
    ]


def test_product_holds_group_price_exceptions_and_sellers():
    products: dict = {}
    chain_products("shufersal", READY, products)
    milk = products["milk"]
    assert milk["n"] == "חלב 3%"
    assert milk["c"]["shufersal"] == {
        "g": {"g1": "7.35"},
        "s": ["shufersal:1", "shufersal:2"],
        "x": {"shufersal:2": "6.90"},
    }
    assert products["tomato"]["c"]["shufersal"]["s"] == ["shufersal:1"]


def test_two_chains_share_one_product():
    products: dict = {}
    chain_products("shufersal", READY, products)
    chain_products("ramilevi", READY, products)
    assert set(products["milk"]["c"]) == {"shufersal", "ramilevi"}


def test_stores_need_a_location_and_online_stores_are_left_out():
    listed = [
        {"store_id": "1", "name": "שלי", "is_online": False},
        {"store_id": "2", "name": "אונליין", "is_online": True},
    ]
    located = {"1": {"lat": 32.0, "lon": 34.8, "precision": "address", "city": "תל אביב"}}
    stores, unlocated = chain_stores("shufersal", READY, listed, located)
    assert list(stores) == ["shufersal:1"]
    assert stores["shufersal:1"]["group"] == "g1"
    assert unlocated == []

    stores, unlocated = chain_stores("shufersal", READY, listed[:1], {})
    assert stores == {}
    assert unlocated == ["shufersal:1", "shufersal:2"]


def test_store_numbers_match_with_or_without_leading_zeros():
    ready = dict(READY, stores={"071": READY["stores"]["1"]})
    listed = [{"store_id": "71", "name": "שלי", "is_online": False}]
    located = {"71": {"lat": 32.0, "lon": 34.8, "precision": "address", "city": "חיפה"}}
    stores, unlocated = chain_stores("shufersal", ready, listed, located)
    assert list(stores) == ["shufersal:71"]
    products: dict = {}
    chain_products("shufersal", ready, products)
    assert products["milk"]["c"]["shufersal"]["s"] == ["shufersal:71"]


def _ready_with(name, quantity="", unit="", maker=""):
    return dict(
        READY,
        products={
            "milk": {"name": name, "quantity": quantity, "unit": unit, "manufacturer": maker}
        },
    )


def test_one_barcode_in_two_chains_shows_the_clearest_name():
    products: dict = {}
    chain_products("ramilevi", _ready_with("חלב 3%"), products)
    chain_products("shufersal", _ready_with("חלב טרה 3% בקרטון 1 ליטר"), products)
    chain_products("osherad", _ready_with("חלב 3% 1 ל..."), products)
    assert products["milk"]["n"] == "חלב טרה 3% בקרטון 1 ליטר"
    # and the other way round
    products = {}
    chain_products("shufersal", _ready_with("חלב טרה 3% בקרטון 1 ליטר"), products)
    chain_products("ramilevi", _ready_with("חלב 3%"), products)
    assert products["milk"]["n"] == "חלב טרה 3% בקרטון 1 ליטר"


def test_a_missing_size_or_maker_is_filled_in_from_another_chain():
    products: dict = {}
    chain_products("ramilevi", _ready_with("חלב 3%"), products)
    chain_products("shufersal", _ready_with("חלב", "1.00", "ליטר", "תנובה"), products)
    assert (products["milk"]["q"], products["milk"]["u"]) == ("1.00", "ליטר")
    assert products["milk"]["_m"] == "תנובה"


def test_finished_products_carry_facts_and_what_the_package_holds():
    products: dict = {}
    chain_products("shufersal", _ready_with("חלב דל לקטוז 1% תנובה 1.5 ליטר"), products)
    chain_products("shufersal", dict(READY, products={}), products)
    finish_products(products)
    milk, tomato = products["milk"], products["tomato"]
    assert milk["a"] == {"f": "1", "b": "תנובה"}
    assert milk["z"] == ["1.5", "l"]
    assert "_m" not in milk
    assert "a" not in tomato and "z" not in tomato  # nothing found, nothing written


def test_a_size_from_the_chain_fields_is_used_when_the_name_has_none():
    products: dict = {}
    chain_products("shufersal", _ready_with("חלב טרי", "0.50", "ליטר"), products)
    finish_products(products)
    assert products["milk"]["z"] == ["0.5", "l"]
