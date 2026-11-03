"""A smaller form of the site files, and the check that nothing is lost (build task 8).

In the current files ("format 1") every product lists, per chain, the key of every store that
sells it: "shufersal:413", "shufersal:414", ... — typically hundreds of keys repeated for
tens of thousands of products, although most products are sold by nearly every store.
Format 2 says the same thing in fewer words:

stores.json  {"format": 2,
              "stores": {... as in format 1 ...},
              "chains": {"<chain>": {"ids": ["1", "2", ...],     # every store, in a fixed order
                                    "groups": ["g1", "g1", "g2"]}}}  # its price group, same order

A product's entry for a chain, {"g": {group: price}, "x": {position: price}} plus the sellers
in whichever of these forms is the shortest:

  nothing      every store of the chain sells it            (most products)
  "o": [...]   every store except these positions
  "k": [...]   every store of these price groups, and
  "s": [...]   these other positions                        ("s" alone: only these)

A position is a store's place in "ids". Exceptions "x" use positions too. Empty fields of a
product ("q", "u", "w" false) are left out. "a" (facts from the name), "z" (what the package
holds, for the unit price) and "k" (category id) are present only when known. Everything
else is as in format 1, so a reader needs only the rules above: `restore_prices` is the
reference decoder, and `publish` runs it on the files it just wrote and compares every
store's prices with what the chain published.
"""

import json
from collections.abc import Mapping
from pathlib import Path

FORMAT = 2


def _size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def build_index(chain: str, ready_stores: Mapping[str, dict], same_store) -> dict:
    """Store numbers in a fixed order with the price group of each (every store of the
    chain, including online and unlocated ones: they appear in sellers' lists)."""
    group_of = {same_store(raw): entry["group"] for raw, entry in ready_stores.items()}
    ids = sorted(group_of, key=lambda i: (len(i), i))
    return {"ids": ids, "groups": [group_of[i] for i in ids]}


def seller_fields(sellers: set[int], groups: list[str]) -> dict:
    """The shortest way to say which positions sell a product."""
    if len(sellers) == len(groups):
        return {}
    candidates: list[dict] = [{"s": sorted(sellers)}]
    missing = sorted(set(range(len(groups))) - sellers)
    candidates.append({"o": missing})
    members: dict[str, set[int]] = {}
    for position, group in enumerate(groups):
        members.setdefault(group, set()).add(position)
    whole = [g for g, m in members.items() if m <= sellers]
    if whole:
        covered = set().union(*(members[g] for g in whole))
        spec: dict = {"k": whole}
        if sellers - covered:
            spec["s"] = sorted(sellers - covered)
        candidates.append(spec)
    return min(candidates, key=_size)


def sellers_of(fields: Mapping, groups: list[str]) -> set[int]:
    """Inverse of `seller_fields`."""
    if "o" in fields:
        return set(range(len(groups))) - set(fields["o"])
    if "s" not in fields and "k" not in fields:
        return set(range(len(groups)))
    chosen = set(fields.get("s", ()))
    for group in fields.get("k", ()):
        chosen |= {i for i, g in enumerate(groups) if g == group}
    return chosen


def compact_product(product: Mapping, indexes: Mapping[str, dict]) -> dict:
    """One format-1 product (sellers as store keys) in format 2."""
    result = {"n": product["n"]}
    for field in ("q", "u"):
        if product.get(field):
            result[field] = product[field]
    if product.get("w"):
        result["w"] = True
    for field in ("a", "z", "k"):
        if field in product:
            result[field] = product[field]
    result["c"] = {}
    for chain, entry in product["c"].items():
        index = indexes[chain]
        position = {f"{chain}:{store_id}": i for i, store_id in enumerate(index["ids"])}
        compact = {
            "g": entry["g"],
            **seller_fields({position[k] for k in entry["s"]}, index["groups"]),
        }
        if entry.get("x"):
            compact["x"] = {str(position[k]): price for k, price in entry["x"].items()}
        if entry.get("d"):
            compact["d"] = entry["d"]  # deal ids, see collector.sitedeals
        result["c"][chain] = compact
    return result


def restore_prices(site_dir: Path) -> dict[str, dict[str, dict[str, str]]]:
    """chain -> store number -> {barcode: price}, read back from the files on disk.

    Format 1 can only restore the stores listed in stores.json (those with a location);
    format 2 restores every store of the chain."""
    listing = json.loads((site_dir / "stores.json").read_text(encoding="utf-8"))
    compact = listing.get("format") == FORMAT
    stores = listing["stores"] if compact else listing
    restored: dict[str, dict[str, dict[str, str]]] = {}
    group_of: dict[str, str] = {}  # "chain:id" -> price group (format 1)
    if compact:
        for chain, index in listing["chains"].items():
            restored[chain] = {i: {} for i in index["ids"]}
    else:
        for key, info in stores.items():
            chain, store_id = key.split(":", 1)
            restored.setdefault(chain, {})[store_id] = {}
            group_of[key] = info["group"]

    for path in sorted((site_dir / "p").glob("*.json")):
        for code, product in json.loads(path.read_text(encoding="utf-8")).items():
            for chain, entry in product["c"].items():
                if compact:
                    index = listing["chains"][chain]
                    for position in sellers_of(entry, index["groups"]):
                        price = entry.get("x", {}).get(str(position))
                        if price is None:
                            price = entry["g"][index["groups"][position]]
                        restored[chain][index["ids"][position]][code] = price
                else:
                    for key in entry["s"]:
                        if key in group_of:
                            price = entry.get("x", {}).get(key)
                            if price is None:
                                price = entry["g"][group_of[key]]
                            restored[chain][key.split(":", 1)[1]][code] = price
    return restored


def verify_restored(
    restored: Mapping[str, Mapping[str, Mapping[str, str]]],
    expected: Mapping[str, Mapping[str, Mapping[str, str]]],
    complete: bool,
) -> None:
    """Raise AssertionError at the first store whose restored prices differ from the
    published ones. `complete`: every store must be restorable (format 2)."""
    for chain, stores in restored.items():
        for store_id, prices in stores.items():
            if prices != expected[chain].get(store_id):
                raise AssertionError(f"{chain}:{store_id}: restored prices do not match")
        if complete and set(stores) != set(expected[chain]):
            raise AssertionError(f"{chain}: some stores are missing from the files")
    if complete and set(restored) != set(expected):
        raise AssertionError("some chains are missing from the files")
