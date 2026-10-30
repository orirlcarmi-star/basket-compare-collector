from datetime import datetime
from decimal import Decimal

from collector.deals import usable_deals
from collector.model import Audience, FileHeader, PromoFile, Promotion, PromotionItem

NOW = datetime(2026, 10, 30, 12, 0)


def promo(*items, coupon=False, min_purchase=None, ends=datetime(2026, 11, 5), pid="1"):
    return Promotion(
        promotion_id=pid,
        description="deal",
        starts_at=datetime(2026, 10, 1),
        ends_at=ends,
        audience=Audience.EVERYONE,
        is_coupon=coupon,
        min_purchase_amount=min_purchase,
        items=tuple(items),
    )


def item(code, reward, min_qty, price):
    return PromotionItem(code, reward, Decimal(min_qty), Decimal(price) if price else None)


def run(*promotions):
    return usable_deals(PromoFile(FileHeader("c", "1", "2"), tuple(promotions)), NOW)


def test_multi_buy_keeps_price_for_min_qty():
    deals, _ = run(promo(item("a", "1", "2", "20.00"), item("b", "1", "2", "20.00")))
    assert len(deals) == 1
    assert deals[0].item_codes == ("a", "b")  # any two of them
    assert (deals[0].min_qty, deals[0].price) == (Decimal(2), Decimal("20.00"))


def test_reward_10_multi_buy_by_weight():
    deals, _ = run(promo(item("cheese", "10", "0.3", "25.00")))
    assert (deals[0].min_qty, deals[0].price) == (Decimal("0.3"), Decimal("25.00"))


def test_fixed_price_is_a_unit_price_whatever_min_qty_says():
    deals, _ = run(promo(item("cheese", "3", "0.01", "109.00")))
    assert (deals[0].min_qty, deals[0].price) == (Decimal(1), Decimal("109.00"))


def test_left_out_with_reason():
    deals, skipped = run(
        promo(item("a", "3", "1", "5.00"), coupon=True),
        promo(item("a", "3", "1", "5.00"), min_purchase=Decimal(200)),
        promo(item("a", "3", "1", "5.00"), ends=datetime(2026, 10, 29)),
        promo(item("a", "2", "1", "4.75")),  # percentage discount
        promo(item("a", "1", "2", "0.00")),  # gift
    )
    assert deals == []
    assert skipped == {
        "coupon": 1,
        "minimum basket amount": 1,
        "not active now": 1,
        "type not in version 1": 2,
    }
