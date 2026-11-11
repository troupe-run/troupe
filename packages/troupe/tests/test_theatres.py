"""The git theatres the tests build: each test owns its repository and HOME, and a theatre looks to
git as a fresh build does, however the helpers make it (theatre-template-and-guard-xdist design
D3)."""

from pathlib import Path

from gitrepo import make_repo
from runtesting import theatre
from test_run_workspaces import committed


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


def test_a_repository_starts_on_the_branch_and_ref_format_it_was_asked_for(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path, branch="trunk")

    assert repo.git("symbolic-ref", "HEAD") == "refs/heads/trunk\n"
    assert not (repo.path / ".git" / "reftable").exists()  # files refs, not reftable
