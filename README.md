# basket-compare-collector

Collects the price files that Israeli supermarket chains are required to publish under the
Food Act price-transparency regulations (in force since 2015), and turns them into compact,
ready-made data files.

This is the open part of a larger product. It only **reads** public files; it never changes
anything on the chains' servers.

אוסף את קבצי המחירים שרשתות המזון בישראל מחויבות לפרסם לפי חוק שקיפות המחירים, והופך אותם
לקבצים מוכנים ודחוסים. הפרויקט קורא קבצים ציבוריים בלבד.

## Layout

| Path | What it holds |
|---|---|
| `src/collector/` | The collector code |
| `tests/` | Automated tests — run on every push |

## Tools

| Command | What it does |
|---|---|
| `python -m collector.collect <chain> --out data` | download a chain's latest files |
| `python -m collector.build <chain>` | ready-made files; sets aside suspicious prices |
| `python -m collector.locate <chain>` | store locations (hand corrections: `locations/README.md`) |
| `python -m collector.publish <chains> [--compact]` | the files the website serves, checked by reading them back |
| `python -m collector.deal_check <chain>` | compares each deal with its own wording |
| `python -m collector.categories <chain>` | share of products with a category, and the names without one |
| `python -m collector.daily ...` | the daily pipeline's decisions (run gate, summary file, issue text, staleness) |
| `python -m collector.hourly <chain>` | hourly update from the partial Price files (workflow off until approved) |
| `python -m collector.probe [names]` | read-only check of Cerberus usernames, before adding a chain |

## Daily update

`.github/workflows/daily.yml` runs every morning at 06:00 Israel time, collects the four chains,
builds and checks them, and replaces the files of the release `site-data-latest`
(format: [SITE-DATA.md](SITE-DATA.md)). A failed or rejected update opens an issue; `freshness.yml` opens one
when the data is more than 36 hours old; `heartbeat.yml` keeps the schedule from being switched off.
The first run should be started by hand with *dry_run* ticked.

## Development

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # on Linux/macOS: .venv/bin/python
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m ruff format --check .
.venv/Scripts/python -m pytest
```

## Notes

- Not affiliated with any supermarket chain.
- Secrets (API keys, tokens) never live in this repository — only in GitHub Actions secrets.

## License

MIT — see [LICENSE](LICENSE).
