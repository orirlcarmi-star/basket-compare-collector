from datetime import UTC, datetime

from collector.files import file_date, kind_of, latest_per_store, store_and_stamp


def test_reads_store_and_stamp_with_or_without_extension():
    assert store_and_stamp("PriceFull7290027600007-001-413-20261027-030000") == (
        "413",
        "20261027030000",
    )
    assert store_and_stamp("PriceFull7290058140886-001-001-20261027-070006.gz") == (
        "001",
        "20261027070006",
    )


def test_chain_wide_files_have_no_store():
    assert store_and_stamp("Stores7290027600007-000-20261028-020") is None
    assert store_and_stamp("Stores7290058140886-000-20261027-050501.xml") is None


def test_latest_per_store_keeps_newest():
    names = [
        "PriceFull7290027600007-001-002-20261027-030000",
        "PriceFull7290027600007-001-002-20261028-030000",
        "PriceFull7290027600007-001-413-20261026-030000",
        "Stores7290027600007-000-20261028-020",
    ]
    latest = latest_per_store(names)
    assert sorted(latest) == ["002", "413"]
    assert latest["002"].endswith("20261028-030000")


def test_kind_and_date():
    assert kind_of("PriceFull7290058140886-001-001-20261027-070006.gz") == "pricefull"
    assert file_date("Price7290058140886-001-001-20261027-070006.gz") == datetime(
        2026, 10, 27, tzinfo=UTC
    )
