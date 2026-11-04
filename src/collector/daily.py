"""The daily pipeline's decisions, kept in Python so they can be tested (build task A).

The workflows (.github/workflows/daily.yml, freshness.yml) only run commands; what they
decide is here:

  hourly-gate  The same for the hourly update (07:00-23:59 in Israel, after today's full update).
  gate     Is it time to run? The schedule fires at 03:00 and 04:00 UTC because Israel is
           UTC+3 in summer and UTC+2 in winter, and GitHub cannot schedule in a time zone.
           A scheduled run goes ahead only when it is 06:00-07:59 in Israel and today's
           update has not been published yet, so exactly one of the two does the work (and a
           late or failed first run is retried by the second). A manual run always goes ahead.
  chains   Which chains have data to publish.
  meta     The small file published beside the data: when it was updated and how much it holds.
  issue    The text of the automatic GitHub Issue when something failed or was rejected.
  stale    Is the published data older than 36 hours?

Release layout ("site-data-latest", replaced every day):
  site-data.tar.gz     the files the website serves
  meta.json            the small file made by `meta`
  state-<chain>.tar.gz each chain's last accepted ready-made files, so tomorrow's build can
                       compare with them (sanity.py) and a rejected day keeps yesterday's data
"""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ISRAEL = ZoneInfo("Asia/Jerusalem")
RUN_HOURS = (6, 7)  # Israel clock hours in which a scheduled run may start
HOURLY_HOURS = range(7, 24)  # Israel clock hours of the hourly update (07:00 to 23:59)
MAX_AGE = timedelta(hours=36)


def parse_time(text: str) -> datetime:
    when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def read_meta(path: Path) -> dict | None:
    """The published meta file, or None when there is none yet or it cannot be read."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def should_run(event: str, now: datetime, last_updated: datetime | None) -> tuple[bool, str]:
    if event != "schedule":
        return True, f"started by hand ({event or 'no event'})"
    local = now.astimezone(ISRAEL)
    if local.hour not in RUN_HOURS:
        return False, f"{local:%H:%M} in Israel: not the morning run"
    if last_updated and last_updated.astimezone(ISRAEL).date() == local.date():
        return False, f"already updated today ({last_updated.astimezone(ISRAEL):%H:%M})"
    return True, f"{local:%H:%M} in Israel and not yet updated today"


def should_run_hourly(event: str, now: datetime, meta: dict | None) -> tuple[bool, str]:
    """The hourly update runs 07:00-23:59 in Israel, and only once today's full update has been
    published: it builds on that day's full files, and an old base would miss earlier changes."""
    if event != "schedule":
        return True, f"started by hand ({event or 'no event'})"
    local = now.astimezone(ISRAEL)
    if local.hour not in HOURLY_HOURS:
        return False, f"{local:%H:%M} in Israel: outside 07:00-23:59"
    stamp = (meta or {}).get("full_updated_at") or (meta or {}).get("updated_at")
    try:
        full = parse_time(stamp).astimezone(ISRAEL) if stamp else None
    except ValueError:
        full = None
    if full is None or full.date() != local.date():
        return False, "today's full update has not been published yet"
    return True, f"{local:%H:%M} in Israel, after today's full update ({full:%H:%M})"


def chains_with_data(data: Path) -> list[str]:
    return sorted(p.parent.parent.name for p in data.glob("*/ready/groups.json"))


def _read(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def make_meta(
    data: Path, chains: list[str], site: Path, now: datetime, full_updated_at: str | None = None
) -> dict:
    """What happened to each chain today, and how much the published data holds."""
    report: dict[str, dict] = {}
    for chain in chains:
        folder = data / chain
        ready = folder / "ready"
        last = _read(folder / "last_run.json", {})
        have_data = (ready / "groups.json").exists()
        result = last.get("result", "not run")
        if result == "updated" and have_data:
            status = "updated"
        elif result == "nothing new" and have_data:
            status = "unchanged"  # the hourly update found nothing to take in: not a problem
        elif have_data:
            status = "kept previous"
        else:
            status = "missing"
        summary = _read(ready / "summary.json", {})
        report[chain] = {
            "status": status,
            "reason": "; ".join(last.get("problems", []))
            or ("" if status == "updated" else result),
            "built_at": _read(ready / "built.json", {}).get("at", ""),
            "stores": summary.get("stores", 0),
            "prices": summary.get("prices", 0),
            "products": len(_read(ready / "products.json", {})),
            "suspicious": len(_read(ready / "suspicious.json", [])),
        }
    stats = _read(site / "stats.json", {})
    updated_at = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "updated_at": updated_at,
        # the last FULL update (the daily run); the hourly update keeps it from the meta it replaces
        "full_updated_at": full_updated_at or updated_at,
        "format": 2,
        "stores": stats.get("stores", 0),  # physical stores with a map location
        "products": stats.get("products", 0),
        "suspicious": sum(c["suspicious"] for c in report.values()),
        "classified_percent": stats.get("classified_percent", 0.0),
        "search_index_bytes": stats.get("search_bytes", 0),
        "search_index_largest_bytes": stats.get("search_largest_bytes", 0),
        "deal_files": stats.get("deal_files", 0),
        "deal_bytes": stats.get("deal_bytes", 0),
        "deals_left_out": stats.get("deals_left_out", {}),
        "files_total": stats.get("files_total", 0),
        "files_by_part": stats.get("files_by_part", {}),
        "deals_held_back": stats.get("deals_held_back", 0),
        "warnings": stats.get("warnings", []),
        "chains": report,
    }


def problems_in(meta: dict | None, collect_result: str = "", publish_result: str = "") -> list[str]:
    """Everything that needs a person's look, in plain Hebrew; empty when all is well."""
    found = []
    if collect_result not in ("", "success"):
        found.append(f"שלב האיסוף נגמר ב: {collect_result}")
    if publish_result not in ("", "success"):
        found.append(f"שלב ההכנה והפרסום נגמר ב: {publish_result}")
    if meta is None:
        if not found:
            found.append("לא נוצר קובץ סיכום לריצה")
        return found
    found += [w.split("\n")[0] for w in meta.get("warnings", [])]  # the Hebrew line of each
    for chain, info in meta["chains"].items():
        if info["status"] == "kept previous":
            found.append(
                f"{chain}: העדכון של היום נדחה, האתר ממשיך להציג את הנתונים הקודמים"
                + (f" ({info['reason']})" if info["reason"] else "")
            )
        elif info["status"] == "missing":
            found.append(f"{chain}: אין נתונים כלל, הרשת לא תופיע באתר")
    return found


def issue_body(problems: list[str], run_url: str, meta: dict | None) -> str:
    lines = ["העדכון היומי של הנתונים לא עבר כרגיל.", ""]
    lines += [f"- {p}" for p in problems]
    lines += ["", "מה זה אומר: הנתונים שכבר באתר נשארים כפי שהיו, ולא נפגע מהם דבר. "]
    if meta:
        lines += [f"העדכון האחרון שפורסם: {meta['updated_at']}"]
    if run_url:
        lines += ["", f"פרטי הריצה: {run_url}"]
    return "\n".join(lines) + "\n"


def stale_message(meta: dict | None, now: datetime) -> str | None:
    """None when the data is fresh; otherwise why it is not."""
    if meta is None:
        return "אין קובץ סיכום מפורסם: הנתונים לא פורסמו מעולם, או שהקובץ לא נקרא"
    try:
        age = now - parse_time(meta["updated_at"])
    except (KeyError, ValueError):
        return "בקובץ הסיכום אין זמן עדכון תקין"
    if age > MAX_AGE:
        hours = int(age.total_seconds() // 3600)
        return f"הנתונים לא עודכנו כבר {hours} שעות (העדכון האחרון: {meta['updated_at']})"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("gate", "hourly-gate", "chains", "meta", "issue", "stale"):
        command = sub.add_parser(name)
        command.add_argument("--now", help="ISO time instead of the clock (tests)")
    sub.choices["gate"].add_argument("--event", default="")
    sub.choices["gate"].add_argument("--meta", type=Path, default=Path("meta.json"))
    sub.choices["hourly-gate"].add_argument("--event", default="")
    sub.choices["hourly-gate"].add_argument("--meta", type=Path, default=Path("meta.json"))
    sub.choices["chains"].add_argument("--data", type=Path, default=Path("data"))
    sub.choices["meta"].add_argument("--data", type=Path, default=Path("data"))
    sub.choices["meta"].add_argument("--site", type=Path, default=Path("site-data"))
    sub.choices["meta"].add_argument("--out", type=Path, default=Path("site-data/meta.json"))
    sub.choices["meta"].add_argument(
        "--carry-full-from", type=Path, help="hourly update: keep the full-update time of this meta"
    )
    sub.choices["meta"].add_argument("chains", nargs="+")
    sub.choices["issue"].add_argument("--meta", type=Path, default=Path("meta.json"))
    sub.choices["issue"].add_argument("--collect-result", default="")
    sub.choices["issue"].add_argument("--publish-result", default="")
    sub.choices["issue"].add_argument("--run-url", default="")
    sub.choices["stale"].add_argument("--meta", type=Path, default=Path("meta.json"))
    args = parser.parse_args(argv)
    now = parse_time(args.now) if args.now else datetime.now(UTC)

    if args.command == "gate":
        meta = read_meta(args.meta)
        last = parse_time(meta["updated_at"]) if meta and "updated_at" in meta else None
        go, reason = should_run(args.event, now, last)
        print(f"run={'true' if go else 'false'}")
        print(f"reason={reason}", file=sys.stderr)
        return 0
    if args.command == "hourly-gate":
        go, reason = should_run_hourly(args.event, now, read_meta(args.meta))
        print(f"run={'true' if go else 'false'}")
        print(f"reason={reason}", file=sys.stderr)
        return 0
    if args.command == "chains":
        print(" ".join(chains_with_data(args.data)))
        return 0
    if args.command == "meta":
        carried = None
        if args.carry_full_from:
            before = read_meta(args.carry_full_from) or {}
            carried = before.get("full_updated_at") or before.get("updated_at")
        meta = make_meta(args.data, args.chains, args.site, now, carried)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        updated = any(c["status"] == "updated" for c in meta["chains"].values())
        print(f"any_updated={'true' if updated else 'false'}")
        return 0
    if args.command == "issue":
        meta = read_meta(args.meta)
        found = problems_in(meta, args.collect_result, args.publish_result)
        if not found:
            return 0
        print(issue_body(found, args.run_url, meta), end="")
        return 2
    message = stale_message(read_meta(args.meta), now)
    if message:
        print(message)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
