"""Are the product names cut in the chains' own files, or by us? (a check, nothing is saved)

Downloads ONE price file of one chain (the first fresh store) and, for the items in it, counts how
long the item names are, as the chain wrote them (before any of our code touches them), next to the
other name field the file may have (ManufacturerItemDescription), and prints a few examples.
If most names are exactly the same length, the chain cut them; if the other field is longer, we
could use it.

    python -m collector.namecheck ramilevi osherad yohananof

The manual Collect workflow runs it for its chain (after the collection, nothing is saved).
"""

import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime

from collector.collect import fresh_only
from collector.encoding import decode_price_file
from collector.files import kind_of, latest_per_store
from collector.sources import cerberus


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def name_fields(text: str) -> list[dict[str, str]]:
    """The raw name fields of every item: {"itemname": ..., "manufactureritemdescription": ...}."""
    root = ET.fromstring(text)
    rows = []
    for element in root.iter():
        fields = {_tag(c): (c.text or "").strip() for c in element}
        if fields.get("itemcode") and "itemprice" in fields:
            rows.append({k: fields.get(k, "") for k in ("itemname", "manufactureritemdescription")})
    return rows


def lengths(values: list[str]) -> list[tuple[int, int]]:
    """(length, how many) for the five most common lengths, longest first."""
    return sorted(Counter(len(v) for v in values if v).most_common(5), reverse=True)


def report(chain: str, text: str) -> str:
    rows = name_fields(text)
    short = [r["itemname"] for r in rows]
    long_ = [r["manufactureritemdescription"] for r in rows]
    cut = max((len(v) for v in short), default=0)
    lines = [
        f"{chain}: {len(rows)} items; longest ItemName {cut}, "
        f"with that length: {sum(len(v) == cut for v in short)}",
        f"  ItemName lengths (length, items): {lengths(short)}",
        f"  ManufacturerItemDescription present on {sum(bool(v) for v in long_)} items; "
        f"lengths: {lengths(long_)}",
    ]
    for row in [r for r in rows if r["manufactureritemdescription"]][:5]:
        lines.append(
            f"  ItemName={row['itemname']!r}  Description={row['manufactureritemdescription']!r}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    chains = argv if argv is not None else sys.argv[1:]
    for chain in chains:
        session = cerberus.Session(cerberus.USERNAMES[chain])
        names = [f.name for f in session.list_files()]
        latest = latest_per_store(
            fresh_only([n for n in names if kind_of(n) == "pricefull"], datetime.now(UTC))
        )
        if not latest:
            print(f"{chain}: no fresh price file")
            continue
        store, name = sorted(latest.items())[0]
        print(f"[{chain}] store {store}, file {name}")
        print(report(chain, decode_price_file(session.download(name))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
