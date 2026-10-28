import pytest

from collector.build import Group, StoreEntry, agreement, build, group_stores, verify

SAME_A = {"milk": "7.35", "bread": "8.90", "coffee": "19.90"}
SAME_B = {"milk": "7.35", "bread": "8.90"}  # same prices, smaller stock
OTHER = {"milk": "6.90", "bread": "7.90", "coffee": "17.90"}  # discount format


def test_agreement_counts_only_shared_items():
    assert agreement(SAME_A, SAME_B) == 1.0
    assert agreement(SAME_A, OTHER) == 0.0
    assert agreement({"a": "1"}, {"b": "1"}) == 0.0


def test_stores_with_equal_prices_share_a_group():
    groups = group_stores({"1": SAME_A, "2": SAME_B, "3": OTHER})
    assert sorted(sorted(g) for g in groups) == [["1", "2"], ["3"]]


def test_one_price_difference_becomes_an_exception_not_a_loss():
    a = {f"item{i}": "10.00" for i in range(100)}
    b = dict(a, item7="9.50")  # 99% agreement: same group, one exception
    stores = {"1": a, "2": b}
    groups, entries = build(stores)
    assert len(groups) == 1
    by_store = {e.store_id: e for e in entries}
    assert by_store["2"].exceptions == {"item7": "9.50"}
    assert by_store["1"].exceptions == {}
    verify(stores, groups, entries)  # rebuilds exactly


def test_stock_differences_are_kept():
    stores = {"1": SAME_A, "2": SAME_B}
    _, entries = build(stores)
    stock = {e.store_id: e.stock for e in entries}
    assert "coffee" in stock["1"]
    assert "coffee" not in stock["2"]


def test_verify_catches_a_wrong_build():
    stores = {"1": {"milk": "7.35"}}
    groups = [Group("g1", {"milk": "7.00"}, ("1",))]
    entries = [StoreEntry("1", "g1", ("milk",), {})]
    with pytest.raises(AssertionError):
        verify(stores, groups, entries)


def test_verify_catches_a_missing_store():
    stores = {"1": {"milk": "7.35"}, "2": {"milk": "7.35"}}
    groups = [Group("g1", {"milk": "7.35"}, ("1",))]
    entries = [StoreEntry("1", "g1", ("milk",), {})]
    with pytest.raises(AssertionError):
        verify(stores, groups, entries)
