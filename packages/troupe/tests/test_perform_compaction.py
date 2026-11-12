"""perform works out each run's onContextFull from the actor and the compaction policy, sends it in
run/start, records it with its source, and refuses an actor policy forbids (spec: runs, policy;
compaction-opt-in design D2, D3)."""

import importlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from runtesting import INIT, OK, Harness, request, script, theatre
from test_perform import configured, nothing_written
from troupe.core.errors import TroupeError
from troupe.core.runs.aggregate import STARTED

VARIABLE = "TROUPE_POLICY_COMPACTION"


def _harness(tmp_path: Path, policy: str | None) -> Harness:
    harness = Harness(theatre(tmp_path))
    if policy is not None:
        harness.env = {**harness.env, VARIABLE: policy}
    return harness


def _sent(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Each RunRequest perform hands the run host, which it sends as run/start."""
    perform_module = importlib.import_module("troupe.core.runs.perform")
    seen: list[Any] = []
    real = perform_module.run_actor

    async def capture(command: Any, run: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        seen.append(run)
        return await real(command, run, *args, **kwargs)

    monkeypatch.setattr(perform_module, "run_actor", capture)
    return seen


def _started(harness: Harness, run_id: str) -> dict[str, Any]:
    [record] = [r for r in harness.stores[0].history(UUID(run_id)) if r.topic == STARTED]
    state: dict[str, Any] = json.loads(record.state)
    return state


def _asked(own: str | None) -> dict[str, Any]:
    if own is None:
        return request(script(INIT, OK))
    return request(script(INIT, OK), onContextFull=own)


# Requirement: A run's onContextFull comes from the actor and policy
# Requirement: A run's start records whether it may compact and why


@pytest.mark.parametrize(
    ("policy", "own", "value", "source"),
    [
        (None, None, "fail", "default"),
        (None, "fail", "fail", "actor"),
        (None, "compact", "compact", "actor"),
        ("actors", None, "fail", "default"),
        ("actors", "compact", "compact", "actor"),
        ("all", None, "compact", "policy"),
        ("all", "fail", "fail", "actor"),
        ("all", "compact", "compact", "actor"),
        ("none", None, "fail", "policy"),
        ("none", "fail", "fail", "actor"),
    ],
)
def test_each_policy_and_actor_value_sends_and_records_the_resolved_value_and_its_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy: str | None,
    own: str | None,
    value: str,
    source: str,
) -> None:
    sent = _sent(monkeypatch)
    harness = _harness(tmp_path, policy)
    run = harness.perform(_asked(own)).run
    assert run.outcome == "succeeded"
    [started] = sent
    assert started.on_context_full == value
    assert _started(harness, run.run_id)["on_context_full"] == {"value": value, "source": source}


# Requirement: Policy none refuses an actor that asks to compact


def test_policy_none_refuses_an_actor_that_asks_to_compact_before_anything_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _sent(monkeypatch)
    harness = _harness(tmp_path, "none")
    before = configured(harness, _asked("compact"))
    with pytest.raises(TroupeError) as caught:
        harness.perform(_asked("compact"))
    error = caught.value
    assert error.code == "policy.compaction-forbidden"
    assert error.details == {"actor": "tester", "variable": VARIABLE}
    assert "tester" in error.problem
    assert VARIABLE in error.problem
    assert "actors.tester.onContextFull" in error.fix
    assert sent == []
    assert nothing_written(harness, before)
    assert harness.updates == []


def test_a_malformed_compaction_policy_refuses_the_perform(tmp_path: Path) -> None:
    harness = _harness(tmp_path, "sometimes")
    before = configured(harness, _asked(None))
    with pytest.raises(TroupeError) as caught:
        harness.perform(_asked(None))
    assert caught.value.code == "policy.invalid-value"
    assert nothing_written(harness, before)
