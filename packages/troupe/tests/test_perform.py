"""perform runs one actor and records the run (spec: runs, stages, policy; perform-status-logs
design D5, D8, D9)."""

import asyncio
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

import claude_stand_in
from runtesting import ADA, ALLOW, INIT, OK, Harness, failing_at, request, script, theatre, turn
from storetesting import git_service, snapshot
from troupe.core import defaults, interim
from troupe.core.client import messages as m
from troupe.core.config import aggregate, projection
from troupe.core.config.merge import merge
from troupe.core.config.stream import read as read_config
from troupe.core.errors import TroupeError
from troupe.core.files import directory_lock
from troupe.core.runners.limits import RunLimits
from troupe.core.runs.aggregate import ENDED, REPORTED, STARTED, Run
from troupe.core.runs.perform import lease_dir, perform

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
    result = harness.perform(request(options, direction="say hello"))
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


def test_the_direction_is_an_artifact_referenced_from_the_start(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    result = harness.perform(request(script(INIT, OK), direction="say hello"))
    run_events = history(harness, result.run.run_id)
    [started] = states(run_events)[:1]
    assert started["direction"] == "sha256:" + hashlib.sha256(b"say hello").hexdigest()
    store = harness.backends().artifact_store(harness.session())
    assert store.read(started["direction"]) == b"say hello"
    assert not any(b"say hello" in record.state for record in run_events)


def test_the_options_are_referenced_through_the_config_version_the_run_used(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    options = script(INIT, OK)
    result = harness.perform(request(options))
    run_events = history(harness, result.run.run_id)
    [started] = states(run_events)[:1]
    config_events = git_service(harness.repo).history(aggregate.STREAM)
    assert started["config"] == sorted(e.id for e in config_events[-1:])
    at_version = merge([e for e in config_events if e.id in set(started["config"])] or [])
    assert at_version.config["actors"]["tester"]["options"] == options
    assert not any(b'"steps"' in record.state for record in run_events)
    assert "options" not in started


def test_a_later_config_change_doesnt_change_the_version_a_run_recorded(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    first = harness.perform(request(script(INIT, OK)))
    harness.perform(request(script(INIT, turn("changed"), OK)))
    [started] = states(history(harness, first.run.run_id))[:1]
    config_events = git_service(harness.repo).history(aggregate.STREAM)
    assert started["config"] == [config_events[0].id]
    assert len(config_events) == 2


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


def configured(harness: Harness, asked: dict[str, Any]) -> dict[str, str]:
    """Define the actor in config, then snapshot .troupe/: what perform must leave as it is."""
    harness.configure(asked)
    projection.flush(
        harness.repo.path, read_config(git_service(harness.repo)).config, {}
    )  # the files too, so a refused perform has nothing to flush either
    return snapshot(harness.repo.path / ".troupe")


def nothing_written(harness: Harness, before: dict[str, str]) -> bool:
    return snapshot(harness.repo.path / ".troupe") == before


def test_no_identity_refuses_before_a_runner_starts_and_leaves_nothing(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path), env=dict(ALLOW), identity_chain=("env",))
    before = configured(harness, request(script(INIT, OK)))
    with pytest.raises(TroupeError) as caught:
        harness.perform(request(script(INIT, OK)))
    assert caught.value.code == "identity.unresolved"
    assert nothing_written(harness, before)
    assert harness.updates == []


@pytest.mark.parametrize(
    ("env", "fields", "code"),
    [
        ({**ADA, "TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE": "yes"}, {}, "policy.invalid-value"),
        (ADA, {}, "stage.effects-unenforced"),
    ],
    ids=["malformed policy", "default policy"],
)
def test_a_refusal_leaves_no_event_artifact_or_lease(
    tmp_path: Path, env: dict[str, str], fields: dict[str, str], code: str
) -> None:
    harness = Harness(theatre(tmp_path), env=env)
    before = configured(harness, {**request(script(INIT, OK)), **fields})
    with pytest.raises(TroupeError) as caught:
        harness.perform({**request(script(INIT, OK)), **fields})
    assert caught.value.code == code
    assert nothing_written(harness, before)
    assert harness.updates == []


def test_a_runner_troupe_no_longer_knows_is_refused_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Config refuses an unknown runner when it's set; a runner uninstalled since is refused here.
    harness = Harness(theatre(tmp_path))
    gone = {**interim.RUNNERS, "gone": interim.RUNNERS["scripted"]}
    monkeypatch.setattr(interim, "RUNNERS", gone)
    before = configured(harness, {**request(script(INIT, OK)), "runner": "gone"})
    monkeypatch.undo()
    with pytest.raises(TroupeError) as caught:
        harness.perform(request(script(INIT, OK)) | {"runner": "gone"})
    assert caught.value.code == "runner.unknown"
    assert nothing_written(harness, before)


def test_an_actor_config_doesnt_have_is_refused_naming_the_actors_it_has(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    before = configured(harness, request(script(INIT, OK)))
    with pytest.raises(TroupeError) as caught:
        asyncio.run(
            perform(
                m.PerformRequest.from_data({"actor": "nobody"}),
                harness.session(),
                harness.send,
                backends=harness.backends(),
            )
        )
    assert caught.value.code == "config.unknown-actor"
    assert caught.value.details == {"actor": "nobody", "known": ["tester"]}
    assert nothing_written(harness, before)


def test_an_unknown_stage_leaves_no_event_artifact_or_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness(theatre(tmp_path))
    before = configured(harness, request(script(INIT, OK)))
    monkeypatch.setattr(defaults, "STAGE", "docker")
    with pytest.raises(TroupeError) as caught:
        harness.perform(request(script(INIT, OK)))
    assert caught.value.code == "stage.unknown"
    assert nothing_written(harness, before)


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


# Requirement: A run uses the actor as config defines it (spec: runs)

CHARACTER = "You are the tester."
CHARACTER_HASH = "sha256:" + hashlib.sha256(CHARACTER.encode()).hexdigest()


def test_the_character_config_gives_the_actor_reaches_the_runner_unchanged(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    checked = script(INIT, {"checkCharacter": {"hash": CHARACTER_HASH}}, OK)
    result = harness.perform({**request(checked), "character": CHARACTER})
    assert result.run.outcome == "succeeded"


def test_a_character_other_than_the_one_the_script_expects_fails_the_run(tmp_path: Path) -> None:
    # The check above can fail: the runner really compares what it received.
    harness = Harness(theatre(tmp_path))
    checked = script(INIT, {"checkCharacter": {"hash": CHARACTER_HASH}}, OK)
    result = harness.perform({**request(checked), "character": "Someone else."})
    assert result.run.outcome == "failed"


def test_a_run_after_a_config_change_uses_the_new_options(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    harness.perform(request(script(INIT, turn("first"), OK)))
    second = harness.perform(request(script(INIT, turn("second"), OK)))
    texts = [
        e["event"].get("text") for e in states(history(harness, second.run.run_id)) if "event" in e
    ]
    assert "second" in texts
    assert "first" not in texts


def test_perform_writes_a_missing_config_file_before_the_run_starts(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    configured(harness, request(script(INIT, OK)))
    actor_file = harness.repo.path / ".troupe" / "actors" / "tester.yaml"
    actor_file.unlink()
    harness.perform(request(script(INIT, OK)))
    assert actor_file.exists()
    assert any(u.get("notice", {}).get("code") == "config.file-rewritten" for u in harness.updates)


def test_a_conflict_on_another_actor_refuses_the_perform(tmp_path: Path) -> None:
    repo = theatre(tmp_path)
    harness = Harness(repo)
    reviewer = {**request(script(INIT, OK)), "actor": "reviewer"}
    harness.configure(reviewer)
    harness.configure(request(script(INIT, OK)))
    repo.commit_all("actors")
    repo.git("branch", "feature")
    for branch, text in (("feature", "One."), ("main", "Two.")):
        repo.git("switch", "-q", branch)
        harness.configure({**request(script(INIT, OK)), "character": text})
        repo.commit_all(text)
    repo.git("merge", "-q", "--no-edit", "feature")
    with pytest.raises(TroupeError) as caught:
        asyncio.run(
            perform(
                m.PerformRequest.from_data({"actor": "reviewer"}),
                harness.session(),
                harness.send,
                backends=harness.backends(),
            )
        )
    assert caught.value.code == "config.conflict"
    assert "actors.tester.character" in caught.value.problem


# claude-code-runner 8.1: perform passes a runner only the variables troupe's table names for it.


def _runner_commands(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Every RunnerCommand perform hands the host, while the host still runs it."""
    perform_module = importlib.import_module("troupe.core.runs.perform")
    seen: list[Any] = []
    real = perform_module.run_actor

    async def capture(command: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        seen.append(command)
        return await real(command, *args, **kwargs)

    monkeypatch.setattr(perform_module, "run_actor", capture)
    return seen


def test_a_scripted_actors_runner_is_given_no_variables_even_with_path_and_a_secret_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _runner_commands(monkeypatch)
    harness = Harness(theatre(tmp_path))
    harness.env = {**harness.env, "PATH": "/usr/bin", "AWS_SECRET_ACCESS_KEY": FAKE_SECRET}
    harness.perform(request(script(INIT, OK)))
    [command] = commands
    assert dict(command.env) == {}


FAKE_TOKEN = "oauth-token"  # noqa: S105 - a stand-in value, checked for where it arrives
FAKE_SECRET = "s3cret"  # noqa: S105 - a stand-in value, checked for where it never arrives


def _claude_code_env(tmp_path: Path, record: Path, **variables: str) -> dict[str, str]:
    """perform's environment for a claude-code actor: the stand-in claude first on PATH, which
    replays the success fixture and records what it was given, plus ``variables``."""
    bin_dir = tmp_path / "bin"
    claude_stand_in.install(
        bin_dir, fixture=claude_stand_in.fixture("success-with-tools"), record=str(record)
    )
    return {"PATH": str(bin_dir), **variables}


def test_a_claude_code_actors_runner_gets_path_home_and_the_oauth_token_from_perform(
    tmp_path: Path,
) -> None:
    record = tmp_path / "record.json"
    harness = Harness(theatre(tmp_path / "theatre"))
    home = str(tmp_path / "home")
    harness.env = {
        **harness.env,
        **_claude_code_env(tmp_path, record, HOME=home, CLAUDE_CODE_OAUTH_TOKEN=FAKE_TOKEN),
    }
    result = harness.perform(request({}, runner="claude-code"))
    assert result.run.outcome == "succeeded"
    seen = claude_stand_in.wait_for_record(record, "env")["env"]
    assert seen["PATH"] == str(tmp_path / "bin")
    assert seen["HOME"] == home
    assert seen["CLAUDE_CODE_OAUTH_TOKEN"] == FAKE_TOKEN


def test_a_variable_the_table_doesnt_name_never_reaches_a_claude_code_runner(
    tmp_path: Path,
) -> None:
    record = tmp_path / "record.json"
    harness = Harness(theatre(tmp_path / "theatre"))
    harness.env = {
        **harness.env,
        **_claude_code_env(tmp_path, record, AWS_SECRET_ACCESS_KEY=FAKE_SECRET),
    }
    harness.perform(request({}, runner="claude-code"))
    seen = claude_stand_in.wait_for_record(record, "env")["env"]
    assert "AWS_SECRET_ACCESS_KEY" not in seen
    assert FAKE_SECRET not in seen.values()


def test_a_named_variable_perform_doesnt_have_is_left_out_not_passed_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _runner_commands(monkeypatch)
    record = tmp_path / "record.json"
    harness = Harness(theatre(tmp_path / "theatre"))
    harness.env = {**harness.env, **_claude_code_env(tmp_path, record)}
    harness.perform(request({}, runner="claude-code"))
    [command] = commands
    assert "ANTHROPIC_API_KEY" not in command.env
    assert dict(command.env) == {"PATH": str(tmp_path / "bin")}
    assert "ANTHROPIC_API_KEY" not in claude_stand_in.wait_for_record(record, "env")["env"]
