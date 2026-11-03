import json

from collector.collect import _write_chain

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
    names = {
        "002": "PriceFull7290000000000-001-002-20261104-0300.gz",
        "003": "PriceFull7290000000000-001-003-20261104-030000.gz",
    }
    asked = []

    def download(name):
        asked.append(name)
        if "-003-" in name:
            raise OSError("reset")  # a store that fails gets no stamp, so it is not taken as known
        return PRICES.encode("utf-8")

    failures = _write_chain(tmp_path / "chain", STORES.encode("utf-8"), names, {}, download, None)
    assert failures == 1
    applied = json.loads((tmp_path / "chain" / "applied.json").read_text(encoding="utf-8"))
    assert applied == {"2": "20261104030000"}  # "0300" is 03:00:00; "002" is store 2
