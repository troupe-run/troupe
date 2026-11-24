"""Hand edits that resolve config's conflicts, on real git branches, through the CLI (spec:
config-hand-edits, "Hand edits resolve config's conflicts", "Every conflict a hand edit resolves
is named"; hand-edit-sweep design D8)."""

import json
from pathlib import Path
from typing import Any

import pytest

from cli_config_merges_shared import BASE, YAML, _merge, cli, ok
from gitrepo import Repo
from runtesting import ADA, ALLOW, theatre

REVIEWER = ".troupe/actors/reviewer.yaml"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    made = theatre(tmp_path)
    for name, value in {**made.env, **ADA, **ALLOW}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made


FIVE = '["out/1", "out/2", "out/3", "out/4", "out/5"]'


def _conflicted(repo: Repo, feature: list[str], main: list[str], base: list[str] = BASE) -> int:
    ok("config", "set", *base)
    repo.commit_all("base")
    repo.git("switch", "-q", "-c", "feature")
    ok("config", "set", *feature)
    repo.commit_all("feature")
    repo.git("switch", "-q", "main")
    ok("config", "set", *main)
    repo.commit_all("main")
    return _merge(repo)


def _get(path: str) -> Any:  # noqa: ANN401 - the config-get result, as JSON
    code, out, err = cli("config", "get", path, "--json")
    assert code == 0, err
    return json.loads(out)


def _events(repo: Repo) -> int:
    return sum(
        len(p.read_bytes().splitlines()) - 1
        for p in (repo.path / ".troupe" / "events").glob("*.jsonl")
    )


def _resolved_by_hand(repo: Repo, path: str, replace: tuple[str, str]) -> None:
    """The person resolves ``path``'s conflict by hand: our side, with ``replace`` made in it."""
    ours = repo.git("show", f"main:{path}")
    (repo.path / path).write_text(ours.replace(*replace), encoding="utf-8")


def test_a_hand_edit_resolves_a_conflict_and_says_so(repo: Repo) -> None:
    assert (
        _conflicted(repo, ['actors.tester.expect=["out/a"]'], ['actors.tester.expect=["out/b"]'])
        != 0
    )
    _resolved_by_hand(repo, YAML, ("out/b", "out/a"))
    code, _, err = cli("sync")
    assert code == 0, err
    assert "resolved the conflict on actors.tester.expect" in err
    assert '["out/a"]' in err  # the value it took
    result = _get("actors.tester.expect")
    assert result["value"] == ["out/a"]
    assert result["conflicts"] == []


def test_a_value_that_matches_neither_side_resolves_the_conflict(repo: Repo) -> None:
    assert (
        _conflicted(repo, ['actors.tester.expect=["out/a"]'], ['actors.tester.expect=["out/b"]'])
        != 0
    )
    _resolved_by_hand(repo, YAML, ("out/b", "out/c"))
    code, _, err = cli("sync")
    assert code == 0, err
    assert _get("actors.tester.expect")["value"] == ["out/c"]


def test_a_partial_resolution_is_refused_naming_whats_left_and_keeps_the_edit(repo: Repo) -> None:
    base = [*BASE, *(arg.replace("tester", "reviewer") for arg in BASE)]
    feature = ['actors.tester.expect=["out/a"]', 'actors.reviewer.expect=["out/a"]']
    main = ['actors.tester.expect=["out/b"]', 'actors.reviewer.expect=["out/b"]']
    assert _conflicted(repo, feature, main, base) != 0
    _resolved_by_hand(repo, YAML, ("out/b", "out/a"))
    edited = (repo.path / YAML).read_bytes()
    before = _events(repo)
    code, _, err = cli("sync")
    assert code != 0
    assert "config.conflict" in err or "conflict" in err
    assert "actors.reviewer.expect" in err
    assert _events(repo) == before
    assert (repo.path / YAML).read_bytes() == edited


def test_a_partial_resolution_finished_by_a_config_set_is_recorded_together(repo: Repo) -> None:
    base = [*BASE, *(arg.replace("tester", "reviewer") for arg in BASE)]
    feature = ['actors.tester.expect=["out/a"]', 'actors.reviewer.expect=["out/a"]']
    main = ['actors.tester.expect=["out/b"]', 'actors.reviewer.expect=["out/b"]']
    assert _conflicted(repo, feature, main, base) != 0
    _resolved_by_hand(repo, YAML, ("out/b", "out/a"))
    before = _events(repo)
    code, _, err = cli("config", "set", 'actors.reviewer.expect=["out/z"]')
    assert code == 0, err
    assert _events(repo) == before + 3  # the settle, the hand edit and the person's change
    assert _get("actors.tester.expect")["value"] == ["out/a"]
    assert _get("actors.reviewer.expect")["value"] == ["out/z"]


def test_config_get_with_a_partial_resolution_records_nothing_and_says_why(repo: Repo) -> None:
    base = [*BASE, *(arg.replace("tester", "reviewer") for arg in BASE)]
    feature = ['actors.tester.expect=["out/a"]', 'actors.reviewer.expect=["out/a"]']
    main = ['actors.tester.expect=["out/b"]', 'actors.reviewer.expect=["out/b"]']
    assert _conflicted(repo, feature, main, base) != 0
    _resolved_by_hand(repo, YAML, ("out/b", "out/a"))
    before = _events(repo)
    result = _get("actors")
    [conflict] = result["conflicts"]
    assert conflict["paths"] == [["actors", "reviewer", "expect"], ["actors", "tester", "expect"]]
    [notice] = [n for n in result["notices"] if n["code"] == "config.hand-edit-unrecorded"]
    assert notice["details"]["files"] == [YAML]
    assert notice["details"]["left"] == [["actors", "reviewer", "expect"]]
    assert _events(repo) == before


def test_two_conflicting_values_in_one_edited_file_are_both_resolved_and_named(repo: Repo) -> None:
    write = '["out/**", "w/2", "w/3", "w/4", "w/5"]'
    base = [*BASE, f"actors.tester.expect={FIVE}", f"actors.tester.effects.write={write}"]
    # Each branch changes lines of each list far enough apart: git merges the text, config
    # conflicts (each list is one whole value).
    feature = [
        'actors.tester.expect=["out/one", "out/2", "out/3", "out/4", "out/5"]',
        'actors.tester.effects.write=["out/**", "w/two", "w/3", "w/4", "w/5"]',
    ]
    main = [
        'actors.tester.expect=["out/1", "out/2", "out/3", "out/4", "out/five"]',
        'actors.tester.effects.write=["out/**", "w/2", "w/3", "w/4", "w/five"]',
    ]
    assert _conflicted(repo, feature, main, base) == 0  # git merged the lines cleanly
    text = (repo.path / YAML).read_text("utf-8")
    first = text.index("expect:")
    (repo.path / YAML).write_text(
        text[:first] + text[first:].replace("out/five", "out/mine", 1), encoding="utf-8"
    )
    code, _, err = cli("sync")
    assert code == 0, err
    assert "resolved the conflict on actors.tester.expect" in err
    assert "resolved the conflict on actors.tester.effects.write" in err
    assert _get("actors.tester.expect")["conflicts"] == []


def test_taking_a_side_with_git_checkout_resolves_the_conflict(repo: Repo) -> None:
    assert (
        _conflicted(repo, ['actors.tester.expect=["out/a"]'], ['actors.tester.expect=["out/b"]'])
        != 0
    )
    repo.git("checkout", "--theirs", YAML)
    code, _, err = cli("sync")
    assert code == 0, err
    assert _get("actors.tester.expect")["value"] == ["out/a"]


def test_a_merge_git_made_resolves_nothing(repo: Repo) -> None:
    assert (
        _conflicted(repo, ['actors.tester.expect=["out/a"]'], ['actors.tester.expect=["out/b"]'])
        != 0
    )
    before = _events(repo)
    code, _, err = cli("perform", "tester", "--rehearse")
    assert code != 0
    assert "conflict" in err
    assert _events(repo) == before


def test_a_rehearsal_names_the_conflict_it_would_resolve(repo: Repo) -> None:
    assert (
        _conflicted(repo, ['actors.tester.expect=["out/a"]'], ['actors.tester.expect=["out/b"]'])
        != 0
    )
    _resolved_by_hand(repo, YAML, ("out/b", "out/a"))
    before = _events(repo)
    code, _, err = cli("sync", "--rehearse")
    assert "would resolve the conflict on actors.tester.expect" in err
    assert _events(repo) == before
    assert code != 0  # would change: exit 3


def test_perform_names_a_conflict_its_sweep_resolved_before_the_run(repo: Repo) -> None:
    assert (
        _conflicted(repo, ['actors.tester.expect=["out/a"]'], ['actors.tester.expect=["out/b"]'])
        != 0
    )
    _resolved_by_hand(repo, YAML, ("out/b", "out/a"))
    _, _, err = cli("perform", "tester", "--rehearse")
    assert "would resolve the conflict on actors.tester.expect" in err
    _, _, err = cli("perform", "tester", "--direction", "go")
    assert "resolved the conflict on actors.tester.expect" in err
    assert err.index("resolved the conflict") < err.index("run ")  # named before the run starts
