"""Download a chain's latest files and write them in the internal format.

Usage:  python -m collector.collect shufersal --out data [--limit N]

Writes data/<chain>/stores.json and data/<chain>/prices/<store>.json.
One store's failure is reported and skipped; it never stops the rest.
"""

import argparse
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from collector.encoding import decode_price_file
from collector.model import PriceFile
from collector.parse import parse_price_file, parse_stores_file
from collector.sources import shufersal
from collector.store_output import to_json, write_record

# Files older than this belong to closed or abandoned stores (seen: files from July
# still listed in October).
MAX_FILE_AGE = timedelta(days=7)


def _file_date(name: str) -> datetime | None:
    try:
        return datetime.strptime(name.split("-")[3], "%Y%m%d").replace(tzinfo=UTC)
    except (IndexError, ValueError):
        return None


def collect_shufersal(out: Path, limit: int | None = None) -> int:
    chain_dir = out / "shufersal"
    failures = 0

    stores_links = shufersal.list_all(shufersal.CATEGORY_STORES)
    stores = parse_stores_file(decode_price_file(shufersal.fetch(stores_links[0].url)))
    chain_dir.mkdir(parents=True, exist_ok=True)
    (chain_dir / "stores.json").write_text(
        "[" + ",".join(to_json(s) for s in stores) + "]", encoding="utf-8"
    )

    cutoff = datetime.now(UTC) - MAX_FILE_AGE
    latest = shufersal.latest_per_store(shufersal.list_all(shufersal.CATEGORY_PRICE_FULL))
    fresh = {
        store: link
        for store, link in latest.items()
        if (date := _file_date(link.name)) is not None and date >= cutoff
    }
    print(f"shufersal: {len(stores)} stores, {len(latest)} price files, {len(fresh)} fresh")

    for count, (store, link) in enumerate(sorted(fresh.items()), start=1):
        if limit is not None and count > limit:
            break
        try:
            parsed: PriceFile = parse_price_file(decode_price_file(shufersal.fetch(link.url)))
            write_record(chain_dir / "prices" / f"{store}.json", parsed)
        except Exception as error:  # one bad file must not stop the run
            failures += 1
            print(f"  store {store}: FAILED {type(error).__name__}: {error}", file=sys.stderr)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chain", choices=["shufersal"])
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--limit", type=int, default=None, help="stop after N stores (testing)")
    args = parser.parse_args(argv)

    started = time.monotonic()
    failures = collect_shufersal(args.out, args.limit)
    print(f"done in {time.monotonic() - started:.0f}s, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
