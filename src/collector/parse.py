"""Parse the regulated price-transparency XML into `collector.model` records.

All chains share one schema, but tag case varies (ItemCode / ITEMCODE, StoreID /
StoreId), so every lookup here is case-insensitive.
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation

from collector.model import (
    Audience,
    FileHeader,
    PriceFile,
    PriceItem,
    PromoFile,
    Promotion,
    PromotionItem,
    Store,
)

_EMPTY_MAKERS = {"", "---", "לא ידוע"}
_ONLINE_STORE = re.compile(r"אינטרנט|אונליין|online", re.IGNORECASE)
_CREDIT_WORDING = re.compile(r"אשראי|SBOX", re.IGNORECASE)
_CLUB_WORDING = re.compile(r"מועדון|חברי")
_COUPON_WORDING = re.compile(r"קופון")
_REWARD_CREDIT = "12"


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def _fields(element: ET.Element) -> dict[str, str]:
    """Direct children as {lower-case tag: stripped text}."""
    return {_tag(child): (child.text or "").strip() for child in element}


def _find_all(root: ET.Element, tag: str) -> Iterable[ET.Element]:
    tag = tag.lower()
    return (el for el in root.iter() if _tag(el) == tag)


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value) if value else None
    except InvalidOperation:
        return None


def _datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None


def _header(root: ET.Element) -> FileHeader:
    top = _fields(root)
    return FileHeader(
        chain_id=top.get("chainid", ""),
        sub_chain_id=top.get("subchainid", ""),
        store_id=top.get("storeid", ""),
    )


def parse_price_file(text: str) -> PriceFile:
    root = ET.fromstring(text)
    items = []
    for element in root.iter():
        f = _fields(element)
        code, price = f.get("itemcode", ""), _decimal(f.get("itemprice", ""))
        if not code or price is None:
            continue  # not an item element, or an item without a usable price
        maker = f.get("manufacturername", "")
        items.append(
            PriceItem(
                item_code=code,
                name=f.get("itemname", "") or f.get("manufactureritemdescription", ""),
                manufacturer="" if maker in _EMPTY_MAKERS else maker,
                quantity=_decimal(f.get("quantity", "")),
                unit=f.get("unitqty", ""),
                is_weighted=f.get("bisweighted", "").lower() in {"1", "true"},
                price=price,
                unit_price=_decimal(f.get("unitofmeasureprice", "")),
                updated_at=_datetime(f.get("priceupdatetime", "")),
            )
        )
    return PriceFile(header=_header(root), items=tuple(items))


def classify_audience(club_id: str, description: str, reward_types: Iterable[str]) -> Audience:
    """ClubID alone is not reliable (a credit-card deal was seen marked "0 - everyone")."""
    rewards = set(reward_types)
    if club_id.startswith("2") or _REWARD_CREDIT in rewards or _CREDIT_WORDING.search(description):
        return Audience.CREDIT_CARD
    if club_id.startswith(("1", "3")) or _CLUB_WORDING.search(description):
        return Audience.CLUB
    return Audience.EVERYONE


def parse_promo_file(text: str) -> PromoFile:
    root = ET.fromstring(text)
    promotions = []
    for element in _find_all(root, "promotion"):
        f = _fields(element)
        items = tuple(
            PromotionItem(
                item_code=i.get("itemcode", ""),
                reward_type=i.get("rewardtype", ""),
                min_qty=_decimal(i.get("minqty", "")),
                discounted_price=_decimal(i.get("discountedprice", "")),
            )
            for i in (_fields(el) for el in _find_all(element, "promotionitem"))
            if i.get("itemcode")
        )
        rewards = [i.reward_type for i in items]
        description = f.get("promotiondescription", "")
        min_purchase = [
            _decimal(_fields(g).get("minpurchaseamount", "")) for g in _find_all(element, "group")
        ]
        promotions.append(
            Promotion(
                promotion_id=f.get("promotionid", ""),
                description=description,
                starts_at=_datetime(f.get("promotionstartdatetime", "")),
                ends_at=_datetime(f.get("promotionenddatetime", "")),
                audience=classify_audience(f.get("clubid", ""), description, rewards),
                is_coupon=f.get("additionaliscoupon", "") == "1"
                or bool(_COUPON_WORDING.search(description)),
                min_purchase_amount=next((m for m in min_purchase if m), None),
                items=items,
            )
        )
    return PromoFile(header=_header(root), promotions=tuple(promotions))


def parse_stores_file(text: str) -> tuple[Store, ...]:
    root = ET.fromstring(text)
    chain_id = _fields(root).get("chainid", "")
    stores = []
    for sub_chain in _find_all(root, "subchain"):
        sub_chain_id = _fields(sub_chain).get("subchainid", "")
        for element in _find_all(sub_chain, "store"):
            f = _fields(element)
            name = f.get("storename", "")
            stores.append(
                Store(
                    chain_id=chain_id,
                    sub_chain_id=sub_chain_id,
                    store_id=f.get("storeid", ""),
                    name=name,
                    address=f.get("address", ""),
                    city=f.get("city", ""),
                    is_online=bool(_ONLINE_STORE.search(name)),
                )
            )
    return tuple(stores)
