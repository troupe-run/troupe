"""Every path a tool takes is checked the same way on every platform (spec: runner-tools, "Paths are
workspace-relative", "A link can't lead out of the workspace", "The repository's metadata is out of
reach", "Effects are checked on the path that would change"; runner-sdk design D6)."""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sdk_links import link_directory
from troupe_plugin_sdk.paths import PathRefusedError, Workspace, parts_of


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_bytes(b"print('a')\n")
    return Workspace(root)


REFUSED = [
    ("", "empty"),
    ("/etc/passwd", "absolute"),
    ("src/../../secret.txt", "'..'"),
    ("..", "'..'"),
    ("src\\main.py", "Use /"),
    ("C:/Windows/win.ini", "colon"),
    ("notes.txt:hidden", "colon"),
    ("src/a\x00.py", "control character"),
    ("src/a\n.py", "control character"),
    ("CON", "reserves"),
    ("out/nul.txt", "reserves"),
    ("out/com1.log", "reserves"),
    ("out/name.", "dot or a space"),
    ("out/name ", "dot or a space"),
]


@pytest.mark.parametrize(("path", "problem"), REFUSED, ids=[repr(p) for p, _ in REFUSED])
def test_each_refused_form_is_refused_naming_the_problem(
    workspace: Workspace, path: str, problem: str
) -> None:
    with pytest.raises(PathRefusedError) as refused:
        workspace.path(path)
    assert problem in refused.value.problem
    assert refused.value.path == path


def test_dot_parts_and_repeated_slashes_are_dropped(workspace: Workspace) -> None:
    checked = workspace.path("./src//./a.py")
    assert checked.relative == "src/a.py"
    assert checked.absolute == workspace.root / "src" / "a.py"


def test_a_path_that_names_the_workspace_itself_is_refused_for_a_file(workspace: Workspace) -> None:
    with pytest.raises(PathRefusedError, match="the workspace itself"):
        workspace.path(".")


def test_a_search_may_start_at_the_workspace_itself(workspace: Workspace) -> None:
    assert workspace.path(".", directory=True).relative == ""


@pytest.mark.parametrize("path", [".git/config", ".GIT/config", ".git", "./.git/HEAD"])
def test_a_path_into_git_is_refused_in_any_case(workspace: Workspace, path: str) -> None:
    with pytest.raises(PathRefusedError, match=r"\.git"):
        workspace.path(path)


def test_a_git_directory_deeper_down_is_an_ordinary_path(workspace: Workspace) -> None:
    assert workspace.path("vendor/.git/config").relative == "vendor/.git/config"


def test_a_link_out_of_the_workspace_is_refused(workspace: Workspace, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_bytes(b"secret")
    link_directory(workspace.root / "notes", outside)

    with pytest.raises(PathRefusedError, match="outside the workspace"):
        workspace.path("notes/a.txt")
    with pytest.raises(PathRefusedError, match="outside the workspace"):
        workspace.path("notes/new.txt")


def test_a_link_inside_the_workspace_is_checked_by_where_it_leads(workspace: Workspace) -> None:
    (workspace.root / "out").mkdir()
    link_directory(workspace.root / "out" / "link", workspace.root / "src")

    checked = workspace.path("out/link/a.py")

    assert checked.relative == "src/a.py"
    assert checked.given == "out/link/a.py"


def test_a_link_into_git_is_refused(workspace: Workspace) -> None:
    (workspace.root / ".git").mkdir()
    link_directory(workspace.root / "meta", workspace.root / ".git")
    with pytest.raises(PathRefusedError, match=r"\.git"):
        workspace.path("meta/config")


def test_a_path_that_doesnt_exist_yet_resolves_inside_the_workspace(workspace: Workspace) -> None:
    checked = workspace.path("out/new/a.txt")
    assert checked.relative == "out/new/a.txt"
    assert checked.absolute == workspace.root / "out" / "new" / "a.txt"


PARTS = st.sampled_from(["src", "a.py", ".", "..", "", "x y", "é", "*", "-", "_"])


@given(st.lists(PARTS, min_size=1, max_size=6).map("/".join))
def test_no_accepted_path_resolves_outside_the_workspace(text: str) -> None:
    # A property over the syntax rules: whatever mix of parts is generated, a path either is refused
    # or lands inside the workspace. The workspace is the package's own tests directory, which
    # exists on every machine, and nothing is created.
    root = Workspace(Path(__file__).parent)
    try:
        checked = root.path(text)
    except PathRefusedError:
        return
    assert checked.absolute.is_relative_to(root.root)
    assert ".." not in parts_of(text)
