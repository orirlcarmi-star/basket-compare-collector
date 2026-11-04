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
* `categories.json` — the 14 categories `{id, name}`: dairy, meat, fish, produce, bakery, pantry, snacks, drinks, frozen,
  cleaning, hygiene, baby, home and **pets (חיות מחמד, new)**. A product with no `k` is "לא מסווג". A product is left
  without a category when no rule is sure; make-up, nail and lip products are deliberately never given one.
* `s/<file>.json` — the search index, split by the first two letters of each word:
  `{"p": [[barcode, name, category?], ...], "w": {word: [position, ...]}}`. `w` lists the words that begin with those two
  letters, each with the positions (in `p`) of the products that contain it; `p` holds the barcode, **the name to show**
  and the category id (left out when there is none). The file name is the two letters as 4 hex digits each. See
  "Search" below.
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

**Variants:** a promotion id whose terms differ between stores has one file per variant: `7`, `7-2`, `7-3`... A variant
exists only when `q`, `p`, `m`, `c` or `e` differ. The variant that applies in the most stores has the plain id.
Different wording does not make a variant, and neither do the items: stores that sell other kinds ("2 for 13.90 on
herbs" lists 3, 4 or 5 barcodes depending on the store) share **one** file whose `i` is all their barcodes together
and whose `s` is all their stores together. This is safe because the calculator only prices products that the store
really sells (check the store's stock before applying a deal); it assumes that a store's own deal list names every
product it sells that takes part, which is what the chain publishes for the store.

**Left out** (counted in `stats.json` under `deals_left_out`): coupons and deals needing a minimum basket; credit-card
deals (this format has only a club flag, and showing them to everyone would be wrong); deals whose quantity is not a
whole number (such as "300 g for 25": there is no whole `q` in the units of the prices); deals already over; deals
whose limit is below `q`; deals none of whose items the chain sells.

**Which units get the price:** when the basket holds units of different prices from `i`, the `q` units that get the
price `p` are **the cheapest ones** (decided with the product owner). The deal never promises more than the register
gives. Example: two units of milk at 7.00 and one at 9.00 under "2 for 12": the two cheapest cost 12.00 together, the
dearer one costs 9.00 — 21.00 in all.

## How many files

Cloudflare Pages takes at most 20,000 files in one deployment. `publish` counts the files of the site folder (products
`p/`, search `s/`, deals `d/`, the rest) and **fails above 18,000** with a message that names the biggest part, so a
package the host would refuse is never published. The count is in `stats.json` (`files_total`, `files_by_part`) and in
`meta.json`. With 8,192 product files the other parts have about 9,800 files between them.

## Search (`s/`)

**What changed for the website:** the search files now carry the product name and category, so showing results needs
**one request per word of the query** (usually 1 or 2) instead of one per result (~30). The product files (`p/`) are
read only when something is added to the basket. Before, `s/<file>.json` was `{word: [barcode, ...]}`; now it is the
object above. A barcode is `p[i][0]`, its name `p[i][1]`, its category id `p[i][2]` when present.

How to search (the reference is `collector.searchindex.search`):

1. Write the query in the normal form of `collector.textnorm` (no vowel points or apostrophes, final letters made
   plain, a dotted abbreviation such as "גב." spelled out, stop words and numbers dropped; "גבינת" is "גבינה").
2. For each word of two or more letters read `s/<file of its first two letters>.json`; take the products of every word
   that **starts with** the query word (typing "גבינ" finds גבינה and גבינות).
3. Keep only the products found for all the words of the query. The first file already holds them all.

**Prefix letters:** a word with a prefix letter is also indexed without it, so "קרטון" finds "בקרטון", "חלב" finds
"וחלב", and "הדרין" finds "מהדרין". Only for ו ב ל כ ש ה מ, only when at least three letters remain, and only when the
rest is a word the catalog really uses on its own (or one of a short list, `EXTRA_STEMS`). The word itself is always
indexed too. So "בקר" (beef) is never cut to "קר" (cold), and "בננה" is not "ננה". If a word still gets it wrong,
add it to `EXTRA_STEMS` or leave it out of the vocabulary; it only ever adds results, never hides one.

**Size:** the index is bigger than before, because a product's name is repeated in the file of each of its words.
The real size is in `meta.json` (`search_index_bytes`, `search_index_largest_bytes`) after each run. A test catalog of
38,000 invented products with few distinct words (a pessimistic case: common words pile up in few files) gave 473
files, 9.0 MB (2.2 MB gzipped), the largest 1.0 MB. If the real largest file is big, split the heavy prefixes by three
letters. The number of files is checked together with all the others (18,000 in all, see "How many files").

**Facts in the search record (optional — off until the product owner decides, see `SEARCH-FACTS.md`).**
`publish --compact --search-facts` adds a fourth place to a record: an object with the facts the website needs for
its narrowing buttons ("which fat percent? which size?"), so it need not read the product files of up to 60 candidates:

| key | meaning | same as in the product file |
|---|---|---|
| `f` | fat percent | `a.f` (`"3"`) |
| `z` | what the package holds, `[amount, "l" \| "kg" \| "unit"]` | `z` |
| `w` | `true` when sold by weight | `w` |

A missing value is not written, and when a product has none of them the record is exactly what it was
(`[barcode, name, category?]`). **The first three places do not move and do not change meaning**, so a reader that knows
only those keeps working. One detail: when a product has facts but no category, the category place holds `""` (the
empty string, meaning "no category") so that the facts can stay in the fourth place; a reader that takes the category
as "the third place, if there is one" should treat `""` as none. Example, a file with three products:

```json
{"p": [["7290000000015", "חלב 3% בקרטון 1 ליטר", "dairy", {"f": "3", "z": ["1", "l"]}],
       ["7290000000084", "עגבניות", "", {"w": true}],
       ["7290000000206", "מוצר ללא נתונים"]],
 "w": {"חלב": [0], "עגבנית": [1], "מוצר": [2]}}
```
The index grows by about 30% (the name and facts are repeated in the file of every word of the name): measurements
and options in `SEARCH-FACTS.md`.

## `meta.json` and the hourly update

`updated_at` is when the files were last replaced (by the daily run or by the hourly update); `full_updated_at` is when
the last **full** update (the daily run) was. Per chain, `status` is `updated`, `unchanged` (the hourly update found
nothing new), `kept previous` (the update was rejected by the checks, yesterday's data stays) or `missing`.

The hourly update (`collector.hourly`, workflow `hourly.yml`, **off until approved**) takes in the chains' small "Price"
files, which hold only the items whose price changed, on top of the morning's full update. It runs 07:00-23:59 Israel
time, only after today's full update, with the same checks as the daily run. It cannot learn that a product is gone
(only the full file says so) and does not change deals. The files of the website have the same format as after the
daily run; only `updated_at` and some prices differ.

## Proposal (not implemented): deals by weight

**The gap.** "300 g for 25" (the chain's `MinQty` 0.3 kg, price 25.00) is left out today, because `q` is a whole number
of the units of the prices, and for a product sold by weight those units are kilos. On 6 Shufersal stores that was
121 deals of about 2,000 (counted under `deals_left_out` as "quantity not a whole number"). A fixed price per kilo
("109 per kg") is already in, as `q = 1`.

**The proposal** — nothing changes for what the website reads today:

1. Weight deals get their **own reference list in the product**: `"dw": [id, ...]` next to `"d"`, and their files go to
   the same folder `d/<chain>/<id>.json`. A reader that only knows `"d"` never meets one, so it cannot misread a
   fractional quantity.
2. In a weight deal file `q` is **kilos as a decimal string**, `"0.3"`; `p` is the price of those `q` kilos together;
   `m` (when stated) is the most kilos that get the deal, also a decimal string. Everything else (`t`, `c`, `e`, `i`, `s`)
   means what it means now.
3. How to apply (for the website): the basket holds `w` kilos of a product of `i`; the deal applies
   `floor(w / q)` times (no more than `floor(m / q)`), each time at `p`; the remaining weight costs the normal price per
   kilo. Several products in `i` add up their weights; the cheapest kilos get the price, as for the other deals.
4. `publish` would write them only for items sold by weight and only when `q` is a decimal; every other deal stays as it is.

**Choices to decide:**
- *Rounding of the weight at the register.* A shopper rarely weighs exactly 0.3 kg. The proposal charges the normal price
  for the weight left after the whole applications; some chains charge the deal price per gram instead (`p / q` per kg
  for the whole weight once it reaches `q`). Which one is true for each chain is not in the files; the first never
  promises more than the register gives.
- *Alternative:* `q` in grams (`300`) with a `"u": "g"` field. A whole number again, but a reader that ignores `u`
  would read 300 units, so the weight deals would have to be kept apart anyway. Not recommended.

**Effort:** small on our side (one more list in the products and the same deal file with a decimal `q`) and a short
addition to the calculator on the website; no change to the files it reads today.
