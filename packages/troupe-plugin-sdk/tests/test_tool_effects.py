"""Every call is checked against the actor's declared effects before it runs, driven by a fake
model that issues calls the way an engine's tool loop would (spec: runner-tools, "With nothing
declared, an actor is read-only", "Writing needs the write effect", "Deleting and moving need
effects of their own", "A refusal names the effect it needs", "Effects are checked on the path that
would change", "A link can't lead out of the workspace"; #240's "done when")."""

import os
from pathlib import Path

import pytest

from sdk_links import link_directory
from sdk_tools import RUN, FakeModel, call, workspace
from troupe_plugin_sdk.effects import Effects
from troupe_plugin_sdk.events import EventNumbering
from troupe_plugin_sdk.tools import Tools

FILES = {"README.md": b"# hi\n", "src/a.py": b"a = 1\n", "out/old.txt": b"old\n"}


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_with_nothing_declared_reads_and_searches_work_and_every_change_is_refused(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path, FILES)
    before = _snapshot(root)
    model = FakeModel(
        [
            ("Read", {"file_path": "README.md"}),
            ("Glob", {"pattern": "**"}),
            ("Grep", {"pattern": "a"}),
            ("Write", {"file_path": "out/hello.txt", "content": "hello"}),
            ("Edit", {"file_path": "src/a.py", "old_string": "1", "new_string": "2"}),
            ("Delete", {"file_path": "out/old.txt"}),
            ("Move", {"source": "out/old.txt", "destination": "out/new.txt"}),
        ]
    )

    model.drive(Tools(root), EventNumbering(RUN, 65536, next_seq=1))

    assert [is_error for _, is_error in model.seen] == [False] * 3 + [True] * 4
    assert model.seen[0][0] == "1\t# hi"
    assert _snapshot(root) == before


REFUSED = [
    # (declared, tool, input, the effect and path named)
    (
        Effects(),
        "Write",
        {"file_path": "out/a.txt", "content": "x"},
        ("Write", "out/a.txt", "write"),
    ),
    (
        Effects(write=("out/**",)),
        "Edit",
        {"file_path": "src/a.py", "old_string": "1", "new_string": "2"},
        ("Edit", "src/a.py", "write"),
    ),
    (
        Effects(write=("**",)),
        "Delete",
        {"file_path": "out/old.txt"},
        ("Delete", "out/old.txt", "delete"),
    ),
    (
        Effects(write=("**",), delete=("**",)),
        "Move",
        {"source": "out/old.txt", "destination": "out/new.txt"},
        ("Move", "out/old.txt", "move"),
    ),
    (
        Effects(move=("out/**",)),
        "Move",
        {"source": "out/old.txt", "destination": "src/old.txt"},
        ("Move", "src/old.txt", "move"),
    ),
    (
        Effects(delete=("out/**",), move=("out/**",)),
        "Write",
        {"file_path": "out/a.txt", "content": "x"},
        ("Write", "out/a.txt", "write"),
    ),
]


@pytest.mark.parametrize(
    ("effects", "tool", "data", "named"),
    REFUSED,
    ids=[
        "write with nothing declared",
        "edit outside write",
        "delete with only write",
        "move with only write and delete",
        "move to an undeclared destination",
        "write with only delete and move",
    ],
)
def test_a_refused_call_names_the_tool_path_and_effect_and_changes_nothing(
    tmp_path: Path,
    effects: Effects,
    tool: str,
    data: dict[str, object],
    named: tuple[str, str, str],
) -> None:
    root = workspace(tmp_path, FILES)
    before = _snapshot(root)
    model = FakeModel([(tool, data), ("Read", {"file_path": "README.md"})])

    steps = model.drive(Tools(root, effects), EventNumbering(RUN, 65536, next_seq=1))

    name, path, effect = named
    assert steps[0].is_error
    assert steps[0].output.startswith(f"{name} on {path} needs the {effect} effect for {path}")
    assert _snapshot(root) == before
    assert steps[1].is_error is False  # the run goes on


def test_the_refusal_lists_what_the_actor_does_declare(tmp_path: Path) -> None:
    root = workspace(tmp_path, FILES)
    step = call(
        Tools(root, Effects(write=("out/**", "docs/**"))),
        "Write",
        {"file_path": "a", "content": ""},
    )
    assert step.output.endswith("It declares write for: out/**, docs/**.")
    assert call(Tools(root), "Write", {"file_path": "a", "content": ""}).output.endswith(
        "It declares no write paths."
    )


ALLOWED = [
    (Effects(write=("out/**",)), "Write", {"file_path": "out/hello.txt", "content": "hello"}),
    (
        Effects(write=("src/**",)),
        "Edit",
        {"file_path": "src/a.py", "old_string": "1", "new_string": "2"},
    ),
    (Effects(delete=("out/*.txt",)), "Delete", {"file_path": "out/old.txt"}),
    (
        Effects(move=("out/**",)),
        "Move",
        {"source": "out/old.txt", "destination": "out/older/old.txt"},
    ),
]


@pytest.mark.parametrize(
    ("effects", "tool", "data"), ALLOWED, ids=["write", "edit", "delete", "move"]
)
def test_each_change_is_carried_out_where_its_effect_is_declared(
    tmp_path: Path, effects: Effects, tool: str, data: dict[str, object]
) -> None:
    root = workspace(tmp_path, FILES)
    before = _snapshot(root)
    step = call(Tools(root, effects), tool, data)
    assert step.is_error is False, step.output
    assert _snapshot(root) != before


def test_a_write_through_a_link_is_checked_on_the_path_it_would_change(tmp_path: Path) -> None:
    root = workspace(tmp_path, FILES)
    link_directory(root / "out" / "link", root / "src")

    step = call(
        Tools(root, Effects(write=("out/**",))),
        "Write",
        {"file_path": "out/link/a.py", "content": "x"},
    )

    assert step.is_error
    assert step.output.startswith("Write on src/a.py needs the write effect for src/a.py")
    assert (root / "src" / "a.py").read_bytes() == b"a = 1\n"


LINK_CALLS = [
    ("Read", {"file_path": "notes/a.txt"}),
    ("Write", {"file_path": "notes/a.txt", "content": "x"}),
    ("Edit", {"file_path": "notes/a.txt", "old_string": "s", "new_string": "t"}),
    ("Glob", {"pattern": "*", "path": "notes"}),
    ("Grep", {"pattern": "s", "path": "notes"}),
    ("Delete", {"file_path": "notes/a.txt"}),
    ("Move", {"source": "notes/a.txt", "destination": "b.txt"}),
    ("Move", {"source": "README.md", "destination": "notes/b.txt"}),
]


@pytest.mark.parametrize(
    ("tool", "data"), LINK_CALLS, ids=[f"{t} {sorted(d)}" for t, d in LINK_CALLS]
)
def test_a_link_out_of_the_workspace_is_refused_for_every_tool_whatever_is_declared(
    tmp_path: Path, tool: str, data: dict[str, object]
) -> None:
    root = workspace(tmp_path, FILES)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_bytes(b"secret")
    link_directory(root / "notes", outside)
    everything = Effects(write=("**",), delete=("**",), move=("**",))

    step = call(Tools(root, everything), tool, data)

    assert step.is_error
    assert "leads outside the workspace" in step.output
    assert sorted(p.name for p in outside.iterdir()) == ["a.txt"]
    assert (outside / "a.txt").read_bytes() == b"secret"
    assert "secret" not in step.output


def test_searching_the_whole_workspace_leaves_out_files_behind_a_link_out(tmp_path: Path) -> None:
    root = workspace(tmp_path, FILES)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_bytes(b"secret")
    link_directory(root / "notes", outside)
    tools = Tools(root)
    assert "notes/" not in call(tools, "Glob", {"pattern": "**"}).output
    assert "secret" not in call(tools, "Grep", {"pattern": "secret"}).output


def test_a_write_into_git_is_refused_whatever_is_declared(tmp_path: Path) -> None:
    root = workspace(tmp_path, {**FILES, ".git/config": b"[core]\n"})
    step = call(
        Tools(root, Effects(write=("**",))), "Write", {"file_path": ".git/config", "content": "x"}
    )
    assert step.is_error
    assert ".git" in step.output
    assert (root / ".git" / "config").read_bytes() == b"[core]\n"


def test_searching_never_descends_into_a_directory_that_reads_as_a_junction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # os.walk(followlinks=False) descends into a Windows junction, since it isn't a symbolic link.
    # This makes a plain directory read as a junction, so the check runs on every platform; the
    # link tests above cover a real junction on Windows.
    root = workspace(tmp_path, {**FILES, "notes/a.txt": b"secret"})
    real = os.path.isjunction
    monkeypatch.setattr(os.path, "isjunction", lambda p: Path(p).name == "notes" or real(p))
    tools = Tools(root)
    assert "notes/" not in call(tools, "Glob", {"pattern": "**"}).output
    assert "secret" not in call(tools, "Grep", {"pattern": "secret"}).output
