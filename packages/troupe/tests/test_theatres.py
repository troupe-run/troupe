"""The git theatres the tests build: each test owns its repository and HOME, and a theatre looks to
git as a fresh build does, however the helpers make it (theatre-template-and-guard-xdist design
D3)."""

import json
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import gitrepo
from gitrepo import COUNTS_VARIABLE, Repo, counts, from_template, make_repo
from runtesting import build_committed, committed, theatre

pytest_plugins = ["pytester"]

TESTS = Path(__file__).resolve().parent


def test_a_committed_theatre_has_a_clean_status_and_no_stat_dirty_files(tmp_path: Path) -> None:
    repo = committed(tmp_path)

    # diff-files compares the index's stat data with the files and doesn't refresh it, so a file
    # whose stat data the index doesn't match is listed even though its content is unchanged.
    assert repo.git("diff-files", "--name-only") == ""
    assert repo.git("status", "--porcelain") == ""
    assert repo.git("ls-files").split() == [".gitignore", "src/a.txt", "src/b.txt"]


def test_two_repositories_made_in_one_test_are_independent(tmp_path: Path) -> None:
    first = make_repo(tmp_path, "first")
    second = make_repo(tmp_path, "second")

    first.write("only-here.txt", "x\n")
    first.commit_all("first's commit")

    assert first.git("log", "--format=%s") == "first's commit\n"
    assert second.git("status", "--porcelain") == ""
    assert not (second.path / "only-here.txt").exists()
    assert second.git("for-each-ref") == ""


def test_two_committed_theatres_are_independent(tmp_path: Path) -> None:
    first = committed(tmp_path / "one")
    second = committed(tmp_path / "two")
    base = second.git("rev-parse", "HEAD")

    first.write("src/a.txt", "changed\n")
    first.commit_all("change a")

    assert second.git("rev-parse", "HEAD") == base
    assert (second.path / "src" / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert second.git("log", "--format=%s") == "base\n"


def test_each_repository_has_its_own_empty_home(tmp_path: Path) -> None:
    first = make_repo(tmp_path, "first")
    second = theatre(tmp_path / "other")

    homes = [Path(repo.env["HOME"]) for repo in (first, second)]
    assert homes[0] != homes[1]
    for home in homes:
        assert home.is_dir()
        assert list(home.iterdir()) == []


@pytest.mark.parametrize("refs", ["files", "reftable"])
def test_a_repository_starts_on_the_branch_and_ref_format_it_was_asked_for(
    tmp_path: Path, refs: str
) -> None:
    repo = make_repo(tmp_path, branch="trunk", refs=refs)

    assert repo.git("symbolic-ref", "HEAD") == "refs/heads/trunk\n"
    assert (repo.path / ".git" / "reftable").is_dir() == (refs == "reftable")


# A copy against a fresh build of the same shape (design D3)


def _observed(repo: Repo) -> dict[str, Any]:
    """What a test can see of a repository through git, and its .git directory's layout and modes,
    less what differs between any two builds of it: the commit's time (so its SHA, its object's
    name, and how many fan-out directories the objects take) and reftable's table names. Files'
    contents are seen only through git's own answers."""
    git_dir = repo.path / ".git"
    layout: Counter[str] = Counter()
    for path in git_dir.rglob("*"):
        parts = path.relative_to(git_dir).parts
        if path.suffix == ".lock":
            continue  # git's background maintenance holds one for a moment after a commit
        if parts[0] == "objects" and len(parts) == 2 and len(parts[1]) == 2:
            # How many fan-out directories there are follows the objects' names, which differ
            # between builds, so only an empty one is counted: no build makes one (troupe#408).
            if any(path.iterdir()):
                continue
            name = "objects/<fan-out> empty"
        elif parts[0] == "objects" and len(parts) == 3 and len(parts[1]) == 2:
            name = "objects/<fan-out>/<loose object>"
        elif parts[0] == "reftable" and path.suffix == ".ref":
            name = "reftable/<table>"
        else:
            name = "/".join(parts)
        kind = "dir" if path.is_dir() else oct(path.stat().st_mode & 0o777)
        layout[f"{name} {kind}"] += 1
    return {
        "layout": layout,
        "worktree": sorted(
            p.relative_to(repo.path).as_posix()
            for p in repo.path.rglob("*")
            if ".git" not in p.relative_to(repo.path).parts
        ),
        "config": sorted(repo.git("config", "--local", "--list").splitlines()),
        "head": repo.git("symbolic-ref", "HEAD"),
        "refs": repo.git("for-each-ref", "--format=%(refname) %(objecttype) %(tree)"),
        "index": repo.git("ls-files", "-s"),
        "status": repo.git("status", "--porcelain", "--ignored"),
        "stat-dirty": repo.git("diff-files", "--name-only"),
    }


SHAPES: dict[str, tuple[Callable[[Path], Repo], Callable[[Path], Repo]]] = {
    "make_repo-files": (
        lambda root: make_repo(root, refs="files"),
        lambda root: make_repo(root, refs="files", fresh=True),
    ),
    "make_repo-reftable": (
        lambda root: make_repo(root, refs="reftable"),
        lambda root: make_repo(root, refs="reftable", fresh=True),
    ),
    "committed": (committed, lambda root: build_committed(root, "theatre")),
}


@pytest.mark.parametrize("shape", SHAPES)
def test_a_copy_shows_git_what_a_fresh_build_of_its_shape_shows(tmp_path: Path, shape: str) -> None:
    copy_of, build = SHAPES[shape]
    copy_of(tmp_path / "warm")  # the template exists now, so the copy below makes nothing else
    before = counts()

    copied = copy_of(tmp_path / "copied")
    assert counts()["copies"] - before["copies"] == 1  # really a copy, not a second build
    built = build(tmp_path / "built")

    assert _observed(copied) == _observed(built)


def _fan_outs(repo: Repo) -> list[str]:
    return sorted(p.name for p in (repo.path / ".git" / "objects").iterdir() if len(p.name) == 2)


def _loose_objects(repo: Repo) -> int:
    return len(list((repo.path / ".git" / "objects").glob("??/*")))


def _built_at(root: Path, seconds: int, monkeypatch: pytest.MonkeyPatch) -> Repo:
    """``committed()``'s theatre built from scratch, committed at ``seconds`` past the epoch."""
    with monkeypatch.context() as patch:
        for variable in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
            patch.setitem(gitrepo.AUTHOR, variable, f"{seconds} +0000")
        return build_committed(root, "theatre")


def test_two_builds_whose_commits_fall_in_different_fan_out_directories_look_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # committed()'s blobs and trees always have the same names, in four fan-out directories. A
    # commit made at 1700000030 is named 566047d7..., sharing 56/ with one of them; one made at
    # 1700000000 is named c232587f..., in a directory of its own (troupe#408, design D2).
    sharing = _built_at(tmp_path / "sharing", 1_700_000_030, monkeypatch)
    alone = _built_at(tmp_path / "alone", 1_700_000_000, monkeypatch)

    # The premise: if committed()'s contents change, these times may stop giving two layouts, and
    # this fails, naming the counts, rather than passing on two identical ones.
    assert (len(_fan_outs(sharing)), len(_fan_outs(alone))) == (4, 5)
    assert _loose_objects(sharing) == _loose_objects(alone) == 6

    assert _observed(sharing) == _observed(alone)


ONE_BLOB = Path("objects") / "56" / "26abf0f72e58d7a153368ba57db4c673c0e171"
"""src/a.txt's blob ("one\\n") as a loose object, in every committed() theatre."""


def _remove_one_blob(git_dir: Path) -> None:
    (git_dir / ONE_BLOB).chmod(0o644)  # loose objects are read-only, which Windows won't unlink
    (git_dir / ONE_BLOB).unlink()


def _remove_main(git_dir: Path) -> None:
    (git_dir / "refs" / "heads" / "main").unlink()


def _make_an_empty_fan_out(git_dir: Path) -> None:
    assert not (git_dir / "objects" / "00").exists()  # no object of the copy's is named 00...
    (git_dir / "objects" / "00").mkdir()


@pytest.mark.parametrize(
    "alter", [_remove_one_blob, _remove_main, _make_an_empty_fan_out], ids=lambda f: f.__name__
)
def test_a_copy_that_differs_from_a_fresh_build_where_git_looks_compares_unequal(
    tmp_path: Path, alter: Callable[[Path], None]
) -> None:
    # The comparison leaves out what differs between any two builds, and nothing more (design D3).
    copied = committed(tmp_path / "copied")
    built = build_committed(tmp_path / "built", "theatre")
    assert (copied.path / ".git" / ONE_BLOB).is_file()

    alter(copied.path / ".git")

    assert _observed(copied) != _observed(built)


def test_a_lock_file_in_the_template_is_left_out_of_the_copy(tmp_path: Path) -> None:
    def build_with_a_lock(root: Path, name: str) -> Repo:
        repo = build_committed(root, name)
        # As git's background maintenance leaves for a moment after the template's commit.
        (repo.path / ".git" / "objects" / "maintenance.lock").write_text("", encoding="utf-8")
        return repo

    copied = from_template(tmp_path, "theatre", ("with-a-lock",), build_with_a_lock)

    assert not (copied.path / ".git" / "objects" / "maintenance.lock").exists()
    assert (copied.path / ".git" / "objects").is_dir()
    assert copied.git("status", "--porcelain") == ""


def test_a_template_changed_by_mistake_fails_every_copy_naming_the_file(tmp_path: Path) -> None:
    key = ("changed-template",)
    from_template(tmp_path, "first", key, build_committed)
    # Only this test reaches the template, to show what a stray write into it would do.
    (gitrepo._built[key] / "src" / "a.txt").write_text("changed by mistake\n", encoding="utf-8")

    with pytest.raises(AssertionError, match=r"git update-index --refresh failed"):
        from_template(tmp_path, "second", key, build_committed)


# How the repositories are made (design D1, D2, D4)


def test_repositories_of_one_shape_are_counted_as_copies_of_one_template(tmp_path: Path) -> None:
    before = counts()

    make_repo(tmp_path, "first", branch="copied-shape")
    make_repo(tmp_path, "second", branch="copied-shape")

    after = counts()
    assert after["copies"] - before["copies"] == 2
    assert after["templates"] - before["templates"] == 1  # a branch no other test asks for
    assert after["fresh"] == before["fresh"]


def test_a_fresh_repository_is_built_not_copied(tmp_path: Path) -> None:
    before = counts()

    repo = make_repo(tmp_path, fresh=True)

    after = counts()
    assert after["fresh"] - before["fresh"] == 1
    assert after["copies"] == before["copies"]
    assert repo.git("symbolic-ref", "HEAD") == "refs/heads/main\n"


def test_a_session_that_makes_no_repository_makes_no_base_temp(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Making pytest's base temp registers a cleanup of older runs' directories at exit, which a
    # child pytest run that builds no repository shouldn't pay for (design D2).
    temproot = tmp_path / "temproot"
    temproot.mkdir()
    monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", str(temproot))
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")])
    )
    pytester.makepyfile(test_nothing="def test_nothing():\n    pass\n")

    result = pytester.runpytest_subprocess("-p", "gitrepo", "-p", "no:cacheprovider")

    result.assert_outcomes(passed=1)
    assert list(temproot.iterdir()) == []


def test_outside_pytest_a_repository_is_built_from_scratch(tmp_path: Path) -> None:
    child = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "import gitrepo\n"
        "repo = gitrepo.make_repo(Path(sys.argv[1]))\n"
        "print(json.dumps(gitrepo.counts()))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", child, str(tmp_path)],
        env={**os.environ, "PYTHONPATH": str(TESTS)},
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(completed.stdout) == {"copies": 0, "fresh": 1, "templates": 0}
    assert (tmp_path / "theatre" / ".git").is_dir()


# The counts, for measuring the templates (design D5)

COUNTED = """
from gitrepo import make_repo


def test_two(tmp_path):
    make_repo(tmp_path, "a")
    make_repo(tmp_path, "b", fresh=True)
"""


@pytest.fixture
def counted(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")])
    )
    monkeypatch.delenv(COUNTS_VARIABLE, raising=False)
    pytester.makepyfile(test_counted=COUNTED)
    return pytester


def test_without_the_counts_variable_no_counts_are_written(counted: pytest.Pytester) -> None:
    result = counted.runpytest_subprocess("-p", "gitrepo", "-p", "no:cacheprovider")

    result.assert_outcomes(passed=1)
    assert not list(counted.path.rglob("theatres-*.json"))


def test_with_the_counts_variable_the_process_writes_its_counts(
    counted: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    directory = tmp_path_factory.mktemp("counts")
    monkeypatch.setenv(COUNTS_VARIABLE, str(directory))

    result = counted.runpytest_subprocess("-p", "gitrepo", "-p", "no:cacheprovider")

    result.assert_outcomes(passed=1)
    [written] = list(directory.glob("theatres-*.json"))
    assert json.loads(written.read_text(encoding="utf-8")) == {
        "copies": 1,
        "fresh": 1,
        "templates": 1,
    }


@pytest.mark.parametrize("value", ["", "no/such/directory"], ids=["empty", "missing"])
def test_a_counts_variable_that_isnt_a_directory_is_refused(
    counted: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(COUNTS_VARIABLE, value)

    result = counted.runpytest_subprocess("-p", "gitrepo", "-p", "no:cacheprovider")

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(
        [f"*{COUNTS_VARIABLE} is {value!r}, which isn't an existing directory.*unset it.*"]
    )


COUNTED_ACROSS_WORKERS = """
from gitrepo import make_repo


def test_one(tmp_path):
    make_repo(tmp_path)


def test_two(tmp_path):
    make_repo(tmp_path)
"""


def test_across_workers_each_worker_that_made_a_repository_writes_its_own_counts(
    counted: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    directory = tmp_path_factory.mktemp("counts")
    monkeypatch.setenv(COUNTS_VARIABLE, str(directory))
    counted.makepyfile(test_counted=COUNTED_ACROSS_WORKERS)

    result = counted.runpytest_subprocess("-p", "gitrepo", "-p", "no:cacheprovider", "-n", "2")

    result.assert_outcomes(passed=2)
    written = [json.loads(f.read_text(encoding="utf-8")) for f in directory.glob("theatres-*.json")]
    # One file per worker that ran a test (the controller makes none, so writes none), and each
    # of those workers built its own template.
    assert 1 <= len(written) <= 2
    assert sum(counts["copies"] for counts in written) == 2
    assert all(counts["templates"] == 1 for counts in written)
