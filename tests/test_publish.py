from collector.publish import bucket_of, chain_products, chain_stores

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
