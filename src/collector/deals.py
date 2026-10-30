"""Which promotions the basket calculator may use, in one simple shape (build step 2.6).

Read from Shufersal's files (store 002, 2026-10-30, 1,463 promotions):
- DiscountedPrice is the price of MinQty units: "2ב20" -> MinQty 2, 20.00; by weight
  "300ב25" -> MinQty 0.3 (kg), 25.00. Fixed-price deals (reward type 3) give the unit
  price whatever MinQty says ("109 גבינה במשקל" -> MinQty 0.01, 109.00 per kg).
- Reward types 1 and 10 are both multi-buy deals; 3 is a fixed price.
- Kept out in version 1 (docs/12-build-plan.md): coupons, deals needing a minimum basket
  amount, percentage discounts (2), gifts and "2+1" lists (0), other types.

Club and credit-card deals are kept with their audience: the calculator uses them only
for shoppers who said they are members.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from collector.model import PromoFile

FIXED_PRICE = "3"
MULTI_BUY = {"1", "10"}


@dataclass(frozen=True)
class Deal:
    promotion_id: str
    description: str
    audience: str  # "everyone", "club" or "credit_card"
    ends_at: datetime | None
    item_codes: tuple[str, ...]  # any of these items count towards min_qty
    min_qty: Decimal  # units, or kilos for items sold by weight
    price: Decimal  # for min_qty units together


def usable_deals(promo_file: PromoFile, now: datetime) -> tuple[list[Deal], Counter[str]]:
    """Deals active now that version 1 can price; also why the others were left out."""
    deals: list[Deal] = []
    skipped: Counter[str] = Counter()
    for promo in promo_file.promotions:
        if promo.is_coupon:
            skipped["coupon"] += 1
        elif promo.min_purchase_amount:
            skipped["minimum basket amount"] += 1
        elif (promo.starts_at and promo.starts_at > now) or (promo.ends_at and promo.ends_at < now):
            skipped["not active now"] += 1
        else:
            # One promotion may hold several offers; group items that share one.
            offers: dict[tuple[str, Decimal, Decimal], list[str]] = {}
            for item in promo.items:
                if item.discounted_price is None or item.discounted_price <= 0:
                    continue
                if item.reward_type == FIXED_PRICE:
                    key = (item.reward_type, Decimal(1), item.discounted_price)
                elif item.reward_type in MULTI_BUY and item.min_qty and item.min_qty > 0:
                    key = (item.reward_type, item.min_qty, item.discounted_price)
                else:
                    continue
                offers.setdefault(key, []).append(item.item_code)
            if not offers:
                skipped["type not in version 1"] += 1
            for (_, min_qty, price), codes in offers.items():
                deals.append(
                    Deal(
                        promotion_id=promo.promotion_id,
                        description=promo.description,
                        audience=promo.audience.value,
                        ends_at=promo.ends_at,
                        item_codes=tuple(sorted(codes)),
                        min_qty=min_qty,
                        price=price,
                    )
                )
    return deals, skipped
