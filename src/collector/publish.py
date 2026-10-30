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

Usage: python -m collector.publish shufersal ramilevi ... --data data --out site-data
"""

import argparse
import json
import sys
from pathlib import Path

from collector.files import same_store

BUCKETS = 8192


def bucket_of(code: str) -> int:
    """FNV-1a, 32 bit — must match the website's copy (character codes of the barcode)."""
    h = 0x811C9DC5
    for char in code:
        h ^= ord(char)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h % BUCKETS


def chain_products(chain: str, ready: dict, into: dict[str, dict]) -> None:
    """Add one chain's prices to the product map (barcode -> product)."""
    bases = {g["id"]: g["base"] for g in ready["groups"]}
    for store_id, entry in ready["stores"].items():
        key = f"{chain}:{same_store(store_id)}"
        for code in entry["stock"]:
            meta = ready["products"].get(code, {})
            product = into.setdefault(
                code,
                {
                    "n": meta.get("name", ""),
                    "q": meta.get("quantity", ""),
                    "u": meta.get("unit", ""),
                    "w": meta.get("is_weighted", False),
                    "c": {},
                },
            )
            prices = product["c"].setdefault(chain, {"g": {}, "s": []})
            prices["g"].setdefault(entry["group"], bases[entry["group"]][code])
            prices["s"].append(key)
            if code in entry["exceptions"]:
                prices.setdefault("x", {})[key] = entry["exceptions"][code]


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
    args = parser.parse_args(argv)

    products: dict[str, dict] = {}
    stores: dict[str, dict] = {}
    unlocated: list[str] = []
    for chain in args.chains:
        ready_dir = args.data / chain / "ready"
        ready = {
            name: read_json(ready_dir / f"{name}.json") for name in ("groups", "stores", "products")
        }
        chain_products(chain, ready, products)
        located = read_json(args.locations / f"{chain}.json")
        found, missing = chain_stores(
            chain, ready, read_json(args.data / chain / "stores.json"), located
        )
        stores.update(found)
        unlocated += missing

    buckets: list[dict] = [{} for _ in range(BUCKETS)]
    for code, product in products.items():
        buckets[bucket_of(code)][code] = product
    for number, bucket in enumerate(buckets):
        write_json(args.out / "p" / f"{number}.json", bucket)
    write_json(args.out / "stores.json", stores)

    sizes = [f.stat().st_size for f in (args.out / "p").iterdir()]
    print(
        f"{len(stores)} stores, {len(products):,} products in {BUCKETS} files "
        f"({sum(sizes) / 1e6:.0f}MB, largest {max(sizes) / 1e3:.0f}KB)"
    )
    if unlocated:
        print(f"left out, no location: {', '.join(unlocated)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
