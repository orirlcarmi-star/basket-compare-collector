"""Sanity checks on collected prices before they become ready-made files (build step 3.2).

Two levels (docs/05-data-model.md):
- A single suspicious price is set aside: it is left out of the ready-made files, so
  the site never shows it as a fact, and listed for review.
- A whole update that looks broken is rejected: the ready-made files are not replaced,
  so the site keeps the previous prices.

Thresholds come from all of Shufersal (2026-10-29, 2.33M prices): no zero prices; 30
prices 3-5x away from the chain's usual price, all plausible (clearance, local deals);
one obvious error at 840x (tomato at 10,000 per kilo). Hence 10x.
"""

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

# A price this many times above or below the chain's usual price for the item is suspicious.
OUTLIER_FACTOR = Decimal(10)
# The usual price is only trusted when at least this many stores sell the item.
MIN_STORES_FOR_USUAL = 5
# An update is rejected when, compared with the previous one, it lost more than this
# share of its stores or of its prices (a source failing half way, a format change).
MAX_DROP = 0.2
# ... or when more than this share of its prices is suspicious (prices read wrongly).
MAX_SUSPICIOUS_SHARE = 0.001

Prices = Mapping[str, str]  # item code -> price as an exact decimal string


@dataclass(frozen=True)
class Suspicious:
    store_id: str
    item_code: str
    price: str
    usual: str  # the chain's usual price for the item, or "" when there is none
    reason: str


def _ratio(price: Decimal, usual: Decimal) -> Decimal:
    return max(price / usual, usual / price)


def screen(stores: Mapping[str, Prices]) -> tuple[dict[str, dict[str, str]], list[Suspicious]]:
    """Split prices into those safe to show and those set aside as suspicious."""
    by_item: dict[str, list[Decimal]] = {}
    for prices in stores.values():
        for code, price in prices.items():
            by_item.setdefault(code, []).append(Decimal(price))
    usual = {
        code: statistics.median(values)
        for code, values in by_item.items()
        if len(values) >= MIN_STORES_FOR_USUAL
    }

    clean: dict[str, dict[str, str]] = {}
    suspicious: list[Suspicious] = []
    for store, prices in stores.items():
        kept = {}
        for code, text in prices.items():
            price, typical = Decimal(text), usual.get(code)
            if price <= 0:
                suspicious.append(Suspicious(store, code, text, str(typical or ""), "zero"))
            elif typical and typical > 0 and _ratio(price, typical) >= OUTLIER_FACTOR:
                suspicious.append(Suspicious(store, code, text, str(typical), "far from usual"))
            else:
                kept[code] = text
        clean[store] = kept
    return clean, suspicious


@dataclass(frozen=True)
class Summary:
    stores: int
    prices: int


def summarize(stores: Mapping[str, Prices]) -> Summary:
    return Summary(stores=len(stores), prices=sum(len(p) for p in stores.values()))


def update_problems(
    current: Summary, suspicious: int, previous: Summary | None = None
) -> list[str]:
    """Reasons to reject this update; empty when it may go live."""
    problems = []
    if current.prices and suspicious / current.prices > MAX_SUSPICIOUS_SHARE:
        problems.append(f"{suspicious:,} suspicious prices out of {current.prices:,}")
    if previous:
        for name, now, before in (
            ("stores", current.stores, previous.stores),
            ("prices", current.prices, previous.prices),
        ):
            if before and (before - now) / before > MAX_DROP:
                problems.append(f"{name} dropped from {before:,} to {now:,}")
    return problems
