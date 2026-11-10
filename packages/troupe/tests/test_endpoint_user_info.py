"""An endpoint refused for holding user info is repeated nowhere: not by a runner refusing
run/start, not by troupe refusing config or a runtime variable (spec: runtimes, "An endpoint
refused for its user info is repeated nowhere"; plugin-sdk, "The SDK never repeats a refused
endpoint"; runtime-checks design D8, #323)."""

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from runtesting import ADA, theatre
from troupe.cli import main

CANARY = "q7ZxW9pL4vR2canary"
WITH_PASSWORD = f"https://user:{CANARY}@example.com/v1"

RUNNERS = ["claude-code", "ollama", "openai", "scripted"]
PARSE_FIRST = {"claude-code", "ollama", "openai"}
"""The runners that parse run/start with the SDK before anything else, so refuse it at once with
runner.invalid-params. The scripted runner reads its script first."""


def _drive(runner: str, workspace: Path) -> tuple[list[dict[str, Any]], bytes]:
    """Initialize the runner, send it a run/start whose endpoint holds a password, end its input,
    and return every message it wrote and its standard error."""
    module = "troupe_runner_" + runner.replace("-", "_")
    scratch = workspace.parent / "scratch"
    scratch.mkdir(exist_ok=True)
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersions": [0],
                "host": {"name": "test", "version": "1"},
                "capabilities": ["transcript-kinds"],
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "run/start",
            "params": {
                "runId": "0f8fad5b-d9cb-469f-a165-70867728950e",
                "direction": "Do the task.",
                "workspace": str(workspace),
                "options": {},
                "limits": {"eventMaxBytes": 65536},
                "effects": {"write": [], "delete": [], "move": []},
                "scratch": str(scratch),
                "runtime": {
                    "name": "box",
                    "endpoint": WITH_PASSWORD,
                    "model": "m",
                    "credential": False,
                },
            },
        },
    ]
    done = subprocess.run(
        [sys.executable, "-m", module],
        input=b"".join(json.dumps(m).encode() + b"\n" for m in messages),
        capture_output=True,
        cwd=workspace,
        timeout=60,
        check=False,
    )
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()], done.stderr


@pytest.mark.parametrize("runner", RUNNERS)
def test_a_runner_refusing_a_run_start_never_repeats_the_endpoints_password(
    runner: str, tmp_path: Path
) -> None:
    workspace = tmp_path / "w"
    workspace.mkdir()
    written, stderr = _drive(runner, workspace)
    everything = json.dumps(written).encode() + stderr
    assert CANARY.encode() not in everything
    assert b"example.com" not in everything
    if runner in PARSE_FIRST:
        [answer] = [message for message in written if message.get("id") == 2]
        assert answer["error"]["data"]["code"] == "runner.invalid-params"
        assert "runtime.endpoint" in answer["error"]["message"] + json.dumps(answer["error"])


@pytest.fixture
def in_theatre(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    made = theatre(tmp_path)
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made.path


def _cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_config_set_with_a_password_in_an_endpoint_never_repeats_it(in_theatre: Path) -> None:
    code, out, err = _cli("config", "set", f"runtimes.box.endpoint={WITH_PASSWORD}")
    assert code != 0
    assert "runtimes.box.endpoint" in err
    assert CANARY not in out + err
    assert "example.com" not in out + err


def test_an_endpoint_variable_with_a_password_is_never_repeated(
    in_theatre: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TROUPE_RUNTIME_OLLAMA_ENDPOINT", WITH_PASSWORD)
    for json_flag in ((), ("--json",)):
        code, out, err = _cli("config", "get", "--resolved", "runtimes.ollama", *json_flag)
        assert code != 0
        assert "TROUPE_RUNTIME_OLLAMA_ENDPOINT" in out + err
        assert CANARY not in out + err
        assert "example.com" not in out + err
