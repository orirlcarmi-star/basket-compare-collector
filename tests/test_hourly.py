import json

import pytest

from collector.build import build_ready
from collector.hourly import MAX_FILES, new_files, prices_from_ready, update_chain

FULL = "20261104030000"  # stamp of the full price files the daily run took in
CODES = [f"729000000{n:04d}" for n in range(1500)]  # 9,000 prices: one bad one is under 0.1%


def partial(store, items, stamp="20261104090000", kind="Price"):
    """(file name, file content) of a partial price file: items = {barcode: price}."""
    name = f"{kind}7290000000000-001-{store}-{stamp[:8]}-{stamp[8:]}.gz"
    rows = "".join(
        f"<Item><ItemCode>{code}</ItemCode><ItemName>מוצר {code[-4:]} 1 ליטר</ItemName>"
        f"<ManufacturerName>---</ManufacturerName><ItemPrice>{price}</ItemPrice>"
        f"<bIsWeighted>0</bIsWeighted></Item>"
        for code, price in items.items()
    )
    head = f"<Root><ChainID>7290000000000</ChainID><StoreID>{store}</StoreID>"
    xml = f"{head}<Items>{rows}</Items></Root>"
    return name, xml.encode("utf-8")


class Chain:
    """A chain with six stores in the state the daily run leaves: ready files + applied.json."""

    def __init__(self, tmp_path):
        self.dir = tmp_path / "chain"
        collected = {
            f"{n:03d}": {code: f"{10 + i / 10:.2f}" for i, code in enumerate(CODES)}
            for n in range(1, 7)
        }
        products = {
            code: {"name": f"מוצר {code[-4:]} 1 ליטר", "manufacturer": "", "quantity": None,
                   "unit": "", "is_weighted": False}
            for code in CODES
        }  # fmt: skip
        applied = {str(n): FULL for n in range(1, 7)}
        assert build_ready("chain", self.dir, collected, products, applied) == 0
        self.files: dict[str, bytes] = {}

    def offer(self, *files):
        for name, content in files:
            self.files[name] = content

    def run(self, **kwargs):
        def download(name):
            if self.files[name] is None:
                raise OSError("connection reset")
            return self.files[name]

        return update_chain("chain", self.dir, list(self.files), download, pause=0, **kwargs)

    def prices(self):
        return prices_from_ready(self.dir / "ready")[0]

    def last_run(self):
        return json.loads((self.dir / "last_run.json").read_text(encoding="utf-8"))

    def applied(self):
        return json.loads((self.dir / "ready" / "applied.json").read_text(encoding="utf-8"))


@pytest.fixture
def chain(tmp_path):
    return Chain(tmp_path)


def test_prices_are_rebuilt_exactly_from_the_ready_files(chain):
    prices, products = prices_from_ready(chain.dir / "ready")
    assert sorted(prices) == ["001", "002", "003", "004", "005", "006"]
    assert prices["003"][CODES[3]] == "10.30" and len(products) == 1500


def test_only_newer_partial_price_files_of_known_stores_are_chosen():
    applied = {"1": FULL, "2": FULL}
    names = [
        "Price7290000000000-001-001-20261104-090000.gz",  # newer: yes
        "Price7290000000000-001-001-20261104-100000.gz",  # newer, later
        "Price7290000000000-001-001-20261104-0200.gz",  # older, time written with 4 digits
        "Price7290000000000-001-002-20261104-030000.gz",  # same stamp as the full file: no
        "PriceFull7290000000000-001-001-20261104-110000.gz",  # a full file: not this job's
        "Promo7290000000000-001-001-20261104-110000.gz",
        "Price7290000000000-001-099-20261104-110000.gz",  # a store the daily run did not know
        "Stores7290000000000-000-20261104-110000.gz",
    ]
    assert new_files(names, applied) == {
        "1": [
            "Price7290000000000-001-001-20261104-090000.gz",
            "Price7290000000000-001-001-20261104-100000.gz",
        ]
    }


def test_new_prices_are_taken_in_and_nothing_else_changes(chain):
    before = chain.prices()
    chain.offer(partial("002", {CODES[0]: "12.50", CODES[1]: "10.10"}))
    assert chain.run() == 0
    after = chain.prices()
    assert after["002"][CODES[0]] == "12.50"
    assert after["002"][CODES[1]] == "10.10"  # same price: unchanged
    assert {s: p for s, p in after.items() if s != "002"} == {
        s: p for s, p in before.items() if s != "002"
    }
    assert {k: v for k, v in after["002"].items() if k != CODES[0]} == {
        k: v for k, v in before["002"].items() if k != CODES[0]
    }
    assert chain.last_run()["result"] == "updated"
    assert chain.applied()["2"] == "20261104090000" and chain.applied()["1"] == FULL


def test_files_are_applied_oldest_first_and_a_later_price_wins(chain):
    chain.offer(
        partial("001", {CODES[2]: "30.00"}, stamp="20261104100000"),
        partial("001", {CODES[2]: "11.00"}, stamp="20261104090000"),
    )
    assert chain.run() == 0
    assert chain.prices()["001"][CODES[2]] == "30.00"
    assert chain.applied()["1"] == "20261104100000"


def test_a_new_product_is_added_with_its_name(chain):
    chain.offer(partial("001", {"7290999999999": "5.90"}))
    assert chain.run() == 0
    assert chain.prices()["001"]["7290999999999"] == "5.90"
    assert "7290999999999" in json.loads((chain.dir / "ready" / "products.json").read_text("utf-8"))


def test_nothing_new_leaves_the_files_alone(chain):
    ready_before = (chain.dir / "ready" / "stores.json").read_bytes()
    chain.offer(
        partial("001", {CODES[0]: "10.00"}, stamp="20261104020000")
    )  # older than the full file
    assert chain.run() == 0
    assert chain.last_run()["result"] == "nothing new"
    assert (chain.dir / "ready" / "stores.json").read_bytes() == ready_before


def test_same_prices_again_is_nothing_new_too(chain):
    chain.offer(partial("001", {CODES[0]: "10.00"}))  # the price it already has
    assert chain.run() == 0
    assert chain.last_run()["result"] == "nothing new"


def test_a_suspicious_new_price_keeps_the_old_one_in_the_store(chain):
    chain.offer(partial("004", {CODES[5]: "9999.00", CODES[6]: "11.00"}))
    assert chain.run() == 0
    prices = chain.prices()["004"]
    assert prices[CODES[5]] == "10.50"  # not 9999, and the product is still there
    assert prices[CODES[6]] == "11.00"  # the good price of the same file was taken in
    suspicious = json.loads((chain.dir / "ready" / "suspicious.json").read_text("utf-8"))
    assert [s["item_code"] for s in suspicious] == [CODES[5]]


def test_an_update_the_checks_reject_changes_nothing(chain):
    # Every store's price jumps by 10x: far more suspicious prices than allowed.
    chain.offer(*[partial(f"{n:03d}", {c: "500.00" for c in CODES}) for n in range(1, 7)])
    ready_before = (chain.dir / "ready" / "stores.json").read_bytes()
    assert chain.run() == 1
    assert chain.last_run()["result"] == "rejected"
    assert (chain.dir / "ready" / "stores.json").read_bytes() == ready_before
    assert chain.applied()["1"] == FULL  # the files will be tried again next hour


def test_a_failed_download_leaves_that_store_as_it_was(chain):
    chain.offer(
        partial("001", {CODES[0]: "20.00"}),
        partial("002", {CODES[0]: "21.00"}),
    )
    broken = "Price7290000000000-001-003-20261104-090000.gz"
    chain.files[broken] = None
    assert chain.run() == 0
    prices = chain.prices()
    assert prices["001"][CODES[0]] == "20.00" and prices["002"][CODES[0]] == "21.00"
    assert prices["003"][CODES[0]] == "10.00"
    assert chain.applied()["3"] == FULL  # so that file is tried again


def test_without_stamps_from_a_full_run_there_is_nothing_to_do(chain):
    (chain.dir / "ready" / "applied.json").unlink()
    chain.offer(partial("001", {CODES[0]: "12.00"}))
    assert chain.run() == 0
    assert chain.last_run()["result"] == "nothing new"
    assert chain.prices()["001"][CODES[0]] == "10.00"


def test_too_many_new_files_waits_for_the_full_run(chain, monkeypatch):
    monkeypatch.setattr("collector.hourly.MAX_FILES", 2)
    chain.offer(
        *[partial("001", {CODES[0]: "12.00"}, stamp=f"2026110409{n:02d}00") for n in range(3)]
    )
    assert chain.run() == 1
    assert chain.last_run()["result"] == "rejected"
    assert MAX_FILES >= 1000


def test_the_limit_caps_how_many_files_are_taken(chain):
    chain.offer(*[partial(f"{n:03d}", {CODES[0]: "13.00"}) for n in range(1, 7)])
    assert chain.run(limit=2) == 0
    prices = chain.prices()
    assert sum(prices[f"{n:03d}"][CODES[0]] == "13.00" for n in range(1, 7)) == 2
