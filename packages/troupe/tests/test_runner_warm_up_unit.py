"""Which runners warm their engine, and how it's announced: a runner without a warm-up starts no
process, only the mistralrs runner has one (its --warm-up argument), and a runner.warming-up
notice naming the runner comes before it starts (spec: cli; in-process-runner design D4; owner,
2026-11-14).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_runner_warm_up.py."""

from pathlib import Path

import pytest

from protocol_schemas import check_notice
from runner_warm_up_shared import _runner
from troupe.core import interim
from troupe.core.runners.warm_up import warm_up


def test_a_runner_without_a_warm_up_starts_no_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _runner(monkeypatch, "raise SystemExit('started')", warm=())
    assert warm_up("mistralrs", tmp_path, {}) == []


def test_the_mistralrs_runner_warms_with_its_own_argument() -> None:
    assert interim.RUNNERS["mistralrs"].warm_up == ("--warm-up",)
    assert all(not entry.warm_up for name, entry in interim.RUNNERS.items() if name != "mistralrs")


def test_the_warm_up_is_announced_before_it_starts() -> None:
    from troupe.core.runners.warm_up import warming

    notice = warming("mistralrs")
    assert notice.code == "runner.warming-up"
    assert notice.details == {"runner": "mistralrs"}
    check_notice(notice.to_data())
