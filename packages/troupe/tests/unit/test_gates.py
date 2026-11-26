"""The approvers' rules, the default list and troupe's own actor (spec: gates, config; manual-gates
design D2, D5)."""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from event_schemas import is_valid, lineage
from troupe.core import gates
from troupe.platform import processes


def rules(approvers: list[str], workspace: str | None = None) -> list[str]:
    return [problem.rule for problem in gates.approvers_problems(approvers, workspace=workspace)]


def test_an_actor_that_sets_no_approvers_gets_troupe_then_director() -> None:
    assert gates.resolve(None) == gates.Approvers(("troupe", "director"), "default")


def test_an_actor_that_sets_approvers_gets_its_own_with_source_actor() -> None:
    assert gates.resolve(["director"]) == gates.Approvers(("director",), "actor")


@pytest.mark.parametrize("approvers", [["director"], ["troupe", "director"]])
def test_a_list_ending_in_director_with_troupe_only_first_is_accepted(approvers: list[str]) -> None:
    assert rules(approvers) == []


def test_troupe_alone_is_refused_because_the_last_approver_must_be_a_persons_role() -> None:
    [rule] = rules(["troupe"])
    assert "last approver must be a role a person can hold, such as director" in rule


def test_troupe_after_a_person_is_refused_saying_it_can_come_only_first() -> None:
    assert any("troupe can come only first" in rule for rule in rules(["director", "troupe"]))


def test_an_empty_list_is_refused_and_the_fix_says_unsetting_gives_the_default() -> None:
    [problem] = gates.approvers_problems([], workspace=None)
    assert "role a person can hold" in problem.rule
    assert "unset approvers to get the default" in problem.fix


def test_a_role_named_twice_is_refused_naming_it() -> None:
    assert any("director is named more than once" in rule for rule in rules(["director"] * 2))


def test_a_role_that_doesnt_exist_yet_is_refused_naming_it_and_the_two_roles() -> None:
    assert any(
        "reviewer isn't a role" in rule and "troupe and director" in rule
        for rule in rules(["reviewer", "director"])
    )


def test_approvers_on_an_actor_that_works_in_the_theatre_are_refused() -> None:
    [rule] = rules(["director"], workspace="theatre")
    assert "works in the theatre has no gate" in rule


@given(st.lists(st.sampled_from(["troupe", "director", "reviewer"]), max_size=4))
def test_every_list_accepted_ends_in_director_and_holds_troupe_at_most_once_first(
    approvers: list[str],
) -> None:
    if rules(approvers):
        return
    assert approvers[-1] == "director"
    assert approvers.count("troupe") <= 1
    assert "troupe" not in approvers[1:]
    assert len(set(approvers)) == len(approvers)
    assert set(approvers) <= {"troupe", "director"}


def test_troupes_actor_names_the_core_on_this_host_and_fits_the_lineage_schema() -> None:
    actor = gates.troupe_actor()
    assert actor.id == f"core@{processes.host_name()}"
    assert is_valid(lineage(actor=actor.to_data()), "lineage.schema.json")


@pytest.mark.parametrize(
    ("given_name", "expected"),
    [
        ("Build-01.local", "build-01.local"),
        ("my host", "my-host"),
        ("a@b", "a-b"),
        ("  ", "localhost"),
    ],
)
def test_the_host_name_is_lower_case_with_no_space_or_at_sign(
    monkeypatch: pytest.MonkeyPatch, given_name: str, expected: str
) -> None:
    import socket

    monkeypatch.setattr(socket, "gethostname", lambda: given_name)
    assert processes.host_name() == expected
    assert re.fullmatch(r"[^\s@]+", processes.host_name())
