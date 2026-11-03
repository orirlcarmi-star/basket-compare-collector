"""Turn each store's address into a point on the map (build step 2.5).

Done once per store and kept in locations/<chain>.json (committed: public data, and
it spares the free map service). A store is looked up again only when it is new or
its address changed.

- City: some chains write the official settlement code (Shufersal: "2530") instead of
  the name; the code is translated with the Central Bureau of Statistics list.
- Map service: OpenStreetMap's Nominatim, at most one request per second, with a
  User-Agent naming this project (its usage policy).
- Precision: "address" (street and number), "street" (the street, number unknown to
  the map), "store name" (the map's own mark for the chain in that city — may be another
  branch there), or "city" (the city centre). The last two are rough, for review. A street found far
  from its city centre is another street with the same name, and is not used.

- Manual corrections: locations/<chain>.manual.json (see locations/README.md) fixes a store
  by hand. It beats the map search: those stores are never looked up, and the published
  files use the corrected point (`apply_manual`).

Usage: python -m collector.locate <chain> --data data
"""

import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = (
    "basket-compare-collector (+https://github.com/orirlcarmi-star/basket-compare-collector)"
)
NOMINATIM = "https://nominatim.openstreetmap.org/search"
SETTLEMENTS = (
    "https://data.gov.il/api/3/action/datastore_search"
    "?resource_id=5c78e9fa-c2e2-4771-93ff-7f400a12f7ba&limit=5000"
)
SECONDS_BETWEEN_REQUESTS = 1.1
# A street found farther than this from its city centre is most likely another street
# with the same name elsewhere.
MAX_KM_FROM_CITY = 15

Lookup = Callable[[str], tuple[float, float] | None]


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    precision: str  # "address", "street", "store name" or "city"
    address: str  # the address this was found for; a change means looking up again
    city: str


def http_json(url: str) -> object:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https hosts only
        return json.loads(response.read())


def load_settlements(get: Callable[[str], object] = http_json) -> dict[str, str]:
    """Official settlement code -> name."""
    records = get(SETTLEMENTS)["result"]["records"]  # type: ignore[index]
    return {r["סמל_ישוב"].strip(): " ".join(r["שם_ישוב"].split()) for r in records}


def city_name(city: str, settlements: Mapping[str, str]) -> str:
    city = city.strip()
    return settlements.get(city.lstrip("0") or "0", city) if city.isdigit() else city


_NOISE = re.compile(r"""רח['׳]|רחוב|שד['׳]|פינת.*|ת\.?ד\.?.*|[()"״]""")


def clean_address(address: str) -> str:
    """Drop words the map service trips on: "רח'", "פינת ...", P.O. boxes, quotes, and
    whatever follows the house number ("אדום 24 פארק התעשיות" -> "אדום 24")."""
    first = " ".join(_NOISE.sub(" ", address.split(",")[0]).split())
    street_and_number = re.match(r"^(\D+?\s*\d+)(?!\d)", first)
    return street_and_number.group(1) if street_and_number else first


def street_only(address: str) -> str:
    """The street without its number: the map often has the street but not the house."""
    return " ".join(re.sub(r"\d+", " ", clean_address(address)).split())


_ABBREVIATED_STREET = re.compile(r"(?<![\w])(?:רח|שד|ד)\.\s*")
_COMMERCIAL_CENTRE = re.compile(r"מרכז מסחרי\s+")
_INDUSTRIAL_ZONE = re.compile(r"(?<![\w])(?:א\.ת\.?|אזה\"ת)\s*")
_NUMBER_FIRST = re.compile(r"^(\d+)\s+(\D+)$")


def other_spellings(address: str) -> list[str]:
    """More ways to write an address the map did not know, from the habits seen in the
    chains' lists: "רח.המלאכה 2" (a dot instead of a space), "ד.ויצמן 1", "מרכז מסחרי X"
    (the map knows X), "א.ת באר טוביה" (written "אזור התעשייה ..." on the map), and the house
    number written first ("1 אחי מאיר"). Only spellings that differ from the usual cleaning."""
    usual = clean_address(address)
    variants: list[str] = []
    text = " ".join(address.split(",")[0].split())
    for pattern, replacement in (
        (_ABBREVIATED_STREET, ""),
        (_COMMERCIAL_CENTRE, ""),
        (_INDUSTRIAL_ZONE, "אזור התעשייה "),
    ):
        changed = " ".join(pattern.sub(replacement, text).split())
        if changed != text:
            variants.append(clean_address(changed))
    for candidate in (text, *variants):
        match = _NUMBER_FIRST.match(" ".join(candidate.replace("רח'", " ").split()))
        if match:
            variants.append(clean_address(f"{match[2]} {match[1]}"))
    unique = {v: None for v in variants if v and v != usual}
    return list(unique)


def nominatim(query: str, get: Callable[[str], object] = http_json) -> tuple[float, float] | None:
    params = {"q": query, "countrycodes": "il", "format": "json", "limit": 1}
    results = get(f"{NOMINATIM}?{urlencode(params)}")
    time.sleep(SECONDS_BETWEEN_REQUESTS)
    if not results:
        return None
    first = results[0]  # type: ignore[index]
    return float(first["lat"]), float(first["lon"])


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def locate(
    address: str,
    city: str,
    lookup: Lookup,
    centres: dict[str, tuple[float, float] | None],
    chain_name: str = "",
    best: str = "address",
) -> Location | None:
    """Try the address, then the street, then the chain's name in the city (the map
    marks some supermarkets), then the city centre. `best` caps the precision claimed
    (an address guessed from the store's name is "street" at best)."""
    if city not in centres:
        centres[city] = lookup(city)
    centre = centres[city]
    attempts = {}  # query -> precision; a repeated query is tried once
    for street, precision in (
        (address, best),
        (clean_address(address), best),
        (street_only(address), "street"),
        *((v, best if re.search(r"\d", v) else "street") for v in other_spellings(address)),
        (chain_name, "store name"),
    ):
        if street.strip():
            attempts.setdefault(f"{street}, {city}", precision)
    for query, precision in attempts.items():
        point = lookup(query)
        if point and (centre is None or distance_km(point, centre) <= MAX_KM_FROM_CITY):
            return Location(point[0], point[1], precision, address, city)
    if centre:
        return Location(centre[0], centre[1], "city", address, city)
    return None


CHAIN_NAMES = {
    "shufersal": "שופרסל",
    "ramilevi": "רמי לוי",
    "osherad": "אושר עד",
    "yohananof": "יוחננוף",
}
_CHAIN_WORDS = re.compile("|".join(CHAIN_NAMES.values()))
_ABBREVIATIONS = {
    "ראשלצ": "ראשון לציון",
    'ת"א': "תל אביב",
    'ב"ש': "באר שבע",
    'פ"ת': "פתח תקווה",
    'ר"ג': "רמת גן",
}


# Settlements whose name is far more often a word of the address or store name than the city:
# "רחוב אחד העם", "אזור התעשייה", "יגאל אלון" must not become the cities רחוב, אזור, אלון.
_NOT_CITY_WORDS = {"אזור", "רחוב", "ישן", "אלון"}


def settlement_in(text: str, settlements: Mapping[str, str]) -> str:
    """The longest settlement name written in the text ("נתניה הדרים" -> "נתניה")."""
    for short, full in _ABBREVIATIONS.items():
        text = text.replace(short, full)
    words = f" {' '.join(re.sub(r'[^\w"]', ' ', text).split())} "
    found = ""
    for name in settlements.values():
        if name in _NOT_CITY_WORDS:
            continue
        for variant in {name, name.split(" -")[0]}:  # "תל אביב -יפו" is written "תל אביב"
            if len(variant) > len(found) and len(variant) >= 3 and f" {variant} " in words:
                found = name
    return found


def place_of(store: Mapping[str, str], settlements: Mapping[str, str]) -> tuple[str, str, bool]:
    """(address, city, address_from_name). Without a city (Yochananof writes code 0),
    the store name names it ("יוחננוף נתניה הדרים"), and the rest of the name ("הדרים")
    stands in for a missing address."""
    city = city_name(store["city"], settlements)
    address = store["address"].strip()
    if address.lower() == "unknown":
        address = ""
    if city and not city.isdigit():
        return ("" if address == city else address), city, False
    name = " ".join(_CHAIN_WORDS.sub(" ", store["name"]).split())
    city = settlement_in(f"{name} {address}", settlements)
    if not city:
        return ("" if address == name else address), name, False
    if address and address != city:
        return address, city, False
    rest = name
    for short, full in _ABBREVIATIONS.items():
        rest = rest.replace(short, full)
    rest = " ".join(re.sub(r"[-–]", " ", rest.replace(city.split(" -")[0], " ")).split())
    return rest, city, True


# Israel, with a margin: a hand-written point outside it is a typo (swapped or missing digits).
_LAT_RANGE, _LON_RANGE = (29.0, 33.6), (34.0, 36.0)
_PRECISIONS = {"address", "street", "store name", "city"}


def load_manual(path: Path) -> dict[str, dict]:
    """The hand-written corrections of one chain; {} when there is no such file.

    {"413": {"lat": 32.07, "lon": 34.78, "city": "תל אביב", "note": "why"}} — the store
    number may be written with or without leading zeros. Raises ValueError, naming the
    store, for a point outside Israel or a missing field, so a typo never reaches the map."""
    if not path.exists():
        return {}
    corrections: dict[str, dict] = {}
    for raw_id, entry in json.loads(path.read_text(encoding="utf-8")).items():
        if raw_id.startswith("_"):  # "_help" and other comments
            continue
        sid = raw_id.strip().lstrip("0") or "0"
        try:
            lat, lon = float(entry["lat"]), float(entry["lon"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"{path.name}: store {raw_id}: lat and lon are needed") from None
        if not (_LAT_RANGE[0] <= lat <= _LAT_RANGE[1] and _LON_RANGE[0] <= lon <= _LON_RANGE[1]):
            raise ValueError(f"{path.name}: store {raw_id}: {lat}, {lon} is not in Israel")
        precision = entry.get("precision", "address")
        if precision not in _PRECISIONS:
            raise ValueError(f"{path.name}: store {raw_id}: unknown precision {precision!r}")
        corrections[sid] = {
            "lat": lat,
            "lon": lon,
            "precision": precision,
            "address": entry.get("note", ""),
            "city": entry.get("city", ""),
        }
    return corrections


def apply_manual(located: Mapping[str, dict], manual: Mapping[str, dict]) -> dict[str, dict]:
    """The searched locations with the hand-written ones on top (store numbers compared
    without leading zeros). A correction without a city keeps the searched city."""
    result = {(sid.strip().lstrip("0") or "0"): place for sid, place in located.items()}
    for sid, fix in manual.items():
        result[sid] = dict(fix, city=fix["city"] or result.get(sid, {}).get("city", ""))
    return result


def update_locations(
    stores: list[dict],
    known: Mapping[str, dict],
    settlements: Mapping[str, str],
    lookup: Lookup,
    chain_name: str = "",
    retry_rough: bool = False,
    manual: Mapping[str, dict] | None = None,
) -> tuple[dict[str, dict], list[str]]:
    """Locations for all physical stores, reusing known ones; also the stores not found.
    `retry_rough` looks up again the stores known only by city centre (run by hand after
    improving the search — not every night, to spare the free map service). Stores with a
    hand-written correction are not searched, and not listed here: the correction wins."""
    result: dict[str, dict] = {}
    missing: list[str] = []
    centres: dict[str, tuple[float, float] | None] = {}
    for store in stores:
        if store["is_online"]:
            continue
        sid = store["store_id"]
        if (sid.strip().lstrip("0") or "0") in (manual or {}):
            continue
        address, city, from_name = place_of(store, settlements)
        old = known.get(sid)
        rough = retry_rough and old is not None and old["precision"] == "city"
        if old and old["address"] == address and old["city"] == city and not rough:
            result[sid] = old
            continue
        best = "street" if from_name else "address"
        found = locate(address, city, lookup, centres, chain_name, best)
        if found:
            result[sid] = asdict(found)
        else:
            missing.append(f"{sid} {store['name']} | {store['address']} | {city}")
    return without_shared_name_points(result, lookup, centres), missing


def without_shared_name_points(
    located: dict[str, dict], lookup: Lookup, centres: dict[str, tuple[float, float] | None]
) -> dict[str, dict]:
    """A chain-name point given to several stores is one branch among many in that city
    (seen: 6 Shufersal stores in Haifa on one spot) — those go back to the city centre."""
    by_point: dict[tuple[float, float], list[str]] = {}
    for sid, loc in located.items():
        if loc["precision"] == "store name":
            by_point.setdefault((loc["lat"], loc["lon"]), []).append(sid)
    for sids in by_point.values():
        if len(sids) < 2:
            continue
        for sid in sids:
            city = located[sid]["city"]
            if city not in centres:
                centres[city] = lookup(city)
            centre = centres[city]
            if centre:
                located[sid] = dict(located[sid], lat=centre[0], lon=centre[1], precision="city")
    return located


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chain")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--locations", type=Path, default=Path("locations"))
    parser.add_argument("--retry-rough", action="store_true", help="look up city-only ones again")
    args = parser.parse_args(argv)

    stores = json.loads((args.data / args.chain / "stores.json").read_text(encoding="utf-8"))
    path = args.locations / f"{args.chain}.json"
    manual = load_manual(args.locations / f"{args.chain}.manual.json")
    known = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    locations, missing = update_locations(
        stores,
        known,
        load_settlements(),
        nominatim,
        CHAIN_NAMES.get(args.chain, ""),
        args.retry_rough,
        manual,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(sorted(locations.items())), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",  # the same file on every computer
    )
    counts = Counter(loc["precision"] for loc in locations.values())
    print(
        f"{args.chain}: {len(locations)} stores located (by address {counts['address']}, "
        f"by street {counts['street']}, by store name {counts['store name']}, "
        f"city centre only {counts['city']}), "
        f"{len(missing)} not found; {len(manual)} fixed by hand"
    )
    for line in missing:
        print(f"  not found: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
