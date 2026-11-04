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
from collector.files import (
    file_date,
    file_stamp,
    kind_of,
    latest_per_store,
    same_store,
    store_and_stamp,
)
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


class ChainWriter:
    """Writes what is collected for one chain: stores.json, prices/<store>.json, deals/<store>.json
    and applied.json (the stamp of each full price file, for collector.hourly). One bad file is
    counted (`fail`) and never stops the run."""

    def __init__(self, chain_dir: Path, stores_raw: bytes) -> None:
        self.dir = chain_dir
        self.failures = self.prices = self.deals = 0
        self.applied: dict[str, str] = {}
        stores = parse_stores_file(decode_price_file(stores_raw))
        chain_dir.mkdir(parents=True, exist_ok=True)
        (chain_dir / "stores.json").write_text(
            "[" + ",".join(to_json(s) for s in stores) + "]", encoding="utf-8"
        )
        print(f"{chain_dir.name}: {len(stores)} stores", flush=True)

    def add_price(self, store: str, name: str, raw: bytes) -> None:
        parsed = parse_price_file(decode_price_file(raw))
        write_record(self.dir / "prices" / f"{store}.json", parsed)
        if same_store(store) not in self.applied:
            self.prices += 1
        self.applied[same_store(store)] = file_stamp(name)

    def add_promo(self, store: str, raw: bytes) -> None:
        promos = parse_promo_file(decode_price_file(raw))
        deals, _ = usable_deals(promos, israel_now())
        self.deals += len(deals)
        (self.dir / "deals").mkdir(exist_ok=True)
        (self.dir / "deals" / f"{store}.json").write_text(
            "[" + ",".join(to_json(d) for d in deals) + "]", encoding="utf-8"
        )

    def fail(self, store: str, error: Exception) -> None:
        self.failures += 1
        print(f"  store {store}: FAILED {type(error).__name__}: {error}", file=sys.stderr)

    def finish(self) -> int:
        (self.dir / "applied.json").write_text(
            json.dumps(self.applied, sort_keys=True), encoding="utf-8"
        )
        print(
            f"{self.dir.name}: {self.prices} price files, {self.deals:,} usable deals, "
            f"{self.failures} failed"
        )
        return self.failures


class StoreWork(NamedTuple):
    """How to get one store's files, for a chain that lists them all at once (Cerberus).
    `price()` gives (file name, content) of the newest full price file, or None; `promo()` gives
    the content of the promotion file, or None."""

    price: Callable[[], tuple[str, bytes] | None]
    promo: Callable[[], bytes | None]


def _write_chain(
    chain_dir: Path,
    stores_raw: bytes,
    work: dict[str, StoreWork],
    limit: int | None,
) -> int:
    writer = ChainWriter(chain_dir, stores_raw)
    print(f"{chain_dir.name}: {len(work)} stores to fetch", flush=True)
    for count, (store, how) in enumerate(sorted(work.items()), start=1):
        if limit is not None and count > limit:
            break
        try:
            found = how.price()
            if found is None:  # a store without a (fresh) price file
                continue
            writer.add_price(store, *found)
            promo_raw = how.promo()
            if promo_raw is not None:
                writer.add_promo(store, promo_raw)
        except Exception as error:  # one bad file must not stop the run
            writer.fail(store, error)
        if count % 50 == 0:
            print(f"  {chain_dir.name}: {count} of {len(work)} stores", flush=True)
    return writer.finish()


def _fresh(name: str, now: datetime) -> bool:
    date = file_date(name)
    return date is not None and date >= now - MAX_FILE_AGE


def shufersal_stream(
    category: int,
    kind: str,
    handle: Callable[[str, str, bytes], None],
    writer: ChainWriter,
    now: datetime,
    wanted: Callable[[str], bool] = lambda store: True,
    stop: Callable[[], bool] = lambda: False,
) -> None:
    """Read a category's listing page by page; download the files of each page at once (before the
    next page is asked for), because the links expire. Per store only its newest fresh file is
    taken; a newer one on a later page replaces an older one taken before. `handle(store, name,
    raw)` stores a file; a store `wanted` says no to is skipped; `stop()` ends the reading."""
    best: dict[str, str] = {}  # store -> stamp of the newest file taken so far
    for links in shufersal.pages(category):
        newest: dict[str, shufersal.FileLink] = {}
        for link in links:
            parsed = store_and_stamp(link.name)
            if kind_of(link.name) != kind or parsed is None or not _fresh(link.name, now):
                continue
            store = parsed[0]
            if wanted(store) and (
                store not in newest or file_stamp(link.name) > file_stamp(newest[store].name)
            ):
                newest[store] = link
        for store, link in newest.items():
            if stop():
                return
            if file_stamp(link.name) <= best.get(store, ""):
                continue  # already taken this one or a newer one
            try:
                raw = shufersal.download(link, category, int(store))
                handle(store, link.name, raw)
                best[store] = file_stamp(link.name)
            except Exception as error:  # one bad file must not stop the run
                writer.fail(store, error)
        if stop():
            return


def collect_shufersal(out: Path, limit: int | None) -> int:
    started = time.monotonic()
    first_page = next(shufersal.pages(shufersal.CATEGORY_STORES), [])
    if not first_page:
        raise RuntimeError("Shufersal's list of stores has no file")
    stores_link = max(first_page, key=lambda link: file_stamp(link.name))
    stores_raw = shufersal.download(stores_link, shufersal.CATEGORY_STORES, 0)  # right away
    writer = ChainWriter(out / "shufersal", stores_raw)
    now = datetime.now(UTC)

    shufersal_stream(
        shufersal.CATEGORY_PRICE_FULL,
        "pricefull",
        writer.add_price,
        writer,
        now,
        stop=lambda: limit is not None and writer.prices >= limit,
    )
    # Promotions only for the stores whose prices were taken (as before), and with a limit only
    # until every one of them has its file.
    promo_stores = {same_store(store) for store in writer.applied}
    promos_taken: set[str] = set()

    def handle_promo(store: str, name: str, raw: bytes) -> None:
        writer.add_promo(store, raw)
        promos_taken.add(same_store(store))

    shufersal_stream(
        shufersal.CATEGORY_PROMO_FULL,
        "promofull",
        handle_promo,
        writer,
        now,
        wanted=lambda store: same_store(store) in promo_stores,
        stop=lambda: promos_taken >= promo_stores,
    )
    print(f"shufersal: collected in {(time.monotonic() - started) / 60:.1f} minutes", flush=True)
    return writer.finish()


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
