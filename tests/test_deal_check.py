import json
from decimal import Decimal

import pytest

from collector.deal_check import check, check_chain
from collector.deal_check import main as check_main

D = Decimal


@pytest.mark.parametrize(
    ("description", "min_qty", "price", "verdict"),
    [
        ("2ב20", "2", "20.00", "ok"),
        ("3 ב-30 ₪", "3", "30.00", "ok"),
        ("מבצע 2 ב 15.90", "2", "15.90", "ok"),
        ("300 גרם ב-25", "0.3", "25.00", "ok"),  # kilos written as grams
        ("109 גבינה במשקל", "1", "109.00", "ok"),  # a quantity of 1 is not written
        ("1+1 ב 12.5", "2", "12.50", "ok"),
        ("3 ב-30", "3", "10.00", "price not in wording"),  # the per-unit misreading
        ("4 ב-20", "2", "20.00", "quantity not in wording"),
        ("מבצע השבוע", "2", "20.00", "no numbers"),
    ],
)
def test_reading_versus_wording(description, min_qty, price, verdict):
    assert check(description, D(min_qty), D(price)) == verdict


def write_deals(tmp_path, chain, deals):
    folder = tmp_path / chain / "deals"
    folder.mkdir(parents=True)
    rows = [
        {"promotion_id": str(i), "description": d, "min_qty": q, "price": p}
        for i, (d, q, p) in enumerate(deals)
    ]
    (folder / "001.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return folder


def test_counts_and_examples(tmp_path):
    folder = write_deals(
        tmp_path, "c", [("2ב20", "2", "20.00"), ("3 ב-30", "3", "10.00"), ("בלי מספרים", "2", "5")]
    )
    results, examples = check_chain(folder)
    assert dict(results) == {"ok": 1, "price not in wording": 1, "no numbers": 1}
    assert len(examples) == 1 and "3 ב-30" in examples[0]


def test_a_chain_read_wrongly_fails_the_check(tmp_path, capsys):
    # Every "3 ב-30" read as 3 units for 10.00: the reward code means a unit price here.
    write_deals(tmp_path, "wrong", [(f"3 ב-{n}", "3", str(n / 3)) for n in range(30, 60, 3)])
    assert check_main(["wrong", "--data", str(tmp_path)]) == 1
    assert "may mean something else" in capsys.readouterr().out

    write_deals(tmp_path, "right", [(f"2 ב-{n}", "2", f"{n}.00") for n in range(10, 20)])
    assert check_main(["right", "--data", str(tmp_path)]) == 0
