"""The workflows are not run by the tests, but their wiring to the code is checked."""

import re
from pathlib import Path

from collector.collect import CHAINS

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def text(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_daily_is_scheduled_off_the_round_hour_with_retries_in_both_seasons():
    crons = re.findall(r'cron: "([^"]+)"', text("daily.yml"))
    assert crons == ["7,37 3-5 * * *"]
    # GitHub delays or drops runs at minute 0 (03:00 and 04:00 UTC of 2026-11-04 never started)
    for cron in crons:
        assert not cron.startswith("0 "), "do not schedule on the round hour"
    # 06:07 in Israel is 03:07 UTC in summer (UTC+3) and 04:07 UTC in winter (UTC+2)
    assert "7,37 3-5" in crons[0]  # 03:07, 03:37 ... 05:37 UTC: six tries before the catch-up


def test_daily_covers_every_chain_and_the_site_files_are_compact():
    daily = text("daily.yml")
    matrix = re.search(r"chain: \[([^\]]*)\]", daily)[1].replace(" ", "").split(",")
    assert matrix == CHAINS
    assert "collector.publish $CHAINS --compact" in daily
    for chain in CHAINS:
        assert chain in re.search(r"for chain in ([^;]*); do", daily)[1]
        assert f"meta {' '.join(CHAINS)} " in daily  # the summary lists all four


def test_the_release_is_the_fixed_one_and_the_summary_goes_up_last():
    daily = text("daily.yml")
    assert "RELEASE: site-data-latest" in daily
    uploads = [line.strip() for line in daily.splitlines() if "gh release upload" in line]
    assert uploads[-1].startswith('gh release upload "$RELEASE" meta.json')
    assert any("site-data.tar.gz" in u for u in uploads)


def test_a_test_run_never_touches_the_release_or_the_issues():
    daily = text("daily.yml")
    release_step = daily.split("- name: Replace the release files")[1].split("\n  report:")[0]
    assert "inputs.dry_run != true" in release_step.split("env:")[0]
    report_job = daily.split("\n  report:")[1]
    assert "inputs.dry_run != true" in report_job.split("steps:")[0]


def test_only_the_jobs_that_need_it_may_write():
    daily = text("daily.yml")
    assert daily.count("contents: write") == 1  # the publish job only
    assert daily.count("issues: write") == 1  # the report job only
    assert re.match(r"(?s).*\npermissions:\n  contents: read\n", daily)


def test_stale_data_check_uses_36_hours_and_runs_often():
    from collector.daily import MAX_AGE

    assert MAX_AGE.total_seconds() == 36 * 3600
    assert re.search(r'cron: "\d+ \*/6 \* \* \*"', text("freshness.yml"))
    assert "collector.daily stale" in text("freshness.yml")


def test_heartbeat_runs_monthly_well_inside_60_days():
    heartbeat = text("heartbeat.yml")
    day_of_month = re.search(r'cron: "\d+ \d+ (\S+) \* \*"', heartbeat)[1]
    assert day_of_month == "1"
    for workflow in ("daily.yml", "freshness.yml", "heartbeat.yml"):
        assert "gh workflow enable" in heartbeat and workflow in heartbeat


def test_no_secret_or_token_is_written_in_a_workflow():
    for path in WORKFLOWS.glob("*.yml"):
        body = path.read_text(encoding="utf-8")
        assert not re.search(r"ghp_|github_pat_|password:\s*\S", body), path.name
        # the only credential is the job's own token
        assert set(re.findall(r"secrets\.(\w+)", body)) <= set(), path.name


def test_deals_travel_with_the_chain_files_and_with_yesterdays_state():
    daily = text("daily.yml")
    assert "ready stores.json last_run.json deals" in daily  # to the publish job
    assert "$chain/deals" in daily  # and into the state kept in the release


def test_the_hourly_update_is_off_until_it_is_approved():
    hourly = text("hourly.yml")
    active = [line for line in hourly.splitlines() if not line.lstrip().startswith("#")]
    assert not any(line.strip().startswith("schedule:") for line in active)
    assert not any("cron:" in line for line in active)
    assert "# schedule:" in hourly and '#   - cron: "7 4-21 * * *"' in hourly  # ready to switch on
    assert "workflow_dispatch:" in hourly  # but can be started by hand to try it


def test_the_hourly_update_shares_the_lock_and_the_checks_of_the_daily_run():
    hourly = text("hourly.yml")
    assert "group: daily-update" in hourly  # never overlaps the daily run
    assert "collector.daily hourly-gate" in hourly and "collector.hourly" in hourly
    assert "collector.publish $CHAINS --compact" in hourly  # the same exact restore check
    chains = re.search(r"chain: \[([^\]]*)\]", hourly)[1].replace(" ", "").split(",")
    assert chains == CHAINS
    assert hourly.count("contents: write") == 1 and "issues:" not in hourly
    assert "inputs.dry_run != true" in hourly.split("Replace the release files")[1].split("env:")[0]


def test_the_hourly_cron_when_switched_on_covers_the_israeli_day_in_both_seasons():
    cron = re.search(r'# {3}- cron: "(\d+) (\d+)-(\d+) \* \* \*"', text("hourly.yml"))
    first, last = int(cron[2]), int(cron[3])
    assert first <= 4 and last >= 20  # 07:00 at UTC+3 .. 23:00 at UTC+3 (and UTC+2: 05..21)


def test_the_freshness_check_starts_a_missed_daily_run():
    freshness = text("freshness.yml")
    assert "actions: write" in freshness  # needed to start a workflow
    assert re.search(
        r'cron: "23 5-19 \* \* \*"', freshness
    )  # every hour of the day, off the round hour
    assert "collector.daily catch-up" in freshness
    assert "gh workflow run daily.yml" in freshness
    assert "daily runs waiting or running" in freshness  # never piles a second run on a running one
    assert "started in the last 2 hours" in freshness  # nor repeats a failing run every hour
