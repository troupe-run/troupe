"""Recorded events validate by topic, from real runs (spec: event-store; strict-schemas design D6).

Its tests that stay in their own process are in unit/test_event_payloads.py."""

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from protocol_guard import ProtocolGuardError
from protocol_schemas import PROTOCOL_BASE, SCHEMAS, SCRIPTED, load, validator_for
from runtesting import INIT, OK, Harness, failing_at, request, script, theatre, turn
from storetesting import git_service, segments
from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.core.runners.limits import RunLimits
from troupe.core.runs.aggregate import (
    ENDED,
    NOTICED,
    REPORTED,
    STARTED,
    TOPICS,
    WORKTREE_MADE,
    Run,
)

# troupe.core.runs re-exports perform the function, so the module is reached by name.
perform_module = importlib.import_module("troupe.core.runs.perform")
RECORD = validator_for(PROTOCOL_BASE + "event-record.schema.json", SCRIPTED)
ERROR = {
    "event": {
        "type": "result",
        "status": "error",
        "reason": "authentication",
        "message": "401 Unauthorized",
    }
}
TOOLS: list[dict[str, Any]] = [
    {"event": {"type": "tool_call", "callId": "c1", "tool": "Write", "inputSummary": "a.txt"}},
    {
        "event": {
            "type": "tool_result",
            "callId": "c1",
            "isError": False,
            "outputSummary": "ok",
            "outputBytes": 2,
        }
    },
]


def _lines(harness: Harness) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for path in segments(harness.repo.path)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _problems(lines: list[dict[str, Any]]) -> list[str]:
    return [
        f"{line.get('topic', 'header')}: {error.message}"
        for line in lines
        for error in RECORD.iter_errors(line)
    ]


def test_every_line_a_succeeded_run_records_validates_by_topic(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    harness.perform(request(script(INIT, turn("hello"), *TOOLS, OK)))
    lines = _lines(harness)
    assert [line.get("topic") for line in lines if line.get("topic") in TOPICS] == [
        STARTED,
        *[REPORTED] * 5,
        ENDED,
    ]
    assert _problems(lines) == []


@pytest.mark.parametrize("announce_after", [None, 0], ids=["default", "always-announced"])
def test_every_line_a_worktree_run_records_validates_by_topic_with_its_worktree_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, announce_after: float | None
) -> None:
    """A worktree step slower than WORKSPACE_ANNOUNCE_AFTER_SECONDS, as on a loaded machine,
    records workspace.waiting among the run's topics (#402). At 0 it always does, so the
    comparison is checked with them there."""
    if announce_after is not None:
        monkeypatch.setattr(defaults, "WORKSPACE_ANNOUNCE_AFTER_SECONDS", announce_after)
    harness = Harness(theatre(tmp_path))
    (harness.repo.path / "a.txt").write_text("one\n", encoding="utf-8")
    harness.repo.commit_all("base")
    asked = request(script(INIT, OK), workspace="worktree")
    harness.configure(asked)
    harness.repo.commit_all("config")
    harness.perform(asked)
    lines = _lines(harness)
    topics = [line.get("topic") for line in lines if line.get("topic") in TOPICS]
    assert [topic for topic in topics if topic != NOTICED] == [
        STARTED,
        WORKTREE_MADE,
        REPORTED,
        REPORTED,
        ENDED,
    ]
    waiting = {line["state"]["notice"]["code"] for line in lines if line.get("topic") == NOTICED}
    assert waiting <= {"workspace.waiting"}
    if announce_after == 0:
        assert waiting == {"workspace.waiting"}
    started = next(line for line in lines if line.get("topic") == STARTED)["state"]
    assert "clones" not in started["workspace"]
    assert "runner_reported" not in started
    made = next(line for line in lines if line.get("topic") == WORKTREE_MADE)["state"]
    assert made["clones"] == sorted(made["clones"])
    assert _problems(lines) == []


def test_every_line_a_run_that_raised_notices_records_validates_by_topic(tmp_path: Path) -> None:
    quick = RunLimits(start_timeout=10.0, cancel_grace=2.0, run_timeout=20.0, silence_announce=0.3)
    harness = Harness(theatre(tmp_path), limits=quick)
    retry = {"type": "retry", "attempt": 1, "delayMs": 10, "reason": "network"}
    harness.perform(request(script(INIT, {"wait": {"ms": 800}}, {"event": retry}, OK)))
    lines = _lines(harness)
    noticed = [line["state"]["notice"]["code"] for line in lines if line.get("topic") == NOTICED]
    # The wait's silence comes before the retry; on a loaded CI machine a slow runner start or a
    # slow write is a silence of its own too (test_run_notices.apart_from_silences).
    assert noticed.count("run.retrying") == 1
    assert "run.silent" in noticed[: noticed.index("run.retrying")]
    assert set(noticed) == {"run.silent", "run.retrying"}
    assert _problems(lines) == []


@pytest.fixture(scope="module")
def worktree_start(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The Run.Started payload a real worktree run records."""
    harness = Harness(theatre(tmp_path_factory.mktemp("start")))
    (harness.repo.path / "a.txt").write_text("one\n", encoding="utf-8")
    harness.repo.commit_all("base")
    asked = request(script(INIT, OK), workspace="worktree")
    harness.configure(asked)
    harness.repo.commit_all("config")
    harness.perform(asked)
    started: dict[str, Any] = next(
        line for line in _lines(harness) if line.get("topic") == STARTED
    )["state"]
    return started


# Requirement: A run's start always records its workspace, and The reported runner comes from the
# run's init (spec: runs; require-always-written-fields design D2, D3): a start holds what troupe
# writes now, and nothing troupe no longer writes.


def test_the_start_a_worktree_run_records_validates(worktree_start: dict[str, Any]) -> None:
    started = load(SCHEMAS / "events" / "run-started.schema.json")
    assert validator_for(started["$id"], SCRIPTED).is_valid(worktree_start)


@pytest.mark.parametrize(
    "label",
    [
        "a start without its workspace",
        "a start that names the reported runner",
        "a start with clones",
    ],
)
def test_a_start_that_leaves_out_its_workspace_or_holds_an_older_troupes_fields_does_not_validate(
    worktree_start: dict[str, Any], label: str
) -> None:
    started = load(SCHEMAS / "events" / "run-started.schema.json")
    validator = validator_for(started["$id"], SCRIPTED)
    assert validator.is_valid(worktree_start)
    state = json.loads(json.dumps(worktree_start))
    if label == "a start without its workspace":
        del state["workspace"]
    elif label == "a start that names the reported runner":
        state["runner_reported"] = {"name": "scripted", "version": "0.1.0"}
    else:
        state["workspace"]["clones"] = ["copy"]
    assert not validator.is_valid(state), label


def test_every_line_a_failed_run_records_validates_by_topic(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    harness.perform(request(script(INIT, ERROR)))
    lines = _lines(harness)
    ended = next(line for line in lines if line.get("topic") == ENDED)
    assert ended["state"]["outcome"]["error"]["code"] == "run.error-result"
    assert _problems(lines) == []


def test_every_line_a_run_whose_runner_refused_it_records_validates_by_topic(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    # Options its schema allows (a path is any non-empty string), which the runner refuses.
    outside = {"writeFile": {"path": "/outside/the/workspace", "content": "x"}}
    harness.perform(request({"script": {"steps": [outside]}}))
    lines = _lines(harness)
    started = next(line for line in lines if line.get("topic") == STARTED)
    ended = next(line for line in lines if line.get("topic") == ENDED)
    assert "runner_reported" not in started["state"]
    assert ended["state"]["outcome"]["error"]["details"]["runnerError"]["code"] == (
        "scripted.invalid-script"
    )
    assert _problems(lines) == []


def test_every_line_a_run_whose_recording_failed_records_validates_by_topic(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path), store_wrapper=failing_at(1))
    with pytest.raises(TroupeError):
        harness.perform(request(script(INIT, turn("hello"), OK)))
    lines = _lines(harness)
    ended = next(line for line in lines if line.get("topic") == ENDED)
    assert ended["state"]["recording"]["failedAt"] == 1
    assert _problems(lines) == []


def _nulls(value: object, at: str = "") -> list[str]:
    """Where ``value`` holds a null, at any depth."""
    if value is None:
        return [at or "/"]
    if isinstance(value, dict):
        return [n for key, item in value.items() for n in _nulls(item, f"{at}/{key}")]
    if isinstance(value, list):
        return [n for index, item in enumerate(value) for n in _nulls(item, f"{at}/{index}")]
    return []


def test_a_run_whose_runner_never_started_records_no_null_and_validates_by_topic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(perform_module, "runner_command", lambda _: ["troupe-no-such-runner"])
    harness = Harness(theatre(tmp_path))
    result = harness.perform(request(script(INIT, OK)))
    lines = _lines(harness)
    assert [line.get("topic") for line in lines if line.get("topic") in TOPICS] == [STARTED, ENDED]
    assert _nulls(lines) == []
    assert _problems(lines) == []
    ended = next(line for line in lines if line.get("topic") == ENDED)["state"]
    assert ended["outcome"]["outcome"] == "could-not-start"
    assert ended["outcome"]["ending"] == "never-started"
    assert ended["outcome"]["error"]["code"] == "runner.start-failed"
    absent = {"exitCode", "transcript", "transcriptFormat", "stderr", "result"} & set(
        ended["outcome"]
    )
    assert absent == set()
    assert "recording" not in ended
    assert result.run.transcript is None
    assert result.run.stderr is None


def test_a_succeeded_run_records_its_exit_code_transcript_stderr_and_result_and_no_error(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    harness.perform(request(script(INIT, OK)))
    lines = _lines(harness)
    ended = next(line for line in lines if line.get("topic") == ENDED)["state"]
    assert ended["outcome"]["exitCode"] == 0
    assert {"transcript", "stderr", "result"} <= set(ended["outcome"])
    assert ended["outcome"]["transcriptFormat"] == "native"
    assert "error" not in ended["outcome"]
    assert "recording" not in ended
    assert _nulls(lines) == []
    assert _problems(lines) == []
    assert isinstance(git_service(harness.repo).load(Run.create_id(_run_id(lines))), Run)


@pytest.mark.parametrize(
    ("flag", "format_"),
    [([], "native"), (["--transcript-kinds"], "kinds")],
    ids=["native", "kinds"],
)
def test_a_runs_end_and_summary_name_its_transcripts_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: list[str], format_: str
) -> None:
    command = [sys.executable, "-m", "troupe_runner_scripted", *flag]
    monkeypatch.setattr(perform_module, "runner_command", lambda _: command)
    harness = Harness(theatre(tmp_path))
    result = harness.perform(request(script(INIT, OK)))
    lines = _lines(harness)
    ended = next(line for line in lines if line.get("topic") == ENDED)["state"]
    assert ended["outcome"]["transcriptFormat"] == format_
    assert _problems(lines) == []
    assert result.run.transcript_format == format_


def _run_id(lines: list[dict[str, Any]]) -> str:
    return str(next(line["stream"] for line in lines if line.get("topic") == STARTED))


def test_a_recorded_payload_with_a_field_its_topic_does_not_define_is_refused(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    harness.perform(request(script(INIT, OK)))
    reported = next(line for line in _lines(harness) if line.get("topic") == REPORTED)
    reported["state"]["colour"] = "blue"
    assert not RECORD.is_valid(reported)


# Requirement: Every error, notice and recorded event is checked as tests make it

HASH = "sha256:" + "ab" * 32
STAGE = {
    "name": "local",
    "effects": "unenforced",
    "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
}


def _run() -> Run:
    return Run(
        run_id="0f8fad5b-d9cb-469f-a165-70867728950e",
        actor="tester",
        runner_requested="scripted",
        stage=STAGE,
        effect_check={"kind": "none"},
        direction=HASH,
        config=[HASH],
        workspace={"kind": "theatre"},
        on_context_full={"value": "fail", "source": "default"},
    )


def test_recording_a_payload_with_a_field_its_topic_does_not_define_fails_naming_the_topic(
    tmp_path: Path,
) -> None:
    store = git_service(theatre(tmp_path))
    run = _run()
    event = {**INIT["event"], "effects": "checked", "runId": run.run_id, "seq": 0, "colour": "blue"}
    run.report(0, event)
    with pytest.raises(ProtocolGuardError, match=r"Run\.Reported.*'colour' was unexpected"):
        store.command(via="cli").record(run.collect_events())


def test_recording_a_run_whose_payloads_match_their_topics_passes_the_guard(
    tmp_path: Path,
) -> None:
    store = git_service(theatre(tmp_path))
    run = _run()
    run.report(0, {**INIT["event"], "effects": "checked", "runId": run.run_id, "seq": 0})
    assert len(store.command(via="cli").record(run.collect_events())) == 2


WORKTREE = {"kind": "worktree", "path": ".troupe/local/worktrees/run", "base": "c" * 40}


def test_a_worktree_made_with_a_field_its_topic_does_not_define_fails_naming_the_topic(
    tmp_path: Path,
) -> None:
    store = git_service(theatre(tmp_path))
    run = Run(
        run_id="0f8fad5b-d9cb-469f-a165-70867728950e",
        actor="tester",
        runner_requested="scripted",
        stage=STAGE,
        effect_check={"kind": "none"},
        direction=HASH,
        config=[HASH],
        workspace={**WORKTREE, "dirty": False},
        on_context_full={"value": "fail", "source": "default"},
        approvers={"value": ["troupe", "director"], "source": "default"},
    )
    run.made_worktree(["teleport"])
    with pytest.raises(ProtocolGuardError, match=r"Run\.WorktreeMade.*'teleport'"):
        store.command(via="cli").record(run.collect_events())
