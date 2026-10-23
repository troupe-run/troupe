"""The git adapter's worktree operations, against real repositories (spec: vcs, run-workspaces;
worktree-stage design D2, D4, D5, D6, D10)."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gitrepo import AUTHOR, Repo, make_repo
from troupe.core.errors import TroupeError
from troupe.core.files import clone_file
from troupe.core.vcs import SharedChange
from troupe_vcs_git import GitAdapter

WINDOWS = sys.platform == "win32"


def adapter(repo: Repo, **options: object) -> GitAdapter:
    return GitAdapter(repo.path, source=repo.env, **options)  # type: ignore[arg-type]


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    repo = make_repo(tmp_path)
    put(repo, "src/a.txt", "one\n")
    put(repo, "src/b.txt", "bee\n")
    put(repo, ".troupe/events/x.jsonl", "{}\n")
    put(repo, ".gitignore", "build/\n")
    repo.commit_all("base")
    return repo


def put(repo: Repo, relative: str, text: str) -> Path:
    """Write ``text`` as UTF-8 bytes exactly, so a commit holds LF on every OS (write_text would
    write CRLF on Windows)."""
    path = repo.path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def git_in(repo: Repo, cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],  # noqa: S607
        cwd=cwd,
        env={**repo.env, **AUTHOR},
        capture_output=True,
        check=True,
    )
    return completed.stdout.decode("utf-8")


def worktree(repo: Repo, tmp_path: Path, name: str = "wt") -> tuple[GitAdapter, Path, str]:
    """A filled worktree of ``repo`` at its HEAD, with the baseline its diff is taken from."""
    git = adapter(repo)
    path = repo.path / ".troupe" / "local" / "worktrees" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    base = git.head()
    assert base is not None
    git.add_worktree(path, base)
    filled = git.fill_worktree(path, clone_file, frozenset(git.differing_from_head()))
    return git, path, filled.baseline


def tree_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


# Requirement: The git adapter's worktrees are registered with git and leave its refs alone


def test_making_and_removing_a_worktree_leaves_branches_and_the_worktree_list_as_they_were(
    repo: Repo, tmp_path: Path
) -> None:
    branches, worktrees = repo.git("branch", "--list"), repo.git("worktree", "list")
    git, path, _ = worktree(repo, tmp_path)
    assert repo.git("branch", "--list") == branches
    git.remove_worktree(path)
    assert not path.exists()
    assert repo.git("worktree", "list") == worktrees


def test_removing_a_worktree_whose_directory_was_deleted_by_hand_unregisters_it(
    repo: Repo, tmp_path: Path
) -> None:
    worktrees = repo.git("worktree", "list")
    git, path, _ = worktree(repo, tmp_path)
    shutil.rmtree(path)
    git.remove_worktree(path)
    assert repo.git("worktree", "list") == worktrees


def test_removing_a_directory_that_was_never_registered_removes_it(
    repo: Repo, tmp_path: Path
) -> None:
    path = repo.path / ".troupe" / "local" / "worktrees" / "partial"
    (path / "sub").mkdir(parents=True)
    (path / "sub" / "f.txt").write_text("x", encoding="utf-8")
    adapter(repo).remove_worktree(path)
    assert not path.exists()


# Requirement: A worktree run works in its own worktree at HEAD


def test_a_dirty_theatres_worktree_holds_exactly_heads_files(repo: Repo, tmp_path: Path) -> None:
    put(repo, "src/a.txt", "edited, not committed\n")
    put(repo, "untracked.txt", "new\n")
    (repo.path / "src" / "b.txt").unlink()
    _git, path, _ = worktree(repo, tmp_path)
    assert tree_files(path) == {
        "src/a.txt": b"one\n",
        "src/b.txt": b"bee\n",
        ".troupe/events/x.jsonl": b"{}\n",
        ".gitignore": b"build/\n",
    }
    assert git_in(repo, path, "status", "--porcelain") == ""


def test_the_paths_differing_from_head_are_staged_unstaged_and_untracked_ones(
    repo: Repo,
) -> None:
    put(repo, "src/a.txt", "edited\n")
    put(repo, "new.txt", "new\n")
    repo.git("add", "new.txt")
    put(repo, "loose.txt", "loose\n")
    put(repo, "build/ignored.bin", "ignored\n")
    assert sorted(adapter(repo).differing_from_head()) == ["loose.txt", "new.txt", "src/a.txt"]


def test_files_that_match_head_are_cloned_and_differing_ones_checked_out(
    repo: Repo, tmp_path: Path
) -> None:
    put(repo, "src/a.txt", "edited\n")
    git = adapter(repo)
    path = repo.path / ".troupe" / "local" / "worktrees" / "wt"
    git.add_worktree(path, git.head() or "")
    cloned: list[str] = []

    def recording_clone(source: Path, destination: Path) -> str:
        cloned.append(source.relative_to(repo.path).as_posix())
        return clone_file(source, destination)

    filled = git.fill_worktree(path, recording_clone, frozenset(git.differing_from_head()))
    assert sorted(cloned) == [".gitignore", ".troupe/events/x.jsonl", "src/b.txt"]
    assert (filled.cloned, filled.checked_out) == (3, 1)
    assert filled.mechanisms
    assert (path / "src" / "a.txt").read_bytes() == b"one\n"


def test_a_file_edited_while_it_is_cloned_is_checked_out_again_from_head(
    repo: Repo, tmp_path: Path
) -> None:
    git = adapter(repo)
    path = repo.path / ".troupe" / "local" / "worktrees" / "wt"
    git.add_worktree(path, git.head() or "")

    def editing_clone(source: Path, destination: Path) -> str:
        if source.name == "a.txt":
            source.write_text("edited during the clone\n", encoding="utf-8")
        return clone_file(source, destination)

    git.fill_worktree(path, editing_clone, frozenset())
    assert (path / "src" / "a.txt").read_bytes() == b"one\n"


def test_a_file_missing_from_the_theatre_is_checked_out(repo: Repo, tmp_path: Path) -> None:
    (repo.path / "src" / "b.txt").unlink()
    git = adapter(repo)
    path = repo.path / ".troupe" / "local" / "worktrees" / "wt"
    git.add_worktree(path, git.head() or "")
    filled = git.fill_worktree(path, clone_file, frozenset())  # not told it differs
    assert (path / "src" / "b.txt").read_bytes() == b"bee\n"
    assert filled.checked_out == 1


def test_a_clone_that_fails_falls_back_to_a_checkout(repo: Repo, tmp_path: Path) -> None:
    git = adapter(repo)
    path = repo.path / ".troupe" / "local" / "worktrees" / "wt"
    git.add_worktree(path, git.head() or "")

    def failing_clone(source: Path, destination: Path) -> str:
        return clone_file(source.parent / "no-such-file", destination)

    filled = git.fill_worktree(path, failing_clone, frozenset())
    assert filled.mechanisms == ()
    assert tree_files(path)["src/a.txt"] == b"one\n"


def test_a_file_committed_in_a_form_git_would_normalise_neither_stops_the_fill_nor_is_in_the_diff(
    tmp_path: Path,
) -> None:
    # CRLF committed, then an attribute saying the file is text with CRLF endings: git lists it as
    # modified in every checkout, the theatre's included (found in CI on Windows, 2026-10-23).
    repo = make_repo(tmp_path)
    put(repo, "crlf.txt", "a\r\nb\r\n")
    repo.commit_all("crlf")
    put(repo, ".gitattributes", "*.txt text eol=crlf\n")
    repo.git("add", ".gitattributes")  # only it: add -A would renormalise crlf.txt
    repo.git("commit", "-q", "-m", "attributes")
    (repo.path / "crlf.txt").unlink()
    repo.git("checkout", "--", "crlf.txt")  # a fresh checkout, as a clone or a teammate has
    git = adapter(repo)
    assert git.differing_from_head() == ("crlf.txt",)
    path = repo.path / ".troupe" / "local" / "worktrees" / "wt"
    git.add_worktree(path, git.head() or "")
    filled = git.fill_worktree(path, clone_file, frozenset(git.differing_from_head()))
    captured = git.capture(path, filled.baseline, (".troupe",), tmp_path / "run.diff")
    assert captured.empty
    assert (tmp_path / "run.diff").read_bytes() == b""


# Requirement: The git adapter's diff is git's normalised binary diff


def test_a_capture_counts_added_modified_and_deleted_files_and_its_diff_rebuilds_the_tree(
    repo: Repo, tmp_path: Path
) -> None:
    git, path, base = worktree(repo, tmp_path)
    (path / "out").mkdir()
    (path / "out" / "hello.txt").write_text("hello\n", encoding="utf-8")
    (path / "src" / "a.txt").write_text("two\n", encoding="utf-8")
    (path / "src" / "b.txt").unlink()
    out = tmp_path / "run.diff"
    captured = git.capture(path, base, (".troupe",), out)
    assert (captured.added, captured.modified, captured.deleted) == (
        ("out/hello.txt",),
        ("src/a.txt",),
        ("src/b.txt",),
    )
    expected = tree_files(path)
    other = make_repo(tmp_path, "other")
    head = repo.git("rev-parse", "HEAD").strip()
    git_in(repo, other.path, "fetch", "-q", str(repo.path), head)
    git_in(repo, other.path, "checkout", "-q", head)
    git_in(repo, other.path, "apply", str(out))
    assert tree_files(other.path) == expected


def test_a_binary_file_round_trips_through_the_diff(repo: Repo, tmp_path: Path) -> None:
    git, path, base = worktree(repo, tmp_path)
    data = bytes(range(256)) * 4
    (path / "blob.bin").write_bytes(data)
    out = tmp_path / "run.diff"
    git.capture(path, base, (".troupe",), out)
    git.apply(out)
    assert (repo.path / "blob.bin").read_bytes() == data


def test_a_commit_the_actor_made_in_the_worktree_is_in_the_diff_from_the_base(
    repo: Repo, tmp_path: Path
) -> None:
    git, path, base = worktree(repo, tmp_path)
    (path / "src" / "a.txt").write_text("committed\n", encoding="utf-8")
    git_in(repo, path, "commit", "-qam", "actor")
    (path / "src" / "b.txt").write_text("uncommitted\n", encoding="utf-8")
    captured = git.capture(path, base, (".troupe",), tmp_path / "run.diff")
    assert captured.modified == ("src/a.txt", "src/b.txt")


def test_an_ignored_file_is_left_out_of_the_diff(repo: Repo, tmp_path: Path) -> None:
    git, path, base = worktree(repo, tmp_path)
    (path / "build").mkdir()
    (path / "build" / "out.bin").write_bytes(b"ignored")
    captured = git.capture(path, base, (".troupe",), tmp_path / "run.diff")
    assert captured.empty
    assert (tmp_path / "run.diff").read_bytes() == b""


def test_a_change_under_troupe_is_counted_and_left_out(repo: Repo, tmp_path: Path) -> None:
    git, path, base = worktree(repo, tmp_path)
    (path / ".troupe" / "events" / "x.jsonl").write_text("{}\n{}\n", encoding="utf-8")
    (path / "out.txt").write_text("hello\n", encoding="utf-8")
    out = tmp_path / "run.diff"
    captured = git.capture(path, base, (".troupe",), out)
    assert captured.added == ("out.txt",)
    assert captured.left_out == (".troupe/events/x.jsonl",)
    assert b".troupe" not in out.read_bytes()


def test_the_persons_diff_settings_dont_change_the_diff(repo: Repo, tmp_path: Path) -> None:
    git, path, base = worktree(repo, tmp_path)
    (path / "src" / "a.txt").write_text("two\n", encoding="utf-8")
    plain = tmp_path / "plain.diff"
    git.capture(path, base, (".troupe",), plain)
    for key, value in [
        ("diff.renames", "copies"),
        ("diff.noprefix", "true"),
        ("diff.mnemonicPrefix", "true"),
        ("diff.external", "false"),
        ("color.diff", "always"),
        ("diff.relative", "true"),
    ]:
        repo.git("config", key, value)
    configured = tmp_path / "configured.diff"
    git.capture(path, base, (".troupe",), configured)
    assert configured.read_bytes() == plain.read_bytes()


def test_a_diff_over_the_limit_fails_as_too_large_and_leaves_no_diff(
    repo: Repo, tmp_path: Path
) -> None:
    _, path, base = worktree(repo, tmp_path)
    (path / "big.txt").write_text("x" * 4096, encoding="utf-8")
    out = tmp_path / "run.diff"
    with pytest.raises(TroupeError) as caught:
        adapter(repo, diff_max_bytes=1024).capture(path, base, (".troupe",), out)
    assert caught.value.code == "workspace.diff-too-large"
    assert not out.exists()


def test_a_crlf_file_comes_back_crlf_with_the_worktrees_content(repo: Repo, tmp_path: Path) -> None:
    put(repo, ".gitattributes", "*.txt text eol=crlf\n")
    repo.commit_all("attributes")
    (repo.path / "src" / "a.txt").unlink()
    repo.git("checkout", "--", "src/a.txt")  # checked out again, now with CRLF
    assert (repo.path / "src" / "a.txt").read_bytes() == b"one\r\n"
    git, path, base = worktree(repo, tmp_path)
    (path / "src" / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    out = tmp_path / "run.diff"
    git.capture(path, base, (".troupe",), out)
    assert b"\r" not in out.read_bytes()  # git's normalised form
    git.apply(out)
    assert (repo.path / "src" / "a.txt").read_bytes() == b"one\r\ntwo\r\n"


# Requirement: The git adapter applies a diff only when all of it applies


def test_a_diff_with_one_conflicting_file_changes_neither_and_names_it(
    repo: Repo, tmp_path: Path
) -> None:
    git, path, base = worktree(repo, tmp_path)
    (path / "src" / "a.txt").write_text("two\n", encoding="utf-8")
    (path / "src" / "b.txt").write_text("bee two\n", encoding="utf-8")
    out = tmp_path / "run.diff"
    git.capture(path, base, (".troupe",), out)
    put(repo, "src/b.txt", "the person's own edit\n")
    applicability = git.check_apply(out)
    assert applicability.files == ("src/a.txt", "src/b.txt")
    assert applicability.failing == ("src/b.txt",)
    with pytest.raises(TroupeError):
        git.apply(out)
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert (repo.path / "src" / "b.txt").read_text(encoding="utf-8") == "the person's own edit\n"


def test_applying_leaves_the_index_and_head_unchanged(repo: Repo, tmp_path: Path) -> None:
    head = repo.git("rev-parse", "HEAD").strip()
    git, path, base = worktree(repo, tmp_path)
    (path / "src" / "a.txt").write_text("two\n", encoding="utf-8")
    (path / "new.txt").write_text("new\n", encoding="utf-8")
    out = tmp_path / "run.diff"
    git.capture(path, base, (".troupe",), out)
    assert git.apply(out) == ("new.txt", "src/a.txt")
    assert repo.git("rev-parse", "HEAD").strip() == head
    assert repo.git("diff", "--cached", "--name-only") == ""
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert (repo.path / "new.txt").read_text(encoding="utf-8") == "new\n"


def test_a_file_the_diff_adds_that_the_person_has_since_made_is_named_as_failing(
    repo: Repo, tmp_path: Path
) -> None:
    git, path, base = worktree(repo, tmp_path)
    (path / "new.txt").write_text("from the run\n", encoding="utf-8")
    out = tmp_path / "run.diff"
    git.capture(path, base, (".troupe",), out)
    put(repo, "new.txt", "the person's\n")
    assert git.check_apply(out).failing == ("new.txt",)


def test_an_empty_diff_applies_and_changes_nothing(repo: Repo, tmp_path: Path) -> None:
    git, path, base = worktree(repo, tmp_path)
    out = tmp_path / "run.diff"
    git.capture(path, base, (".troupe",), out)
    assert git.apply(out) == ()


# A theatre in a subdirectory of its repository


def test_a_theatre_in_a_subdirectory_reports_its_prefix(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    put(repo, "apps/theatre/a.txt", "a\n")
    repo.commit_all()
    sub = GitAdapter(repo.path / "apps" / "theatre", source=repo.env)
    assert sub.theatre_prefix() == "apps/theatre/"
    assert adapter(repo).theatre_prefix() == ""


# Requirement: The git adapter snapshots the shared repository's state


def test_a_tag_between_two_snapshots_is_the_only_change(repo: Repo) -> None:
    git = adapter(repo)
    before = git.shared_state()
    repo.git("tag", "v0")
    changes = before.compare(git.shared_state())
    assert changes.refs == (SharedChange("refs/tags/v0", "added"),)
    assert changes.config == ()
    assert changes.hooks == ()


def test_making_and_removing_a_worktree_changes_nothing_shared(repo: Repo, tmp_path: Path) -> None:
    git = adapter(repo)
    before = git.shared_state()
    _, path, _ = worktree(repo, tmp_path)
    assert before.compare(git.shared_state()).empty
    git.remove_worktree(path)
    assert before.compare(git.shared_state()).empty


def test_a_branch_a_stash_a_config_change_and_a_hook_made_in_a_worktree_are_each_reported(
    repo: Repo, tmp_path: Path
) -> None:
    git, path, _ = worktree(repo, tmp_path)
    before = git.shared_state()
    git_in(repo, path, "branch", "scratch")
    (path / "src" / "a.txt").write_text("stash me\n", encoding="utf-8")
    git_in(repo, path, "stash", "-q")
    git_in(repo, path, "config", "core.hooksPath", ".git/hooks")
    hooks = Path(git_in(repo, path, "rev-parse", "--git-common-dir").strip())
    hooks = (path / hooks / "hooks") if not hooks.is_absolute() else hooks / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    changes = before.compare(git.shared_state())
    assert SharedChange("refs/heads/scratch", "added") in changes.refs
    assert SharedChange("refs/stash", "added") in changes.refs
    assert changes.config == (SharedChange("config", "changed"),)
    assert changes.hooks == (SharedChange("pre-commit", "added"),)


def test_moving_the_theatres_own_head_is_reported_as_head(repo: Repo) -> None:
    git = adapter(repo)
    before = git.shared_state()
    repo.git("switch", "-q", "-c", "elsewhere")
    assert SharedChange("HEAD", "changed") in before.compare(git.shared_state()).refs


@pytest.mark.skipif(WINDOWS, reason="an executable bit is POSIX's")
def test_making_a_hook_executable_is_a_change(repo: Repo) -> None:
    git = adapter(repo)
    hook = repo.path / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    before = git.shared_state()
    hook.chmod(0o755)
    assert before.compare(git.shared_state()).hooks == (SharedChange("pre-push", "changed"),)


# Requirement: Calls to git are bounded and fail clearly (the worktree limits)


def _sleeping_git(directory: Path, seconds: float) -> dict[str, str]:
    """PATH for a stand-in git that sleeps for ``seconds`` and then succeeds, saying nothing."""
    directory.mkdir()
    script = directory / "sleep.py"
    script.write_text(f"import time\ntime.sleep({seconds})\n", encoding="utf-8")
    if WINDOWS:
        (directory / "git.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        stub = directory / "git"
        stub.write_text(
            f"#!{sys.executable}\nexec(open({str(script)!r}).read())\n", encoding="utf-8"
        )
        stub.chmod(0o755)
    return {"PATH": str(directory)}


def test_a_worktree_command_past_its_timeout_fails_naming_the_command_and_the_timeout(
    repo: Repo, tmp_path: Path
) -> None:
    path = _sleeping_git(tmp_path / "bin", 60)
    git = GitAdapter(repo.path, source={**repo.env, **path}, worktree_timeout=1.0, timeout=60.0)
    with pytest.raises(TroupeError) as caught:
        git.add_worktree(tmp_path / "wt", "HEAD")
    assert caught.value.code == "command.timeout"
    assert caught.value.details["command"].startswith("git worktree add")
    assert caught.value.details["timeoutSeconds"] == 1.0


def test_a_slow_worktree_command_is_announced_once(repo: Repo, tmp_path: Path) -> None:
    announced: list[str] = []
    git = GitAdapter(
        repo.path,
        source={**repo.env, **_sleeping_git(tmp_path / "bin", 1.0)},
        announce_after=0.1,
        on_wait=lambda command, waited: announced.append(command),
    )
    git.add_worktree(tmp_path / "wt", "HEAD")
    assert announced == ["git"]  # the platform announces the program it is waiting for


def test_a_deleted_tag_is_reported_as_removed(repo: Repo) -> None:
    repo.git("tag", "v0")
    git = adapter(repo)
    before = git.shared_state()
    repo.git("tag", "-d", "v0")
    assert before.compare(git.shared_state()).refs == (SharedChange("refs/tags/v0", "removed"),)
