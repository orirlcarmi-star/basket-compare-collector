"""The one internal format every connector produces (build plan step 2.1).

Chains differ in where they publish and how they encode files, but the XML
schema is set by regulation. Connectors fetch and decode; `collector.parse`
turns the XML into these records; everything downstream sees only these.
Money and quantities are Decimal — never float — so totals are exact.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


@dataclass(frozen=True)
class FileHeader:
    chain_id: str  # 13-digit chain code, e.g. "7290027600007" (Shufersal)
    sub_chain_id: str
    store_id: str  # as published, e.g. "413"


@dataclass(frozen=True)
class PriceItem:
    item_code: str  # barcode for most items; short internal codes exist too
    name: str
    manufacturer: str  # "" when the chain left it empty or wrote "---"
    quantity: Decimal | None  # amount in the package, in `unit`
    unit: str  # as published: "ליטר", "גרם", "יחידות", ...
    is_weighted: bool  # sold by weight; price is per unit of measure
    price: Decimal
    unit_price: Decimal | None
    updated_at: datetime | None


@dataclass(frozen=True)
class PriceFile:
    header: FileHeader
    items: tuple[PriceItem, ...]


class Audience(StrEnum):
    """Who a promotion is for (the file's ClubID, plus wording checks)."""

    EVERYONE = "everyone"
    CLUB = "club"  # chain club / organisation members
    CREDIT_CARD = "credit_card"


@dataclass(frozen=True)
class PromotionItem:
    item_code: str
    reward_type: str  # as published; meaning per docs/04-data-sources.md
    min_qty: Decimal | None
    discounted_price: Decimal | None


@dataclass(frozen=True)
class Promotion:
    promotion_id: str
    description: str
    starts_at: datetime | None
    ends_at: datetime | None
    audience: Audience
    is_coupon: bool
    min_purchase_amount: Decimal | None
    items: tuple[PromotionItem, ...]


@dataclass(frozen=True)
class PromoFile:
    header: FileHeader
    promotions: tuple[Promotion, ...]


@dataclass(frozen=True)
class Store:
    chain_id: str
    sub_chain_id: str
    store_id: str
    name: str
    address: str
    city: str
    is_online: bool  # the chain's "internet" store whose prices match its website
