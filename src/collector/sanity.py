"""Sanity checks on collected prices before they become ready-made files (build step 3.2).

Two levels (docs/05-data-model.md):
- A single suspicious price is set aside: it is left out of the ready-made files, so
  the site never shows it as a fact, and listed for review.
- A whole update that looks broken is rejected: the ready-made files are not replaced,
  so the site keeps the previous prices.

Thresholds come from all of Shufersal (2026-10-29, 2.33M prices): no zero prices; 30
prices 3-5x away from the chain's usual price, all plausible (clearance, local deals);
one obvious error at 840x (tomato at 10,000 per kilo). Hence 10x.

A third check looks back: the usual price of each item is kept from the previous update
(`previous_usual.json`, one price per item, simply written), and a price that is several
times above that is set aside too. It catches what the other check cannot: a whole chain
suddenly wrong in the same way (prices in agorot, a shifted column), where every store
agrees with every other store. Only rises are checked: a price falling many times is
usually a real clearance, and a rise of 5x or more in a day almost never is.
"""

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

# A price this many times above or below the chain's usual price for the item is suspicious.
OUTLIER_FACTOR = Decimal(10)
# A price this many times above the item's usual price in the previous update is suspicious.
# (Rises of 2-3x overnight happen with real price changes; 5x is where they stop.)
JUMP_FACTOR = Decimal(5)
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
    usual: str  # the usual price for the item (today's, or the previous update's), or ""
    reason: str


def _ratio(price: Decimal, usual: Decimal) -> Decimal:
    return max(price / usual, usual / price)


def usual_prices(stores: Mapping[str, Prices]) -> dict[str, str]:
    """The chain's usual price (the median over stores) of each item that enough stores sell."""
    by_item: dict[str, list[Decimal]] = {}
    for prices in stores.values():
        for code, price in prices.items():
            by_item.setdefault(code, []).append(Decimal(price))
    return {
        code: str(statistics.median(values))
        for code, values in by_item.items()
        if len(values) >= MIN_STORES_FOR_USUAL
    }


def screen(
    stores: Mapping[str, Prices], previous: Mapping[str, str] | None = None
) -> tuple[dict[str, dict[str, str]], list[Suspicious]]:
    """Split prices into those safe to show and those set aside as suspicious.

    `previous` is `usual_prices` of the previous update, when there is one."""
    usual = {code: Decimal(price) for code, price in usual_prices(stores).items()}
    before = {code: Decimal(price) for code, price in (previous or {}).items()}

    clean: dict[str, dict[str, str]] = {}
    suspicious: list[Suspicious] = []
    for store, prices in stores.items():
        kept = {}
        for code, text in prices.items():
            price, typical, last = Decimal(text), usual.get(code), before.get(code)
            if price <= 0:
                suspicious.append(Suspicious(store, code, text, str(typical or ""), "zero"))
            elif typical and typical > 0 and _ratio(price, typical) >= OUTLIER_FACTOR:
                suspicious.append(Suspicious(store, code, text, str(typical), "far from usual"))
            elif last and last > 0 and price / last >= JUMP_FACTOR:
                suspicious.append(
                    Suspicious(store, code, text, str(last), "jumped since last update")
                )
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
