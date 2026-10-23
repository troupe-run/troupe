"""Config files git merged, driven through the command line against real git merges (spec:
config-files, "A file git merged from troupe's versions is rewritten from the merged config" and
"Only an explicit command rewrites a file git merged"; config-projection-conflicts design D4 to D7).

Each rewritten file is checked against what the merged config renders, and against both sides, so
the file says what the merge of the two histories says, never what either side's text said.
"""

import io
import json
import subprocess
from pathlib import Path

import pytest

from gitrepo import AUTHOR, Repo
from runtesting import ADA, ALLOW, theatre
from troupe.cli import main
from troupe.core import defaults
from troupe.core.config.projection import file_hash, render
from troupe.core.errors import CODES
from troupe.core.exit_codes import ExitCode

YAML = ".troupe/actors/tester.yaml"
MD = ".troupe/actors/tester.md"
STEPS = 'actors.tester.options.script.steps=[{"exit": %d}]'
CHARACTER = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.\n"


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def ok(*argv: str) -> str:
    code, out, err = cli(*argv)
    assert code == 0, err
    return out


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    made = theatre(tmp_path)
    for name, value in {**made.env, **ADA, **ALLOW}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made


def _merge(repo: Repo) -> int:
    """``git merge feature`` into main, which may stop on a conflict."""
    return subprocess.run(
        ["git", "merge", "-q", "--no-edit", "feature"],  # noqa: S607 - git from the test's PATH
        cwd=repo.path,
        env={**repo.env, **AUTHOR},
        capture_output=True,
        check=False,
    ).returncode


def _branches(repo: Repo, base: list[str], feature: list[str], main: list[str]) -> None:
    """Set ``base`` and commit it on main, then ``feature`` on a branch from it and ``main`` on
    main, each committed; ends on main, unmerged."""
    ok("config", "set", *base)
    repo.commit_all("base")
    repo.git("switch", "-q", "-c", "feature")
    ok("config", "set", *feature)
    repo.commit_all("feature")
    repo.git("switch", "-q", "main")
    ok("config", "set", *main)
    repo.commit_all("main")


def _sides(repo: Repo, path: str) -> tuple[bytes, bytes]:
    return tuple(  # type: ignore[return-value]  # two sides
        subprocess.run(
            ["git", "show", f"{ref}:{path}"],  # noqa: S607
            cwd=repo.path,
            env=repo.env,
            capture_output=True,
            check=True,
        ).stdout
        for ref in ("main", "feature")
    )


def _merged_config() -> dict[str, object]:
    value = json.loads(ok("config", "get", "--json"))["value"]
    assert isinstance(value, dict)
    return value


def _kept(repo: Repo, kept: str) -> bytes:
    return (repo.path / ".troupe/local/artifacts/sha256" / kept[7:9] / kept[7:]).read_bytes()


def _events(repo: Repo) -> int:
    return sum(
        len(path.read_bytes().splitlines()) for path in (repo.path / ".troupe/events").iterdir()
    )


def _unmerged(repo: Repo) -> list[str]:
    return repo.git("diff", "--name-only", "--diff-filter=U").split()


BASE = ["actors.tester.runner=scripted", "actors.tester.expect=[]", STEPS % 0]
"""A tester whose YAML ends in its options' last line followed by ``expect: []``: one branch
changing each puts the changes on adjacent lines, which git can't merge, while config can."""


def _yaml_conflicted(repo: Repo) -> None:
    _branches(repo, BASE, [STEPS % 1], ['actors.tester.expect=["out/other.txt"]'])
    assert _merge(repo) != 0
    assert _unmerged(repo) == [YAML]


# Requirement: A file git merged from troupe's versions is rewritten from the merged config


def test_flush_writes_a_conflicted_file_from_the_merged_config_keeps_it_and_leaves_git_unmerged(
    repo: Repo,
) -> None:
    _yaml_conflicted(repo)
    ours, theirs = _sides(repo, YAML)
    conflicted = (repo.path / YAML).read_bytes()
    code, out, err = cli("flush")
    assert code == 0, err
    written = (repo.path / YAML).read_bytes()
    assert written == render(_merged_config())["actors/tester.yaml"]
    assert written not in (ours, theirs)
    assert b"exit: 1" in written  # feature's change
    assert b"out/other.txt" in written  # main's change
    assert "git left it conflicted, from versions troupe wrote" in out
    assert f"git add {YAML} and commit the merge" in err
    assert file_hash(conflicted) in err
    assert _kept(repo, file_hash(conflicted)) == conflicted
    assert _unmerged(repo) == [YAML]  # troupe leaves git's index alone (#156)


def test_a_resolution_started_by_hand_is_kept_under_the_hash_the_notice_names(
    repo: Repo,
) -> None:
    _yaml_conflicted(repo)
    by_hand = (repo.path / YAML).read_bytes().replace(b"<<<<<<< HEAD\n", b"")
    (repo.path / YAML).write_bytes(by_hand)  # these bytes exactly, on Windows too
    code, _, err = cli("flush")
    assert code == 0, err
    assert file_hash(by_hand) in err
    assert _kept(repo, file_hash(by_hand)) == by_hand
    assert (repo.path / YAML).read_bytes() == render(_merged_config())["actors/tester.yaml"]


def test_removed_on_one_side_and_changed_on_the_other_is_written_as_resolved_with_no_copy(
    repo: Repo,
) -> None:
    ok("config", "set", *BASE, "actors.tester.character=Old.")
    repo.commit_all("base")
    repo.git("switch", "-q", "-c", "feature")
    ok("config", "set", "actors.tester.character=New.")
    repo.commit_all("feature")
    repo.git("switch", "-q", "main")
    ok("config", "unset", "actors.tester.character")
    repo.commit_all("main")
    assert _merge(repo) != 0
    assert _unmerged(repo) == [MD]
    # git leaves the side that kept the file in place: a version troupe wrote, so it's replaced
    # as any older version is.
    assert (repo.path / MD).read_bytes() == b"New."
    code, _, err = cli("config", "set", "actors.tester.character=Kept.")
    assert code == 0, err
    assert (repo.path / MD).read_bytes() == b"Kept."
    assert not (repo.path / ".troupe/local/artifacts").exists()  # no copy was needed


def test_a_clean_line_merge_of_two_character_edits_is_rewritten_by_the_resolving_config_set(
    repo: Repo,
) -> None:
    edited_first = CHARACTER.replace("First", "Edited first")
    edited_third = CHARACTER.replace("Third", "Edited third")
    _branches(
        repo,
        [*BASE, f"actors.tester.character={CHARACTER}"],
        [f"actors.tester.character={edited_first}"],
        [f"actors.tester.character={edited_third}"],
    )
    assert _merge(repo) == 0  # git merged the text and committed the merge
    merged_text = (repo.path / MD).read_bytes()
    assert b"Edited first" in merged_text
    assert b"Edited third" in merged_text
    code, _, err = cli("config", "set", "actors.tester.character=Both.")
    assert code == 0, err
    assert (repo.path / MD).read_bytes() == b"Both."
    assert "git merged it from versions troupe wrote" in err
    assert _kept(repo, file_hash(merged_text)) == merged_text


def test_a_clean_merge_edited_after_git_made_it_is_refused_as_a_hand_edit(repo: Repo) -> None:
    _branches(
        repo,
        [*BASE, f"actors.tester.character={CHARACTER}"],
        [f"actors.tester.character={CHARACTER.replace('First', 'Edited first')}"],
        [f"actors.tester.character={CHARACTER.replace('Third', 'Edited third')}"],
    )
    assert _merge(repo) == 0
    edited = (repo.path / MD).read_bytes() + b"And a line of my own.\n"
    (repo.path / MD).write_bytes(edited)
    code, _, err = cli("config", "set", "actors.tester.character=Both.")
    assert code == CODES["config.file-not-troupes"]
    assert "git restore" in err
    assert (repo.path / MD).read_bytes() == edited


def test_a_clean_merge_older_than_head_is_refused(repo: Repo) -> None:
    _branches(
        repo,
        [*BASE, f"actors.tester.character={CHARACTER}"],
        [f"actors.tester.character={CHARACTER.replace('First', 'Edited first')}"],
        [f"actors.tester.character={CHARACTER.replace('Third', 'Edited third')}"],
    )
    assert _merge(repo) == 0
    repo.write("notes.txt", "a later commit\n")
    repo.commit_all("after the merge")
    code, _, _ = cli("config", "set", "actors.tester.character=Both.")
    assert code == CODES["config.file-not-troupes"]


def test_a_rehearsed_flush_names_the_merged_file_and_its_reason_and_writes_and_keeps_nothing(
    repo: Repo,
) -> None:
    _yaml_conflicted(repo)
    conflicted = (repo.path / YAML).read_bytes()
    code, out, err = cli("flush", "--rehearse")
    assert code == ExitCode.WOULD_CHANGE, err
    assert YAML in out
    assert "git left it conflicted, from versions troupe wrote" in out
    assert (repo.path / YAML).read_bytes() == conflicted
    assert not (repo.path / ".troupe/local/artifacts").exists()


def test_without_git_a_file_with_conflict_markers_is_refused(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    _yaml_conflicted(repo)
    conflicted = (repo.path / YAML).read_bytes()
    monkeypatch.setattr(defaults, "VCS", "files")
    code, _, err = cli("flush")
    assert code == CODES["config.file-not-troupes"]
    assert "conflict markers" in err
    assert (repo.path / YAML).read_bytes() == conflicted


# Requirement: Only an explicit command rewrites a file git merged


def test_perform_refuses_a_conflicted_file_naming_flush_and_starts_no_run(repo: Repo) -> None:
    _yaml_conflicted(repo)
    conflicted = (repo.path / YAML).read_bytes()
    code, _, err = cli("perform", "tester")
    assert code == CODES["config.file-not-troupes"]
    assert "git merged it from versions troupe wrote" in err
    assert "Run troupe flush" in err
    assert (repo.path / YAML).read_bytes() == conflicted
    assert cli("status") == (0, "No runs yet.\n", "")


def test_the_config_set_resolving_a_conflict_rewrites_a_merged_file_its_change_doesnt_write(
    repo: Repo,
) -> None:
    # Found by the merge property test: config conflicts in tester.md's character, and git also
    # conflicts tester.yaml. The resolving config set writes only tester.md, and troupe flush can't
    # run until config is resolved, so this config set must rewrite tester.yaml too.
    _branches(
        repo,
        BASE,
        [STEPS % 1, "actors.tester.character=One."],
        ['actors.tester.expect=["out/other.txt"]', "actors.tester.character=Two."],
    )
    assert _merge(repo) != 0
    assert sorted(_unmerged(repo)) == [MD, YAML]
    conflicted = (repo.path / YAML).read_bytes()
    code, _, err = cli("config", "set", "actors.tester.character=Both.")
    assert code == 0, err
    assert (repo.path / MD).read_bytes() == b"Both."
    assert (repo.path / YAML).read_bytes() == render(_merged_config())["actors/tester.yaml"]
    assert _kept(repo, file_hash(conflicted)) == conflicted


def test_a_config_set_that_doesnt_write_the_file_is_refused_naming_flush_and_records_nothing(
    repo: Repo,
) -> None:
    _yaml_conflicted(repo)
    events = _events(repo)
    code, _, err = cli(
        "config",
        "set",
        "actors.reviewer.runner=scripted",
        "actors.reviewer.expect=[]",
        STEPS.replace("tester", "reviewer") % 0,
    )
    assert code == CODES["config.file-not-troupes"]
    assert "Run troupe flush" in err
    assert _events(repo) == events
    assert not (repo.path / ".troupe/actors/reviewer.yaml").exists()
