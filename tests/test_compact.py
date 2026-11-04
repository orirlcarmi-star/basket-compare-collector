import json
import random

import pytest

from collector import publish
from collector.compact import (
    build_index,
    restore_prices,
    seller_fields,
    sellers_of,
    verify_restored,
)
from collector.files import same_store

GROUPS = ["g1", "g1", "g1", "g2", "g2", "g3"]  # six stores, three price groups


@pytest.mark.parametrize(
    ("sellers", "spec"),
    [
        ({0, 1, 2, 3, 4, 5}, {}),  # everyone: nothing to write
        ({0, 1, 2, 3, 4}, {"o": [5]}),  # everyone but one
        ({0}, {"s": [0]}),  # one store
        ({0, 1, 2}, {"k": ["g1"]}),  # a whole price group
        ({0, 1, 2, 5}, {"o": [3, 4]}),  # with so few stores, naming the two missing is shorter
    ],
)
def test_the_shortest_form_and_back(sellers, spec):
    assert seller_fields(sellers, GROUPS) == spec
    assert sellers_of(spec, GROUPS) == sellers


def test_whole_price_groups_win_when_the_chain_is_big():
    groups = ["g1"] * 100 + ["g2"] * 100 + ["g3"] * 100
    sellers = set(range(100)) | {250}  # all of g1, and one store of g3
    spec = seller_fields(sellers, groups)
    assert spec == {"k": ["g1"], "s": [250]}
    assert sellers_of(spec, groups) == sellers


def test_every_possible_seller_set_survives_the_round_trip():
    rng = random.Random(1)
    for _ in range(300):
        sellers = {i for i in range(len(GROUPS)) if rng.random() < rng.choice([0.2, 0.5, 0.9])}
        if sellers:
            assert sellers_of(seller_fields(sellers, GROUPS), GROUPS) == sellers


def fake_ready(chain_seed, stores=40, products=250):
    """A chain like the real ones: most products in every store, some in a few, a few
    prices that differ from the group's, a second price group."""
    rng = random.Random(chain_seed)
    ids = [f"{n:03d}" for n in range(1, stores + 1)]
    codes = [f"7290{chain_seed}{n:05d}" for n in range(products)]
    group_of = {i: "g1" if n < stores * 0.7 else "g2" for n, i in enumerate(ids)}
    bases = {g: {c: f"{rng.randint(300, 4000) / 100:.2f}" for c in codes} for g in ("g1", "g2")}
    ready_stores = {}
    for i in ids:
        stock = [c for c in codes if rng.random() < (0.97 if int(c[-5:]) % 10 else 0.3)]
        exceptions = {c: "1.00" for c in stock if rng.random() < 0.01}
        ready_stores[i] = {"group": group_of[i], "stock": stock, "exceptions": exceptions}
    return {
        "groups": [
            {"id": g, "stores": [i for i in ids if group_of[i] == g], "base": bases[g]}
            for g in ("g1", "g2")
        ],
        "stores": ready_stores,
        "products": {
            c: {"name": f"מוצר {c} 1 ליטר", "quantity": "1.00", "unit": "ליטר", "manufacturer": ""}
            for c in codes
        },
    }


def write_chain(tmp_path, chain, ready):
    data = tmp_path / "data" / chain
    for name, value in ready.items():
        (data / "ready").mkdir(parents=True, exist_ok=True)
        (data / "ready" / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    listed = [{"store_id": i, "name": f"סניף {i}", "is_online": False} for i in ready["stores"]]
    (data / "stores.json").write_text(json.dumps(listed, ensure_ascii=False), encoding="utf-8")
    # the last store has no location: it must still be restorable in format 2
    places = {
        i: {"lat": 32.0, "lon": 34.8, "precision": "address", "city": "חיפה"}
        for i in list(ready["stores"])[:-1]
    }
    (tmp_path / "locations").mkdir(exist_ok=True)
    (tmp_path / "locations" / f"{chain}.json").write_text(json.dumps(places), encoding="utf-8")


def run_publish(tmp_path, out, *flags):
    folders = {"--data": "data", "--locations": "locations", "--out": out}
    arguments = [x for flag, name in folders.items() for x in (flag, str(tmp_path / name))]
    return publish.main(["alpha", "beta", *arguments, *flags])


def total_bytes(folder):
    return sum(f.stat().st_size for f in folder.rglob("*.json"))


@pytest.fixture
def two_chains(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "BUCKETS", 16)  # 16 files instead of 8,192: same logic, faster
    write_chain(tmp_path, "alpha", fake_ready(1))
    write_chain(tmp_path, "beta", fake_ready(2))
    return tmp_path


def test_compact_files_are_much_smaller_and_restore_exactly(two_chains, capsys):
    assert run_publish(two_chains, "v1") == 0
    assert run_publish(two_chains, "v2", "--compact") == 0
    old, new = total_bytes(two_chains / "v1"), total_bytes(two_chains / "v2")
    assert new < old * 0.5, f"format 2 is {new:,} bytes, format 1 {old:,}"
    assert "verified" in capsys.readouterr().out

    # format 2 restores every store, including the one with no location
    restored = restore_prices(two_chains / "v2")
    assert len(restored["alpha"]) == 40
    # and format 1, the stores it lists, give the same prices
    for chain, stores in restore_prices(two_chains / "v1").items():
        assert len(stores) == 39
        assert all(restored[chain][s] == prices for s, prices in stores.items())


def test_format_1_stays_as_the_website_reads_it(two_chains):
    assert run_publish(two_chains, "v1") == 0
    stores = json.loads((two_chains / "v1" / "stores.json").read_text(encoding="utf-8"))
    assert "format" not in stores and "alpha:1" in stores  # keyed by store, as before
    files = sorted((two_chains / "v1" / "p").glob("*.json"))
    products = [p for f in files for p in json.loads(f.read_text("utf-8")).values()]
    first = products[0]
    assert {"n", "q", "u", "w", "c"} <= set(first)
    assert isinstance(first["c"]["alpha"]["s"][0], str)  # store keys, not positions


def test_a_change_to_the_files_is_caught(two_chains):
    assert run_publish(two_chains, "v2", "--compact") == 0
    expected_ready = {"alpha": fake_ready(1), "beta": fake_ready(2)}
    expected = {
        chain: publish.published_prices(chain, ready) for chain, ready in expected_ready.items()
    }
    restored = restore_prices(two_chains / "v2")
    verify_restored(restored, expected, complete=True)  # fine as it is

    restored["alpha"]["5"][next(iter(restored["alpha"]["5"]))] = "9999.00"
    with pytest.raises(AssertionError, match="alpha:5"):
        verify_restored(restored, expected, complete=True)

    del restored["alpha"]["5"]
    with pytest.raises(AssertionError, match="missing"):
        verify_restored(restored, expected, complete=True)


def test_index_covers_every_store_in_a_fixed_order():
    index = build_index(
        "c", {"010": {"group": "g2"}, "9": {"group": "g1"}, "009": {"group": "g1"}}, same_store
    )
    assert index == {"ids": ["9", "10"], "groups": ["g1", "g2"]}  # "009" and "9" are one store


def test_publish_works_without_todays_store_list_and_writes_stats(two_chains):
    # Today's collection failed for beta: its ready-made files are yesterday's, and there
    # is no stores.json. The store names are unknown but the prices are all there.
    (two_chains / "data" / "beta" / "stores.json").unlink()
    assert run_publish(two_chains, "v2", "--compact") == 0
    stats = json.loads((two_chains / "v2" / "stats.json").read_text(encoding="utf-8"))
    assert stats["products"] == 500 and stats["stores"] == 78 and stats["unlocated"] == 2


def test_site_files_carry_category_facts_unit_contents_and_a_search_index(two_chains, capsys):
    from collector.searchindex import search

    review = two_chains / "review" / "unclassified.txt"
    assert run_publish(two_chains, "v2", "--compact", "--review", str(review)) == 0
    out = capsys.readouterr().out
    assert "have a category; search index" in out

    # fake_ready names are "מוצר <barcode> 1 ליטר": no category word, but a size
    product = next(iter(products_in(two_chains / "v2").values()))
    assert product["z"] == ["1", "l"] and "k" not in product
    assert len(review.read_text(encoding="utf-8").splitlines()) == 500  # all named, none sorted

    categories = json.loads((two_chains / "v2" / "categories.json").read_text(encoding="utf-8"))
    assert len(categories) == 14 and categories[0] == {"id": "dairy", "name": "חלב וביצים"}

    # the index finds a product by its barcode word and by "ליטר"
    code = next(iter(fake_ready(1)["products"]))
    assert code in search(two_chains / "v2" / "s", f"מוצר {code}")
    assert len(search(two_chains / "v2" / "s", "ליטר")) == 500
    stats = json.loads((two_chains / "v2" / "stats.json").read_text(encoding="utf-8"))
    assert stats["classified_percent"] == 0.0 and stats["search_files"] > 0


def products_in(site):
    """name -> product, read from every bucket file of a site folder."""
    found = {}
    for path in (site / "p").glob("*.json"):
        for product in json.loads(path.read_text(encoding="utf-8")).values():
            found[product["n"]] = product
    return found


def test_category_reaches_the_compact_product(two_chains):
    ready = fake_ready(3, products=6)
    for code, name in zip(
        ready["products"], ["חלב 3% 1 ליטר", "עוף טרי", "מארז מתנה"], strict=False
    ):
        ready["products"][code]["name"] = name
    write_chain(two_chains, "alpha", ready)
    assert run_publish(two_chains, "v3", "--compact") == 0
    by_name = products_in(two_chains / "v3")
    assert by_name["חלב 3% 1 ליטר"]["k"] == "dairy" and by_name["עוף טרי"]["k"] == "meat"
    assert "k" not in by_name["מארז מתנה"]
    # format 1 carries the same fields, so nothing is hidden from the old reader
    assert run_publish(two_chains, "v4") == 0
    assert products_in(two_chains / "v4")["חלב 3% 1 ליטר"]["k"] == "dairy"


def test_search_files_of_a_published_site_carry_the_facets(two_chains, monkeypatch):
    from collector.searchindex import search_records

    monkeypatch.setattr(publish, "MAX_FACET_GROWTH", 10.0)  # these invented names are very short
    assert run_publish(two_chains, "v2", "--compact") == 0
    code = next(iter(fake_ready(1)["products"]))
    found = search_records(two_chains / "v2" / "s", f"מוצר {code}")
    record = found[code]
    assert record[:2] == [code, f"מוצר {code} 1 ליטר"]
    assert record[-1] == {"z": ["1", "l"]}  # from the product file's z, nothing else
    assert record[2] == ""  # no category for these invented names: its place is kept
    stats = json.loads((two_chains / "v2" / "stats.json").read_text(encoding="utf-8"))
    assert stats["search_facets"] is True and stats["warnings"] == []
    assert stats["search_facets_growth_percent"] > 0


def test_facets_over_the_growth_limit_are_left_out_with_a_warning(two_chains, capsys, monkeypatch):
    """The product owner's rule: more than the limit bigger and they are not written. These
    invented names are short, so with a low limit the records keep their old shape."""
    from collector.searchindex import search_records

    monkeypatch.setattr(publish, "MAX_FACET_GROWTH", 0.05)
    assert run_publish(two_chains, "v2", "--compact") == 0
    stats = json.loads((two_chains / "v2" / "stats.json").read_text(encoding="utf-8"))
    assert stats["search_facets"] is False
    assert stats["search_facets_growth_percent"] > 5
    assert "נתוני הצמצום" in stats["warnings"][0] and "Facets left out" in stats["warnings"][0]
    code = next(iter(fake_ready(1)["products"]))
    record = search_records(two_chains / "v2" / "s", f"מוצר {code}")[code]
    assert record == [code, f"מוצר {code} 1 ליטר"]  # exactly the shape from before
    assert "Facets left out" in capsys.readouterr().err


def test_the_limit_accepts_the_growth_measured_on_real_data():
    """The owner accepted the growth measured on the first real package (+28.2% in all, +32.3%
    in the largest file) and set the limit at 45%: that growth is kept, a much bigger one is not."""
    assert publish.MAX_FACET_GROWTH == 0.45
    assert max(0.282, 0.323) <= publish.MAX_FACET_GROWTH < 0.56  # +56%: every fact on every product


def test_the_largest_file_counts_too(two_chains, monkeypatch):
    """The limit is checked on the whole index and on its largest file: either one over, and the
    facets are left out."""
    monkeypatch.setattr(publish, "MAX_FACET_GROWTH", 10.0)
    assert run_publish(two_chains, "probe", "--compact") == 0
    stats = json.loads((two_chains / "probe" / "stats.json").read_text(encoding="utf-8"))
    total, largest = (
        stats["search_facets_growth_percent"],
        stats["search_facets_largest_growth_percent"],
    )
    assert stats["search_facets"] is True and total > 0 and largest > 0
    if total == largest:
        return  # nothing to tell the two apart on this sample
    limit = (min(total, largest) + max(total, largest)) / 2 / 100  # between the two
    monkeypatch.setattr(publish, "MAX_FACET_GROWTH", limit)
    assert run_publish(two_chains, "between", "--compact") == 0
    stats = json.loads((two_chains / "between" / "stats.json").read_text(encoding="utf-8"))
    assert stats["search_facets"] is False and "Facets left out" in stats["warnings"][0]
