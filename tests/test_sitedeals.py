import json
from datetime import datetime

import pytest

from collector import publish
from collector.compact import restore_prices
from collector.sitedeals import (
    build_chain_deals,
    load_store_deals,
    places_to_positions,
    shortest_places,
)
from tests.test_compact import fake_ready, run_publish, write_chain

NOW = datetime(2026, 11, 4, 8, 0)
# six stores in two price groups: positions 0-2 are g1, 3-5 are g2
INDEX = {"ids": ["1", "2", "3", "4", "5", "6"], "groups": ["g1", "g1", "g1", "g2", "g2", "g2"]}
SOLD = {"milk", "tomato", "cheese"}


def deal(promotion="7", items=("milk", "tomato"), qty="2", price="20.00", **extra):
    return {
        "promotion_id": promotion,
        "description": "2ב20",
        "audience": "everyone",
        "ends_at": "2026-11-05T23:59:59",
        "item_codes": list(items),
        "min_qty": qty,
        "price": price,
        "max_qty": None,
    } | extra


def build(store_deals, sold=SOLD):
    return build_chain_deals(store_deals, INDEX, sold, NOW)


EVERYWHERE = {str(i): [deal()] for i in range(1, 7)}


def test_a_deal_in_every_store_has_no_place_list():
    files, by_item, skipped = build(EVERYWHERE)
    assert files == {
        "7": {"t": "2ב20", "q": 2, "p": "20.00", "e": "2026-11-05T23:59", "i": ["milk", "tomato"]}
    }
    assert by_item == {"milk": ["7"], "tomato": ["7"]}
    assert not skipped


def test_all_the_fields_of_a_file():
    capped = deal(max_qty="6", audience="club", description="מבצע מועדון")
    files, _, _ = build({"1": [capped]})
    assert files["7"] == {
        "t": "מבצע מועדון", "q": 2, "p": "20.00", "m": 6, "c": True,
        "e": "2026-11-05T23:59", "i": ["milk", "tomato"], "s": [0],
    }  # fmt: skip
    # no end stated: no "e"; a fixed price per unit is q = 1
    files, _, _ = build({"1": [deal(ends_at=None, qty="1", price="109.00")]})
    assert files["7"]["q"] == 1 and "e" not in files["7"]


def test_where_it_applies_is_named_by_group_when_a_whole_group_has_it():
    only_g1 = {str(i): [deal()] for i in (1, 2, 3)}
    assert build(only_g1)[0]["7"]["s"] == ["g1"]
    g1_and_one_more = {str(i): [deal()] for i in (1, 2, 3, 5)}
    assert build(g1_and_one_more)[0]["7"]["s"] == ["g1", 4]
    some = {str(i): [deal()] for i in (1, 5)}
    assert build(some)[0]["7"]["s"] == [0, 4]


@pytest.mark.parametrize("positions", [{0}, {0, 1, 2}, {0, 1, 2, 4}, {3, 4, 5}, {1, 5}])
def test_places_round_trip(positions):
    places = shortest_places(positions, INDEX["groups"])
    assert places_to_positions(places, INDEX["groups"]) == positions
    assert shortest_places(set(range(6)), INDEX["groups"]) is None
    assert places_to_positions(None, INDEX["groups"]) == set(range(6))


def test_terms_that_differ_between_stores_get_their_own_id_the_commonest_first():
    stores = {
        "1": [deal(price="20.00")],
        "2": [deal(price="20.00")],
        "3": [deal(price="18.00")],  # another price in one store
        "4": [deal(price="19.00")],  # and another in one more
    }
    files, by_item, _ = build(stores)
    assert {k: v["p"] for k, v in files.items()} == {"7": "20.00", "7-2": "18.00", "7-3": "19.00"}
    assert files["7"]["s"] == [0, 1] and files["7-2"]["s"] == [2] and files["7-3"]["s"] == [3]
    assert by_item["milk"] == ["7", "7-2", "7-3"]


def test_different_items_or_end_are_different_deals_but_different_wording_is_not():
    stores = {
        "1": [deal(description="2 ב-20")],
        "2": [deal(description="2ב20")],
        "3": [deal(description="2ב20")],
        "4": [deal(items=("milk",))],
        "5": [deal(ends_at="2026-11-09T00:00:00")],
    }
    files, _, _ = build(stores)
    assert len(files) == 3
    assert files["7"]["t"] == "2ב20" and files["7"]["s"] == ["g1"]  # wording: the commonest


def test_one_promotion_with_two_offers_in_a_store_gives_two_files():
    files, _, _ = build({"1": [deal(), deal(qty="3", price="27.00")]})
    assert sorted(files) == ["7", "7-2"]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"audience": "credit_card"}, "credit-card deal"),
        ({"qty": "0.3", "price": "25.00"}, "quantity not a whole number"),
        ({"ends_at": "2026-11-03T23:59:59"}, "already over"),
        ({"max_qty": "1"}, "limit below the quantity needed"),
        ({"items": ("nothing sold",)}, "no item sold in the files"),
    ],
)
def test_deals_that_cannot_be_used_are_left_out_and_counted(changes, reason):
    files, by_item, skipped = build({"1": [deal(**changes)]})
    assert files == {} and by_item == {} and skipped == {reason: 1}


def test_items_not_sold_by_the_chain_are_dropped_from_the_deal():
    files, by_item, _ = build({"1": [deal(items=("milk", "unknown"))]})
    assert files["7"]["i"] == ["milk"] and set(by_item) == {"milk"}


def test_a_store_that_is_not_in_the_files_is_ignored():
    _, _, skipped = build({"99": [deal()]})
    assert skipped == {"store not in the files": 1}


def test_unsafe_characters_in_a_promotion_id_cannot_reach_a_file_name():
    files, _, _ = build({"1": [deal(promotion="../x/7")]})
    assert list(files) == ["___x_7"]


def test_whole_kilos_are_fine_and_a_fraction_of_a_kilo_is_not():
    assert "7" in build({"1": [deal(qty="2.00", price="30.00")]})[0]
    assert build({"1": [deal(qty="0.300", price="25.00")]})[0] == {}


def test_store_numbers_match_with_or_without_leading_zeros(tmp_path):
    (tmp_path / "001.json").write_text(json.dumps([deal()]), encoding="utf-8")
    assert list(load_store_deals(tmp_path)) == ["1"]


# --- through publish: the files, the product references, the exact restore check ---


def write_deals(tmp_path, chain, per_store):
    folder = tmp_path / "data" / chain / "deals"
    folder.mkdir(parents=True)
    for store, deals in per_store.items():
        (folder / f"{store}.json").write_text(json.dumps(deals), encoding="utf-8")


@pytest.fixture
def with_deals(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "BUCKETS", 16)
    monkeypatch.setattr(publish, "israel_now", lambda: NOW)
    ready = fake_ready(1)
    write_chain(tmp_path, "alpha", ready)
    write_chain(tmp_path, "beta", fake_ready(2))
    codes = list(ready["products"])[:3]
    stores = list(ready["stores"])
    write_deals(
        tmp_path,
        "alpha",
        {
            stores[0]: [
                deal(items=codes),
                deal(promotion="8", qty="1", price="5.00", items=codes[:1]),
            ],
            stores[1]: [deal(items=codes)],
        },
    )
    return tmp_path, codes, stores


def products_of(site):
    return {
        code: product
        for path in (site / "p").glob("*.json")
        for code, product in json.loads(path.read_text(encoding="utf-8")).items()
    }


def test_published_files_hold_the_deals_and_the_products_point_to_them(with_deals):
    tmp_path, codes, stores = with_deals
    assert run_publish(tmp_path, "v2", "--compact") == 0  # includes the exact restore check
    site = tmp_path / "v2"
    seven = json.loads((site / "d" / "alpha" / "7.json").read_text(encoding="utf-8"))
    assert seven["q"] == 2 and seven["p"] == "20.00" and seven["i"] == codes
    assert seven["s"] == [0, 1]  # two stores of forty, written as positions
    products = products_of(site)
    assert products[codes[0]]["c"]["alpha"]["d"] == ["7", "8"]
    assert products[codes[1]]["c"]["alpha"]["d"] == ["7"]
    beta = [p["c"]["beta"] for p in products.values() if "beta" in p["c"]]
    assert beta and all("d" not in entry for entry in beta)  # no deals for that chain
    stats = json.loads((site / "stats.json").read_text(encoding="utf-8"))
    assert stats["deal_files"] == 2 and stats["deal_bytes"] > 0 and stats["deals_left_out"] == {}
    # the prices themselves are untouched
    restored = restore_prices(site)
    assert len(restored["alpha"]) == 40


def test_old_format_has_no_deals_and_stale_deal_files_are_removed(with_deals):
    tmp_path, _, _ = with_deals
    assert run_publish(tmp_path, "v1") == 0
    assert not (tmp_path / "v1" / "d").exists()
    entries = [p["c"]["alpha"] for p in products_of(tmp_path / "v1").values() if "alpha" in p["c"]]
    assert entries and all("d" not in entry for entry in entries)
    assert run_publish(tmp_path, "v2", "--compact") == 0
    stale = tmp_path / "v2" / "d" / "alpha" / "gone.json"
    stale.write_text("{}", encoding="utf-8")
    assert run_publish(tmp_path, "v2", "--compact") == 0
    assert not stale.exists()


def test_deals_make_the_site_files_only_slightly_bigger(with_deals):
    tmp_path, _, _ = with_deals
    assert run_publish(tmp_path, "plain", "--compact") == 0
    for folder in (tmp_path / "data" / "alpha" / "deals").glob("*.json"):
        folder.unlink()
    assert run_publish(tmp_path, "none", "--compact") == 0
    with_size = sum(f.stat().st_size for f in (tmp_path / "plain").rglob("*.json"))
    without = sum(f.stat().st_size for f in (tmp_path / "none").rglob("*.json"))
    assert without < with_size < without * 1.05
