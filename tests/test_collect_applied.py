import json

from collector.collect import StoreWork, _write_chain

STORES = (
    "<Root><ChainID>7290000000000</ChainID><SubChains><SubChain><SubChainID>1</SubChainID><Stores>"
    "<Store><StoreID>002</StoreID><StoreName>סניף</StoreName><Address>א</Address><City>חיפה</City></Store>"
    "</Stores></SubChain></SubChains></Root>"
)
PRICES = (
    "<Root><ChainID>7290000000000</ChainID><SubChainID>1</SubChainID><StoreID>002</StoreID><Items>"
    "<Item><ItemCode>1</ItemCode><ItemName>חלב</ItemName><ItemPrice>7.35</ItemPrice></Item>"
    "</Items></Root>"
)


def test_collect_records_the_stamp_of_each_full_file_for_the_hourly_update(tmp_path):
    def price(name):
        return lambda: (name, PRICES.encode("utf-8"))

    def broken():
        raise OSError("reset")  # a store that fails gets no stamp, so it is not taken as known

    work = {
        "002": StoreWork(price("PriceFull7290000000000-001-002-20261104-0300.gz"), lambda: None),
        "003": StoreWork(broken, lambda: None),
        "004": StoreWork(lambda: None, lambda: None),  # a store with no price file: not a failure
    }
    failures = _write_chain(tmp_path / "chain", STORES.encode("utf-8"), work, None)
    assert failures == 1
    applied = json.loads((tmp_path / "chain" / "applied.json").read_text(encoding="utf-8"))
    assert applied == {"2": "20261104030000"}  # "0300" is 03:00:00; "002" is store 2


def test_a_failing_promotion_file_does_not_lose_the_price_file(tmp_path):
    def promo():
        raise OSError("reset")

    work = {"002": StoreWork(lambda: ("PriceFull7290000000000-001-002-20261104-030000.gz",
                                      PRICES.encode("utf-8")), promo)}  # fmt: skip
    assert _write_chain(tmp_path / "chain", STORES.encode("utf-8"), work, None) == 1
    assert (tmp_path / "chain" / "prices" / "002.json").exists()  # the prices are there
