"""Download a chain's latest files and write them in the internal format.

Usage:  python -m collector.collect <chain> --out data [--limit N]
        chains: shufersal, ramilevi, osherad, yohananof

Writes data/<chain>/stores.json and data/<chain>/prices/<store>.json.
One store's failure is reported and skipped; it never stops the rest.
"""

import argparse
import sys
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from collector.encoding import decode_price_file
from collector.files import file_date, kind_of, latest_per_store
from collector.parse import parse_price_file, parse_stores_file
from collector.sources import cerberus, shufersal
from collector.store_output import to_json, write_record

# Files older than this belong to closed or abandoned stores (seen: files from July
# still listed in October).
MAX_FILE_AGE = timedelta(days=7)

CHAINS = ["shufersal", *cerberus.USERNAMES]


def fresh_only(names: Iterable[str], now: datetime) -> list[str]:
    cutoff = now - MAX_FILE_AGE
    return [n for n in names if (d := file_date(n)) is not None and d >= cutoff]


def _write_chain(
    chain_dir: Path,
    stores_raw: bytes,
    price_files: dict[str, str],
    download: Callable[[str], bytes],
    limit: int | None,
) -> int:
    stores = parse_stores_file(decode_price_file(stores_raw))
    chain_dir.mkdir(parents=True, exist_ok=True)
    (chain_dir / "stores.json").write_text(
        "[" + ",".join(to_json(s) for s in stores) + "]", encoding="utf-8"
    )
    print(f"{chain_dir.name}: {len(stores)} stores, {len(price_files)} fresh price files")

    failures = 0
    for count, (store, name) in enumerate(sorted(price_files.items()), start=1):
        if limit is not None and count > limit:
            break
        try:
            parsed = parse_price_file(decode_price_file(download(name)))
            write_record(chain_dir / "prices" / f"{store}.json", parsed)
        except Exception as error:  # one bad file must not stop the run
            failures += 1
            print(f"  store {store}: FAILED {type(error).__name__}: {error}", file=sys.stderr)
    return failures


def collect_shufersal(out: Path, limit: int | None) -> int:
    stores_link = shufersal.list_all(shufersal.CATEGORY_STORES)[0]
    links = {link.name: link for link in shufersal.list_all(shufersal.CATEGORY_PRICE_FULL)}
    latest = latest_per_store(fresh_only(links, datetime.now(UTC)))
    return _write_chain(
        out / "shufersal",
        shufersal.fetch(stores_link.url),
        latest,
        lambda name: shufersal.fetch(links[name].url),
        limit,
    )


def collect_cerberus(chain: str, out: Path, limit: int | None) -> int:
    session = cerberus.Session(cerberus.USERNAMES[chain])
    names = [f.name for f in session.list_files()]
    stores_name = max(n for n in names if kind_of(n) in {"stores", "storesfull"})
    full = [n for n in names if kind_of(n) == "pricefull"]
    latest = latest_per_store(fresh_only(full, datetime.now(UTC)))
    return _write_chain(out / chain, session.download(stores_name), latest, session.download, limit)


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
