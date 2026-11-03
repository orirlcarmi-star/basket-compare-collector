"""Check that deals are read correctly by comparing them with their own wording (task 1).

`collector.deals` turns reward codes into "min_qty units for price". That reading was
checked against Shufersal's site. For the other chains the codes might mean something else
(for instance a price per unit instead of for all of them: "3 ב-30" read as 3 units for
10.00), and a wrong reading means wrong savings on the shopper's screen.

A deal's description says what the chain advertises ("2ב20", "3 ב-30 ₪", "300 גרם ב-25").
This compares the reading with the numbers in that wording:

- the price must be written in the wording;
- so must the quantity (a weight in kilos may be written in grams: 0.3 -> 300);
  a quantity of 1 needs no mention ("109 גבינה במשקל").

A chain where many deals fail is read wrongly, or words its deals in a way this does not
know — either way a person looks at the examples printed here, next to the chain's website.

Usage: python -m collector.deal_check <chain> --data data   (after `collect`)
"""

import argparse
import json
import re
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

# Above this share of mismatches the chain's reading is considered doubtful (exit code 1).
MAX_MISMATCH_SHARE = 0.1
EXAMPLES = 8

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


_PLUS = re.compile(r"(\d+)\s*\+\s*(\d+)")


def numbers_in(text: str) -> set[Decimal]:
    """Every number in the wording; "1+1" also counts as the 2 units it means."""
    found = {Decimal(n.replace(",", ".")) for n in _NUMBER.findall(text)}
    return found | {Decimal(int(a) + int(b)) for a, b in _PLUS.findall(text)}


def check(description: str, min_qty: Decimal, price: Decimal) -> str:
    """ "ok", "no numbers" (cannot tell), "price not in wording" or "quantity not in wording"."""
    written = numbers_in(description)
    if not written:
        return "no numbers"
    if price not in written and price.normalize() not in {w.normalize() for w in written}:
        return "price not in wording"
    quantity_forms = {min_qty, min_qty * 1000}  # units or kilos, or the kilos written in grams
    if min_qty != 1 and not any(
        q.normalize() in {w.normalize() for w in written} for q in quantity_forms
    ):
        return "quantity not in wording"
    return "ok"


def check_chain(deals_dir: Path) -> tuple[Counter[str], list[str]]:
    results: Counter[str] = Counter()
    examples: list[str] = []
    for path in sorted(deals_dir.glob("*.json")):
        for deal in json.loads(path.read_text(encoding="utf-8")):
            verdict = check(deal["description"], Decimal(deal["min_qty"]), Decimal(deal["price"]))
            results[verdict] += 1
            if verdict not in ("ok", "no numbers") and len(examples) < EXAMPLES:
                examples.append(
                    f"  {verdict}: \"{deal['description']}\" read as {deal['min_qty']} "
                    f"for {deal['price']} (store file {path.stem}, "
                    f"promotion {deal['promotion_id']})"
                )
    return results, examples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chain")
    parser.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args(argv)

    results, examples = check_chain(args.data / args.chain / "deals")
    checked = sum(n for verdict, n in results.items() if verdict != "no numbers")
    bad = sum(n for verdict, n in results.items() if verdict not in ("ok", "no numbers"))
    print(
        f"{args.chain}: {sum(results.values()):,} deals; "
        + ", ".join(f"{verdict} {count:,}" for verdict, count in results.most_common())
    )
    for line in examples:
        print(line)
    if checked and bad / checked > MAX_MISMATCH_SHARE:
        print(
            f"{args.chain}: {bad / checked:.0%} of the deals disagree with their own wording "
            "- the reward codes may mean something else for this chain; compare with its website"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
