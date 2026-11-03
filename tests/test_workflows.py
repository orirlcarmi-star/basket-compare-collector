"""The workflows are not run by the tests, but their wiring to the code is checked."""

import re
from pathlib import Path

from collector.collect import CHAINS

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def text(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_daily_runs_at_6_in_israel_in_both_summer_and_winter():
    crons = re.findall(r'cron: "([^"]+)"', text("daily.yml"))
    assert crons == ["0 3 * * *", "0 4 * * *"]  # 06:00 at UTC+3 and at UTC+2


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
