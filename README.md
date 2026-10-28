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
