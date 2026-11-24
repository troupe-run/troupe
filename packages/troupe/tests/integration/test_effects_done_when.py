"""#241's done-when, through troupe perform with the scripted runner's tool steps as the fake model:
an actor with no declared effects can read but not write; one that declares write paths writes
only there; deleting and moving each work only where they're declared (spec: effects; spec:
runner-tools; spec: stages, "The effect check is not enforcement"; declared-effects design D9)."""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from runtesting import INIT, OK, Harness, request, script, theatre
from troupe.core.client import messages as m
from troupe.core.runners import host
from troupe_plugin_sdk import runner as p

LOCAL = {
    "name": "local",
    "effects": "unenforced",
    "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
}


def _tool(name: str, input_: dict[str, Any], *, refused: bool) -> dict[str, Any]:
    return {"tool": {"name": name, "input": input_, "isError": refused}}


def _harness(tmp_path: Path) -> Harness:
    harness = Harness(theatre(tmp_path))
    for relative, data in {"README.md": b"read me\n", "drafts/a.md": b"draft\n"}.items():
        path = harness.repo.path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    harness.repo.commit_all("files")
    return harness


def _perform(harness: Harness, steps: list[dict[str, Any]], effects: dict[str, list[str]]) -> Any:  # noqa: ANN401
    return harness.perform(request(script(INIT, *steps, OK), effects=effects)).run


def _tool_results(harness: Harness, run_id: str) -> list[bool]:
    """Whether each tool call's result was an error, as troupe logs shows them."""
    logged = [e for e in harness.logs(run=run_id).log if isinstance(e, m.LoggedEvent)]
    return [e.event.is_error for e in logged if isinstance(e.event, p.ToolResultEvent)]


def _unenforced(harness: Harness, run_id: str) -> bool:
    records = list(harness.stores[0].history(UUID(run_id)))
    lineages = [record.lineage for record in records]
    return bool(lineages) and all(
        lineage is not None and lineage["stage"] == LOCAL for lineage in lineages
    )


def test_an_actor_with_nothing_declared_can_read_but_not_write(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run = _perform(
        harness,
        [
            _tool("Read", {"file_path": "README.md"}, refused=False),
            _tool("Grep", {"pattern": "draft"}, refused=False),
            _tool("Write", {"file_path": "out/a.txt", "content": "x"}, refused=True),
            _tool(
                "Edit",
                {"file_path": "README.md", "old_string": "read", "new_string": "r"},
                refused=True,
            ),
        ],
        {},
    )
    assert run.outcome == "succeeded", run.to_data().get("error")
    assert _tool_results(harness, run.run_id) == [False, False, True, True]
    assert not (harness.repo.path / "out").exists()
    assert (harness.repo.path / "README.md").read_bytes() == b"read me\n"
    assert _unenforced(harness, run.run_id)


def test_an_actor_that_declares_write_paths_writes_only_there(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run = _perform(
        harness,
        [
            _tool("Write", {"file_path": "out/a.txt", "content": "x"}, refused=False),
            _tool("Write", {"file_path": "src/a.py", "content": "x"}, refused=True),
            _tool("Delete", {"file_path": "out/a.txt"}, refused=True),
            _tool("Move", {"source": "out/a.txt", "destination": "out/b.txt"}, refused=True),
        ],
        {"write": ["out/**"]},
    )
    assert run.outcome == "succeeded", run.to_data().get("error")
    assert (harness.repo.path / "out" / "a.txt").read_bytes() == b"x"
    assert not (harness.repo.path / "src" / "a.py").exists()
    assert _unenforced(harness, run.run_id)


def test_an_actor_deletes_only_where_it_declares_delete(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run = _perform(
        harness,
        [
            _tool("Delete", {"file_path": "README.md"}, refused=True),
            _tool("Delete", {"file_path": "drafts/a.md"}, refused=False),
            _tool("Write", {"file_path": "drafts/b.md", "content": "x"}, refused=True),
        ],
        {"delete": ["drafts/**"]},
    )
    assert run.outcome == "succeeded", run.to_data().get("error")
    assert not (harness.repo.path / "drafts" / "a.md").exists()
    assert (harness.repo.path / "README.md").exists()
    assert _unenforced(harness, run.run_id)


def test_an_actor_moves_only_where_it_declares_move(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run = _perform(
        harness,
        [
            _tool("Move", {"source": "drafts/a.md", "destination": "docs/a.md"}, refused=True),
            _tool(
                "Move", {"source": "drafts/a.md", "destination": "drafts/old/a.md"}, refused=False
            ),
            _tool("Delete", {"file_path": "drafts/old/a.md"}, refused=True),
        ],
        {"move": ["drafts/**"]},
    )
    assert run.outcome == "succeeded", run.to_data().get("error")
    assert (harness.repo.path / "drafts" / "old" / "a.md").read_bytes() == b"draft\n"
    assert not (harness.repo.path / "docs").exists()
    assert _unenforced(harness, run.run_id)


def test_a_write_outside_the_workspace_passes_the_audit_and_is_still_unenforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A write outside the workspace isn't the audit's to see on the local stage (spec: effects).
    # The run's scratch directory is pinned to a known place, outside the theatre, so the script
    # can name it.
    harness = _harness(tmp_path)
    outside = tmp_path / "outside-the-workspace"
    outside.mkdir()
    monkeypatch.setattr(host, "make_scratch", lambda root=None: outside)
    note = str(outside / "home-note.txt")
    run = _perform(
        harness,
        [_tool("Write", {"file_path": note, "content": "x"}, refused=False)],
        {},
    )
    assert run.outcome == "succeeded", run.to_data().get("error")
    assert _unenforced(harness, run.run_id)
