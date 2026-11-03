"""Turn the chains' ready-made files into the files the website serves (build step 3.3).

The shopper's browser prices the basket itself (docs/10-tools.md, decision 3), so it
must fetch only what the basket needs:

- stores.json — every physical store with a location: chain, name, city, point,
  location precision, price group. One small file.
- p/<bucket>.json — products spread over BUCKETS files by barcode. Each product holds
  its name and, per chain, its price per group ("g"), the stores whose price differs
  ("x") and the stores that sell it ("s"). A basket of 25 products reads ~25 files.

Store keys are "<chain>:<store number>" (numbers repeat across chains; leading zeros
dropped, as files of one chain disagree on them). The bucket of a barcode
is FNV-1a modulo BUCKETS, the same function the website uses.

Format 1 (the default) is what the website reads today. `--compact` writes format 2, which
says the same in far fewer bytes (collector.compact: sellers as "everyone", "everyone but",
or whole price groups, instead of a list of store keys). The website must be changed to read
it before that is switched on. Either way, the files just written are read back and every
store's prices are compared with what the chain published; a single difference fails the run.

Usage: python -m collector.publish shufersal ramilevi ... --data data --out site-data [--compact]
"""

import argparse
import json
import shutil
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

from collector.attributes import attributes_of
from collector.categories import CATEGORIES, categorize
from collector.collect import israel_now
from collector.compact import (
    FORMAT,
    build_index,
    compact_product,
    restore_prices,
    verify_restored,
)
from collector.files import same_store
from collector.locate import apply_manual, load_manual
from collector.names import better_name
from collector.searchindex import build_index as build_search_index
from collector.searchindex import write_index
from collector.sitedeals import build_chain_deals, load_store_deals
from collector.unitprice import contents

BUCKETS = 8192
# Cloudflare Pages takes at most 20,000 files in one deployment. The run fails above this many,
# leaving room for growth, so a package the host would refuse is never published.
MAX_SITE_FILES = 18_000


def bucket_of(code: str) -> int:
    """FNV-1a, 32 bit — must match the website's copy (character codes of the barcode)."""
    h = 0x811C9DC5
    for char in code:
        h ^= ord(char)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h % BUCKETS


def chain_products(chain: str, ready: dict, into: dict[str, dict]) -> None:
    """Add one chain's prices to the product map (barcode -> product).

    When chains disagree about a barcode, the clearest name wins (collector.names) and an
    empty size or manufacturer is filled from whichever chain has it."""
    bases = {g["id"]: g["base"] for g in ready["groups"]}
    for store_id, entry in ready["stores"].items():
        key = f"{chain}:{same_store(store_id)}"
        for code in entry["stock"]:
            meta = ready["products"].get(code, {})
            product = into.setdefault(
                code, {"n": "", "q": "", "u": "", "w": False, "_m": "", "c": {}}
            )
            product["n"] = better_name(product["n"], meta.get("name") or "")
            for field, source in (("q", "quantity"), ("u", "unit"), ("_m", "manufacturer")):
                product[field] = product[field] or meta.get(source) or ""
            product["w"] = product["w"] or bool(meta.get("is_weighted"))
            prices = product["c"].setdefault(chain, {"g": {}, "s": []})
            prices["g"].setdefault(entry["group"], bases[entry["group"]][code])
            prices["s"].append(key)
            if code in entry["exceptions"]:
                prices.setdefault("x", {})[key] = entry["exceptions"][code]


def finish_products(products: dict[str, dict]) -> None:
    """Once every chain is in: read facts from each final name (collector.attributes).

    "a" holds what was found — f fat percent, b brand, d "free of" labels — and "z" what the
    package holds as [amount, "l" | "kg" | "unit"]: the unit price is the shopper's price
    divided by that amount (collector.unitprice). "k" is the category id (collector.categories).
    All are left out when nothing was found."""
    for product in products.values():
        maker = product.pop("_m")
        found = attributes_of(
            product["n"], maker, Decimal(product["q"]) if product["q"] else None, product["u"],
            product["w"],
        )  # fmt: skip
        facts = {
            "f": str(found.fat_percent) if found.fat_percent is not None else "",
            "b": found.brand,
            "d": list(found.free_of),
        }
        if any(facts.values()):
            product["a"] = {k: v for k, v in facts.items() if v}
        category = categorize(product["n"])
        if category:
            product["k"] = category
        if found.size:
            amount, base = contents(found.size)
            product["z"] = [str(amount), base]


def chain_stores(chain: str, ready: dict, listed: list[dict], located: dict) -> tuple[dict, list]:
    """Physical stores with a location; also the ones left out for lack of one."""
    names = {same_store(s["store_id"]): s for s in listed}
    where_is = {same_store(sid): place for sid, place in located.items()}
    stores, unlocated = {}, []
    for raw_id, entry in ready["stores"].items():
        store_id = same_store(raw_id)
        info, where = names.get(store_id, {}), where_is.get(store_id)
        if info.get("is_online"):
            continue
        if not where:
            unlocated.append(f"{chain}:{store_id}")
            continue
        stores[f"{chain}:{store_id}"] = {
            "chain": chain,
            "name": info.get("name", ""),
            "city": where["city"],
            "lat": where["lat"],
            "lon": where["lon"],
            "precision": where["precision"],
            "group": entry["group"],
        }
    return stores, unlocated


def published_prices(chain: str, ready: dict) -> dict[str, dict[str, str]]:
    """What the chain published, per store number: {barcode: price} (the check's reference)."""
    bases = {g["id"]: g["base"] for g in ready["groups"]}
    return {
        same_store(raw_id): {
            code: entry["exceptions"].get(code, bases[entry["group"]][code])
            for code in entry["stock"]
        }
        for raw_id, entry in ready["stores"].items()
    }


def attach_deals(
    out: Path, data: Path, chains: list[str], products: dict, indexes: dict
) -> tuple[list[Path], int, Counter[str]]:
    """Write d/<chain>/<id>.json for every chain with deals and add "d" to the products.

    Returns the files written, the size of the deal references added to the products (bytes, as
    the products' own files will carry them) and why deals were left out (collector.sitedeals)."""
    shutil.rmtree(out / "d", ignore_errors=True)  # deals that are gone
    written: list[Path] = []
    references = 0
    skipped: Counter[str] = Counter()
    now = israel_now()
    for chain in chains:
        folder = data / chain / "deals"
        if not folder.exists():
            continue
        sold = {code for code, product in products.items() if chain in product["c"]}
        files, by_item, left_out = build_chain_deals(
            load_store_deals(folder), indexes[chain], sold, now
        )
        skipped += left_out
        for deal_id, content in files.items():
            path = out / "d" / chain / f"{deal_id}.json"
            write_json(path, content)
            written.append(path)
        for code, ids in by_item.items():
            products[code]["c"][chain]["d"] = ids
            references += len(json.dumps(ids, separators=(",", ":")))
    return written, references, skipped


def count_files(out: Path) -> dict[str, int]:
    """Files in the site folder by part: p (products), s (search), d (deals), other."""
    parts = {"p": 0, "s": 0, "d": 0, "other": 0}
    for path in out.rglob("*"):
        if path.is_file():
            top = path.relative_to(out).parts[0]
            parts[top if top in parts else "other"] += 1
    return parts


def too_many_files(parts: dict[str, int], limit: int) -> str | None:
    total = sum(parts.values())
    if total <= limit:
        return None
    return (
        f"TOO MANY FILES: {total:,} in the site folder, the limit is {limit:,} "
        f"(products {parts['p']:,}, search {parts['s']:,}, deals {parts['d']:,}, "
        f"other {parts['other']:,}). The host refuses more than 20,000 files, so nothing is "
        f"published.\nיותר מדי קבצים: {total:,} במקום עד {limit:,}. האתר לא יקבל יותר מ-20,000 "
        f"קבצים, ולכן שום דבר לא פורסם. הסעיף הגדול ביותר הוא "
        f"{max(parts, key=parts.get)!r}: כדי להקטין, ממזגים קבצי מבצעים או מקטינים את מספר "
        "קבצי המוצרים (BUCKETS)."
    )


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chains", nargs="+")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--locations", type=Path, default=Path("locations"))
    parser.add_argument("--out", type=Path, default=Path("site-data"))
    parser.add_argument(
        "--review", type=Path, help="write the names no category rule was sure about to this file"
    )
    parser.add_argument(
        "--compact", action="store_true", help="write the smaller format 2 (collector.compact)"
    )
    args = parser.parse_args(argv)

    products: dict[str, dict] = {}
    stores: dict[str, dict] = {}
    unlocated: list[str] = []
    indexes: dict[str, dict] = {}
    expected: dict[str, dict] = {}
    for chain in args.chains:
        ready_dir = args.data / chain / "ready"
        ready = {
            name: read_json(ready_dir / f"{name}.json") for name in ("groups", "stores", "products")
        }
        chain_products(chain, ready, products)
        indexes[chain] = build_index(chain, ready["stores"], same_store)
        expected[chain] = published_prices(chain, ready)
        auto = args.locations / f"{chain}.json"  # a new chain has none until `locate` has run
        located = apply_manual(
            read_json(auto) if auto.exists() else {},
            load_manual(args.locations / f"{chain}.manual.json"),
        )
        listed_path = args.data / chain / "stores.json"  # absent when today's collection failed
        listed = read_json(listed_path) if listed_path.exists() else []
        found, missing = chain_stores(chain, ready, listed, located)
        stores.update(found)
        unlocated += missing

    finish_products(products)
    deal_files: list[Path] = []
    deal_references = 0
    deals_skipped: Counter[str] = Counter()
    if args.compact:  # the deal files use store positions, which only format 2 has
        deal_files, deal_references, deals_skipped = attach_deals(
            args.out, args.data, args.chains, products, indexes
        )
    buckets: list[dict] = [{} for _ in range(BUCKETS)]
    for code, product in products.items():
        buckets[bucket_of(code)][code] = (
            compact_product(product, indexes) if args.compact else product
        )
    for number, bucket in enumerate(buckets):
        write_json(args.out / "p" / f"{number}.json", bucket)
    listing = {"format": FORMAT, "stores": stores, "chains": indexes} if args.compact else stores
    write_json(args.out / "stores.json", listing)

    verify_restored(restore_prices(args.out), expected, complete=args.compact)

    write_json(args.out / "categories.json", [{"id": c.id, "name": c.name} for c in CATEGORIES])
    for old in (args.out / "s").glob("*.json"):  # words of products that are gone
        old.unlink()
    index_files = write_index(
        build_search_index({code: p["n"] for code, p in products.items()}), args.out / "s"
    )
    index_sizes = [f.stat().st_size for f in index_files]
    unclassified = sorted((p["n"], code) for code, p in products.items() if "k" not in p)
    if args.review:
        args.review.parent.mkdir(parents=True, exist_ok=True)
        args.review.write_text(
            "".join(f"{code}\t{name}\n" for name, code in unclassified), encoding="utf-8"
        )
    classified = 100 * (1 - len(unclassified) / len(products)) if products else 0.0
    write_json(
        args.out / "stats.json",
        {
            "stores": len(stores),
            "products": len(products),
            "unlocated": len(unlocated),
            "classified_percent": round(classified, 1),
            "search_files": len(index_files),
            "search_bytes": sum(index_sizes),
            "search_largest_bytes": max(index_sizes, default=0),
            "deal_files": len(deal_files),
            "deal_bytes": sum(f.stat().st_size for f in deal_files),
            "deal_largest_bytes": max((f.stat().st_size for f in deal_files), default=0),
            "deal_references_bytes": deal_references,
            "deals_left_out": dict(deals_skipped),
        },
    )
    parts = count_files(args.out)  # stats.json is in; meta.json is added later, within the margin
    stats = read_json(args.out / "stats.json")
    write_json(
        args.out / "stats.json",
        {**stats, "files_total": sum(parts.values()), "files_by_part": parts},
    )

    sizes = [f.stat().st_size for f in (args.out / "p").iterdir()]
    print(
        f"{len(stores)} stores, {len(products):,} products in {BUCKETS} files "
        f"({sum(sizes) / 1e6:.0f}MB, largest {max(sizes) / 1e3:.0f}KB), "
        f"format {FORMAT if args.compact else 1}; verified: every store's prices restore exactly"
    )
    print(
        f"{classified:.1f}% of products have a category; search index: {len(index_files)} files, "
        f"{sum(index_sizes) / 1e6:.1f}MB, largest {max(index_sizes, default=0) / 1e3:.0f}KB"
    )
    if args.compact:
        deal_mb = sum(f.stat().st_size for f in deal_files) / 1e6
        print(
            f"deals: {len(deal_files):,} files ({deal_mb:.1f}MB), "
            f"references in the product files {deal_references / 1e3:.0f}KB; "
            f"left out: {dict(deals_skipped) or 'none'}"
        )
    print(
        f"files in the site folder: {sum(parts.values()):,} of {MAX_SITE_FILES:,} allowed {parts}"
    )
    if unlocated:
        print(f"left out, no location: {', '.join(unlocated)}")
    problem = too_many_files(parts, MAX_SITE_FILES)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
