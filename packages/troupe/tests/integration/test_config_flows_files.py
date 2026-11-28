"""A flow's config file end to end through the client protocol: written, swept after a hand edit,
removed, and moved or rewritten by renames (spec: config-files, "Each flow is projected to its own
file"; config-renames, "An actor's rename carries the flows that name it"; flows, "A flow is a
config kind of its own")."""

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


def _config(repo: Repo) -> dict[str, Any]:
    value = _call(repo, "config-get", {})["value"]
    return value if isinstance(value, dict) else {}


def _flow_file(repo: Repo, name: str = "review") -> Path:
    return repo.path / ".troupe" / "flows" / f"{name}.yaml"


def _with_a_flow(repo: Repo) -> None:
    _set(repo, ["actors", "writer"], TESTER)
    _set(repo, ["actors", "reviewer"], TESTER)
    _set(
        repo,
        ["flows", "review"],
        {"steps": [{"actor": "writer"}, {"actor": "reviewer", "direction": "review it"}]},
    )


def test_setting_a_flow_writes_its_file_with_its_steps_in_order(repo: Repo) -> None:
    _with_a_flow(repo)
    text = _flow_file(repo).read_text(encoding="utf-8")
    assert "config/flow.schema.json" in text
    assert text.index("actor: writer") < text.index("actor: reviewer")
    assert "direction: review it" in text


def test_a_hand_edit_to_a_flow_is_swept_with_an_unknown_actor_and_the_file(repo: Repo) -> None:
    _with_a_flow(repo)
    path = _flow_file(repo)
    path.write_text(path.read_text(encoding="utf-8") + "  - actor: writer\n", encoding="utf-8")
    steps = _config(repo)["flows"]["review"]["steps"]
    assert [step["actor"] for step in steps] == ["writer", "reviewer", "writer"]
    swept = git_service(repo).history(aggregate.STREAM)[-1].lineage or {}
    assert swept["actor"] == {"kind": "unknown"}
    assert swept["vcs"]["source"]["path"] == ".troupe/flows/review.yaml"


def test_unsetting_a_flow_removes_its_file(repo: Repo) -> None:
    _with_a_flow(repo)
    _call(repo, "config-set", {"operations": [{"path": ["flows", "review"], "unset": True}]})
    assert not _flow_file(repo).exists()


def test_renaming_a_flow_moves_its_file(repo: Repo) -> None:
    _with_a_flow(repo)
    before = _flow_file(repo).read_bytes()
    _call(
        repo,
        "config-set",
        {"operations": [{"path": ["flows", "check"], "renamedFrom": ["flows", "review"]}]},
    )
    assert not _flow_file(repo).exists()
    assert _flow_file(repo, "check").read_bytes() == before


def test_renaming_an_actor_rewrites_the_flow_that_names_it_in_the_same_change(repo: Repo) -> None:
    _with_a_flow(repo)
    result = _call(
        repo,
        "config-set",
        {"operations": [{"path": ["actors", "author"], "renamedFrom": ["actors", "writer"]}]},
    )
    assert ["flows", "review", "steps"] in [entry["path"] for entry in result["entries"]]
    assert "actor: author" in _flow_file(repo).read_text(encoding="utf-8")
    assert [s["actor"] for s in _config(repo)["flows"]["review"]["steps"]] == ["author", "reviewer"]


def test_unsetting_an_actor_a_flow_names_is_refused_naming_the_flow(repo: Repo) -> None:
    _with_a_flow(repo)
    from troupe.core.errors import TroupeError

    with pytest.raises(TroupeError) as caught:
        _call(repo, "config-set", {"operations": [{"path": ["actors", "writer"], "unset": True}]})
    assert caught.value.code == "config.invalid"
    assert caught.value.details["path"] == ["flows", "review", "steps"]
