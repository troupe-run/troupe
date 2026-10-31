"""A push to main skips the legs only when the merge queue passed that exact commit, and a read
that fails runs everything without failing the job (spec: quality-check; ci-once-per-commit design
D1).

GitHub's runs come from a fake `gh`, and time from a fake clock, so nothing waits for real."""

import re
import subprocess
from typing import Any

import pytest

import queue_passed

REPOSITORY = "troupe-run/troupe"
SHA = "efa5105" + "0" * 33


def run(status: str, conclusion: str = "") -> dict[str, str]:
    return {"status": status, "conclusion": conclusion}


class FakeGh:
    """CI's merge-queue runs on the commit, one answer per poll; the last one stays. An exception
    in the list is what that read raises. Each call's arguments are kept."""

    def __init__(self, *answers: Any) -> None:  # noqa: ANN401 (JSON)
        self.answers = list(answers)
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> Any:  # noqa: ANN401 (JSON)
        self.calls.append(args)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


class Clock:
    def __init__(self) -> None:
        self.time = 0.0
        self.sleeps = 0

    def now(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.time += seconds


def decide(gh: FakeGh, clock: Clock | None = None) -> queue_passed.Answer:
    clock = clock or Clock()
    return queue_passed.decide(gh, REPOSITORY, SHA, now=clock.now, sleep=clock.sleep)


def test_a_successful_queue_run_skips_the_legs() -> None:
    answer = decide(FakeGh([run("completed", "success")]))
    assert answer.passed
    assert not answer.warning


def test_one_success_among_failed_runs_is_enough() -> None:
    answer = decide(FakeGh([run("completed", "failure"), run("completed", "success")]))
    assert answer.passed


def test_no_queue_run_runs_everything_without_a_warning() -> None:
    answer = decide(FakeGh([]))
    assert not answer.passed
    assert not answer.warning
    assert "no merge-queue run" in answer.why


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "skipped", ""])
def test_a_queue_run_that_did_not_succeed_runs_everything(conclusion: str) -> None:
    answer = decide(FakeGh([run("completed", conclusion)]))
    assert not answer.passed
    assert not answer.warning


def test_a_run_that_completes_during_the_wait_is_waited_for() -> None:
    clock = Clock()
    gh = FakeGh([run("in_progress")], [run("in_progress")], [run("completed", "success")])
    answer = decide(gh, clock)
    assert answer.passed
    assert clock.sleeps == 2


def test_a_run_still_waiting_at_the_limit_runs_everything_with_a_warning() -> None:
    clock = Clock()
    answer = decide(FakeGh([run("queued")]), clock)
    assert not answer.passed
    assert answer.warning
    assert clock.time >= queue_passed.LIMIT_SECONDS


def test_an_unknown_status_runs_everything_with_a_warning() -> None:
    answer = decide(FakeGh([run("exploded")]))
    assert not answer.passed
    assert answer.warning
    assert "exploded" in answer.why


def test_a_failed_read_runs_everything_with_a_warning() -> None:
    answer = decide(FakeGh(queue_passed.ReadError("HTTP 502")))
    assert not answer.passed
    assert answer.warning
    assert "HTTP 502" in answer.why


@pytest.mark.parametrize(
    "shape",
    [{"runs": []}, [{"status": "completed"}], ["completed"], [{"status": 1, "conclusion": ""}]],
)
def test_an_answer_of_the_wrong_shape_runs_everything_with_a_warning(shape: object) -> None:
    answer = decide(FakeGh(shape))
    assert not answer.passed
    assert answer.warning


def test_only_ci_merge_queue_runs_on_the_commit_are_asked_for() -> None:
    gh = FakeGh([])
    decide(gh)
    args = gh.calls[0]
    for flag, value in (
        ("--workflow", "ci.yml"),
        ("--event", "merge_group"),
        ("--commit", SHA),
        ("--repo", REPOSITORY),
    ):
        assert args[args.index(flag) + 1] == value


def test_unparseable_gh_output_is_a_read_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Done:
        returncode = 0
        stdout = "not json"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: Done())
    with pytest.raises(queue_passed.ReadError, match="isn't JSON"):
        queue_passed.gh(["run", "list"])


def test_a_failing_gh_is_a_read_error_naming_its_message(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failed:
        returncode = 1
        stdout = ""
        stderr = "HTTP 404: Not Found\n"

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: Failed())
    with pytest.raises(queue_passed.ReadError, match="HTTP 404: Not Found"):
        queue_passed.gh(["run", "list"])


@pytest.mark.parametrize(
    ("answer", "printed", "warned"),
    [
        (queue_passed.Answer(True, "passed"), "scope=none\ncheck-args=", False),
        (queue_passed.Answer(False, "none"), "scope=full\ncheck-args=", False),
        (queue_passed.Answer(False, "bad read", True), "scope=full\ncheck-args=", True),
    ],
)
def test_main_prints_only_name_value_lines_and_always_exits_0(
    answer: queue_passed.Answer,
    printed: str,
    warned: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(queue_passed, "decide", lambda *_a, **_k: answer)
    assert queue_passed.main(["--repository", REPOSITORY, "--sha", SHA]) == 0
    out, err = capsys.readouterr()
    assert out.strip() == printed
    assert all(re.fullmatch(r"[a-z-]+=[a-z]*", line) for line in out.splitlines())
    assert ("::warning::" in err) is warned
