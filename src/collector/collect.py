"""Download a chain's latest files and write them in the internal format.

Usage:  python -m collector.collect <chain> --out data [--limit N]
        chains: shufersal, ramilevi, osherad, yohananof

Writes data/<chain>/stores.json, data/<chain>/prices/<store>.json and
data/<chain>/deals/<store>.json (promotions the calculator may use, collector.deals).
One store's failure is reported and skipped; it never stops the rest.
"""

import argparse
import json
import sys
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from collector.deals import usable_deals
from collector.encoding import decode_price_file
from collector.files import file_date, file_stamp, kind_of, latest_per_store, same_store
from collector.parse import parse_price_file, parse_promo_file, parse_stores_file
from collector.sources import cerberus, shufersal
from collector.store_output import to_json, write_record

# Files older than this belong to closed or abandoned stores (seen: files from July
# still listed in October).
MAX_FILE_AGE = timedelta(days=7)

CHAINS = ["shufersal", *cerberus.USERNAMES]


def israel_now() -> datetime:
    """Israel's clock time, as the chains write their dates (no time zone). Israel is
    UTC+2 or +3; +2 is at most an hour behind, which only keeps an ending deal an hour
    longer — the calculator checks end times again when it prices a basket."""
    return (datetime.now(UTC) + timedelta(hours=2)).replace(tzinfo=None)


def fresh_only(names: Iterable[str], now: datetime) -> list[str]:
    cutoff = now - MAX_FILE_AGE
    return [n for n in names if (d := file_date(n)) is not None and d >= cutoff]


class StoreWork(NamedTuple):
    """How to get one store's files. `price()` gives (file name, content) of the newest full price
    file, or None when the store has none; `promo()` gives the content of the promotion file, or
    None. They are called one after the other, store by store, so that a download starts right
    after the link to it was read (Shufersal's links expire)."""

    price: Callable[[], tuple[str, bytes] | None]
    promo: Callable[[], bytes | None]


def _write_chain(
    chain_dir: Path,
    stores_raw: bytes,
    work: dict[str, StoreWork],
    limit: int | None,
) -> int:
    stores = parse_stores_file(decode_price_file(stores_raw))
    chain_dir.mkdir(parents=True, exist_ok=True)
    (chain_dir / "stores.json").write_text(
        "[" + ",".join(to_json(s) for s in stores) + "]", encoding="utf-8"
    )
    print(f"{chain_dir.name}: {len(stores)} stores, {len(work)} to fetch", flush=True)

    failures = deal_count = taken = 0
    # store -> stamp of the full price file taken in (for collector.hourly)
    applied: dict[str, str] = {}
    for count, (store, how) in enumerate(sorted(work.items()), start=1):
        if limit is not None and count > limit:
            break
        try:
            found = how.price()
            if found is None:  # a store without a (fresh) price file
                continue
            name, raw = found
            parsed = parse_price_file(decode_price_file(raw))
            write_record(chain_dir / "prices" / f"{store}.json", parsed)
            applied[same_store(store)] = file_stamp(name)
            taken += 1
            promo_raw = how.promo()
            if promo_raw is not None:
                promos = parse_promo_file(decode_price_file(promo_raw))
                deals, _ = usable_deals(promos, israel_now())
                deal_count += len(deals)
                (chain_dir / "deals").mkdir(exist_ok=True)
                (chain_dir / "deals" / f"{store}.json").write_text(
                    "[" + ",".join(to_json(d) for d in deals) + "]", encoding="utf-8"
                )
        except Exception as error:  # one bad file must not stop the run
            failures += 1
            print(f"  store {store}: FAILED {type(error).__name__}: {error}", file=sys.stderr)
        if count % 50 == 0:
            print(f"  {chain_dir.name}: {count} of {len(work)} stores", flush=True)
    (chain_dir / "applied.json").write_text(json.dumps(applied, sort_keys=True), encoding="utf-8")
    print(f"{chain_dir.name}: {taken} price files, {deal_count:,} usable deals, {failures} failed")
    return failures


def _fresh(name: str, now: datetime) -> bool:
    date = file_date(name)
    return date is not None and date >= now - MAX_FILE_AGE


def shufersal_work(store_ids: list[str], now: datetime) -> dict[str, StoreWork]:
    """Per store: list its files, then download them at once (see sources/shufersal.py)."""

    def price_for(store: str) -> Callable[[], tuple[str, bytes] | None]:
        number = int(store)

        def get() -> tuple[str, bytes] | None:
            link = shufersal.latest_link(shufersal.CATEGORY_PRICE_FULL, number)
            if link is None or not _fresh(link.name, now):
                return None
            raw = shufersal.download(link, shufersal.CATEGORY_PRICE_FULL, number)
            return link.name, raw

        return get

    def promo_for(store: str) -> Callable[[], bytes | None]:
        number = int(store)

        def get() -> bytes | None:
            link = shufersal.latest_link(shufersal.CATEGORY_PROMO_FULL, number)
            if link is None or not _fresh(link.name, now):
                return None
            return shufersal.download(link, shufersal.CATEGORY_PROMO_FULL, number)

        return get

    return {store: StoreWork(price_for(store), promo_for(store)) for store in store_ids}


def collect_shufersal(out: Path, limit: int | None) -> int:
    stores_link = shufersal.latest_link(shufersal.CATEGORY_STORES, 0)
    if stores_link is None:
        raise RuntimeError("Shufersal's list of stores has no file")
    stores_raw = shufersal.download(stores_link, shufersal.CATEGORY_STORES, 0)  # right away
    store_ids = sorted(
        {
            s.store_id
            for s in parse_stores_file(decode_price_file(stores_raw))
            if s.store_id.isdigit()
        }
    )
    return _write_chain(
        out / "shufersal", stores_raw, shufersal_work(store_ids, datetime.now(UTC)), limit
    )


def collect_cerberus(chain: str, out: Path, limit: int | None) -> int:
    session = cerberus.Session(cerberus.USERNAMES[chain])
    names = [f.name for f in session.list_files()]
    stores_name = max(n for n in names if kind_of(n) in {"stores", "storesfull"})
    now = datetime.now(UTC)
    latest = latest_per_store(fresh_only([n for n in names if kind_of(n) == "pricefull"], now))
    promos = latest_per_store(fresh_only([n for n in names if kind_of(n) == "promofull"], now))
    if not latest:  # the file names may follow a pattern we do not know yet
        print(f"  no fresh price files; {len(names)} files, e.g. {sorted(names)[-5:]}")

    def work_for(store: str, name: str) -> StoreWork:
        promo_name = promos.get(store)
        return StoreWork(
            lambda: (name, session.download(name)),
            lambda: session.download(promo_name) if promo_name else None,
        )

    work = {store: work_for(store, name) for store, name in latest.items()}
    return _write_chain(out / chain, session.download(stores_name), work, limit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chain", choices=CHAINS)
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--limit", type=int, default=None, help="stop after N stores (testing)")
    args = parser.parse_args(argv)

    started = time.monotonic()
    if args.chain == "shufersal":
        failures = collect_shufersal(args.out, args.limit)
    else:
        failures = collect_cerberus(args.chain, args.out, args.limit)
    print(f"done in {time.monotonic() - started:.0f}s, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
