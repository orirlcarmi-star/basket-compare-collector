"""Price per kilo, per litre or per unit, the same way for every product (build task 4).

Chains publish their own "price per unit of measure", but in whatever unit they like
("100 גרם", "ליטר", "יחידה"), so two chains cannot be compared by it. This works from
the price and the normalised package size (collector.attributes) instead:

- volume -> price per litre, weight -> price per kilo, count -> price per unit;
- an item sold by weight is priced per kilo already, and stays so;
- no known size -> no unit price (never a guess).

The website divides the shopper's price by `contents()` of the product, which is why that
number is what the published product files carry.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from collector.attributes import COUNT, VOLUME, WEIGHT, Size

_BASE = {VOLUME: ("l", Decimal(1000)), WEIGHT: ("kg", Decimal(1000)), COUNT: ("unit", Decimal(1))}


@dataclass(frozen=True)
class UnitPrice:
    amount: Decimal  # shekels, two decimals
    per: str  # "l", "kg" or "unit"


def contents(size: Size) -> tuple[Decimal, str]:
    """How much the package holds in its base unit: 1500 ml -> (1.5, "l")."""
    base, factor = _BASE[size.kind]
    amount = size.amount / factor
    return Decimal(format(amount.normalize(), "f")), base


def unit_price(price: Decimal, size: Size | None) -> UnitPrice | None:
    if size is None or size.amount <= 0:
        return None
    holds, base = contents(size)
    return UnitPrice((price / holds).quantize(Decimal("0.01"), ROUND_HALF_UP), base)
