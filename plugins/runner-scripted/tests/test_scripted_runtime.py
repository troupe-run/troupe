"""The scripted runner's runtime steps (spec: scripted-runner, "The scripted runner takes an
optional runtime", "A script can check the runtime it received", "A script can echo the
credential", "A script's result can carry an estimated cost"; runtimes design D11)."""

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from scripted_harness import Session

KEY = "sk-test-canary-0123456789"
KEY_HASH = "sha256:" + hashlib.sha256(KEY.encode()).hexdigest()
OTHER_HASH = "sha256:" + "0" * 64
INIT = {"type": "init", "runner": {"name": "scripted", "version": "0.1.0"}, "tools": []}
OK = {"type": "result", "status": "ok", "message": "done"}
RUNTIME = {
    "name": "openai",
    "endpoint": "https://api.openai.com/v1",
    "model": "gpt-test",
    "credential": True,
}


@pytest.fixture
def keyed(tmp_path: Path) -> Iterator[Session]:
    running = Session(tmp_path, env={"TROUPE_RUNTIME_CREDENTIAL": KEY})
    try:
        yield running
    finally:
        running.kill()


@pytest.fixture
def plain(tmp_path: Path) -> Iterator[Session]:
    running = Session(tmp_path)
    try:
        yield running
    finally:
        running.kill()


def _events(session: Session, count: int) -> list[dict[str, Any]]:
    return [message["params"] for message in session.notifications(count)]


def _then(*steps: dict[str, Any]) -> dict[str, Any]:
    return {"steps": [{"event": INIT}, *steps, {"event": OK}]}


# Requirement: The scripted runner takes an optional runtime


def test_a_run_with_a_runtime_and_no_runtime_steps_plays_as_without(keyed: Session) -> None:
    answer = keyed.play(_then(), runtime=RUNTIME)
    assert "result" in answer
    assert [e["type"] for e in _events(keyed, 2)] == ["init", "result"]
    keyed.validate_all()


# Requirement: A script can check the runtime it received


def test_the_runtime_matches(keyed: Session) -> None:
    check = {**{k: RUNTIME[k] for k in ("name", "endpoint", "model")}, "credentialHash": KEY_HASH}
    keyed.play(_then({"checkRuntime": check}), runtime=RUNTIME)
    assert _events(keyed, 2)[-1]["status"] == "ok"
    keyed.validate_all()


def test_no_runtime_matches_a_check_that_there_is_none(plain: Session) -> None:
    plain.play(_then({"checkRuntime": {"absent": True}}))
    assert _events(plain, 2)[-1]["status"] == "ok"


def test_no_credential_matches_a_check_that_there_is_none(plain: Session) -> None:
    runtime = {**RUNTIME, "name": "ollama", "credential": False}
    plain.play(_then({"checkRuntime": {"noCredential": True}}), runtime=runtime)
    assert _events(plain, 2)[-1]["status"] == "ok"


def test_the_model_differs(keyed: Session) -> None:
    keyed.play(_then({"checkRuntime": {"model": "gpt-a"}}), runtime=RUNTIME)
    _, result = _events(keyed, 2)
    assert result["status"] == "error"
    assert "model: run/start carried 'gpt-test', the script expected 'gpt-a'" in result["message"]
    assert keyed.wait() == 0


def test_the_credential_differs_naming_both_hashes_and_no_part_of_either(keyed: Session) -> None:
    keyed.play(_then({"checkRuntime": {"credentialHash": OTHER_HASH}}), runtime=RUNTIME)
    _, result = _events(keyed, 2)
    assert result["status"] == "error"
    assert KEY_HASH in result["message"]
    assert OTHER_HASH in result["message"]
    assert KEY not in b"".join(keyed.raw_lines).decode()


def test_a_credential_run_start_promises_and_the_environment_lacks_ends_the_run(
    plain: Session,
) -> None:
    plain.play(_then({"checkRuntime": {"credentialHash": KEY_HASH}}), runtime=RUNTIME)
    _, result = _events(plain, 2)
    assert result["status"] == "error"
    assert "TROUPE_RUNTIME_CREDENTIAL isn't set" in result["message"]


@pytest.mark.parametrize(
    "step",
    [
        pytest.param({}, id="nothing to check"),
        pytest.param({"credentialHash": "md5:x"}, id="a hash that isn't one"),
        pytest.param({"credentialHash": KEY_HASH, "noCredential": True}, id="both"),
        pytest.param({"absent": True, "model": "m"}, id="absent with a field"),
        pytest.param({"credential": KEY}, id="a value"),
    ],
)
def test_a_malformed_runtime_check_is_refused_as_an_invalid_script(
    plain: Session, step: dict[str, Any]
) -> None:
    answer = plain.play({"steps": [{"checkRuntime": step}]}, valid=False)
    assert answer["error"]["data"]["code"] == "scripted.invalid-script"
    plain.validate_all()


PRICE = {"input": 2, "output": 8, "cacheRead": 0.5}


def test_the_price_matches(plain: Session) -> None:
    runtime = {**RUNTIME, "credential": False, "price": PRICE}
    plain.play(_then({"checkRuntime": {"price": {**PRICE, "input": 2.0}}}), runtime=runtime)
    assert _events(plain, 2)[-1]["status"] == "ok"
    plain.validate_all()


def test_no_price_matches_a_check_that_there_is_none(plain: Session) -> None:
    runtime = {**RUNTIME, "credential": False}
    plain.play(_then({"checkRuntime": {"noPrice": True}}), runtime=runtime)
    assert _events(plain, 2)[-1]["status"] == "ok"


def test_the_price_differs_when_a_script_expects_none(plain: Session) -> None:
    runtime = {**RUNTIME, "credential": False, "price": PRICE}
    plain.play(_then({"checkRuntime": {"noPrice": True}}), runtime=runtime)
    _, result = _events(plain, 2)
    assert result["status"] == "error"
    assert "price: run/start carried" in result["message"]
    assert "the script expected none" in result["message"]
    assert plain.wait() == 0


def test_the_price_differs_rate_for_rate(plain: Session) -> None:
    runtime = {**RUNTIME, "credential": False, "price": PRICE}
    plain.play(_then({"checkRuntime": {"price": {"input": 2, "output": 8}}}), runtime=runtime)
    _, result = _events(plain, 2)
    assert result["status"] == "error"
    assert "price:" in result["message"]


@pytest.mark.parametrize(
    "step",
    [
        pytest.param({"price": PRICE, "noPrice": True}, id="price and noPrice"),
        pytest.param({"price": {"input": 2}}, id="a price without output"),
        pytest.param({"noPrice": False}, id="noPrice false"),
    ],
)
def test_a_malformed_price_check_is_refused_as_an_invalid_script(
    plain: Session, step: dict[str, Any]
) -> None:
    answer = plain.play({"steps": [{"checkRuntime": step}]}, valid=False)
    assert answer["error"]["data"]["code"] == "scripted.invalid-script"


# Requirement: A script's result can carry an estimated cost


def test_an_estimate_with_no_price_is_sent_as_given(plain: Session) -> None:
    estimate = {**OK, "estimatedCostUsd": 0.5}
    plain.play({"steps": [{"event": INIT}, {"event": estimate}]})
    _, result = _events(plain, 2)
    assert result["estimatedCostUsd"] == 0.5
    assert "costUsd" not in result
    plain.validate_all()


# Requirement: A script can echo the credential


def test_echoing_the_key(keyed: Session) -> None:
    keyed.play(_then({"echoCredential": True}), runtime=RUNTIME)
    messages = keyed.notifications(4)
    log = messages[1]["params"]
    assert log["type"] == "log"
    assert KEY in log["message"]
    assert messages[2]["method"] == "run/transcript"
    assert KEY in messages[2]["params"]["record"]
    assert messages[3]["params"]["status"] == "ok"
    keyed.close_stdin()
    assert keyed.wait() == 0
    assert KEY.encode() in keyed.stderr()


def test_echoing_with_no_credential_ends_the_run_with_an_error(plain: Session) -> None:
    plain.play(_then({"echoCredential": True}))
    _, result = _events(plain, 2)
    assert result["status"] == "error"
    assert "needs a credential" in result["message"]
