"""Hourly update from the chains' partial price files (build task C).

Besides the full price file of each store (read once a day by `collect`), the chains publish
small "Price" files during the day with the items whose price changed. This takes in those that
are new since the full file was read, so prices are at most an hour old:

1. The prices of every store are rebuilt from yesterday's accepted ready-made files
   (the exact rebuild that `build` verifies), together with `applied.json`: for each store the
   stamp of the newest price file already taken in.
2. Only files newer than that stamp are downloaded, oldest first, and each item in them
   replaces the price of that item in that store (a new item is added). Stores that the daily
   run did not know are skipped: they wait for the next full file. A partial file cannot say
   that an item is gone; only the next full file does.
3. The result goes through `build.build_ready`, the same screening (zero prices, far from the
   usual, jumped since the last update), update checks and exact rebuild check as the daily
   build. A bad price in an update does not make the store lose the product: the old price
   stays. An update the checks reject is dropped and the previous files stay.

Usage: python -m collector.hourly <chain> --data data [--limit N]   (state restored first)
Deals are not touched: they change with the daily file.
"""

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from collector.build import build_ready, write_last_run
from collector.encoding import decode_price_file
from collector.files import file_stamp, kind_of, same_store, store_and_stamp
from collector.parse import parse_price_file
from collector.sources import cerberus, shufersal

SECONDS_BETWEEN_DOWNLOADS = 0.2  # the chains' servers are not ours: no hammering
MAX_FILES = 3000  # a safety stop; a normal hour has a few hundred small files


def prices_from_ready(ready: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict]]:
    """Every store's prices {store id: {barcode: price}} and the products, rebuilt exactly from
    the ready-made files (group price list plus the store's own exceptions)."""
    groups = {
        g["id"]: g["base"] for g in json.loads((ready / "groups.json").read_text(encoding="utf-8"))
    }
    stores = json.loads((ready / "stores.json").read_text(encoding="utf-8"))
    prices = {
        store: {
            code: entry["exceptions"].get(code, groups[entry["group"]][code])
            for code in entry["stock"]
        }
        for store, entry in stores.items()
    }
    products = json.loads((ready / "products.json").read_text(encoding="utf-8"))
    return prices, products


def new_files(names: list[str], applied: dict[str, str]) -> dict[str, list[str]]:
    """store -> the partial price files newer than what was taken in, oldest first.
    Stores with no stamp (not in the daily run) get nothing."""
    chosen: dict[str, list[tuple[str, str]]] = {}
    for name in names:
        parsed = store_and_stamp(name)
        if kind_of(name) != "price" or parsed is None:
            continue
        store = same_store(parsed[0])
        stamp = file_stamp(name)
        if store in applied and stamp > applied[store]:
            chosen.setdefault(store, []).append((stamp, name))
    return {store: [name for _, name in sorted(files)] for store, files in chosen.items()}


def apply_updates(
    prices: dict[str, dict[str, str]],
    products: dict[str, dict],
    applied: dict[str, str],
    store_updates: dict[str, list[tuple[str, object]]],
) -> int:
    """Put the items of the partial files into `prices`, `products` and `applied` (in place);
    returns how many prices changed or were added. `store_updates`: normal store number ->
    [(file stamp, parsed price file)] oldest first."""
    raw_id = {same_store(store): store for store in prices}
    changed = 0
    for store, files in store_updates.items():
        target = prices[raw_id[store]]
        for stamp, parsed in files:
            for item in parsed.items:
                price = str(item.price)
                if target.get(item.item_code) != price:
                    changed += 1
                target[item.item_code] = price
                products.setdefault(
                    item.item_code,
                    {
                        "name": item.name,
                        "manufacturer": item.manufacturer,
                        "quantity": None if item.quantity is None else str(item.quantity),
                        "unit": item.unit,
                        "is_weighted": item.is_weighted,
                    },
                )
            applied[store] = max(applied[store], stamp)
    return changed


def _source(chain: str) -> tuple[list[str], Callable[[str], bytes]]:
    """Names of the partial price files on offer, and how to download one."""
    if chain == "shufersal":
        links = {link.name: link for link in shufersal.list_all(shufersal.CATEGORY_PRICE)}
        return list(links), lambda name: shufersal.fetch(links[name].url)
    session = cerberus.Session(cerberus.USERNAMES[chain])
    return [f.name for f in session.list_files()], session.download


def update_chain(
    chain: str,
    chain_dir: Path,
    names: list[str],
    download: Callable[[str], bytes],
    limit: int | None = None,
    pause: float = SECONDS_BETWEEN_DOWNLOADS,
) -> int:
    ready = chain_dir / "ready"
    applied_path = ready / "applied.json"
    if not applied_path.exists():  # the daily run has not recorded stamps yet
        print(f"{chain}: no stamps from a full run yet, nothing to update")
        write_last_run(chain_dir, "nothing new", [])
        return 0
    applied = json.loads(applied_path.read_text(encoding="utf-8"))
    wanted = new_files(names, applied)
    total = sum(len(v) for v in wanted.values())
    if not total:
        print(f"{chain}: no new price files")
        write_last_run(chain_dir, "nothing new", [])
        return 0
    if total > MAX_FILES:
        message = f"{total:,} new price files is more than the limit of {MAX_FILES:,}"
        print(f"{chain}: {message}; waiting for the next full run", file=sys.stderr)
        write_last_run(chain_dir, "rejected", [message])
        return 1

    prices, products = prices_from_ready(ready)
    before = {store: dict(items) for store, items in prices.items()}
    updates: dict[str, list[tuple[str, object]]] = {}
    failures = taken = 0
    for store, files in sorted(wanted.items()):
        for name in files:
            if limit is not None and taken >= limit:
                break
            try:
                parsed = parse_price_file(decode_price_file(download(name)))
            except Exception as error:  # one bad file: skip it and leave the store as it was
                failures += 1
                print(f"  store {store}: {name} FAILED {type(error).__name__}: {error}")
                break  # later files of this store build on this one, so stop for this store
            updates.setdefault(store, []).append((file_stamp(name), parsed))
            taken += 1
            time.sleep(pause)
    changed = apply_updates(prices, products, applied, updates)
    print(f"{chain}: {taken} price files from {len(updates)} stores, {changed:,} prices changed")
    if not changed and not failures:
        write_last_run(chain_dir, "nothing new", [])
        return 0
    return build_ready(chain, chain_dir, prices, products, applied, fallback=before)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chain")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--limit", type=int, default=None, help="take in at most N files (testing)")
    args = parser.parse_args(argv)
    chain_dir = args.data / args.chain
    names, download = _source(args.chain)
    return update_chain(args.chain, chain_dir, names, download, args.limit)


if __name__ == "__main__":
    sys.exit(main())
