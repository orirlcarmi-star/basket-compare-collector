import http.client
import urllib.error
from pathlib import Path

import pytest

from collector import build
from collector.retry import with_retries, worth_retrying
from collector.sources import shufersal


def flaky(failures, error):
    state = {"calls": 0}

    def call():
        state["calls"] += 1
        if state["calls"] <= failures:
            raise error
        return "ok"

    return call, state


def test_a_slow_answer_is_tried_again_and_the_pauses_grow():
    pauses = []
    call, state = flaky(3, TimeoutError("The read operation timed out"))
    assert with_retries(call, sleep=pauses.append, note=None) == "ok"
    assert state["calls"] == 4 and pauses == [2.0, 4.0, 8.0]


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        ConnectionResetError("reset"),
        TimeoutError("timed out"),
        urllib.error.URLError("no route"),
        http.client.RemoteDisconnected("closed"),
        urllib.error.HTTPError("u", 503, "unavailable", {}, None),
        urllib.error.HTTPError("u", 429, "slow down", {}, None),
    ],
)
def test_network_trouble_is_worth_another_try(error):
    assert worth_retrying(error)


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError("u", 404, "not found", {}, None),
        urllib.error.HTTPError("u", 403, "forbidden", {}, None),
        ValueError("a bug is not a network failure"),
    ],
)
def test_a_clear_no_or_a_bug_is_not_retried(error):
    call, state = flaky(5, error)
    with pytest.raises(type(error)):
        with_retries(call, sleep=lambda _: None, note=None)
    assert state["calls"] == 1


def test_it_gives_up_after_the_last_attempt_and_says_so():
    call, state = flaky(99, TimeoutError("timed out"))
    notes = []
    with pytest.raises(TimeoutError):
        with_retries(call, attempts=3, sleep=lambda _: None, note=notes.append)
    assert state["calls"] == 3 and len(notes) == 2  # told twice, the third failure is raised


def test_shufersal_fetch_survives_one_slow_request(monkeypatch):
    calls = []

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"page"

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise TimeoutError("The read operation timed out")
        return Answer()

    monkeypatch.setattr(shufersal, "urlopen", fake_urlopen)
    monkeypatch.setattr("collector.retry.time.sleep", lambda _: None)
    assert shufersal.fetch("https://prices.shufersal.co.il/x") == b"page"
    assert len(calls) == 2


def test_a_chain_that_collected_nothing_still_gets_its_last_run_file(tmp_path: Path):
    """Build crashed with FileNotFoundError when the chain's folder did not exist at all."""
    assert build.main(["shufersal", "--data", str(tmp_path)]) == 1
    assert (tmp_path / "shufersal" / "last_run.json").exists()
