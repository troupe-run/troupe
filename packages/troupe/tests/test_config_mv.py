"""Renaming an actor or runtime with config mv, end to end through the client protocol (spec:
config-renames, "A rename is one entry naming the old name", "A runtime's rename carries the actors
that name it", "Only a whole actor or runtime can be renamed", "A rename needs its source and
refuses an existing target", "A built-in runtime's name is never renamed to or from"; config-files,
"A rename moves an entity's files as they are"; config-hand-edits, "Config mv on files already moved
records the rename"; config-mv design D5, D7)."""

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
from troupe.core.config.changes import value_hash
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


def _mv(repo: Repo, old: list[str], new: list[str], **extra: Any) -> Any:  # noqa: ANN401
    operation = {"path": new, "renamedFrom": old}
    return _call(repo, "config-set", {"operations": [operation], **extra})


def _config(repo: Repo) -> dict[str, Any]:
    value = _call(repo, "config-get", {})["value"]
    return value if isinstance(value, dict) else {}


def _events(repo: Repo) -> list[Any]:
    return git_service(repo).history(aggregate.STREAM)


def _file(repo: Repo, path: str) -> Path:
    return repo.path / ".troupe" / path


def _refused(repo: Repo, old: list[str], new: list[str]) -> TroupeError:
    before = len(_events(repo))
    with pytest.raises(TroupeError) as caught:
        _mv(repo, old, new)
    assert len(_events(repo)) == before
    return caught.value


# Requirement: A rename is one entry naming the old name


def test_renaming_an_actor_records_one_entry_and_holds_its_values_under_the_new_name(
    repo: Repo,
) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    before = _config(repo)["actors"]["tester"]
    result = _mv(repo, ["actors", "tester"], ["actors", "qa"])
    assert result["entries"] == [
        {
            "path": ["actors", "qa"],
            "renamedFrom": ["actors", "tester"],
            "before": value_hash(before),
        }
    ]
    assert _config(repo)["actors"] == {"qa": before}
    assert len(_events(repo)) == 2


def test_a_reason_is_recorded_with_the_rename(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    _mv(repo, ["actors", "tester"], ["actors", "qa"], reason="clearer name")
    assert _events(repo)[-1].lineage["reason"] == "clearer name"


def test_a_rehearsed_rename_records_nothing_and_writes_nothing(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    result = _mv(repo, ["actors", "tester"], ["actors", "qa"], rehearse=True)
    assert result["entries"][0]["renamedFrom"] == ["actors", "tester"]
    assert len(_events(repo)) == 1
    assert _file(repo, "actors/tester.yaml").is_file()
    assert not _file(repo, "actors/qa.yaml").exists()


def test_events_recorded_before_a_rename_read_as_they_did(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    segments = sorted((repo.path / ".troupe" / "events").rglob("*.jsonl"))
    before = {path: path.read_bytes() for path in segments}
    _mv(repo, ["actors", "tester"], ["actors", "qa"])
    for path, data in before.items():
        assert path.read_bytes()[: len(data)] == data


# Requirement: A runtime's rename carries the actors that name it


def _on_gpu_box(repo: Repo) -> None:
    _set(repo, ["runtimes", "gpu-box"], GPU_BOX)
    for name in ("tester", "reviewer"):
        _set(repo, ["actors", name], {"runner": "openai", "runtime": "gpu-box", "expect": []})


def test_renaming_a_runtime_sets_runtime_on_each_actor_that_names_it_in_the_same_change(
    repo: Repo,
) -> None:
    _on_gpu_box(repo)
    result = _mv(repo, ["runtimes", "gpu-box"], ["runtimes", "gpu"])
    assert [entry["path"] for entry in result["entries"]] == [
        ["actors", "reviewer", "runtime"],
        ["actors", "tester", "runtime"],
        ["runtimes", "gpu"],
    ]
    config = _config(repo)
    assert config["runtimes"] == {"gpu": GPU_BOX}
    assert {actor["runtime"] for actor in config["actors"].values()} == {"gpu"}


# Requirement: Only a whole actor or runtime can be renamed


def test_a_value_path_is_refused_as_not_an_entity(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    error = _refused(repo, ["actors", "tester", "runner"], ["actors", "tester", "model"])
    assert error.code == "config.move-not-entity"
    assert "only actors.<name> and runtimes.<name>" in error.problem


def test_a_rename_across_kinds_is_refused_as_not_keeping_its_kind(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    error = _refused(repo, ["actors", "tester"], ["runtimes", "tester"])
    assert error.code == "config.move-not-entity"
    assert error.details["rule"] == "a rename keeps its kind"


def test_an_invalid_new_name_is_refused_by_the_rule_for_names(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    error = _refused(repo, ["actors", "tester"], ["actors", "Q_A"])
    assert error.code == "config.invalid"
    assert "Q_A" in error.problem


# Requirement: A rename needs its source and refuses an existing target


def test_renaming_an_actor_config_doesnt_have_is_refused(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    assert _refused(repo, ["actors", "ghost"], ["actors", "qa"]).code == (
        "config.move-source-missing"
    )


def test_renaming_onto_an_actor_that_exists_is_refused_and_changes_neither(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    _set(repo, ["actors", "qa"], TESTER)
    before = _config(repo)
    error = _refused(repo, ["actors", "tester"], ["actors", "qa"])
    assert error.code == "config.move-target-exists"
    assert "actors.qa" in error.problem
    assert _config(repo) == before


# Requirement: A built-in runtime's name is never renamed to or from


def test_renaming_a_built_in_runtimes_overrides_is_refused(repo: Repo) -> None:
    _set(repo, ["runtimes", "ollama", "model"], "m")
    error = _refused(repo, ["runtimes", "ollama"], ["runtimes", "gpu"])
    assert error.code == "config.move-built-in"
    assert error.details["runtime"] == "ollama"


def test_renaming_onto_a_built_in_runtimes_name_is_refused(repo: Repo) -> None:
    _set(repo, ["runtimes", "gpu-box"], GPU_BOX)
    error = _refused(repo, ["runtimes", "gpu-box"], ["runtimes", "openai"])
    assert error.code == "config.move-built-in"
    assert error.details["runtime"] == "openai"


# Requirement: A rename moves an entity's files as they are


def test_a_hand_formatted_actors_files_move_byte_for_byte(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    yaml = _file(repo, "actors/tester.yaml")
    yaml.write_text(
        "# the tester, by hand\n\n" + yaml.read_text("utf-8") + "\n# end\n", encoding="utf-8"
    )
    _call(repo, "sync", {})
    held = yaml.read_bytes(), _file(repo, "actors/tester.md").read_bytes()
    _mv(repo, ["actors", "tester"], ["actors", "qa"])
    assert (
        _file(repo, "actors/qa.yaml").read_bytes(),
        _file(repo, "actors/qa.md").read_bytes(),
    ) == (held)
    assert not yaml.exists()
    assert not _file(repo, "actors/tester.md").exists()


def test_a_runtime_renamed_under_its_actors_changes_only_their_runtime_line(repo: Repo) -> None:
    _on_gpu_box(repo)
    tester = _file(repo, "actors/tester.yaml")
    tester.write_text("# mine\n" + tester.read_text("utf-8"), encoding="utf-8")
    _call(repo, "sync", {})
    lines = tester.read_text("utf-8").splitlines()
    runtime = _file(repo, "runtimes/gpu-box.yaml").read_bytes()
    _mv(repo, ["runtimes", "gpu-box"], ["runtimes", "gpu"])
    assert _file(repo, "runtimes/gpu.yaml").read_bytes() == runtime
    after = tester.read_text("utf-8").splitlines()
    assert [a for a, b in zip(after, lines, strict=True) if a != b] == ["runtime: gpu"]


# Requirement: Config mv on files already moved records the rename


def _moved_by_hand(repo: Repo, old: str, new: str) -> None:
    for suffix in (".yaml", ".md"):
        _file(repo, f"actors/{old}{suffix}").rename(_file(repo, f"actors/{new}{suffix}"))


def test_config_mv_on_files_already_moved_records_the_persons_rename_and_writes_nothing(
    repo: Repo,
) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    _moved_by_hand(repo, "tester", "qa")
    held = _file(repo, "actors/qa.yaml").read_bytes()
    result = _mv(repo, ["actors", "tester"], ["actors", "qa"])
    assert result["entries"][0]["renamedFrom"] == ["actors", "tester"]
    *_, renamed = _events(repo)
    assert renamed.lineage["actor"]["kind"] != "unknown"
    assert len(_events(repo)) == 2
    assert _file(repo, "actors/qa.yaml").read_bytes() == held
    assert "tester" not in _config(repo)["actors"]


def test_config_mv_on_files_moved_and_edited_records_the_rename_then_the_edit(
    repo: Repo,
) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    _moved_by_hand(repo, "tester", "qa")
    qa = _file(repo, "actors/qa.yaml")
    qa.write_text(qa.read_text("utf-8").replace("expect:", "workspace: theatre\nexpect:"), "utf-8")
    _mv(repo, ["actors", "tester"], ["actors", "qa"])
    *_, renamed, edited = _events(repo)
    assert renamed.lineage["actor"]["kind"] != "unknown"
    assert edited.lineage["actor"] == {"kind": "unknown"}
    assert _config(repo)["actors"]["qa"]["workspace"] == "theatre"


def test_a_plain_config_mv_still_records_a_hand_edit_to_the_old_files_first(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    yaml = _file(repo, "actors/tester.yaml")
    yaml.write_text(yaml.read_text("utf-8") + "workspace: theatre\n", encoding="utf-8")
    _mv(repo, ["actors", "tester"], ["actors", "qa"])
    *_, edited, renamed = _events(repo)
    assert edited.lineage["actor"] == {"kind": "unknown"}
    assert renamed.lineage["actor"]["kind"] != "unknown"
    assert _config(repo)["actors"]["qa"]["workspace"] == "theatre"


def test_config_mv_on_a_runtime_already_moved_records_only_the_rename_and_moves_its_actors(
    repo: Repo,
) -> None:
    """Review of #505: the actors' files still name the old runtime as troupe last wrote them, so
    they're in line, never read as edits setting it back."""
    _on_gpu_box(repo)
    _file(repo, "runtimes/gpu-box.yaml").rename(_file(repo, "runtimes/gpu.yaml"))
    before = len(_events(repo))
    _mv(repo, ["runtimes", "gpu-box"], ["runtimes", "gpu"])
    events = _events(repo)
    assert len(events) == before + 1
    assert events[-1].lineage["actor"]["kind"] != "unknown"
    config = _config(repo)
    assert config["runtimes"] == {"gpu": GPU_BOX}
    assert {actor["runtime"] for actor in config["actors"].values()} == {"gpu"}
    assert "runtime: gpu\n" in _file(repo, "actors/tester.yaml").read_text("utf-8")


def test_config_mv_on_a_runtime_already_moved_keeps_a_hand_formatted_actor_and_its_lines(
    repo: Repo,
) -> None:
    """Review of #505: an actor file a person formatted still names the old runtime, and its values
    are what config held before the rename, so it's in line: only its runtime line changes."""
    _on_gpu_box(repo)
    tester = _file(repo, "actors/tester.yaml")
    tester.write_text("# mine\n" + tester.read_text("utf-8"), encoding="utf-8")
    _call(repo, "sync", {})
    lines = tester.read_text("utf-8").splitlines()
    _file(repo, "runtimes/gpu-box.yaml").rename(_file(repo, "runtimes/gpu.yaml"))
    before = len(_events(repo))
    _mv(repo, ["runtimes", "gpu-box"], ["runtimes", "gpu"])
    events = _events(repo)
    assert len(events) == before + 1
    assert events[-1].lineage["actor"]["kind"] != "unknown"
    after = tester.read_text("utf-8").splitlines()
    assert [a for a, b in zip(after, lines, strict=True) if a != b] == ["runtime: gpu"]
