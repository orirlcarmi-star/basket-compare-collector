import re
from pathlib import Path

import pytest

from collector.collect import CHAINS
from collector.locate import CHAIN_NAMES
from collector.probe import describe
from collector.sources.cerberus import parse_file_list

ROOT = Path(__file__).resolve().parent.parent


def test_describe_a_collectable_chain():
    names = [
        "Stores7290873255550-000-20261027-020000.xml",
        "PriceFull7290873255550-001-001-20261027-070006.gz",
        "PriceFull7290873255550-001-002-20261027-070007.gz",
        "PromoFull7290873255550-001-001-20261027-070006.gz",
    ]
    line = describe(names)
    assert "4 files" in line and "pricefull 2" in line
    assert "chain code 7290873255550" in line
    assert "stores file: yes" in line and "full prices: yes" in line
    assert "cannot be collected" not in line


def test_describe_warns_when_collect_would_not_work():
    assert "stores file: NO" in describe(["PriceFull7290873255550-001-001-20261027-070006.gz"])
    assert "cannot be collected" in describe(["Price7290873255550-001-001-20261027-070006.gz"])
    assert "empty" in describe([])


def test_a_wrong_username_gets_a_clear_error():
    with pytest.raises(ValueError, match="wrong username"):
        parse_file_list("<html><form>login</form></html>")


def test_every_chain_has_a_hebrew_name_and_a_workflow_option():
    for chain in CHAINS:
        assert chain in CHAIN_NAMES, f"{chain}: add its Hebrew name to locate.CHAIN_NAMES"
    workflow = (ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")
    options = re.search(r"options: \[([^\]]*)\]", workflow)[1].replace(" ", "").split(",")
    assert options == CHAINS, "keep the options of collect.yml in step with collect.CHAINS"
