from collector.sanity import Summary, screen, update_problems, usual_prices


def chain(**extra: dict[str, str]) -> dict[str, dict[str, str]]:
    """Six stores selling tomatoes at 11.90, plus any extra stores given."""
    stores = {str(i): {"tomato": "11.90", "milk": "7.35"} for i in range(6)}
    stores.update(extra)
    return stores


def test_normal_prices_pass():
    clean, suspicious = screen(chain())
    assert suspicious == []
    assert clean == chain()


def test_far_price_is_set_aside_not_shown():
    clean, suspicious = screen(chain(bad={"tomato": "10000.00", "milk": "7.35"}))
    assert clean["bad"] == {"milk": "7.35"}
    assert [(s.store_id, s.item_code, s.reason) for s in suspicious] == [
        ("bad", "tomato", "far from usual")
    ]


def test_real_deals_are_kept():
    # 4.7x cheaper (clearance) and 3x dearer: plausible, below the 10x threshold.
    clean, suspicious = screen(chain(sale={"tomato": "2.50"}, dear={"tomato": "35.90"}))
    assert suspicious == []
    assert clean["sale"] == {"tomato": "2.50"}


def test_zero_price_is_set_aside_even_without_a_usual_price():
    clean, suspicious = screen({"1": {"rare": "0.00", "milk": "7.35"}})
    assert clean == {"1": {"milk": "7.35"}}
    assert suspicious[0].reason == "zero"


def test_no_usual_price_when_few_stores_sell_it():
    # Two stores only: cannot tell which one is wrong, so both are kept.
    _, suspicious = screen({"1": {"x": "1.00"}, "2": {"x": "50.00"}})
    assert suspicious == []


def test_healthy_update_has_no_problems():
    assert update_problems(Summary(400, 2_000_000), 1, Summary(410, 2_050_000)) == []
    assert update_problems(Summary(400, 2_000_000), 1) == []  # first build


def test_update_losing_many_stores_is_rejected():
    problems = update_problems(Summary(200, 1_000_000), 0, Summary(416, 2_300_000))
    assert len(problems) == 2


def test_update_with_many_suspicious_prices_is_rejected():
    # e.g. prices read in agorot instead of shekels
    assert update_problems(Summary(10, 10_000), 500) == ["500 suspicious prices out of 10,000"]


def test_price_that_jumped_since_the_last_update_is_set_aside():
    # Every store agrees (a whole chain wrong the same way), so only yesterday's usual
    # price shows it: milk 7.35 yesterday, 73.50 today in all six stores.
    today = {str(i): {"milk": "73.50", "tomato": "11.90"} for i in range(6)}
    yesterday = usual_prices(chain())
    assert yesterday == {"tomato": "11.90", "milk": "7.35"}
    clean, suspicious = screen(today, yesterday)
    assert all(c == {"tomato": "11.90"} for c in clean.values())
    assert {(s.item_code, s.usual, s.reason) for s in suspicious} == {
        ("milk", "7.35", "jumped since last update")
    }
    assert len(suspicious) == 6


def test_moderate_rise_and_any_fall_since_the_last_update_are_kept():
    yesterday = {"milk": "7.35", "tomato": "11.90"}
    today = {str(i): {"milk": "14.70", "tomato": "2.38"} for i in range(6)}  # 2x up, 5x down
    clean, suspicious = screen(today, yesterday)
    assert suspicious == []
    assert clean == today


def test_first_update_and_new_items_have_nothing_to_compare_with():
    assert screen(chain())[1] == []
    assert screen(chain(), {"other": "1.00"})[1] == []


def test_usual_price_needs_enough_stores():
    assert usual_prices({"1": {"x": "1.00"}, "2": {"x": "2.00"}}) == {}
