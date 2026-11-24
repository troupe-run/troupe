"""A known credential appears nowhere troupe writes (spec: runtimes, "A credential's value appears
nowhere troupe writes"; runtimes design D12).

A canary key is set, an actor on a runtime that reads it is defined, and troupe is driven through
the command line: a run whose runner echoes the key in every way it can, a run that fails with it
in its message, a run refused for its endpoint, a rehearsal, ``config get`` with and without
``--resolved``, ``status`` and ``logs``. Then every file under ``.troupe/`` (events, config files,
the artifact store) and every byte the commands printed is searched for the key, its JSON-escaped
form and its base64 form.
"""

import base64
import io
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from gitrepo import Repo
from runtesting import ADA, ALLOW, theatre
from troupe.cli import main
from troupe.core import masking

CANARY = "sk-canary/0123456789abcdefghijklmnopqrstuv"
NAME_LIKE_CANARY = "skcanary0123456789abcdefghijklmnopqrstuv"
"""A key made only of letters and digits, which passes for a variable's name (design D6)."""
FORMS = {
    "the key": CANARY.encode(),
    "its JSON-escaped form": CANARY.replace("/", "\\/").encode(),
    "its base64 form": base64.b64encode(CANARY.encode()),
    "the name-like key": NAME_LIKE_CANARY.encode(),
}
INIT = {"type": "init", "runner": {"name": "scripted", "version": "0.1.0"}, "tools": []}
ECHO = [
    {"event": INIT},
    {"echoCredential": True},
    {"event": {"type": "result", "status": "ok", "message": "done"}},
]
"""The key reaches the runner only through the runtime: the script never holds it, since config
holds the script."""
FAIL = [
    {"event": INIT},
    {"echoCredential": True},
    {
        "event": {
            "type": "result",
            "status": "error",
            "reason": "authentication",
            "message": "refused",
        }
    },
]


def _cli(printed: list[bytes]) -> Callable[..., int]:
    def run(*argv: str) -> int:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = main(list(argv), stdout=stdout, stderr=stderr)
        printed.append(stdout.getvalue().encode() + stderr.getvalue().encode())
        return code

    return run


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    made = theatre(tmp_path)
    for name, value in {**made.env, **ADA, **ALLOW, "MY_CANARY_KEY": CANARY}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made


def _drive(repo: Repo, monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    printed: list[bytes] = []
    cli = _cli(printed)
    actor = (
        "actors.{name}.runner=scripted",
        "actors.{name}.expect=[]",
        "actors.{name}.workspace=theatre",
        "actors.{name}.runtime=canary",
    )
    assert (
        cli(
            "config",
            "set",
            "runtimes.canary.endpoint=https://llm.example/v1",
            "runtimes.canary.model=canary-model",
            "runtimes.canary.credential.env=MY_CANARY_KEY",
            *(a.format(name="echoer") for a in actor),
            f"actors.echoer.options.script.steps={json.dumps(ECHO)}",
            *(a.format(name="failer") for a in actor),
            f"actors.failer.options.script.steps={json.dumps(FAIL)}",
        )
        == 0
    ), printed[-1]
    assert cli("perform", "echoer", "--direction", "go") == 0, printed[-1]
    assert cli("perform", "failer", "--direction", "go") != 0
    assert cli("perform", "echoer", "--rehearse") != 0
    monkeypatch.setenv("TROUPE_RUNTIME_CANARY_ENDPOINT", "http://llm.example/v1")
    assert cli("perform", "echoer", "--direction", "go") != 0  # refused: insecure endpoint
    assert b"runtime.insecure-endpoint" in printed[-1] or b"plain HTTP" in printed[-1]
    monkeypatch.delenv("TROUPE_RUNTIME_CANARY_ENDPOINT")
    monkeypatch.setenv("MY_CANARY_KEY", CANARY + "\r\n")  # a key read with its line ending
    assert cli("perform", "echoer", "--direction", "go") != 0
    assert b"runtime.credential-malformed" in printed[-1] or b"header can't carry" in printed[-1]
    monkeypatch.setenv("MY_CANARY_KEY", CANARY)
    # The key in place of its variable's name: refused as runtime.invalid-value, since it holds
    # "-" and "/", which a name can't.
    monkeypatch.setenv("TROUPE_RUNTIME_CANARY_CREDENTIAL_ENV", CANARY)
    assert cli("perform", "echoer", "--direction", "go") != 0
    assert b"runtime.invalid-value" in printed[-1] or b"isn't an environment" in printed[-1]
    assert cli("config", "get", "--resolved", "runtimes.canary") != 0
    assert cli("config", "get", "--resolved", "--json", "runtimes.canary") != 0
    # A key that passes for a name: refused as runtime.credential-unset, naming the variable that
    # held it (namedBy), never the key, and shown the same way by config get --resolved (#306).
    monkeypatch.setenv("TROUPE_RUNTIME_CANARY_CREDENTIAL_ENV", NAME_LIKE_CANARY)
    assert cli("perform", "echoer", "--direction", "go") != 0
    assert b"the variable TROUPE_RUNTIME_CANARY_CREDENTIAL_ENV names" in printed[-1]
    assert cli("config", "get", "--resolved", "runtimes.canary") == 0
    assert b"the variable TROUPE_RUNTIME_CANARY_CREDENTIAL_ENV names" in printed[-1]
    assert cli("config", "get", "--resolved", "--json", "runtimes.canary") == 0
    assert b'"namedBy": "TROUPE_RUNTIME_CANARY_CREDENTIAL_ENV"' in printed[-1]
    monkeypatch.delenv("TROUPE_RUNTIME_CANARY_CREDENTIAL_ENV")
    assert cli("config", "get", "--resolved") == 0
    assert cli("config", "get", "--resolved", "--json") == 0
    assert cli("config", "get", "--json") == 0
    assert cli("status") == 0
    assert cli("status", "--json") == 0
    for run in json.loads(printed[-1])["runs"]:
        assert cli("logs", run["runId"], "--json") == 0
        assert cli("logs", run["runId"]) == 0
    return printed


def _leaks(repo: Repo, printed: list[bytes]) -> list[str]:
    places = {
        f"{path.relative_to(repo.path).as_posix()}": path.read_bytes()
        for path in sorted((repo.path / ".troupe").rglob("*"))
        if path.is_file()
    }
    places.update({f"the output of command {i + 1}": out for i, out in enumerate(printed)})
    return [
        f"{where} holds {name}"
        for where, data in places.items()
        for name, form in FORMS.items()
        if form in data
    ]


def test_a_known_credential_appears_nowhere_troupe_writes(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    printed = _drive(repo, monkeypatch)
    assert any(masking.MARKER.encode() in out for out in printed)  # the echo did reach troupe
    assert _leaks(repo, printed) == []


def test_the_leak_test_finds_a_leak_when_masking_is_off(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("troupe.core.runners.host.Masker", lambda value: masking.Masker(None))
    printed = _drive(repo, monkeypatch)
    found = _leaks(repo, printed)
    assert any("artifacts" in leak for leak in found)
    assert any("events" in leak for leak in found)
