"""troupe init, and troupe init --audition, in the core (spec: cli, config, client-protocol;
init-and-audition design D1, D2, D6, D8)."""

import asyncio
import dataclasses
import hashlib
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest

from client_schemas import MESSAGES, is_valid
from gitrepo import Repo, isolated_environment, make_repo
from runtesting import ADA
from storetesting import git_service
from troupe.core import audition as auditions
from troupe.core import identity, init, interim
from troupe.core.client.dispatch import call
from troupe.core.client.session import Session
from troupe.core.config import aggregate
from troupe.core.config.changes import apply, change
from troupe.core.config.kinds import check
from troupe.core.config.stream import read
from troupe.core.errors import TroupeError
from troupe.core.policy import ALLOW_UNENFORCED_LOCAL_STAGE, env_name

ALLOW_VARIABLE = env_name(ALLOW_UNENFORCED_LOCAL_STAGE)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return make_repo(tmp_path)


def _env(repo: Repo, **extra: str) -> dict[str, str]:
    return {**repo.env, **ADA, **extra}


def _init(directory: Path, env: dict[str, str], **params: Any) -> Any:  # noqa: ANN401
    result = asyncio.run(call("init", params, Session(theatre=directory, env=env)))
    assert is_valid(params, MESSAGES["init"]["request"])
    assert is_valid(result, MESSAGES["init"]["result"]), result
    return result


def _refused(directory: Path, env: dict[str, str], **params: Any) -> TroupeError:  # noqa: ANN401
    with pytest.raises(TroupeError) as caught:
        asyncio.run(call("init", params, Session(theatre=directory, env=env)))
    return caught.value


def _tree(root: Path) -> dict[str, bytes]:
    """Every file under ``root``, by relative path, with its bytes."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def _outside(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    directory = tmp_path / "plain"
    directory.mkdir()
    env = {
        **isolated_environment(tmp_path / "home"),
        **ADA,
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
    }
    return directory, env


# Requirement: Init makes a theatre in the current directory


def test_plain_init_makes_only_the_theatres_git_files_and_records_nothing(repo: Repo) -> None:
    result = _init(repo.path, _env(repo))
    troupe = repo.path / ".troupe"
    assert sorted(p.name for p in troupe.iterdir()) == [".gitattributes", ".gitignore"]
    ignore = (troupe / ".gitignore").read_text(encoding="utf-8").splitlines()
    attributes = (troupe / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert {"local/", ".*.troupe~"} <= set(ignore)
    assert {"events/** -text", "actors/** -text"} <= set(attributes)
    assert [f["path"] for f in result["files"]] == [".troupe/.gitignore", ".troupe/.gitattributes"]
    assert result["rehearsed"] is False
    assert result["entries"] == []
    assert result["steps"] == []
    assert "change" not in result
    assert "actor" not in result


def test_init_in_a_subdirectory_makes_the_theatre_there(repo: Repo) -> None:
    app = repo.path / "app"
    app.mkdir()
    _init(app, _env(repo))
    assert (app / ".troupe").is_dir()
    assert not (repo.path / ".troupe").exists()


def test_plain_init_needs_no_identity(repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(identity, "load_sources", lambda chain: [])
    _init(repo.path, repo.env)
    assert (repo.path / ".troupe").is_dir()


# Requirement: Init refuses where a theatre already exists


def test_a_theatre_here_is_refused_and_left_as_it_was(repo: Repo) -> None:
    _init(repo.path, _env(repo))
    before = _tree(repo.path)
    error = _refused(repo.path, _env(repo))
    assert error.code == "theatre.exists"
    assert error.path == str(repo.path.absolute())
    assert error.details == {"theatre": str(repo.path.absolute()), "directory": True}
    assert _tree(repo.path) == before


def test_a_theatre_above_is_refused_naming_its_root_and_nothing_is_made_below(
    repo: Repo,
) -> None:
    _init(repo.path, _env(repo))
    src = repo.path / "src"
    src.mkdir()
    error = _refused(src, _env(repo), audition={})
    assert error.code == "theatre.exists"
    assert error.details["theatre"] == str(repo.path.absolute())
    assert not (src / ".troupe").exists()


def test_a_file_named_troupe_in_the_way_is_refused_and_left_alone(repo: Repo) -> None:
    (repo.path / ".troupe").write_bytes(b"notes\n")
    error = _refused(repo.path, _env(repo))
    assert error.code == "theatre.exists"
    assert error.details == {"theatre": str(repo.path.absolute()), "directory": False}
    assert "isn't a directory" in error.problem
    assert (repo.path / ".troupe").read_bytes() == b"notes\n"


# Requirement: Init refuses outside a repository


def test_outside_a_repository_init_is_refused_naming_git_init_and_makes_nothing(
    tmp_path: Path,
) -> None:
    directory, env = _outside(tmp_path)
    error = _refused(directory, env, audition={"runner": "scripted"})
    assert error.code == "vcs.not-a-repository"
    assert error.path == str(directory.absolute())
    assert "git init" in error.fix
    assert list(directory.iterdir()) == []


def test_inside_a_repositorys_git_directory_init_is_refused(repo: Repo) -> None:
    error = _refused(repo.path / ".git", _env(repo))
    assert error.code == "vcs.not-a-repository"
    assert not (repo.path / ".git" / ".troupe").exists()


# Requirement: Init with an audition defines a working example actor
# Requirement: An audition records one change, like any other (spec: config)


def test_an_audition_records_one_change_for_lead_with_a_command_cause(repo: Repo) -> None:
    result = _init(repo.path, _env(repo), audition={})
    [event] = git_service(repo).history(aggregate.STREAM)
    assert event.lineage is not None
    assert event.lineage["via"] == "cli"
    assert event.lineage["actor"] == {"kind": "human", "id": "ada@example.com", "source": "env"}
    assert event.lineage["cause"] == {"kind": "command", "id": event.lineage["change"]}
    assert result["change"] == event.lineage["change"]
    assert result["actor"] == {"name": "lead", "runner": "claude-code"}
    paths = {tuple(entry["path"]) for entry in result["entries"]}
    assert ("actors", "lead", "runner") in paths
    assert ("actors", "lead", "expect") in paths
    assert ("actors", "lead", "character") in paths
    assert any(path[:3] == ("actors", "lead", "options") for path in paths)


def test_plain_init_records_no_config_event(repo: Repo) -> None:
    _init(repo.path, _env(repo))
    assert git_service(repo).history(aggregate.STREAM) == []


def test_the_claude_code_audition_writes_its_files_as_config_set_would(repo: Repo) -> None:
    result = _init(repo.path, _env(repo), audition={})
    actors = repo.path / ".troupe" / "actors"
    assert (actors / "lead.md").read_text(encoding="utf-8") == auditions.CHARACTER
    assert [f["path"] for f in result["files"]] == [
        ".troupe/.gitignore",
        ".troupe/.gitattributes",
        ".troupe/actors/lead.md",
        ".troupe/actors/lead.yaml",
    ]
    assert all(f["action"] == "write" for f in result["files"])


# Requirement: The Ollama audition can edit files with a small local model (spec: config;
# local-model-runner design D13)


def test_the_ollama_actor_has_only_a_model_write_effects_no_expect_and_the_character(
    repo: Repo,
) -> None:
    _init(repo.path, _env(repo), audition={"runner": "ollama"})
    lead = read(git_service(repo)).config["actors"]["lead"]
    assert lead == {
        "runner": "ollama",
        "options": {"model": auditions.OLLAMA_AUDITION_MODEL},
        "effects": {"write": ["**"]},
        "expect": [],
        "character": auditions.CHARACTER,
    }
    assert "workspace" not in lead
    assert (repo.path / ".troupe" / "actors" / "lead.md").read_text(encoding="utf-8").strip()


# Requirement: The OpenAI audition can edit files on a small budget (spec: config;
# openai-style-runner design D14)


def test_the_openai_actor_names_its_runtime_and_model_with_small_limits_and_write_effects(
    repo: Repo,
) -> None:
    _init(repo.path, _env(repo), audition={"runner": "openai"})
    lead = read(git_service(repo)).config["actors"]["lead"]
    assert lead == {
        "runner": "openai",
        "runtime": "openai",
        "model": auditions.OPENAI_AUDITION_MODEL,
        "options": {"maxTurns": 10, "maxTotalTokens": 100_000},
        "effects": {"write": ["**"]},
        "expect": [],
        "character": auditions.CHARACTER,
    }
    assert "workspace" not in lead
    assert (repo.path / ".troupe" / "actors" / "lead.md").read_text(encoding="utf-8").strip()


# Requirement: The Claude Code audition can edit files on a small budget (spec: config)


def test_the_claude_code_actor_has_a_small_budget_read_tools_write_effects_and_no_expect(
    repo: Repo,
) -> None:
    _init(repo.path, _env(repo), audition={"runner": "claude-code"})
    lead = read(git_service(repo)).config["actors"]["lead"]
    assert lead == {
        "runner": "claude-code",
        "options": {"maxBudgetUsd": 1, "allowedTools": ["Read", "Glob", "Grep"]},
        "effects": {"write": ["**"]},
        "expect": [],
        "character": auditions.CHARACTER,
    }
    assert "workspace" not in lead
    assert "permissionMode" not in lead["options"]
    assert lead["character"].strip()


# Requirement: The scripted audition runs offline and checks its effect (spec: config)


def test_the_scripted_actor_writes_one_file_checks_it_and_has_no_character(repo: Repo) -> None:
    _init(repo.path, _env(repo), audition={"runner": "scripted"})
    lead = read(git_service(repo)).config["actors"]["lead"]
    assert lead["runner"] == "scripted"
    assert lead["expect"] == [auditions.FILE]
    assert lead["effects"] == {"write": [auditions.FILE]}
    steps = lead["options"]["script"]["steps"]
    assert [next(iter(step)) for step in steps] == ["event", "writeFile", "event"]
    assert steps[1]["writeFile"]["path"] == auditions.FILE
    assert steps[2]["event"]["status"] == "ok"
    assert "character" not in lead
    assert "workspace" not in lead
    assert not (repo.path / ".troupe" / "actors" / "lead.md").exists()


def test_the_scripted_init_event_reports_the_installed_runners_version() -> None:
    lead = auditions.audition("scripted").actor
    init_event = lead["options"]["script"]["steps"][0]["event"]
    assert init_event["runner"] == {
        "name": "scripted",
        "version": version("troupe-runner-scripted"),
    }


# Requirement: The audition's config is valid; every runner has one (design D6)


@pytest.mark.parametrize("runner", sorted(interim.RUNNERS))
def test_every_runner_troupe_knows_has_an_audition_whose_config_is_valid(runner: str) -> None:
    chosen = auditions.audition(runner)
    assert chosen.runner == runner
    check(apply({}, change({}, chosen.operations())))


def test_no_runner_named_means_claude_code() -> None:
    assert auditions.audition(None).runner == "claude-code"


# Requirement: Init's audition runner is named with --runner


def test_an_unknown_runner_is_refused_naming_the_known_ones_and_nothing_is_made(
    repo: Repo,
) -> None:
    error = _refused(repo.path, _env(repo), audition={"runner": "gemini"})
    assert error.code == "runner.unknown"
    assert "gemini" in error.problem
    assert error.details["known"] == ["claude-code", "ollama", "openai", "scripted"]
    assert not (repo.path / ".troupe").exists()


@pytest.mark.parametrize("rehearse", [False, True], ids=["init", "rehearse"])
def test_a_runner_that_isnt_installed_is_refused_naming_its_extra_and_nothing_is_made(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, rehearse: bool
) -> None:
    """cli: "A runner that isn't installed" (runner-extras design D8)."""
    absent = dataclasses.replace(
        interim.RUNNERS["scripted"], package="troupe_runner_lm_studio", in_extra=True
    )
    monkeypatch.setitem(interim.RUNNERS, "lm-studio", absent)
    asked = {"audition": {"runner": "lm-studio"}} | ({"rehearse": True} if rehearse else {})
    error = _refused(repo.path, _env(repo), **asked)
    assert error.code == "runner.not-installed"
    assert error.details["extra"] == "lm-studio"
    assert "troupe-run[lm-studio]" in error.fix
    assert not (repo.path / ".troupe").exists()


# Requirement: An audition needs an identity before it makes anything (spec: config)


def test_an_audition_with_no_identity_is_refused_and_makes_nothing(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(identity, "load_sources", lambda chain: [])
    error = _refused(repo.path, repo.env, audition={})
    assert error.code == "identity.unresolved"
    assert not (repo.path / ".troupe").exists()


def test_an_identity_override_that_isnt_valid_is_refused_and_makes_nothing(repo: Repo) -> None:
    error = _refused(repo.path, {**repo.env, "TROUPE_ACTOR": "ada"}, audition={})
    assert error.code == "identity.invalid-override"
    assert not (repo.path / ".troupe").exists()


# Requirement: Init's result carries its next steps as data (spec: client-protocol)


def test_the_steps_are_commit_allow_the_local_stage_then_perform(repo: Repo) -> None:
    result = _init(repo.path, _env(repo), audition={})
    assert result["steps"] == [
        {"kind": "commit", "paths": [".troupe"]},
        {"kind": "allow-local-stage", "variable": ALLOW_VARIABLE, "value": "true"},
        {
            "kind": "perform",
            "actor": "lead",
            "runner": "claude-code",
            "direction": auditions.DIRECTION,
        },
    ]


def test_the_perform_step_names_the_extra_of_a_runner_in_one(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """client-protocol: "A runner in an extra" (runner-extras design D8)."""
    entry = dataclasses.replace(interim.RUNNERS["scripted"], in_extra=True)
    monkeypatch.setitem(interim.RUNNERS, "lm-studio", entry)
    monkeypatch.setitem(
        auditions.AUDITIONS,
        "lm-studio",
        lambda: {**auditions.AUDITIONS["scripted"](), "runner": "lm-studio"},
    )
    result = _init(repo.path, _env(repo), audition={"runner": "lm-studio"})
    [perform] = [step for step in result["steps"] if step["kind"] == "perform"]
    assert perform["extra"] == "lm-studio"


def test_the_perform_step_of_a_base_runner_has_no_extra(repo: Repo) -> None:
    result = _init(repo.path, _env(repo), audition={"runner": "scripted"})
    [perform] = [step for step in result["steps"] if step["kind"] == "perform"]
    assert "extra" not in perform


def test_no_local_stage_step_when_policy_already_allows_it(repo: Repo) -> None:
    result = _init(repo.path, _env(repo, **{ALLOW_VARIABLE: "true"}), audition={})
    assert [step["kind"] for step in result["steps"]] == ["commit", "perform"]


def test_a_malformed_policy_value_refuses_the_audition_and_makes_nothing(repo: Repo) -> None:
    error = _refused(repo.path, _env(repo, **{ALLOW_VARIABLE: "yes"}), audition={})
    assert error.code == "policy.invalid-value"
    assert not (repo.path / ".troupe").exists()


def test_plain_init_has_no_perform_step(repo: Repo) -> None:
    result = _init(repo.path, _env(repo))
    assert all(step["kind"] != "perform" for step in result["steps"])


# Requirement: Init can be rehearsed


def test_a_rehearsed_audition_reports_its_files_and_entries_and_makes_nothing(
    repo: Repo,
) -> None:
    before = _tree(repo.path)
    result = _init(repo.path, _env(repo), audition={}, rehearse=True)
    assert result["rehearsed"] is True
    assert [f["path"] for f in result["files"]] == [
        ".troupe/.gitignore",
        ".troupe/.gitattributes",
        ".troupe/actors/lead.md",
        ".troupe/actors/lead.yaml",
    ]
    assert {tuple(e["path"])[:2] for e in result["entries"]} == {("actors", "lead")}
    assert "change" not in result
    assert not (repo.path / ".troupe").exists()
    assert _tree(repo.path) == before


def test_rehearsing_where_a_theatre_exists_is_refused_with_theatre_exists(repo: Repo) -> None:
    _init(repo.path, _env(repo))
    error = _refused(repo.path, _env(repo), rehearse=True)
    assert error.code == "theatre.exists"


# A failure part-way leaves nothing that blocks trying again (design D2)


def test_a_failed_record_removes_the_theatre_it_made_so_init_can_run_again(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(*args: object, **kwargs: object) -> None:
        raise OSError("simulated: the disk is full")

    monkeypatch.setattr(init, "record_change", failing)
    with pytest.raises(OSError, match="simulated"):
        asyncio.run(call("init", {"audition": {}}, Session(theatre=repo.path, env=_env(repo))))
    assert not (repo.path / ".troupe").exists()
    monkeypatch.undo()
    _init(repo.path, _env(repo), audition={})
    assert (repo.path / ".troupe" / "actors" / "lead.yaml").is_file()


def test_the_character_file_is_the_characters_text_byte_for_byte(repo: Repo) -> None:
    _init(repo.path, _env(repo), audition={})
    written = (repo.path / ".troupe" / "actors" / "lead.md").read_bytes()
    assert hashlib.sha256(written).digest() == hashlib.sha256(auditions.CHARACTER.encode()).digest()


# Requirement: Init is a protocol command (spec: client-protocol)


def test_an_init_request_that_names_a_path_is_refused_naming_the_field(repo: Repo) -> None:
    error = _refused(repo.path, _env(repo), path="/elsewhere")
    assert error.code == "client.invalid-request"
    assert "path" in error.problem
    assert not (repo.path / ".troupe").exists()
