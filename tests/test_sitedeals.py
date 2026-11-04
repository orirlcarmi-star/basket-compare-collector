import json
from datetime import datetime

import pytest

from collector import publish
from collector.compact import restore_prices
from collector.sitedeals import (
    DEAL_BUCKETS,
    bucket_deals,
    build_chain_deals,
    deal_bucket,
    fnv1a,
    load_store_deals,
    places_to_positions,
    read_deal,
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


def test_stores_selling_other_kinds_share_one_file_with_all_items_and_all_stores():
    # The real case: "2 for 13.90 on herbs" in stores that sell 3, 4 or 5 of the kinds.
    herbs = ("coriander", "parsley", "dill", "mint", "chives")
    stores = {
        "1": [deal(items=herbs[:3])],
        "2": [deal(items=herbs[:4])],
        "3": [deal(items=herbs)],
        "4": [deal(items=herbs[:3])],
    }
    files, by_item, _ = build(stores, sold=set(herbs))
    assert list(files) == ["7"]  # one file, not 7, 7-2, 7-3
    assert files["7"]["i"] == sorted(herbs)
    assert files["7"]["s"] == ["g1", 3]  # all of g1 (positions 0-2) and position 3
    assert by_item["chives"] == ["7"] and by_item["coriander"] == ["7"]


@pytest.mark.parametrize(
    "change",
    [{"qty": "3", "price": "27.00"}, {"price": "18.00"}, {"max_qty": "6"},
     {"audience": "club"}, {"ends_at": "2026-11-09T00:00:00"}],
)  # fmt: skip
def test_only_q_p_m_c_or_e_make_another_variant(change):
    files, _, _ = build({"1": [deal()], "2": [deal(**change)]})
    assert sorted(files) == ["7", "7-2"]


def test_different_wording_alone_is_not_a_variant():
    stores = {
        "1": [deal(description="2 ב-20")],
        "2": [deal(description="2ב20")],
        "3": [deal(description="2ב20")],
    }
    files, _, _ = build(stores)
    assert len(files) == 1 and files["7"]["t"] == "2ב20" and files["7"]["s"] == ["g1"]


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
    seven = read_deal(site, "alpha", "7")
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
    stale = tmp_path / "v2" / "d" / "alpha" / "999.json"
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


# --- the file budget: Cloudflare takes 20,000 files, the run fails above 18,000 ---


def test_the_site_stays_far_below_the_file_limit_and_says_how_many_files_it_has(with_deals):
    tmp_path, _, _ = with_deals
    assert run_publish(tmp_path, "v2", "--compact") == 0
    stats = json.loads((tmp_path / "v2" / "stats.json").read_text(encoding="utf-8"))
    parts = stats["files_by_part"]
    actual = sum(1 for f in (tmp_path / "v2").rglob("*") if f.is_file())
    assert stats["files_total"] == actual == sum(parts.values())
    assert parts["d"] == 2 and parts["p"] == 16 and parts["s"] > 0
    assert actual < publish.MAX_SITE_FILES


def test_the_real_settings_leave_room_for_deals():
    # the product files alone are fixed by BUCKETS; the rest must fit in what is left
    assert publish.BUCKETS < publish.MAX_SITE_FILES < 20_000
    assert publish.MAX_SITE_FILES - publish.BUCKETS > 9_000


def test_too_many_files_fails_the_run_with_a_clear_message(with_deals, monkeypatch, capsys):
    tmp_path, _, _ = with_deals
    monkeypatch.setattr(publish, "MAX_SITE_FILES", 10)
    assert run_publish(tmp_path, "v2", "--compact") == 1
    message = capsys.readouterr().err
    assert "TOO MANY FILES" in message and "limit is 10" in message
    assert "יותר מדי קבצים" in message and "deals" in message


def test_message_names_the_biggest_part():
    text = publish.too_many_files({"p": 8192, "s": 700, "d": 12000, "other": 5}, 18_000)
    assert text and "'d'" in text and "20,000" in text
    assert publish.too_many_files({"p": 8192, "s": 700, "d": 9000, "other": 5}, 18_000) is None


# --- too many deal files must not stop the prices ---


def test_deals_that_do_not_fit_are_held_back_and_the_prices_still_go_out(
    with_deals, monkeypatch, capsys
):
    tmp_path, codes, _ = with_deals
    assert run_publish(tmp_path, "with", "--compact") == 0
    with_stats = json.loads((tmp_path / "with" / "stats.json").read_text(encoding="utf-8"))
    assert with_stats["deal_files"] == 2 and with_stats["warnings"] == []
    others = with_stats["files_total"] - 2

    # room for everything but the two deal files (+1: meta.json, which is added after publish)
    monkeypatch.setattr(publish, "MAX_SITE_FILES", others + 1)
    assert run_publish(tmp_path, "held", "--compact") == 0  # prices are published all the same
    stats = json.loads((tmp_path / "held" / "stats.json").read_text(encoding="utf-8"))
    assert stats["deal_files"] == 0 and stats["deals_held_back"] == 2
    assert "מבצעים לא פורסמו" in stats["warnings"][0]
    assert not (tmp_path / "held" / "d").exists()
    products = products_of(tmp_path / "held")
    assert all("d" not in p["c"].get("alpha", {}) for p in products.values())  # no dangling ids
    assert restore_prices(tmp_path / "held")["alpha"]  # prices intact
    assert "Deals not published" in capsys.readouterr().err


def test_a_stale_deal_folder_is_removed_when_deals_are_held_back(with_deals, monkeypatch):
    tmp_path, _, _ = with_deals
    assert run_publish(tmp_path, "site", "--compact") == 0
    assert (tmp_path / "site" / "d" / "alpha").exists()
    others = json.loads((tmp_path / "site" / "stats.json").read_text("utf-8"))["files_total"] - 2
    monkeypatch.setattr(publish, "MAX_SITE_FILES", others + 1)
    assert run_publish(tmp_path, "site", "--compact") == 0  # same folder, deals now held back
    assert not (tmp_path / "site" / "d").exists()


def test_the_warning_reaches_the_summary_and_the_issue_text(with_deals, monkeypatch, tmp_path):
    from collector.daily import make_meta, problems_in
    from tests.test_daily import utc

    root, _, _ = with_deals
    assert run_publish(root, "full", "--compact") == 0
    others = json.loads((root / "full" / "stats.json").read_text("utf-8"))["files_total"] - 2
    monkeypatch.setattr(publish, "MAX_SITE_FILES", others + 1)
    assert run_publish(root, "held", "--compact") == 0
    meta = make_meta(root / "data", ["alpha"], root / "held", utc("2026-11-04T10:00"))
    assert meta["deals_held_back"] == 2 and "מבצעים לא פורסמו" in meta["warnings"][0]
    assert any("מבצעים לא פורסמו" in line for line in problems_in(meta, "success", "success"))


# --- the files of the deals: 256 buckets per chain, n = FNV-1a of the deal id modulo 256 ---


def test_fnv1a_is_the_standard_one():
    # published test vectors of 32-bit FNV-1a
    assert fnv1a("") == 0x811C9DC5
    assert fnv1a("a") == 0xE40C292C
    assert fnv1a("foobar") == 0xBF9CF968


@pytest.mark.parametrize(
    ("deal_id", "hash32", "n"),
    [
        # The numbers the website checks its own computation against.
        ("7", 839689206, 246),
        ("7-2", 2298208649, 137),  # the suffix of a variant is part of the id
        ("4662141", 845991053, 141),
        ("4662141-2", 3546552214, 150),
        ("4662141-3", 3563329833, 41),
    ],
)
def test_the_bucket_of_a_deal_id_has_exact_values(deal_id, hash32, n):
    assert fnv1a(deal_id) == hash32
    assert deal_bucket(deal_id) == n == hash32 % 256 == hash32 % DEAL_BUCKETS


def test_the_product_files_use_the_same_function_with_another_modulus():
    assert publish.bucket_of("7") == 839689206 % publish.BUCKETS


def many_deals(count):
    """count promotions in one store, each a different deal, with ids 1000..."""
    return [deal(promotion=str(1000 + n), items=("milk",)) for n in range(count)]


def test_every_deal_is_in_the_file_of_its_hash_and_only_there(with_deals):
    import shutil

    tmp_path, codes, stores = with_deals
    shutil.rmtree(tmp_path / "data" / "alpha" / "deals")  # replace the fixture's two deals
    write_deals(tmp_path, "alpha", {stores[0]: many_deals(300), stores[1]: many_deals(50)})
    # the invented chain sells these codes: use one of them in every deal
    for path in (tmp_path / "data" / "alpha" / "deals").glob("*.json"):
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            row["item_codes"] = [codes[0]]
        path.write_text(json.dumps(rows), encoding="utf-8")
    assert run_publish(tmp_path, "v2", "--compact") == 0
    site = tmp_path / "v2"

    seen: dict[str, str] = {}
    for path in sorted((site / "d" / "alpha").glob("*.json")):
        assert path.stem.isdigit() and 0 <= int(path.stem) < DEAL_BUCKETS
        bucket = json.loads(path.read_text(encoding="utf-8"))
        assert bucket, "an empty bucket must not be written"
        for deal_id, body in bucket.items():
            assert deal_bucket(deal_id) == int(path.stem)  # in the file of its hash
            assert deal_id not in seen  # and in no other file
            seen[deal_id] = path.name
            assert {"q", "p", "i", "t"} <= set(body)
            assert read_deal(site, "alpha", deal_id) == body
    assert len(seen) == 300  # 300 distinct promotions (the 50 are the same ones in another store)
    stats = json.loads((site / "stats.json").read_text(encoding="utf-8"))
    assert stats["deals"] == 300 and stats["deal_files"] == len(
        list((site / "d" / "alpha").glob("*"))
    )
    assert stats["deal_files"] <= DEAL_BUCKETS  # never more than 256 files for the chain
    # the product's list of ids is unchanged: plain ids
    product = products_of(site)[codes[0]]["c"]["alpha"]
    assert "1000" in product["d"] and all(isinstance(i, str) for i in product["d"])


def test_a_missing_deal_is_not_found(with_deals):
    tmp_path, _, _ = with_deals
    assert run_publish(tmp_path, "v2", "--compact") == 0
    assert read_deal(tmp_path / "v2", "alpha", "no-such-deal") is None
    assert read_deal(tmp_path / "v2", "beta", "7") is None  # beta has no deals at all


def test_all_four_chains_with_thousands_of_deals_fit_the_budget():
    """The first real run had 22,342 deals; in buckets they take at most 256 files per chain."""
    chains = 4
    deals_per_chain = 6000
    files = {}
    for chain in range(chains):
        ids = {f"{chain}{n}": {"q": 2} for n in range(deals_per_chain)}
        for number, bucket in bucket_deals(ids).items():
            files[f"d/c{chain}/{number}.json"] = bucket
    assert sum(len(b) for b in files.values()) == chains * deals_per_chain
    assert len(files) <= chains * DEAL_BUCKETS == 1024
    # products 8,192 + search (about 750) + deals (at most 1,024) + the few small files
    assert publish.BUCKETS + 800 + len(files) + 4 < publish.MAX_SITE_FILES
