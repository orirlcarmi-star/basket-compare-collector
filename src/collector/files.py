"""Facts read from regulated file names, shared by every source.

Names look like PriceFull7290027600007-001-413-20261027-030000[.gz|.xml]:
kind, 13-digit chain code, sub-chain, store, date, time.
"""

import re
from collections.abc import Iterable
from datetime import UTC, datetime

_NAME = re.compile(
    r"^(?P<kind>[A-Za-z]+)(?P<chain>\d{13})-(?P<sub>\d+)-(?P<store>\d+)-"
    r"(?P<date>\d{8})-?(?P<time>\d{4,6})?"
)


def strip_extension(name: str) -> str:
    return re.sub(r"\.(gz|xml|zip)$", "", name, flags=re.IGNORECASE)


def same_store(store_id: str) -> str:
    """One spelling per store number: files of the same chain write "071" and "71"."""
    return store_id.strip().lstrip("0") or "0"


def kind_of(name: str) -> str:
    match = re.match(r"[A-Za-z]+", name)
    return match.group(0).lower() if match else ""


def store_and_stamp(name: str) -> tuple[str, str] | None:
    """(store id, sortable timestamp) for a per-store file; None for chain-wide files."""
    match = _NAME.match(strip_extension(name))
    if not match:
        return None
    return match["store"], match["date"] + (match["time"] or "")


def file_date(name: str) -> datetime | None:
    match = _NAME.match(strip_extension(name))
    if not match:
        return None
    return datetime.strptime(match["date"], "%Y%m%d").replace(tzinfo=UTC)


def latest_per_store(names: Iterable[str]) -> dict[str, str]:
    """Newest file name for each store."""
    latest: dict[str, tuple[str, str]] = {}
    for name in names:
        parsed = store_and_stamp(name)
        if parsed is None:
            continue
        store, stamp = parsed
        if store not in latest or stamp > latest[store][0]:
            latest[store] = (stamp, name)
    return {store: name for store, (_, name) in latest.items()}
