# The published data (for whoever builds the website)

Every morning the pipeline replaces the files of the release **`site-data-latest`**:

| Asset | What it is |
|---|---|
| `site-data.tar.gz` | all the files below, packed |
| `meta.json` | small: when it was updated, how many stores / products / suspicious prices, what happened to each chain |
| `state-<chain>.tar.gz` | the pipeline's own memory of yesterday (not for the website) |
| `unclassified.txt` | product names no category rule was sure about: `barcode<TAB>name` |

## Inside `site-data.tar.gz` (format 2)

* `stores.json` — `{"format": 2, "stores": {...}, "chains": {...}}`. `stores`: `"chain:number"` → name, city, lat, lon,
  precision, price group. `chains`: per chain `ids` (every store in a fixed order) and `groups` (its price group).
* `p/<n>.json`, n = 0…8191 — products; the file of a barcode is FNV-1a (32 bit, over its characters) modulo 8192.
  A product: `n` name, `q`/`u` quantity and unit (left out when empty), `w` sold by weight (only when true),
  `k` category id, `a` facts from the name (`f` fat percent, `b` brand, `d` "free of": lactose / gluten / sugar /
  added_sugar), `z` what the package holds `[amount, "l" | "kg" | "unit"]`, and `c` per chain:
  `g` price per price group, and the sellers — nothing = every store of the chain, `o` = every store except these
  positions, `k` = every store of these price groups plus `s`, or `s` alone — and `x` position → price for stores
  whose price differs from their group's, and `d` the ids of the deals that mention the product (see "Deals").
  Positions index `chains[chain].ids`.
  The reference decoder is `collector.compact.restore_prices`.
* **Unit price** = the shopper's price ÷ `z[0]`, per `z[1]` (so 7.35 for a `["1.5","l"]` product is 4.90 per litre).
  Products with no readable size have no `z`.
* `d/<chain>/<id>.json` — one file per deal, fetched only for the products in the basket. See "Deals" below.
* `categories.json` — the 13 categories `{id, name}`. A product with no `k` is "לא מסווג".
* `s/<file>.json` — the search index, split by the first two letters of each word. Rules and a reference search:
  `collector.searchindex` and `collector.textnorm` (spelling of Hebrew: no vowel points or apostrophes, final letters
  made plain, abbreviations such as "גב." spelled out). The file name is the two letters as 4 hex digits each.
* `stats.json`, `meta.json` — counts for monitoring.

The old format (format 1: `publish` without `--compact`) is still available; the pipeline publishes format 2 only.

## Deals (`d/<chain>/<id>.json`, format 2 only)

A product's entry for a chain lists `"d": ["<id>", ...]`, the deals in which it takes part. The browser fetches
`d/<chain>/<id>.json` for each id the basket touches. Only deals the calculator can price are published:
"X for Y" deals and fixed prices, with no coupon and no minimum basket amount.

| Field | Meaning |
|---|---|
| `t` | the chain's wording (display only) |
| `q` | units needed for one application, a whole number. A fixed price per unit is `q = 1` |
| `p` | the price of those `q` units together, an exact decimal string, **in the units of the prices in the product files** (items; kilos for products sold by weight) |
| `m` | the most units that get the deal (the chain's `MaxQty`). Absent: no limit stated. The deal applies `floor(m / q)` times |
| `c` | `true`: only the chain's club members. Absent: everyone |
| `e` | when it ends, `YYYY-MM-DDTHH:MM`, **Israel's clock**. Absent: the chain gave no end. Do not use the deal after it |
| `i` | the barcodes that take part (only products that appear in the product files for that chain) |
| `s` | where it applies. Absent: every store of the chain. Otherwise a list whose elements are price-group ids (a string such as `"g1"`: every store of that group) and store positions (an integer: the place in `chains.<chain>.ids` of `stores.json`). A group is named only when the deal applies in **all** its stores |

**Meaning:** every `q` units taken from the products in `i`, in any mix, cost `p` together. This can be applied again
and again up to `m` units in all; every other unit costs its normal price. Example, "2 for 20":

```json
{"t":"2ב20 גבינה","q":2,"p":"20.00","m":6,"e":"2026-11-12T23:59","i":["7290000000015","7290004131074"],"s":["g1",14]}
```

Basket: three units of `7290000000015` at 12.90 → at a store of price group `g1` (or at the store in position 14) the first
two cost 20.00 together and the third 12.90: 32.90 instead of 38.70. At any other store the deal does not apply.

**Variants:** a promotion id whose terms differ between stores (another price, other items, other end) has one file per
variant: `7`, `7-2`, `7-3`... The variant that applies in the most stores has the plain id. Different wording alone does
not make a variant.

**Left out** (counted in `stats.json` under `deals_left_out`): coupons and deals needing a minimum basket; credit-card
deals (this format has only a club flag, and showing them to everyone would be wrong); deals whose quantity is not a
whole number (such as "300 g for 25": there is no whole `q` in the units of the prices); deals already over; deals
whose limit is below `q`; deals none of whose items the chain sells.

**Not decided here:** when the basket holds units of different prices from `i`, the file does not say which `q` of them
get the price `p`. Giving it to the cheapest units never promises more than the register gives; giving it to the dearest
promises the most. The website must pick one and say which.
