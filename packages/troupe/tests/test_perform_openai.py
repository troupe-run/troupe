"""perform runs the OpenAI runner, against a stand-in Chat Completions service (spec: runs,
"Perform knows the runners troupe ships by name", "Perform passes a runner only the variables it
is known to need"; openai-runner; openai-style-runner tasks 7.1, 7.3).

Every run uses the plugin's TEST_LIMITS (design D7)."""

import json
from pathlib import Path
from typing import Any

import pytest

import openai_stand_in
from gitrepo import Repo
from runtesting import ADA, ALLOW, request, theatre
from test_cli_runs import cli
from test_perform import FAKE_SECRET
from test_perform_runtime import _harness, _runner_commands
from troupe.core.exit_codes import ExitCode

KEY = "sk-test/canary-0123456789abcdef"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    """A committed git theatre as the working directory, ada acting, the local stage allowed, and
    the person's OpenAI key set."""
    made = theatre(tmp_path)
    made.write("README.md", "a theatre\n")
    made.commit_all("base")
    for name, value in {**made.env, **ADA, **ALLOW, "OPENAI_API_KEY": KEY}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made


def _actor(repo: Repo, actor: dict[str, Any]) -> tuple[int, str]:
    path = repo.path / "actor.json"
    path.write_text(json.dumps(actor), encoding="utf-8")
    code, _, err = cli("config", "set", "actors.writer=@actor.json")
    path.unlink()
    return code, err


WRITER: dict[str, Any] = {
    "runner": "openai",
    "runtime": "openai",
    "model": "fake-model",
    "options": openai_stand_in.TEST_LIMITS,
    "effects": {"write": ["out/**"]},
    "expect": ["out/hello.txt"],
    "workspace": "worktree",
}


def test_an_actor_on_the_openai_style_runner_writes_its_file_in_a_worktree(repo: Repo) -> None:
    script = [
        openai_stand_in.write_reply("out/hello.txt", "hello\n"),
        openai_stand_in.text_reply("Wrote it."),
    ]
    with openai_stand_in.serving(script) as fake:
        code, _, err = cli("config", "set", f"runtimes.openai.endpoint={fake.endpoint}")
        assert code == ExitCode.OK, err
        code, err = _actor(repo, WRITER)
        assert code == ExitCode.OK, err
        repo.commit_all("config")
        code, out, err = cli(
            "perform", "writer", "--direction", "Write out/hello.txt saying hello."
        )
        assert code == ExitCode.OK, err
        assert {r.headers["authorization"] for r in fake.requests} == {f"Bearer {KEY}"}
    run_id = out.split()[1]
    assert "succeeded" in out + err
    code, logs, err = cli("logs", run_id[:8])
    assert code == ExitCode.OK, err
    for shown in ("init", "tool_call", "Write", "tool_result", "Wrote it."):
        assert shown in logs
    code, diff, err = cli("diff", run_id[:8])
    assert code == ExitCode.OK, err
    assert "out/hello.txt" in diff
    assert "+hello" in diff
    assert not (repo.path / "out" / "hello.txt").exists()
    assert KEY not in logs + diff + out + err


def test_an_openai_style_actor_that_names_no_runtime_is_refused_naming_the_runtime(
    repo: Repo,
) -> None:
    code, err = _actor(repo, {k: v for k, v in WRITER.items() if k not in ("runtime", "model")})
    assert code != ExitCode.OK
    assert "actors.writer.runtime" in err
    assert "openai" in err


def test_the_runner_gets_its_proxy_its_certificates_and_the_key_under_troupes_name_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _runner_commands(monkeypatch)
    harness = _harness(
        tmp_path,
        OPENAI_API_KEY=KEY,
        HTTPS_PROXY="http://proxy.example:3128",
        SSL_CERT_FILE="/etc/ssl/corp.pem",
        AWS_SECRET_ACCESS_KEY=FAKE_SECRET,
    )
    with openai_stand_in.serving([openai_stand_in.text_reply("Done.")]) as fake:
        harness.perform(
            request(
                openai_stand_in.TEST_LIMITS,
                runner="openai",
                runtime="openai",
                model="fake-model",
                runtimes={"openai": {"endpoint": fake.endpoint}},
            )
        )
    [(command, (run_request, *_))] = commands
    assert dict(command.env) == {
        "HTTPS_PROXY": "http://proxy.example:3128",
        "SSL_CERT_FILE": "/etc/ssl/corp.pem",
        "TROUPE_RUNTIME_CREDENTIAL": KEY,
    }
    assert run_request.runtime.to_data() == {
        "name": "openai",
        "endpoint": fake.endpoint,
        "model": "fake-model",
        "credential": True,
    }
