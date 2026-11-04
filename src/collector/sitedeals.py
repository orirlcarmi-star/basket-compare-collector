"""Deals in the website files (format 2): one small file per deal, referenced from products.

`collect` leaves, per store, the deals the calculator may use (collector.deals). This turns
them into files the browser fetches only for the products in the shopper's basket:

  product, per chain   "d": ["<deal id>", ...]            (the deals that mention it)
  d/<chain>/<n>.json   {"<deal id>": {"t", "q", "p", "m"?, "c"?, "e"?, "i", "s"?}, ...}

The deals of a chain are spread over DEAL_BUCKETS (256) files, n = FNV-1a (32 bit, over the
characters of the deal id, the same function as for the product files `p/`) modulo 256; the
id includes a variant suffix such as "-2". A bucket with no deals has no file. A basket reads
only the buckets of the deals its products mention. `read_deal` is the reference reader.

Meaning of a deal file: every q units taken from the products in i, in any mix, cost p
together; this can be applied again and again, up to m units in all (m absent: no limit);
the rest of the units cost the normal price. A fixed price per unit is q = 1. Units are the
units of the prices in the product files (items, or kilos for items sold by weight).

  t  the chain's wording of the deal (display only)
  q  units needed for one application — a whole number
  p  the price of those q units together, as an exact decimal string like the other prices
  m  most units that get the deal (the chain's MaxQty); applications = floor(m / q)
  c  true when only the chain's club members get it (left out otherwise)
  e  when it ends, "YYYY-MM-DDTHH:MM" on Israel's clock; after that it is not valid
     (absent: the chain gave no end)
  i  barcodes that take part (only products that the chain sells in the files)
  s  where it applies, absent = in every store of the chain; otherwise a list whose elements are
     price-group ids (a string such as "g1" = every store of that group) and store positions
     (an integer = that place in stores.json chains.<chain>.ids). A group is named only when
     the deal applies in all its stores, and the shortest list is written.

A promotion id whose terms differ between stores (another q, p, m, club flag or end) gets one
file per variant: "<id>", "<id>-2", "<id>-3" ... — the variant in most stores has the plain id.
Wording alone does not make a variant, and neither do the items: every store sells other
kinds ("2 for 13.90 on herbs" lists 3, 4 or 5 barcodes depending on the store), so stores with
the same terms share one file whose `i` is all their barcodes together and whose `s` is all their
stores together. That is safe because the calculator only prices products a store really
sells; the one assumption is that a store's own deal list names every product it sells that takes
part (what the chain publishes for the store). Without this merge six Shufersal stores made 1,993
files, 674 of them only differing in `i`.

Left out, and counted: coupons and deals needing a minimum basket (not usable, by deals.py),
credit-card deals (the file has only a club flag, and showing them to everyone would be wrong),
quantities that are not whole numbers (300 g for 25: no whole q in the units of the prices),
deals already over, deals that could never apply (a limit below q), and deals none of whose
items the chain sells.
"""

import json
import re
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from collector.files import same_store

_UNSAFE = re.compile(r"[^0-9A-Za-z_-]")

DEAL_BUCKETS = 256


def fnv1a(text: str) -> int:
    """FNV-1a, 32 bit, over the character codes of the text (what the website also computes)."""
    h = 0x811C9DC5
    for char in text:
        h ^= ord(char)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def deal_bucket(deal_id: str) -> int:
    """The number n of the file d/<chain>/<n>.json that holds this deal."""
    return fnv1a(deal_id) % DEAL_BUCKETS


def bucket_deals(files: dict[str, dict]) -> dict[int, dict[str, dict]]:
    """deal id -> deal  ->  bucket number -> {deal id: deal} (ids in order, so files are stable)."""
    buckets: dict[int, dict[str, dict]] = {}
    for deal_id in sorted(files):
        buckets.setdefault(deal_bucket(deal_id), {})[deal_id] = files[deal_id]
    return buckets


def read_deal(site_dir: Path, chain: str, deal_id: str) -> dict | None:
    """The deal with this id, read the way the website does: from its bucket file."""
    path = site_dir / "d" / chain / f"{deal_bucket(deal_id)}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get(deal_id)


def load_store_deals(deals_dir: Path) -> dict[str, list[dict]]:
    """store number (leading zeros dropped) -> the deals `collect` wrote for it."""
    return {
        same_store(path.stem): json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(deals_dir.glob("*.json"))
    }


def _whole(number: Decimal) -> int | None:
    return int(number) if number == number.to_integral_value() else None


def _minute(iso: str | None) -> str | None:
    return iso[:16] if iso else None  # "2026-11-05T23:59:59" -> "2026-11-05T23:59"


def _term(deal: dict, sold: set[str], now: datetime) -> tuple[tuple | None, set[str], str | None]:
    """(the deal's terms as a hashable key, its items the chain sells, the reason it is left out).

    The key is what makes two deals the same: promotion id, q, p, m, club flag and end. The
    items are not part of it (see the module text)."""
    if deal["audience"] == "credit_card":
        return None, set(), "credit-card deal"
    quantity = _whole(Decimal(deal["min_qty"]))
    if quantity is None or quantity < 1:
        return None, set(), "quantity not a whole number"
    ends = _minute(deal.get("ends_at"))
    if deal.get("ends_at") and datetime.fromisoformat(deal["ends_at"]) < now:
        return None, set(), "already over"
    items = {c for c in deal["item_codes"] if c in sold}
    if not items:
        return None, set(), "no item sold in the files"
    cap = Decimal(deal["max_qty"]) if deal.get("max_qty") else None
    if cap is not None and cap < quantity:
        return None, set(), "limit below the quantity needed"  # it could never apply
    max_units = int(cap) if cap is not None else None
    key = (
        deal["promotion_id"],
        quantity,
        str(Decimal(deal["price"])),
        max_units,
        deal["audience"] == "club",
        ends,
    )
    return key, items, None


def shortest_places(positions: set[int], groups: list[str]) -> list | None:
    """The `s` list for a set of store positions; None when it is every store of the chain."""
    if len(positions) == len(groups):
        return None
    members: dict[str, set[int]] = {}
    for position, group in enumerate(groups):
        members.setdefault(group, set()).add(position)
    whole = sorted(g for g, m in members.items() if m <= positions)
    covered = set().union(*(members[g] for g in whole)) if whole else set()
    return whole + sorted(positions - covered)


def places_to_positions(places: list | None, groups: list[str]) -> set[int]:
    """Inverse of `shortest_places`."""
    if places is None:
        return set(range(len(groups)))
    chosen = {p for p in places if isinstance(p, int)}
    for group in (p for p in places if isinstance(p, str)):
        chosen |= {i for i, g in enumerate(groups) if g == group}
    return chosen


def build_chain_deals(
    store_deals: Mapping[str, list[dict]],
    index: Mapping[str, list],
    sold: set[str],
    now: datetime,
) -> tuple[dict[str, dict], dict[str, list[str]], Counter[str]]:
    """(deal id -> file content, barcode -> deal ids, why deals were left out)."""
    position = {store_id: i for i, store_id in enumerate(index["ids"])}
    groups = list(index["groups"])
    skipped: Counter[str] = Counter()
    where: dict[tuple, set[int]] = {}
    items_of: dict[tuple, set[str]] = {}
    wording: dict[tuple, Counter[str]] = {}
    for store_id, deals in store_deals.items():
        if store_id not in position:
            skipped["store not in the files"] += len(deals)
            continue
        for deal in deals:
            key, items, reason = _term(deal, sold, now)
            if key is None:
                skipped[reason] += 1
                continue
            where.setdefault(key, set()).add(position[store_id])
            items_of.setdefault(key, set()).update(items)
            wording.setdefault(key, Counter())[deal["description"]] += 1

    by_promotion: dict[str, list[tuple]] = {}
    for key in where:
        by_promotion.setdefault(key[0], []).append(key)
    files: dict[str, dict] = {}
    by_item: dict[str, list[str]] = {}
    for promotion_id, keys in sorted(by_promotion.items()):
        # the variant in most stores first, then by terms: the same data gives the same ids
        keys.sort(key=lambda k: (-len(where[k]), k[1], k[2], k[3] or 0, k[4], k[5] or ""))
        for number, key in enumerate(keys, start=1):
            base = _UNSAFE.sub("_", promotion_id) or "x"
            deal_id = base if number == 1 else f"{base}-{number}"
            _, quantity, price, max_units, club, ends = key
            items = sorted(items_of[key])
            content: dict = {
                "t": wording[key].most_common(1)[0][0],
                "q": quantity,
                "p": price,
            }
            if max_units:
                content["m"] = max_units
            if club:
                content["c"] = True
            if ends:
                content["e"] = ends
            content["i"] = items
            places = shortest_places(where[key], groups)
            if places is not None:
                content["s"] = places
            files[deal_id] = content
            for code in items:
                by_item.setdefault(code, []).append(deal_id)
    return files, by_item, skipped
