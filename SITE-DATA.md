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
  whose price differs from their group's. Positions index `chains[chain].ids`.
  The reference decoder is `collector.compact.restore_prices`.
* **Unit price** = the shopper's price ÷ `z[0]`, per `z[1]` (so 7.35 for a `["1.5","l"]` product is 4.90 per litre).
  Products with no readable size have no `z`.
* `categories.json` — the 13 categories `{id, name}`. A product with no `k` is "לא מסווג".
* `s/<file>.json` — the search index, split by the first two letters of each word. Rules and a reference search:
  `collector.searchindex` and `collector.textnorm` (spelling of Hebrew: no vowel points or apostrophes, final letters
  made plain, abbreviations such as "גב." spelled out). The file name is the two letters as 4 hex digits each.
* `stats.json`, `meta.json` — counts for monitoring.

The old format (format 1: `publish` without `--compact`) is still available; the pipeline publishes format 2 only.
