import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from collector.collect import fresh_only
from collector.model import Audience, FileHeader, PriceFile, PriceItem, Promotion
from collector.store_output import to_json


def test_prices_round_trip_as_exact_strings():
    item = PriceItem("729", "חלב", "", Decimal("1.00"), "ליטר", False, Decimal("7.35"), None, None)
    data = json.loads(to_json(PriceFile(FileHeader("1", "001", "002"), (item,))))
    assert data["items"][0]["price"] == "7.35"
    assert data["items"][0]["name"] == "חלב"
    assert data["header"]["store_id"] == "002"


def test_enums_and_dates_become_plain_values():
    promo = Promotion("9", "x", datetime(2026, 10, 1), None, Audience.CLUB, False, None, ())
    data = json.loads(to_json(promo))
    assert data["audience"] == "club"
    assert data["starts_at"] == "2026-10-01T00:00:00"


def test_rejects_non_dataclasses():
    with pytest.raises(TypeError):
        to_json({"a": 1})


def test_fresh_only_drops_old_and_unnamed_files():
    now = datetime(2026, 10, 29, tzinfo=UTC)
    names = [
        "PriceFull7290027600007-001-002-20261028-030000",
        "PriceFull7290027600007-001-003-20260712-030000",
        "Stores7290027600007-000-20261028-020",
    ]
    assert fresh_only(names, now) == ["PriceFull7290027600007-001-002-20261028-030000"]
