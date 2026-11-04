import json
from datetime import UTC, datetime, timedelta

import pytest

from collector.daily import (
    chains_with_data,
    issue_body,
    make_meta,
    problems_in,
    should_run,
    stale_message,
)
from collector.daily import main as daily_main


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


# --- the morning gate: 06:00 in Israel is 04:00 UTC in winter and 03:00 UTC in summer ---


@pytest.mark.parametrize(
    ("now", "last", "go"),
    [
        ("2026-11-04T04:00", None, True),  # winter, first cron: 06:00 in Israel
        ("2026-11-04T03:00", None, False),  # winter, the other cron: only 05:00
        ("2026-07-15T03:00", None, True),  # summer, first cron: 06:00
        ("2026-07-15T04:00", None, True),  # summer, the second cron, nothing done yet: retry
        ("2026-07-15T04:00", "2026-07-15T03:20", False),  # ... but done by the first: skip
        ("2026-11-04T04:40", "2026-11-03T04:20", True),  # yesterday's update does not count
        ("2026-11-04T05:30", None, True),  # a late start (07:30 in Israel) still goes ahead
        ("2026-11-04T07:00", None, False),  # 09:00: too late for the morning run
        ("2026-11-04T21:30", None, False),
    ],
)
def test_scheduled_run_gate(now, last, go):
    assert should_run("schedule", utc(now), utc(last) if last else None)[0] is go


def test_the_day_is_the_israeli_day_not_the_utc_day():
    # Updated at 23:30 UTC on the 3rd = 01:30 on the 4th in Israel: counts as the 4th.
    assert not should_run("schedule", utc("2026-11-04T04:10"), utc("2026-11-03T23:30"))[0]


@pytest.mark.parametrize("event", ["workflow_dispatch", ""])
def test_a_manual_run_always_goes_ahead(event):
    assert should_run(event, utc("2026-11-04T14:00"), utc("2026-11-04T04:10"))[0]


def test_gate_command_writes_the_output_line(tmp_path, capsys):
    meta = tmp_path / "meta.json"
    code = daily_main(
        ["gate", "--event", "schedule", "--meta", str(meta), "--now", "2026-11-04T04:00:00Z"]
    )
    assert code == 0 and capsys.readouterr().out.strip() == "run=true"  # no meta yet: first run
    meta.write_text(json.dumps({"updated_at": "2026-11-04T04:10:00Z"}), encoding="utf-8")
    daily_main(
        ["gate", "--event", "schedule", "--meta", str(meta), "--now", "2026-11-04T05:00:00Z"]
    )
    assert capsys.readouterr().out.strip() == "run=false"
    meta.write_text("not json", encoding="utf-8")  # a broken meta file must not stop the run
    daily_main(
        ["gate", "--event", "schedule", "--meta", str(meta), "--now", "2026-11-04T04:00:00Z"]
    )
    assert capsys.readouterr().out.strip() == "run=true"


# --- what a day left on disk ---


def make_chain(data, chain, *, result, built=True, suspicious=2):
    folder = data / chain
    (folder / "ready").mkdir(parents=True)
    if built:
        for name, value in {
            "groups": [],
            "products": {"a": {}, "b": {}, "c": {}},
            "summary": {"stores": 5, "prices": 100},
            "suspicious": [{}] * suspicious,
            "built": {"at": "2026-11-03T04:30:00+00:00"},
        }.items():
            (folder / "ready" / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    if result:
        problems = ["stores dropped from 10 to 5"] if result == "rejected" else []
        (folder / "last_run.json").write_text(
            json.dumps({"result": result, "problems": problems}), encoding="utf-8"
        )


@pytest.fixture
def day(tmp_path):
    data, site = tmp_path / "data", tmp_path / "site"
    make_chain(data, "good", result="updated")
    make_chain(data, "rejected", result="rejected", suspicious=0)
    make_chain(data, "broken", result="nothing collected", built=False)
    site.mkdir()
    stats = {
        "stores": 7, "products": 42, "classified_percent": 91.5,
        "search_bytes": 5000, "search_largest_bytes": 900,
        "deal_files": 12, "deal_bytes": 3400, "deals_left_out": {"already over": 2},
        "files_total": 9100, "files_by_part": {"p": 8192, "s": 700, "d": 200, "other": 8},
    }  # fmt: skip
    (site / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
    return data, site


def test_chains_with_data_skips_chains_that_never_built(day):
    data, _ = day
    assert chains_with_data(data) == ["good", "rejected"]


def test_meta_says_what_happened_to_every_chain(day):
    data, site = day
    meta = make_meta(data, ["good", "rejected", "broken"], site, utc("2026-11-04T04:30"))
    assert meta["updated_at"] == "2026-11-04T04:30:00Z"
    assert (meta["stores"], meta["products"], meta["suspicious"]) == (7, 42, 2)
    assert meta["classified_percent"] == 91.5
    assert (meta["search_index_bytes"], meta["search_index_largest_bytes"]) == (5000, 900)
    assert (meta["deal_files"], meta["deal_bytes"]) == (12, 3400)
    assert meta["deals_left_out"] == {"already over": 2}
    assert meta["files_total"] == 9100 and meta["files_by_part"]["d"] == 200
    good, rejected, broken = (meta["chains"][c] for c in ("good", "rejected", "broken"))
    assert good == {
        "status": "updated", "reason": "", "built_at": "2026-11-03T04:30:00+00:00",
        "stores": 5, "prices": 100, "products": 3, "suspicious": 2,
    }  # fmt: skip
    assert rejected["status"] == "kept previous"
    assert rejected["reason"] == "stores dropped from 10 to 5"
    assert broken["status"] == "missing" and broken["reason"] == "nothing collected"


def test_meta_command_reports_whether_anything_new_came_in(day, capsys, tmp_path):
    data, site = day
    out = tmp_path / "meta.json"
    args = ["meta", "--data", str(data), "--site", str(site), "--out", str(out)]
    assert daily_main([*args, "good", "rejected"]) == 0
    assert capsys.readouterr().out.strip() == "any_updated=true"
    assert json.loads(out.read_text(encoding="utf-8"))["chains"]["good"]["status"] == "updated"
    daily_main([*args, "rejected", "broken"])
    assert capsys.readouterr().out.strip() == "any_updated=false"


# --- issues ---


def test_nothing_to_report_when_all_is_well(day):
    data, site = day
    meta = make_meta(data, ["good"], site, utc("2026-11-04T04:30"))
    assert problems_in(meta, "success", "success") == []


def test_problems_are_listed_in_plain_hebrew(day):
    data, site = day
    meta = make_meta(data, ["good", "rejected", "broken"], site, utc("2026-11-04T04:30"))
    found = problems_in(meta, "success", "success")
    assert len(found) == 2
    assert "rejected: העדכון של היום נדחה" in found[0] and "stores dropped" in found[0]
    assert found[1].startswith("broken: אין נתונים כלל")
    body = issue_body(found, "https://example.test/run/1", meta)
    assert "https://example.test/run/1" in body and "2026-11-04T04:30:00Z" in body


def test_a_failed_step_or_a_missing_meta_is_a_problem():
    assert problems_in(None, "success", "failure") == ["שלב ההכנה והפרסום נגמר ב: failure"]
    assert problems_in(None, "success", "success") == ["לא נוצר קובץ סיכום לריצה"]


def test_issue_command_exit_code(day, tmp_path, capsys):
    data, site = day
    meta_path = tmp_path / "meta.json"
    meta = make_meta(data, ["good", "rejected"], site, utc("2026-11-04T04:30"))
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    assert daily_main(["issue", "--meta", str(meta_path), "--run-url", "u"]) == 2
    assert "rejected" in capsys.readouterr().out
    meta_path.write_text(json.dumps(make_meta(data, ["good"], site, utc("2026-11-04T04:30"))))
    assert daily_main(["issue", "--meta", str(meta_path)]) == 0


# --- 36 hours ---


def test_stale_after_36_hours():
    meta = {"updated_at": "2026-11-04T04:30:00Z"}
    assert stale_message(meta, utc("2026-11-05T16:00")) is None  # 35.5 hours
    late = stale_message(meta, utc("2026-11-05T17:30"))  # 37 hours
    assert late and "37 שעות" in late
    assert stale_message(None, utc("2026-11-05T17:30"))
    assert stale_message({"updated_at": "garbage"}, utc("2026-11-05T17:30"))
    assert stale_message({}, utc("2026-11-05T17:30"))


def test_stale_command(tmp_path, capsys):
    path = tmp_path / "meta.json"
    path.write_text(json.dumps({"updated_at": "2026-11-04T04:30:00Z"}), encoding="utf-8")
    fresh = (utc("2026-11-04T04:30") + timedelta(hours=10)).isoformat()
    assert daily_main(["stale", "--meta", str(path), "--now", fresh]) == 0
    old = (utc("2026-11-04T04:30") + timedelta(hours=40)).isoformat()
    assert daily_main(["stale", "--meta", str(path), "--now", old]) == 1
    assert "40 שעות" in capsys.readouterr().out
    assert daily_main(["stale", "--meta", str(tmp_path / "none.json"), "--now", old]) == 1


def test_israel_time_zone_is_available_on_every_computer():
    """Windows has no zone database; the tzdata package supplies it (pyproject.toml)."""
    from importlib.metadata import requires
    from zoneinfo import ZoneInfo

    assert any(r.startswith("tzdata") for r in requires("basket-compare-collector") or [])
    jerusalem = ZoneInfo("Asia/Jerusalem")
    winter = utc("2026-01-15T12:00").astimezone(jerusalem)
    summer = utc("2026-07-15T12:00").astimezone(jerusalem)
    assert (winter.utcoffset().total_seconds(), summer.utcoffset().total_seconds()) == (7200, 10800)


# --- the hourly update: 07:00-23:59 Israel, only after today's full update ---


@pytest.mark.parametrize(
    ("now", "full", "go"),
    [
        ("2026-11-04T05:00", "2026-11-04T04:20", True),  # 07:00 winter, full update done today
        (
            "2026-11-04T04:59",
            "2026-11-04T04:20",
            False,
        ),  # 06:59: the morning belongs to the daily run
        ("2026-11-04T21:30", "2026-11-04T04:20", True),  # 23:30
        ("2026-11-04T22:00", "2026-11-04T04:20", False),  # 00:00 next day
        (
            "2026-11-04T10:00",
            "2026-11-03T04:20",
            False,
        ),  # the full update of yesterday is not enough
        ("2026-11-04T10:00", None, False),  # nothing published yet
        ("2026-07-15T04:00", "2026-07-15T03:20", True),  # summer: 07:00
        ("2026-07-15T03:00", "2026-07-15T03:20", False),  # summer: 06:00
    ],
)
def test_hourly_gate(now, full, go):
    from collector.daily import should_run_hourly

    meta = (
        {"updated_at": "2026-11-04T04:20:00Z", "full_updated_at": f"{full}:00Z"} if full else None
    )
    assert should_run_hourly("schedule", utc(now), meta)[0] is go


def test_hourly_gate_uses_the_full_update_time_not_the_last_update_and_allows_manual_runs():
    from collector.daily import should_run_hourly

    # an hourly update at 09:00 today does not make an old full update count as today's
    meta = {"updated_at": "2026-11-04T07:00:00Z", "full_updated_at": "2026-11-03T04:20:00Z"}
    assert not should_run_hourly("schedule", utc("2026-11-04T08:00"), meta)[0]
    assert should_run_hourly("workflow_dispatch", utc("2026-11-04T08:00"), None)[0]
    # a meta file from before this field existed: its update time is the full update
    old = {"updated_at": "2026-11-04T04:20:00Z"}
    assert should_run_hourly("schedule", utc("2026-11-04T08:00"), old)[0]


def test_the_hourly_update_keeps_the_full_update_time_and_unchanged_is_not_a_problem(
    day, tmp_path, capsys
):
    data, site = day
    make_chain(data, "quiet", result="nothing new")
    meta = make_meta(data, ["good", "quiet"], site, utc("2026-11-04T09:00"), "2026-11-04T04:20:00Z")
    assert meta["updated_at"] == "2026-11-04T09:00:00Z"
    assert meta["full_updated_at"] == "2026-11-04T04:20:00Z"
    assert meta["chains"]["quiet"]["status"] == "unchanged"
    assert problems_in(meta, "success", "success") == []
    # the daily run sets both to the same time
    assert make_meta(data, ["good"], site, utc("2026-11-04T04:20"))["full_updated_at"] == (
        "2026-11-04T04:20:00Z"
    )

    old = tmp_path / "old.json"
    old.write_text(json.dumps({"updated_at": "x", "full_updated_at": "2026-11-04T04:20:00Z"}))
    args = ["meta", "--data", str(data), "--site", str(site), "--out", str(tmp_path / "m.json")]
    daily_main([*args, "--carry-full-from", str(old), "quiet"])
    assert (
        capsys.readouterr().out.strip() == "any_updated=false"
    )  # only "unchanged": nothing to publish
    assert json.loads((tmp_path / "m.json").read_text("utf-8"))["full_updated_at"] == (
        "2026-11-04T04:20:00Z"
    )
