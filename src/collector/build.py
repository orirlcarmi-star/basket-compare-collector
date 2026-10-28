"""Build the ready-made files from one chain's collected prices (build steps 3.1–3.2).

Stores whose prices agree are grouped; each group keeps one price list, and each
store keeps only its exceptions and the list of what it stocks
(docs/05-data-model.md). Nothing is lost: after building, every store's prices
are rebuilt from the ready-made files and compared with the originals, and the
build fails on a single mismatch.

Usage:  python -m collector.build <chain> --data data
Reads data/<chain>/prices/*.json, writes data/<chain>/ready/.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Two stores belong together when at least this share of the items they both sell
# have the same price. Only affects how compact the result is, never correctness.
SAME_GROUP = 0.985

Prices = Mapping[str, str]  # item code -> price as an exact decimal string


@dataclass(frozen=True)
class Group:
    group_id: str
    base: dict[str, str]
    stores: tuple[str, ...]


@dataclass(frozen=True)
class StoreEntry:
    store_id: str
    group_id: str
    stock: tuple[str, ...]  # item codes the store sells
    exceptions: dict[str, str]  # item code -> price that differs from the group list


def agreement(a: Prices, b: Prices) -> float:
    common = a.keys() & b.keys()
    if not common:
        return 0.0
    return sum(a[c] == b[c] for c in common) / len(common)


def group_stores(stores: Mapping[str, Prices]) -> list[list[str]]:
    """Greedy: biggest stores first, each joins the first group whose founder it matches."""
    groups: list[list[str]] = []
    for store in sorted(stores, key=lambda s: (-len(stores[s]), s)):
        for members in groups:
            if agreement(stores[members[0]], stores[store]) >= SAME_GROUP:
                members.append(store)
                break
        else:
            groups.append([store])
    return groups


def build(stores: Mapping[str, Prices]) -> tuple[list[Group], list[StoreEntry]]:
    groups, entries = [], []
    for number, members in enumerate(group_stores(stores), start=1):
        group_id = f"g{number}"
        votes: dict[str, Counter[str]] = {}
        for store in members:
            for code, price in stores[store].items():
                votes.setdefault(code, Counter())[price] += 1
        base = {code: counts.most_common(1)[0][0] for code, counts in votes.items()}
        groups.append(Group(group_id, base, tuple(sorted(members))))
        for store in members:
            prices = stores[store]
            entries.append(
                StoreEntry(
                    store_id=store,
                    group_id=group_id,
                    stock=tuple(sorted(prices)),
                    exceptions={c: p for c, p in prices.items() if base[c] != p},
                )
            )
    return groups, entries


def rebuild(group: Group, entry: StoreEntry) -> dict[str, str]:
    return {code: entry.exceptions.get(code, group.base[code]) for code in entry.stock}


def verify(stores: Mapping[str, Prices], groups: list[Group], entries: list[StoreEntry]) -> None:
    """Raise if any store's rebuilt prices differ from what the chain published."""
    by_id = {g.group_id: g for g in groups}
    for entry in entries:
        if rebuild(by_id[entry.group_id], entry) != dict(stores[entry.store_id]):
            raise AssertionError(f"store {entry.store_id}: rebuilt prices do not match")
    if {e.store_id for e in entries} != set(stores):
        raise AssertionError("some stores are missing from the build")


def load_chain(prices_dir: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict]]:
    stores: dict[str, dict[str, str]] = {}
    products: dict[str, dict] = {}
    for path in sorted(prices_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        store_prices = {}
        for item in data["items"]:
            store_prices[item["item_code"]] = item["price"]
            products.setdefault(
                item["item_code"],
                {k: item[k] for k in ("name", "manufacturer", "quantity", "unit", "is_weighted")},
            )
        stores[data["header"]["store_id"]] = store_prices
    return stores, products


def write_ready(out: Path, groups: list[Group], entries: list[StoreEntry], products: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)

    def dump(name: str, value: object) -> None:
        (out / name).write_text(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    dump("products.json", products)
    dump("groups.json", [{"id": g.group_id, "stores": g.stores, "base": g.base} for g in groups])
    dump(
        "stores.json",
        {
            e.store_id: {"group": e.group_id, "stock": e.stock, "exceptions": e.exceptions}
            for e in entries
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chain")
    parser.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args(argv)

    chain_dir = args.data / args.chain
    stores, products = load_chain(chain_dir / "prices")
    if not stores:
        print(f"{args.chain}: no price files to build from", file=sys.stderr)
        return 1
    groups, entries = build(stores)
    verify(stores, groups, entries)
    write_ready(chain_dir / "ready", groups, entries, products)

    before = sum(len(p) for p in stores.values())
    after = sum(len(g.base) for g in groups) + sum(len(e.exceptions) for e in entries)
    print(
        f"{args.chain}: {len(stores)} stores -> {len(groups)} price groups; "
        f"price rows {before:,} -> {after:,} ({after / before:.0%}); "
        f"{len(products):,} products; verified: every store rebuilds exactly"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
