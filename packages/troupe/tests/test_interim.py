"""The interim runner table (perform-status-logs design D4): a name is the only way to a runner."""

import asyncio
import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from troupe.core import interim, schemas
from troupe.core.errors import TroupeError
from troupe.core.interim import RUNNERS, Runner, runner_command
from troupe.core.runners.conformance import check_runner
from troupe.core.runners.host import RunnerCommand
from troupe.core.runners.limits import RunLimits

INIT = {"type": "init", "runner": {"name": "scripted", "version": "0.0.1"}, "tools": []}
OK = {"type": "result", "status": "ok", "message": "done"}


def test_scripted_resolves_to_a_runner_that_passes_every_conformance_check(tmp_path: Path) -> None:
    argv = list(runner_command("scripted"))
    options = {"script": {"steps": [{"event": INIT}, {"wait": {"ms": 200}}, {"event": OK}]}}
    results = asyncio.run(
        check_runner(
            RunnerCommand(argv, cwd=tmp_path),
            options,
            workspace=tmp_path,
            limits=RunLimits(start_timeout=10.0, cancel_grace=3.0, run_timeout=10.0),
        )
    )
    assert {r.name: r.problem for r in results if not r.passed} == {}


def test_an_unknown_runner_fails_naming_the_runners_troupe_knows() -> None:
    with pytest.raises(TroupeError) as caught:
        runner_command("claude")
    assert caught.value.code == "runner.unknown"
    assert "'claude'" in caught.value.problem
    assert caught.value.details == {"runner": "claude", "known": sorted(RUNNERS)}
    assert "scripted" in caught.value.fix


def test_claude_code_resolves_to_the_claude_code_runners_module() -> None:
    assert list(runner_command("claude-code"))[1:] == ["-m", "troupe_runner_claude_code"]


def test_ollama_resolves_to_the_ollama_runners_module_given_no_variables() -> None:
    assert list(runner_command("ollama"))[1:] == ["-m", "troupe_runner_ollama"]
    assert RUNNERS["ollama"].environment == ()


def test_an_unknown_runner_is_refused_naming_every_runner_troupe_ships() -> None:
    with pytest.raises(TroupeError) as caught:
        runner_command("codex")
    assert caught.value.details == {
        "runner": "codex",
        "known": ["anthropic", "claude-code", "lm-studio", "ollama", "openai", "scripted"],
    }
    assert "anthropic, claude-code, lm-studio, ollama, openai, scripted" in caught.value.fix


def test_openai_resolves_to_its_module_requiring_a_runtime_and_naming_no_credential() -> None:
    assert list(runner_command("openai"))[1:] == ["-m", "troupe_runner_openai"]
    assert RUNNERS["openai"].runtime == "required"
    assert set(RUNNERS["openai"].environment) == {
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "https_proxy",
        "http_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }


def test_what_each_runner_takes_as_a_runtime() -> None:
    assert {name: runner.runtime for name, runner in RUNNERS.items()} == {
        "anthropic": "required",
        "claude-code": "none",
        "lm-studio": "required",
        "ollama": "required",
        "openai": "required",
        "scripted": "optional",
    }


# A runner troupe knows whose package isn't installed is refused, naming the extra that installs
# it (spec: runs, protocol; runner-extras design D5, D6).


def absent(*, in_extra: bool) -> Runner:
    """The scripted runner's entry, with a package that isn't installed anywhere."""
    return dataclasses.replace(
        RUNNERS["scripted"], package="troupe_runner_absent", in_extra=in_extra
    )


def test_only_the_anthropic_and_lm_studio_runners_come_as_extras() -> None:
    """anthropic depends on the anthropic package and lm-studio on LM Studio's client library, so
    each is troupe-run's extra of its name; every other shipped runner depends only on the SDK
    (#291, #415; #331 and #332 add more)."""
    assert {name: entry.in_extra for name, entry in RUNNERS.items()} == {
        name: name in ("anthropic", "lm-studio") for name in RUNNERS
    }


def test_anthropic_resolves_to_its_module_requiring_a_runtime_with_only_the_proxy_variables() -> (
    None
):
    """No ANTHROPIC_* variable reaches it: the anthropic package would read them (anthropic-runner
    design D3, D4)."""
    assert list(runner_command("anthropic"))[1:] == ["-m", "troupe_runner_anthropic"]
    assert RUNNERS["anthropic"].runtime == "required"
    assert RUNNERS["anthropic"].environment == RUNNERS["openai"].environment
    assert not any(name.startswith("ANTHROPIC_") for name in RUNNERS["anthropic"].environment)


def test_lm_studio_resolves_to_its_module_requiring_a_runtime_given_no_variables() -> None:
    assert list(runner_command("lm-studio"))[1:] == ["-m", "troupe_runner_lm_studio"]
    assert RUNNERS["lm-studio"].runtime == "required"
    assert RUNNERS["lm-studio"].environment == ()


@pytest.mark.parametrize(
    "use",
    [runner_command, interim.options_schema, interim.options_validator, interim.installed_runner],
    ids=["runner_command", "options_schema", "options_validator", "installed_runner"],
)
def test_a_runner_in_an_extra_that_isnt_installed_is_refused_naming_the_extra(
    monkeypatch: pytest.MonkeyPatch, use: Callable[[str], object]
) -> None:
    monkeypatch.setitem(RUNNERS, "lm-studio", absent(in_extra=True))
    with pytest.raises(TroupeError) as caught:
        use("lm-studio")
    assert caught.value.code == "runner.not-installed"
    assert caught.value.details == {
        "runner": "lm-studio",
        "package": "troupe_runner_absent",
        "extra": "lm-studio",
    }
    assert "'lm-studio'" in caught.value.problem
    assert "troupe-run[lm-studio]" in caught.value.fix
    assert schemas.INSTALL_PAGE in caught.value.fix


def test_a_base_runner_that_isnt_installed_is_refused_with_no_extra() -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(RUNNERS, "scripted", absent(in_extra=False))
        with pytest.raises(TroupeError) as caught:
            runner_command("scripted")
    assert caught.value.code == "runner.not-installed"
    assert caught.value.details == {"runner": "scripted", "package": "troupe_runner_absent"}
    assert schemas.INSTALL_PAGE in caught.value.fix
    assert "uv sync" in caught.value.fix
    assert "troupe-run[" not in caught.value.fix
    assert "brings every runner" not in caught.value.fix


def test_an_installed_runner_is_found_without_importing_it() -> None:
    entry = interim.installed_runner("scripted")
    assert entry is RUNNERS["scripted"]
