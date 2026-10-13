"""perform runs one actor and records the run (spec: runs, stages, policy; perform-status-logs
design D5, D8, D9)."""

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from runtesting import ADA, ALLOW, INIT, OK, Harness, failing_at, request, script, theatre, turn
from storetesting import snapshot
from troupe.core import defaults, strict_json
from troupe.core.errors import TroupeError
from troupe.core.files import directory_lock
from troupe.core.runners.limits import RunLimits
from troupe.core.runs.aggregate import ENDED, REPORTED, STARTED, Run
from troupe.core.runs.perform import lease_dir

AGENT = {"kind": "agent", "id": "tester", "source": "troupe"}
ADA_ACTOR = {"kind": "human", "id": "ada@example.com", "source": "env"}
LOCAL = {
    "name": "local",
    "effects": "unenforced",
    "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
}


def history(harness: Harness, run_id: str) -> list[Any]:
    return list(harness.stores[0].history(UUID(run_id)))


def states(records: list[Any]) -> list[dict[str, Any]]:
    return [json.loads(r.state) for r in records]


# 7.2: a successful run, recorded.


def test_a_successful_run_records_its_start_each_event_in_seq_order_then_its_end(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    options = script(INIT, turn("one"), turn("two"), OK)
    result = harness.perform(request(options, instructions="say hello"))
    run = result.run
    records = history(harness, run.run_id)
    assert [r.topic for r in records] == [STARTED, REPORTED, REPORTED, REPORTED, REPORTED, ENDED]
    reported = states(records)[1:5]
    assert [s["seq"] for s in reported] == [0, 1, 2, 3]
    assert [s["event"]["type"] for s in reported] == ["init", "turn", "turn", "result"]
    assert states(records)[-1]["outcome"]["outcome"] == "succeeded"
    assert run.outcome == "succeeded"
    assert run.state == "ended"
    assert run.events == 4
    assert run.runner.reported is not None
    assert (run.runner.reported.name, run.runner.reported.version) == ("scripted", "0.1.0")


def test_the_start_is_the_persons_and_everything_else_the_agents_under_one_change(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    result = harness.perform(request(script(INIT, turn("one"), OK)))
    records = history(harness, result.run.run_id)
    lineages = [r.lineage for r in records]
    assert lineages[0]["actor"] == ADA_ACTOR
    assert lineages[0]["via"] == "cli"
    for lineage in lineages[1:]:
        assert lineage["actor"] == AGENT
        assert lineage["via"] == "runner"
    change = lineages[0]["change"]
    assert {lineage["change"] for lineage in lineages} == {change}
    assert all(lineage["cause"] == {"kind": "command", "id": change} for lineage in lineages)
    assert all(lineage["stage"] == LOCAL for lineage in lineages)
    assert all(lineage["vcs"]["adapter"] == "git" for lineage in lineages)


def test_the_instructions_and_options_are_artifacts_referenced_from_the_start(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    options = script(INIT, OK)
    result = harness.perform(request(options, instructions="say hello"))
    [started] = states(history(harness, result.run.run_id))[:1]
    canonical = strict_json.dumps(options).encode("utf-8")
    assert started["options"] == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert started["instructions"] == "sha256:" + hashlib.sha256(b"say hello").hexdigest()
    store = harness.backends().artifact_store(harness.session())
    assert store.read(started["options"]) == canonical
    events_text = "".join(
        p.read_text("utf-8") for p in (harness.repo.path / ".troupe" / "events").glob("*.jsonl")
    )
    assert '"steps"' not in events_text


def test_updates_are_the_run_id_first_then_each_event_as_recorded(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    result = harness.perform(request(script(INIT, turn("one"), OK)))
    run_id = result.run.run_id
    assert harness.updates[0] == {"kind": "started", "runId": run_id}
    events = [u for u in harness.updates if u["kind"] == "event"]
    assert [(u["runId"], u["seq"], u["event"]["type"]) for u in events] == [
        (run_id, 0, "init"),
        (run_id, 1, "turn"),
        (run_id, 2, "result"),
    ]
    recorded_at = [r.lineage["at"] for r in history(harness, run_id)[1:4]]
    assert [u["at"] for u in events] == recorded_at


def test_the_runner_works_in_the_theatre_and_the_effect_check_reads_from_it(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    write = {"writeFile": {"path": "out/hello.txt", "content": "hi"}}
    result = harness.perform(
        request(script(INIT, write, OK), effect={"kind": "files", "paths": ["out/hello.txt"]})
    )
    assert (harness.repo.path / "out" / "hello.txt").read_text("utf-8") == "hi"
    assert result.run.outcome == "succeeded"


def test_the_lease_is_released_when_perform_returns(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    result = harness.perform(request(script(INIT, OK)))
    lease = lease_dir(harness.repo.path, result.run.run_id)
    assert lease.is_dir()
    with directory_lock(lease, timeout=0.5):
        pass


# 7.3: each outcome, recorded as the run host derived it.

AUTH_RETRY = {"event": {"type": "retry", "attempt": 1, "delayMs": 10, "reason": "authentication"}}
ERROR = {"event": {"type": "result", "status": "error", "message": "it broke"}}

OUTCOMES = [
    ("succeeded", None, script(INIT, OK), {}, None),
    ("failed", "run.error-result", script(INIT, ERROR), {}, None),
    (
        "failed",
        "run.effect-missing",
        script(INIT, OK),
        {},
        {"kind": "files", "paths": ["never-written.txt"]},
    ),
    ("failed", "run.unclean-exit", script(INIT, OK, {"exit": 3}), {}, None),
    ("failed", "run.authentication", script(INIT, AUTH_RETRY, {"hang": True}), {}, None),
    (
        "failed",
        "run.transcript-too-large",
        script(INIT, {"transcript": "x" * 200}, {"hang": True}),
        {"transcript_max_bytes": 50},
        None,
    ),
    ("crashed", "runner.crashed", script(INIT, {"exit": 0}), {}, None),
    (
        "crashed",
        "runner.protocol",
        script(INIT, {"rawStdout": "not json"}, {"hang": True}),
        {},
        None,
    ),
    ("timed-out", "run.timeout", script(INIT, {"hang": True}), {"run_timeout": 1.0}, None),
    ("could-not-start", "runner.start-timeout", script(INIT, OK), {"start_timeout": 0.001}, None),
]


@pytest.mark.parametrize(
    ("outcome", "code", "options", "limits", "effect"),
    OUTCOMES,
    ids=[f"{o[0]}-{o[1]}" for o in OUTCOMES],
)
def test_the_runs_end_records_the_outcome_and_error_the_host_derived(
    tmp_path: Path,
    outcome: str,
    code: str | None,
    options: dict[str, Any],
    limits: dict[str, float],
    effect: dict[str, Any] | None,
) -> None:
    base = {"start_timeout": 10.0, "cancel_grace": 2.0, "run_timeout": 20.0}
    harness = Harness(theatre(tmp_path), limits=RunLimits(**{**base, **limits}))  # type: ignore[arg-type]
    result = harness.perform(request(options, effect=effect))
    ended = states(history(harness, result.run.run_id))[-1]["outcome"]
    assert ended["outcome"] == outcome == result.run.outcome
    assert ended.get("error", {}).get("code") == code
    assert ("error" in ended) == (code is not None)
    assert (result.run.error.code if result.run.error else None) == code


def test_a_cancelled_run_records_cancelled(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    harness.cancel.request()
    result = harness.perform(request(script(INIT, {"hang": True})))
    assert result.run.outcome == "cancelled"
    assert states(history(harness, result.run.run_id))[-1]["outcome"]["outcome"] == "cancelled"


def test_a_run_that_never_sends_init_records_its_start_without_a_runner_then_its_end(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path), limits=RunLimits(start_timeout=0.001))
    result = harness.perform(request(script(INIT, OK)))
    records = history(harness, result.run.run_id)
    assert [r.topic for r in records] == [STARTED, ENDED]
    assert "runner_reported" not in states(records)[0]
    assert result.run.runner.reported is None
    assert "reported" not in result.run.to_data()["runner"]
    assert result.run.outcome == "could-not-start"
    loaded = harness.stores[-1].load(UUID(result.run.run_id))
    assert isinstance(loaded, Run)
    assert loaded.runner_reported is None


# 7.5: refusals leave nothing behind.


def nothing_written(harness: Harness) -> bool:
    return snapshot(harness.repo.path / ".troupe") == {}


def test_no_identity_refuses_before_a_runner_starts_and_leaves_nothing(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path), env=dict(ALLOW), identity_chain=("env",))
    with pytest.raises(TroupeError) as caught:
        harness.perform(request(script(INIT, OK)))
    assert caught.value.code == "identity.unresolved"
    assert nothing_written(harness)
    assert harness.updates == []


@pytest.mark.parametrize(
    ("env", "fields", "code"),
    [
        ({**ADA, "TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE": "yes"}, {}, "policy.invalid-value"),
        (ADA, {}, "stage.effects-unenforced"),
        ({**ADA, **ALLOW}, {"runner": "claude"}, "runner.unknown"),
    ],
    ids=["malformed policy", "default policy", "unknown runner"],
)
def test_a_refusal_leaves_no_event_artifact_or_lease(
    tmp_path: Path, env: dict[str, str], fields: dict[str, str], code: str
) -> None:
    harness = Harness(theatre(tmp_path), env=env)
    with pytest.raises(TroupeError) as caught:
        harness.perform({**request(script(INIT, OK)), **fields})
    assert caught.value.code == code
    assert nothing_written(harness)
    assert harness.updates == []


def test_an_unknown_stage_leaves_no_event_artifact_or_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(defaults, "STAGE", "docker")
    harness = Harness(theatre(tmp_path))
    with pytest.raises(TroupeError) as caught:
        harness.perform(request(script(INIT, OK)))
    assert caught.value.code == "stage.unknown"
    assert nothing_written(harness)


# 7.4: a recording failure stops the run, and is reported.


def test_a_failure_to_record_an_event_cancels_the_run_and_its_end_says_where_it_stopped(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path), store_wrapper=failing_at(2))
    with pytest.raises(TroupeError) as caught:
        harness.perform(
            request(script(INIT, turn("one"), turn("two"), turn("three"), {"hang": True}))
        )
    error = caught.value
    assert error.code == "run.recording-failed"
    assert error.details["failedAt"] == 2
    assert error.details["error"]["code"] == "artifact.write-failed"
    assert "endError" not in error.details
    run_id = error.details["run"]
    records = history(harness, run_id)
    assert [r.topic for r in records] == [STARTED, REPORTED, REPORTED, ENDED]
    end = states(records)[-1]
    assert end["outcome"]["outcome"] == "cancelled"
    assert end["recording"]["failedAt"] == 2
    assert end["recording"]["error"]["code"] == "artifact.write-failed"
    transcript = end["outcome"]["transcript"]
    assert transcript in error.fix


def test_when_only_the_end_cannot_be_recorded_the_error_has_an_end_error_and_no_failed_at(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path), store_wrapper=failing_at(-1, end_too=True))
    with pytest.raises(TroupeError) as caught:
        harness.perform(request(script(INIT, turn("one"), OK)))
    error = caught.value
    assert error.code == "run.recording-failed"
    assert error.details["endError"]["code"] == "artifact.write-failed"
    assert "failedAt" not in error.details
    assert error.details["transcript"].startswith("sha256:")
    records = history(harness, error.details["run"])
    assert [r.topic for r in records] == [STARTED, REPORTED, REPORTED, REPORTED]


def test_when_the_end_cannot_be_recorded_either_the_error_says_so_and_no_end_is_written(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path), store_wrapper=failing_at(1, end_too=True))
    with pytest.raises(TroupeError) as caught:
        harness.perform(request(script(INIT, turn("one"), {"hang": True})))
    error = caught.value
    assert error.code == "run.recording-failed"
    assert error.details["endError"]["code"] == "artifact.write-failed"
    assert "interrupted" in error.problem
    records = history(harness, error.details["run"])
    assert [r.topic for r in records] == [STARTED, REPORTED]
