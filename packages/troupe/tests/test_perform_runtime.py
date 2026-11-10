"""perform on a runtime: resolving it, recording it, handing it over and masking its credential
(spec: runs, runtimes, runner-protocol; runtimes design D5, D6, D8)."""

import base64
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from runtesting import INIT, OK, Harness, request, script, theatre
from test_perform import configured, nothing_written
from troupe.core.client import messages as m
from troupe.core.errors import TroupeError
from troupe.core.masking import MARKER
from troupe.core.runs.aggregate import STARTED
from troupe_plugin_sdk import runner as p

KEY = "sk-test/canary-0123456789abcdef"
KEY_HASH = "sha256:" + hashlib.sha256(KEY.encode()).hexdigest()
OPENAI: dict[str, Any] = {"runtime": "openai", "model": "gpt-test"}


def _harness(tmp_path: Path, **env: str) -> Harness:
    harness = Harness(theatre(tmp_path))
    harness.env = {**harness.env, **env}
    return harness


def _start(harness: Harness, run_id: str) -> dict[str, Any]:
    [record] = [r for r in harness.stores[0].history(UUID(run_id)) if r.topic == STARTED]
    state: dict[str, Any] = json.loads(record.state)
    return state


def _runner_commands(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    perform_module = importlib.import_module("troupe.core.runs.perform")
    seen: list[Any] = []
    real = perform_module.run_actor

    async def capture(command: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        seen.append((command, args))
        return await real(command, *args, **kwargs)

    monkeypatch.setattr(perform_module, "run_actor", capture)
    return seen


# Requirement: A run uses the actor as config defines it (the runtime reaches the runner)


def test_the_runtime_reaches_the_runner(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    check = {
        "checkRuntime": {
            "name": "ollama",
            "endpoint": "http://127.0.0.1:11434",
            "model": "llama3.2",
            "noCredential": True,
        }
    }
    result = harness.perform(request(script(INIT, check, OK), runtime="ollama", model="llama3.2"))
    assert result.run.outcome == "succeeded"


def test_the_credential_reaches_the_runner(tmp_path: Path) -> None:
    harness = _harness(tmp_path, OPENAI_API_KEY=KEY)
    check = {"checkRuntime": {"name": "openai", "model": "gpt-test", "credentialHash": KEY_HASH}}
    assert harness.perform(request(script(INIT, check, OK), **OPENAI)).run.outcome == "succeeded"


# Requirement: Perform passes a runner only the variables it is known to need


def test_the_credential_reaches_the_runner_under_troupes_name_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _runner_commands(monkeypatch)
    harness = _harness(tmp_path, MY_KEY=KEY)
    harness.perform(
        request(
            script(INIT, OK),
            runtimes={"openai": {"credential": {"env": "MY_KEY"}}},
            **OPENAI,
        )
    )
    [(command, (run_request, *_))] = commands
    assert dict(command.env) == {"TROUPE_RUNTIME_CREDENTIAL": KEY}
    assert run_request.runtime.credential is True
    assert KEY not in json.dumps(run_request.runtime.to_data())


def test_a_troupe_runtime_credential_in_performs_own_environment_never_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _runner_commands(monkeypatch)
    harness = _harness(tmp_path, TROUPE_RUNTIME_CREDENTIAL="sk-from-the-shell-0123")
    harness.perform(request(script(INIT, OK), runtime="ollama", model="llama3.2"))
    [(command, _)] = commands
    assert dict(command.env) == {}


# Requirement: A run's start records its runtime and where each value came from


def test_a_run_on_a_theatre_chosen_endpoint_records_where_each_value_came_from(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, OPENAI_API_KEY=KEY)
    result = harness.perform(
        request(
            script(INIT, OK),
            runtimes={"openai": {"endpoint": "https://gateway.example/v1"}},
            **OPENAI,
        )
    )
    started = _start(harness, result.run.run_id)
    assert started["runtime"] == {
        "name": "openai",
        "endpoint": {"value": "https://gateway.example/v1", "source": "theatre"},
        "model": {"value": "gpt-test", "source": "actor"},
        "credential": {"env": {"value": "OPENAI_API_KEY", "source": "default"}, "set": True},
    }
    assert KEY not in json.dumps(started)


PRICE = {"input": 2, "output": 8, "cacheRead": 0.5, "cacheWrite": 0}
PRICED = {"openai": {"prices": {"gpt-test": PRICE, "gpt-other": {"input": 1, "output": 1}}}}


def test_a_run_on_a_priced_model_hands_over_and_records_the_same_price(tmp_path: Path) -> None:
    harness = _harness(tmp_path, OPENAI_API_KEY=KEY)
    check = {"checkRuntime": {"model": "gpt-test", "price": PRICE}}
    result = harness.perform(request(script(INIT, check, OK), runtimes=PRICED, **OPENAI))
    assert result.run.outcome == "succeeded"
    started = _start(harness, result.run.run_id)
    assert started["runtime"]["price"] == {"value": PRICE, "source": "theatre"}


def test_a_run_on_a_model_config_doesnt_price_hands_over_and_records_no_price(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, OPENAI_API_KEY=KEY)
    check = {"checkRuntime": {"model": "gpt-unpriced", "noPrice": True}}
    result = harness.perform(
        request(script(INIT, check, OK), runtimes=PRICED, runtime="openai", model="gpt-unpriced")
    )
    assert result.run.outcome == "succeeded"
    assert "price" not in _start(harness, result.run.run_id)["runtime"]


# Requirement: The host drops an estimate it gave no price for (spec: runner-protocol)

ESTIMATE = {"event": {**OK["event"], "estimatedCostUsd": 0.5}}


def _dropped(harness: Harness) -> list[dict[str, Any]]:
    return [
        u["notice"]
        for u in harness.updates
        if u.get("kind") == "notice" and u["notice"]["code"] == "run.estimate-dropped"
    ]


def test_an_estimate_with_no_price_given_is_dropped_and_the_run_succeeds_with_a_notice(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, OPENAI_API_KEY=KEY)
    result = harness.perform(request(script(INIT, ESTIMATE), **OPENAI))
    assert result.run.outcome == "succeeded"
    logged = [e for e in harness.logs(run=result.run.run_id).log if isinstance(e, m.LoggedEvent)]
    [ended] = [e.event for e in logged if isinstance(e.event, p.ResultEvent)]
    assert ended.estimated_cost_usd is None
    [notice] = _dropped(harness)
    assert notice["details"] == {"runner": "scripted"}


def test_an_estimate_with_a_price_given_records_the_result_as_sent(tmp_path: Path) -> None:
    harness = _harness(tmp_path, OPENAI_API_KEY=KEY)
    result = harness.perform(request(script(INIT, ESTIMATE), runtimes=PRICED, **OPENAI))
    assert result.run.outcome == "succeeded"
    logged = [e for e in harness.logs(run=result.run.run_id).log if isinstance(e, m.LoggedEvent)]
    [ended] = [e.event for e in logged if isinstance(e.event, p.ResultEvent)]
    assert ended.estimated_cost_usd == 0.5
    assert ended.cost_usd is None
    assert _dropped(harness) == []


def test_a_run_with_no_runtime_records_none(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    result = harness.perform(request(script(INIT, OK)))
    assert "runtime" not in _start(harness, result.run.run_id)


@pytest.mark.parametrize(
    ("env", "code"),
    [
        pytest.param({}, "runtime.credential-unset", id="the key isn't set"),
        pytest.param({"OPENAI_API_KEY": "q7Zx"}, "runtime.credential-too-short", id="too short"),
        pytest.param(
            {"OPENAI_API_KEY": KEY + "\r\n"},
            "runtime.credential-malformed",
            id="a key read with its line ending",
        ),
        pytest.param(
            {"OPENAI_API_KEY": "sk-test-€abcdefgh"},
            "runtime.credential-malformed",
            id="a character a header can't carry",
        ),
        pytest.param(
            {"OPENAI_API_KEY": KEY, "TROUPE_RUNTIME_OPENAI_ENDPOINT": "http://example.com/v1"},
            "runtime.insecure-endpoint",
            id="plain HTTP to another host",
        ),
        pytest.param(
            {"OPENAI_API_KEY": KEY, "TROUPE_RUNTIME_OPENAI_ENDPOINT": "localhost:1"},
            "runtime.invalid-value",
            id="a malformed variable",
        ),
        pytest.param(
            {"OPENAI_API_KEY": KEY, "TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV": "sk-test q7ZxW9pL4vR2"},
            "runtime.invalid-value",
            id="a key where a variable's name should be",
        ),
    ],
)
def test_a_refused_runtime_records_nothing_and_launches_no_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict[str, str], code: str
) -> None:
    launched = _runner_commands(monkeypatch)
    harness = _harness(tmp_path, **env)
    asked = request(script(INIT, OK), **OPENAI)
    before = configured(harness, asked)
    with pytest.raises(TroupeError) as raised:
        harness.perform(asked)
    assert raised.value.code == code
    assert nothing_written(harness, before)
    assert harness.updates == []
    assert launched == []


def test_a_key_where_a_variables_name_should_be_reaches_no_client_message(tmp_path: Path) -> None:
    harness = _harness(
        tmp_path, OPENAI_API_KEY=KEY, TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV="sk-test q7ZxW9pL4vR2"
    )
    with pytest.raises(TroupeError) as raised:
        harness.perform(request(script(INIT, OK), **OPENAI))
    assert raised.value.code == "runtime.invalid-value"
    assert "q7ZxW9pL4vR2" not in json.dumps([raised.value.to_data(), *harness.updates])


def test_a_name_from_the_environment_that_isnt_set_is_refused_without_repeating_it(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV="a3f9c2e17b4d8e05f6a1")
    asked = request(script(INIT, OK), **OPENAI)
    before = configured(harness, asked)
    with pytest.raises(TroupeError) as raised:
        harness.perform(asked)
    assert raised.value.code == "runtime.credential-unset"
    assert raised.value.details == {
        "runtime": "openai",
        "namedBy": "TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV",
    }
    assert nothing_written(harness, before)
    assert "a3f9c2e1" not in json.dumps([raised.value.to_data(), *harness.updates])


def test_no_model_anywhere_is_refused_before_anything_is_recorded(tmp_path: Path) -> None:
    harness = _harness(tmp_path, OPENAI_API_KEY=KEY)
    with pytest.raises(TroupeError) as raised:
        harness.perform(request(script(INIT, OK), runtime="openai"))
    assert raised.value.code == "runtime.no-model"


# Requirement: troupe masks the credential in everything it keeps from a run


def _artifact(harness: Harness, ref: str) -> bytes:
    hex_ = ref.removeprefix("sha256:")
    path = harness.repo.path / ".troupe" / "local" / "artifacts" / "sha256" / hex_[:2] / hex_
    return path.read_bytes()


def test_an_echoed_key_is_masked_in_the_events_transcript_and_standard_error(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, OPENAI_API_KEY=KEY)
    split = {"stderr": KEY[:10]}, {"wait": {"ms": 50}}, {"stderr": KEY[10:] + " after\n"}
    encoded = {
        "transcript": {"record": base64.b64encode(KEY.encode()).decode(), "encoding": "base64"}
    }
    steps = (INIT, {"echoCredential": True}, *split, encoded, OK)
    result = harness.perform(request(script(*steps), **OPENAI))
    records = [json.loads(r.state) for r in harness.stores[0].history(UUID(result.run.run_id))]
    [log] = [s["event"] for s in records if s.get("event", {}).get("type") == "log"]
    assert log["message"] == f"the key is {MARKER}"
    ended = records[-1]["outcome"]
    transcript = _artifact(harness, ended["transcript"])
    assert transcript == f'{{"key": "{MARKER}"}}\n{MARKER}\n'.encode()
    stderr = _artifact(harness, ended["stderr"])
    assert stderr == f"the key is {MARKER}\n{MARKER} after\n".encode()
    for kept in (transcript, stderr, json.dumps(records).encode()):
        assert KEY.encode() not in kept
        assert KEY[:10].encode() not in kept
        assert KEY[10:].encode() not in kept


def test_the_json_escaped_form_is_masked(tmp_path: Path) -> None:
    harness = _harness(tmp_path, OPENAI_API_KEY=KEY)
    escaped = KEY.replace("/", "\\/")
    result = harness.perform(request(script(INIT, {"transcript": escaped}, OK), **OPENAI))
    ended = [json.loads(r.state) for r in harness.stores[0].history(UUID(result.run.run_id))][-1]
    assert _artifact(harness, ended["outcome"]["transcript"]) == f"{MARKER}\n".encode()


# Requirement: A rehearsal shows the run's runtime


def test_a_rehearsal_on_openai_shows_the_runtime_and_no_part_of_the_key(tmp_path: Path) -> None:
    harness = _harness(tmp_path, OPENAI_API_KEY=KEY)
    result = harness.perform_result(request(script(INIT, OK), rehearse=True, **OPENAI))
    assert result.rehearsal is not None
    assert result.rehearsal.runtime is not None
    assert result.rehearsal.runtime.to_data() == {
        "name": "openai",
        "endpoint": {"value": "https://api.openai.com/v1", "source": "default"},
        "model": {"value": "gpt-test", "source": "actor"},
        "credential": {"env": {"value": "OPENAI_API_KEY", "source": "default"}, "set": True},
    }
    assert KEY not in json.dumps(result.to_data())


def test_a_rehearsal_on_a_priced_model_shows_the_price(tmp_path: Path) -> None:
    harness = _harness(tmp_path, OPENAI_API_KEY=KEY)
    result = harness.perform_result(
        request(script(INIT, OK), rehearse=True, runtimes=PRICED, **OPENAI)
    )
    assert result.rehearsal is not None
    assert result.rehearsal.runtime is not None
    shown = result.rehearsal.runtime.to_data()
    assert shown["price"] == {"value": PRICE, "source": "theatre"}


def test_a_rehearsal_refuses_what_perform_would(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with pytest.raises(TroupeError) as raised:
        harness.perform_result(request(script(INIT, OK), rehearse=True, **OPENAI))
    assert raised.value.code == "runtime.credential-unset"


def test_a_rehearsal_refuses_a_malformed_key_as_perform_would(tmp_path: Path) -> None:
    harness = _harness(tmp_path, OPENAI_API_KEY=KEY + "\r\n")
    with pytest.raises(TroupeError) as raised:
        harness.perform_result(request(script(INIT, OK), rehearse=True, **OPENAI))
    assert raised.value.code == "runtime.credential-malformed"
    assert KEY not in json.dumps(raised.value.to_data())
