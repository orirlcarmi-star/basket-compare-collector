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


def test_a_facets_warning_reaches_the_summary_and_the_issue(day):
    data, site = day
    stats = json.loads((site / "stats.json").read_text(encoding="utf-8"))
    stats["search_facets"] = False
    stats["warnings"] = ["נתוני הצמצום לא נכנסו\nFacets left out"]
    (site / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
    meta = make_meta(data, ["good"], site, utc("2026-11-04T04:30"))
    assert meta["search_facets"] is False and meta["warnings"] == stats["warnings"]
    assert "נתוני הצמצום לא נכנסו" in problems_in(meta, "success", "success")


# --- the morning run is retried, and a missed one is started by the freshness check ---


@pytest.mark.parametrize(
    ("now", "last", "go"),
    [
        ("2026-11-04T04:07", None, True),  # winter 06:07: the first try
        ("2026-11-04T04:37", "2026-11-04T04:20", False),  # the second try, already published
        ("2026-11-04T04:37", None, True),  # the first one did not publish: the second goes ahead
        ("2026-11-04T06:07", None, True),  # 08:07: the late try
        ("2026-11-04T07:07", None, False),  # 09:07: too late for the schedule (catch-up takes over)
        ("2026-07-15T03:07", None, True),  # summer 06:07
        ("2026-07-15T05:07", None, True),  # summer 08:07: the late try
    ],
)
def test_scheduled_retries_of_the_morning_run(now, last, go):
    assert should_run("schedule", utc(now), utc(last) if last else None)[0] is go


@pytest.mark.parametrize(
    ("now", "last", "go"),
    [
        ("2026-11-04T07:23", None, True),  # 09:23: nothing published yet today
        ("2026-11-04T07:23", "2026-11-04T04:10", False),  # published this morning
        ("2026-11-04T07:23", "2026-11-03T04:10", True),  # only yesterday's
        ("2026-11-04T03:23", None, False),  # 05:23: the daily run's own time has not come
        ("2026-11-04T11:00", None, True),  # 13:00: still catches up, prices must not stay old
        ("2026-11-04T19:23", None, True),  # 21:23
        ("2026-11-04T21:00", None, False),  # 23:00: the day is over
        ("2026-07-15T08:23", None, True),  # summer 11:23
    ],
)
def test_catch_up_starts_a_missed_morning_run(now, last, go, tmp_path, capsys):
    meta = tmp_path / "meta.json"
    if last:
        meta.write_text(json.dumps({"updated_at": f"{last}:00Z"}), encoding="utf-8")
    daily_main(["catch-up", "--meta", str(meta), "--now", f"{now}:00Z"])
    assert capsys.readouterr().out.splitlines()[0] == f"run={'true' if go else 'false'}"


# --- the limit: at most three daily runs that really work in an Israeli day ---


def run_row(created, seconds=900, status="completed", run_id=1):
    """One row of `gh run list --json databaseId,status,createdAt,startedAt,updatedAt`."""
    start = utc(created)
    return {
        "databaseId": run_id,
        "status": status,
        "createdAt": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "startedAt": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updatedAt": (start + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def test_only_runs_that_really_worked_are_counted():
    from collector.daily import working_runs_today

    runs = [
        run_row("2026-11-04T04:07", seconds=25, run_id=1),  # passed the gate and stopped
        run_row("2026-11-04T04:37", seconds=2400, run_id=2),  # worked 40 minutes
        run_row("2026-11-04T07:00", status="in_progress", run_id=3),  # working now
        run_row("2026-11-03T04:07", seconds=2400, run_id=4),  # yesterday
    ]
    assert working_runs_today(runs, utc("2026-11-04T08:00")) == 2
    assert working_runs_today(runs, utc("2026-11-04T08:00"), exclude_id=3) == 1  # not itself


THREE = [
    run_row("2026-11-04T04:07", 1800, run_id=1),
    run_row("2026-11-04T06:30", 1800, run_id=2),
    run_row("2026-11-04T09:00", 1800, run_id=3),
]


def test_a_scheduled_attempt_stops_after_three_working_runs(tmp_path, capsys):
    now = utc("2026-11-04T05:00")  # 07:00 in Israel, in the retry hours
    assert should_run("schedule", now, None, runs=THREE[:2])[0] is True
    go, reason = should_run("schedule", now, None, runs=THREE)
    assert go is False and "no more tries" in reason
    # a person starting it by hand is never stopped by the limit
    assert should_run("workflow_dispatch", now, None, runs=THREE)[0] is True
    # and the gate command passes the list on, leaving out the run that is asking
    runs = tmp_path / "runs.json"
    runs.write_text(json.dumps([*THREE[:2], run_row("2026-11-04T05:00", 5, "in_progress", 99)]))
    meta = str(tmp_path / "none.json")
    daily_main(["gate", "--event", "schedule", "--runs", str(runs), "--current-run", "99",
                "--meta", meta, "--now", "2026-11-04T05:00:00Z"])  # fmt: skip
    assert capsys.readouterr().out.strip() == "run=true"


def test_catch_up_starts_at_most_two_more_runs_then_asks_for_an_issue(tmp_path, capsys):
    from collector.daily import should_catch_up

    # 14:00 in Israel, nothing published today, the last run started three hours ago
    now = utc("2026-11-04T12:00")
    one = [run_row("2026-11-04T04:07", 1800, run_id=1)]
    two = [*one, run_row("2026-11-04T06:30", 1800, run_id=2)]
    assert should_catch_up(now, None, one) == (True, "nothing was published today", False)
    assert should_catch_up(now, None, two)[0] is True  # the third working run of the day
    go, reason, limited = should_catch_up(now, None, THREE)
    assert (go, limited) == (False, True) and "already worked" in reason

    runs = tmp_path / "runs.json"
    runs.write_text(json.dumps(THREE), encoding="utf-8")
    daily_main(["catch-up", "--meta", str(tmp_path / "none.json"), "--runs", str(runs),
                "--now", "2026-11-04T12:00:00Z"])  # fmt: skip
    assert capsys.readouterr().out.splitlines() == ["run=false", "limit=true"]


def test_catch_up_leaves_a_running_or_a_recent_run_alone():
    from collector.daily import should_catch_up

    now = utc("2026-11-04T10:00")
    running = [run_row("2026-11-04T09:30", 60, "in_progress", run_id=5)]
    assert should_catch_up(now, None, running) == (
        False,
        "a daily run is waiting or running",
        False,
    )
    recent = [run_row("2026-11-04T08:30", 60, run_id=6)]  # 90 minutes ago, passed the gate only
    assert should_catch_up(now, None, recent)[1] == "a daily run started in the last two hours"
    assert should_catch_up(utc("2026-11-04T11:30"), None, recent)[0] is True  # over two hours
    published = utc("2026-11-04T04:20")
    assert should_catch_up(now, published, [])[:2] == (False, "already updated today (06:20)")


def test_a_missing_or_broken_runs_file_means_no_runs(tmp_path):
    from collector.daily import read_runs

    assert read_runs(None) == [] and read_runs(tmp_path / "none.json") == []
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    assert read_runs(tmp_path / "bad.json") == []
