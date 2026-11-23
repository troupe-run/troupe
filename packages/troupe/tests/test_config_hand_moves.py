"""Hand moves: an actor's or runtime's files moved by hand are a rename when their values are the
same (spec: config-hand-edits, "A hand move with the same values is a rename", "A hand move with
different values is a removal and an addition", "An ambiguous hand move is refused", "Config mv
on files already moved records the rename", "Adding or deleting a file adds or removes what it
held"; config-mv design D6)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from configtesting import TESTER
from gitrepo import Repo, make_repo
from storetesting import ADA, git_service
from troupe.core.client.dispatch import call
from troupe.core.client.session import Session
from troupe.core.config import aggregate
from troupe.core.errors import TroupeError

GPU_BOX: dict[str, Any] = {"endpoint": "http://127.0.0.1:11434/v1", "model": "m"}


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    made = make_repo(tmp_path, "theatre")
    (made.path / ".troupe").mkdir()
    return made


def _call(repo: Repo, method: str, params: dict[str, Any]) -> Any:  # noqa: ANN401
    session = Session(theatre=repo.path, env=dict(ADA))
    return asyncio.run(call(method, params, session, lambda _: None))


def _set(repo: Repo, path: list[str], value: object) -> Any:  # noqa: ANN401
    return _call(repo, "config-set", {"operations": [{"path": path, "value": value}]})


def _sync(repo: Repo) -> Any:  # noqa: ANN401
    return _call(repo, "sync", {})


def _config(repo: Repo) -> dict[str, Any]:
    value = _call(repo, "config-get", {})["value"]
    return value if isinstance(value, dict) else {}


def _events(repo: Repo) -> list[Any]:
    return git_service(repo).history(aggregate.STREAM)


def _file(repo: Repo, path: str) -> Path:
    return repo.path / ".troupe" / path


def _move(repo: Repo, old: str, new: str, *, kind: str = "actors") -> None:
    suffixes = (".yaml", ".md") if kind == "actors" else (".yaml",)
    for suffix in suffixes:
        source = _file(repo, f"{kind}/{old}{suffix}")
        if source.exists():
            source.rename(_file(repo, f"{kind}/{new}{suffix}"))


def _codes(result: dict[str, Any]) -> list[str]:
    return [notice["code"] for notice in result["notices"]]


def _entries(event: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    from troupe.core import strict_json

    state = strict_json.loads(event.state)
    assert isinstance(state, dict)
    entries = state["changes"]
    assert isinstance(entries, list)
    return entries


# Requirement: A hand move with the same values is a rename


def test_an_actor_moved_by_hand_is_one_rename_by_the_unknown_author(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    before = _config(repo)["actors"]["tester"]
    _move(repo, "tester", "qa")
    result = _sync(repo)
    assert len(_events(repo)) == 2
    *_, moved = _events(repo)
    assert moved.lineage["actor"] == {"kind": "unknown"}
    assert moved.lineage["vcs"]["source"]["path"] == ".troupe/actors/qa.yaml"
    [entry] = _entries(moved)
    assert entry["renamedFrom"] == ["actors", "tester"]
    assert entry["path"] == ["actors", "qa"]
    assert _codes(result) == ["config.hand-move-recorded"]
    notice = result["notices"][0]["details"]
    assert (notice["from"], notice["to"]) == ("actors.tester", "actors.qa")
    assert result["files"] == []
    assert _config(repo)["actors"] == {"qa": before}


def test_a_second_sync_after_a_hand_move_records_nothing(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    _move(repo, "tester", "qa")
    _sync(repo)
    _sync(repo)
    assert len(_events(repo)) == 2


def test_formatting_changed_while_moving_doesnt_count(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    _move(repo, "tester", "qa")
    qa = _file(repo, "actors/qa.yaml")
    text = qa.read_text("utf-8").splitlines()
    lines = [line for line in text if not line.startswith("$schema")]
    runner = next(line for line in lines if line.startswith("runner:"))
    lines = [line for line in lines if line != runner] + ['runner: "scripted"  # quoted']
    qa.write_text("# moved by hand\n" + "\n".join(lines) + "\n", encoding="utf-8")
    _sync(repo)
    *_, moved = _events(repo)
    assert [entry.get("renamedFrom") for entry in _entries(moved)] == [["actors", "tester"]]
    assert len(_events(repo)) == 2


def test_a_runtime_moved_by_hand_carries_its_actors_and_writes_back_only_their_runtime_line(
    repo: Repo,
) -> None:
    _set(repo, ["runtimes", "gpu-box"], GPU_BOX)
    _set(repo, ["actors", "tester"], {"runner": "openai", "runtime": "gpu-box", "expect": []})
    tester = _file(repo, "actors/tester.yaml")
    tester.write_text("# mine\n" + tester.read_text("utf-8"), encoding="utf-8")
    _sync(repo)
    lines = tester.read_text("utf-8").splitlines()
    _move(repo, "gpu-box", "gpu", kind="runtimes")
    _sync(repo)
    *_, moved = _events(repo)
    assert moved.lineage["actor"] == {"kind": "unknown"}
    assert [entry["path"] for entry in _entries(moved)] == [
        ["actors", "tester", "runtime"],
        ["runtimes", "gpu"],
    ]
    after = tester.read_text("utf-8").splitlines()
    assert [a for a, b in zip(after, lines, strict=True) if a != b] == ["runtime: gpu"]


def test_a_built_in_runtimes_file_moved_is_a_removal_and_an_addition(repo: Repo) -> None:
    _set(repo, ["runtimes", "ollama"], {"endpoint": "http://127.0.0.1:11434", "model": "m"})
    _move(repo, "ollama", "gpu", kind="runtimes")
    result = _sync(repo)
    assert "config.move-not-detected" in _codes(result)
    [notice] = [n for n in result["notices"] if n["code"] == "config.move-not-detected"]
    assert notice["details"]["reason"] == "built-in"
    assert all("renamedFrom" not in e for event in _events(repo) for e in _entries(event))
    assert set(_config(repo)["runtimes"]) == {"gpu"}


def test_files_moved_and_moved_back_before_a_sync_record_nothing(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    _move(repo, "tester", "qa")
    _move(repo, "qa", "tester")
    _sync(repo)
    assert len(_events(repo)) == 1


def test_files_moved_back_after_a_sync_are_a_rename_back(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    _move(repo, "tester", "qa")
    _sync(repo)
    _move(repo, "qa", "tester")
    _sync(repo)
    *_, back = _events(repo)
    assert back.lineage["actor"] == {"kind": "unknown"}
    assert [entry.get("renamedFrom") for entry in _entries(back)] == [["actors", "qa"]]
    assert set(_config(repo)["actors"]) == {"tester"}


# Requirement: A hand move with different values is a removal and an addition


def test_files_moved_and_edited_are_a_removal_and_an_addition_with_a_notice(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    _move(repo, "tester", "qa")
    qa = _file(repo, "actors/qa.yaml")
    qa.write_text(qa.read_text("utf-8") + "workspace: theatre\n", encoding="utf-8")
    result = _sync(repo)
    [notice] = [n for n in result["notices"] if n["code"] == "config.move-not-detected"]
    assert notice["details"] == {
        "removed": ["actors.tester"],
        "added": ["actors.qa"],
        "reason": "values differ",
    }
    assert "troupe config mv" in notice["fix"]
    assert all("renamedFrom" not in e for event in _events(repo) for e in _entries(event))
    assert set(_config(repo)["actors"]) == {"qa"}


# Requirement: An ambiguous hand move is refused


def test_two_identical_actors_moved_at_once_are_refused_naming_the_files(repo: Repo) -> None:
    _set(repo, ["actors", "a"], TESTER)
    _set(repo, ["actors", "b"], TESTER)
    _move(repo, "a", "x")
    _move(repo, "b", "y")
    with pytest.raises(TroupeError) as caught:
        _sync(repo)
    assert caught.value.code == "config.move-ambiguous"
    assert caught.value.details["files"] == [
        ".troupe/actors/a.yaml",
        ".troupe/actors/b.yaml",
        ".troupe/actors/x.yaml",
        ".troupe/actors/y.yaml",
    ]
    assert "troupe config mv" in caught.value.fix
    assert len(_events(repo)) == 2


def test_one_actor_copied_to_two_names_and_deleted_is_refused(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    for name in ("qa", "qa2"):
        for suffix in (".yaml", ".md"):
            data = _file(repo, f"actors/tester{suffix}").read_bytes()
            _file(repo, f"actors/{name}{suffix}").write_bytes(data)
    for suffix in (".yaml", ".md"):
        _file(repo, f"actors/tester{suffix}").unlink()
    with pytest.raises(TroupeError) as caught:
        _sync(repo)
    assert caught.value.code == "config.move-ambiguous"
    assert len(_events(repo)) == 1


# Requirement: Config mv on files already moved records the rename


def test_config_mv_is_the_way_out_of_an_ambiguous_move(repo: Repo) -> None:
    _set(repo, ["actors", "a"], TESTER)
    _set(repo, ["actors", "b"], TESTER)
    _move(repo, "a", "x")
    _move(repo, "b", "y")
    operation = {"path": ["actors", "x"], "renamedFrom": ["actors", "a"]}
    _call(repo, "config-set", {"operations": [operation]})
    *_, person, unknown = _events(repo)
    assert person.lineage["actor"]["kind"] != "unknown"
    assert [e.get("renamedFrom") for e in _entries(person)] == [["actors", "a"]]
    assert unknown.lineage["actor"] == {"kind": "unknown"}
    assert [e.get("renamedFrom") for e in _entries(unknown)] == [["actors", "b"]]
    assert set(_config(repo)["actors"]) == {"x", "y"}


# Requirement: Adding or deleting a file adds or removes what it held ("A character left without
# its actor")


def test_a_yaml_moved_without_its_md_is_refused_saying_to_move_both(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    _file(repo, "actors/tester.yaml").rename(_file(repo, "actors/qa.yaml"))
    with pytest.raises(TroupeError) as caught:
        _sync(repo)
    assert caught.value.code == "config.file-invalid"
    assert "move this file with its .yaml" in caught.value.fix
    assert "troupe config mv" in caught.value.fix
    assert len(_events(repo)) == 1


def test_a_yaml_deleted_with_no_actor_arriving_keeps_the_old_fix(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    _file(repo, "actors/tester.yaml").unlink()
    with pytest.raises(TroupeError) as caught:
        _sync(repo)
    assert "troupe config mv" not in caught.value.fix
