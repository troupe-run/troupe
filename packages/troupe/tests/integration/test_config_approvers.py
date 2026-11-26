"""An actor's approvers, set on the command line and by hand (spec: config, "An actor's approvers
are an ordered list of roles", "An approvers list always ends with a person", "An actor that works
in place has no approvers"; manual-gates design D5)."""

import io
import json
from pathlib import Path

import pytest

from gitrepo import Repo
from runtesting import ADA, theatre
from troupe.cli import main

STEPS = '[{"exit": 0}]'


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    made = theatre(tmp_path)
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    code, _, err = cli(
        "config",
        "set",
        "actors.tester.runner=scripted",
        'actors.tester.effects.write=["out/**"]',
        'actors.tester.expect=["out/hello.txt"]',
        f"actors.tester.options.script.steps={STEPS}",
    )
    assert code == 0, err
    return made


def _actor_file(repo: Repo) -> Path:
    return repo.path / ".troupe" / "actors" / "tester.yaml"


def _get(path: str) -> object:
    code, out, _ = cli("config", "get", path, "--json")
    assert code == 0
    return json.loads(out).get("value")


def test_an_actor_whose_runs_wait_for_a_person_is_recorded_and_written(repo: Repo) -> None:
    code, _, err = cli("config", "set", 'actors.tester.approvers=["director"]')
    assert code == 0, err
    assert _get("actors.tester.approvers") == ["director"]
    assert "approvers:" in _actor_file(repo).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("value", "said"),
    [
        ('["troupe"]', "the last approver must be a role a person can hold, such as director"),
        ('["director", "troupe"]', "troupe can come only first"),
        ('["director", "director"]', "director is named more than once"),
        ("[]", "unset approvers to get the default"),
    ],
    ids=["troupe alone", "troupe after a person", "a role twice", "empty"],
)
def test_an_approvers_list_that_breaks_a_rule_is_refused_naming_the_path(
    repo: Repo, value: str, said: str
) -> None:
    before = _actor_file(repo).read_bytes()
    code, _, err = cli("config", "set", f"actors.tester.approvers={value}")
    assert code == 1
    assert "actors.tester.approvers" in err
    assert said in err
    assert _actor_file(repo).read_bytes() == before
    assert _get("actors.tester.approvers") is None


def test_an_unknown_role_is_refused_naming_both_roles_and_not_the_refused_name(
    repo: Repo,
) -> None:
    code, _, err = cli("config", "set", 'actors.tester.approvers=["reviewer"]')
    assert code == 1
    assert "actors.tester.approvers" in err
    assert "'troupe'" in err
    assert "'director'" in err
    assert "reviewer" not in err


def test_approvers_on_an_actor_that_works_in_the_theatre_are_refused_naming_both_paths(
    repo: Repo,
) -> None:
    assert cli("config", "set", "actors.tester.workspace=theatre")[0] == 0
    code, _, err = cli("config", "set", 'actors.tester.approvers=["director"]')
    assert code == 1
    assert "actors.tester.approvers" in err
    assert "actors.tester.workspace" in err
    assert _get("actors.tester.approvers") is None


def test_a_hand_edit_to_troupe_alone_is_refused_by_the_sweep_and_records_nothing(
    repo: Repo,
) -> None:
    path = _actor_file(repo)
    path.write_text(path.read_text(encoding="utf-8") + "approvers: [troupe]\n", encoding="utf-8")
    code, _, err = cli("config", "get", "actors.tester", "--json")
    assert code == 1
    assert "actors/tester.yaml" in err
    assert "the last approver must be a role a person can hold" in err
    path.write_text(path.read_text(encoding="utf-8").replace("approvers: [troupe]\n", ""))
    assert _get("actors.tester.approvers") is None
