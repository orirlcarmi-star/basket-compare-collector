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
