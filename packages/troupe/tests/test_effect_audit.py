"""The audit of a run's changes against its declared effects (spec: effects, "Every run's changes
are audited against its declaration", "Each kind of change needs its own effect" and "A failed
audit fails the run and names every change"; declared-effects design D3)."""

from collections.abc import Mapping

import pytest
from hypothesis import given
from hypothesis import strategies as st

from protocol_schemas import check_error
from troupe.core.errors import TroupeError
from troupe.core.runners.effects import (
    Change,
    Combined,
    DeclaredEffects,
    EffectVerdict,
    outside,
)
from troupe_plugin_sdk.effects import Effects

BASE = {"README.md": "r", "src/a.py": "a", "drafts/a.md": "d", "out/old.txt": "o"}


def test_writing_where_declared_passes() -> None:
    after = {**BASE, "out/a.txt": "new", "out/old.txt": "changed"}
    assert outside(Effects(write=("out/**",)), BASE, after) == []


def test_a_change_outside_the_declaration_names_the_path_and_the_write_effect() -> None:
    after = {**BASE, "out/a.txt": "new", "src/a.py": "edited"}
    assert outside(Effects(write=("out/**",)), BASE, after) == [
        Change("src/a.py", "modified", "write")
    ]


def test_an_added_file_outside_the_declaration_needs_write() -> None:
    assert outside(Effects(), BASE, {**BASE, "out/a.txt": "new"}) == [
        Change("out/a.txt", "added", "write")
    ]


def test_a_delete_with_only_write_declared_needs_delete() -> None:
    after = {k: v for k, v in BASE.items() if k != "README.md"}
    assert outside(Effects(write=("**",)), BASE, after) == [
        Change("README.md", "removed", "delete")
    ]


def test_a_move_within_what_is_declared_passes() -> None:
    after = {k: v for k, v in BASE.items() if k != "drafts/a.md"} | {"drafts/old/a.md": "d"}
    assert outside(Effects(move=("drafts/**",)), BASE, after) == []


def test_a_move_whose_destination_isnt_declared_names_both_paths_and_the_move_effect() -> None:
    after = {k: v for k, v in BASE.items() if k != "drafts/a.md"} | {"docs/a.md": "d"}
    assert outside(Effects(move=("drafts/**",)), BASE, after) == [
        Change("drafts/a.md", "moved", "move", to="docs/a.md")
    ]


def test_a_move_allowed_by_delete_and_write_apart_passes() -> None:
    after = {k: v for k, v in BASE.items() if k != "drafts/a.md"} | {"docs/a.md": "d"}
    assert outside(Effects(write=("docs/**",), delete=("drafts/**",)), BASE, after) == []


def test_with_two_identical_files_moves_pair_in_path_order() -> None:
    before = {"a/1.txt": "same", "a/2.txt": "same"}
    after = {"b/1.txt": "same", "b/2.txt": "same"}
    assert outside(Effects(), before, after) == [
        Change("a/1.txt", "moved", "move", to="b/1.txt"),
        Change("a/2.txt", "moved", "move", to="b/2.txt"),
    ]


def test_nothing_changed_with_nothing_declared_passes() -> None:
    assert outside(Effects(), BASE, dict(BASE)) == []


PATHS = st.sampled_from(["a.txt", "out/a.txt", "out/b.txt", "src/a.py", "docs/x.md"])
STATES = st.dictionaries(PATHS, st.sampled_from(["1", "2", "3"]), max_size=5)


@given(before=STATES, after=STATES)
def test_declaring_everything_allows_every_change(
    before: Mapping[str, str], after: Mapping[str, str]
) -> None:
    assert outside(Effects(write=("**",), delete=("**",), move=("**",)), before, after) == []


@given(before=STATES, after=STATES)
def test_with_nothing_declared_every_difference_is_reported_once(
    before: Mapping[str, str], after: Mapping[str, str]
) -> None:
    changes = outside(Effects(), before, after)
    named = [c.path for c in changes] + [str(c.to) for c in changes if c.to is not None]
    differing = {p for p in {*before, *after} if before.get(p) != after.get(p)}
    assert sorted(named) == sorted(differing)


def _audit(
    actor: str, effects: Effects, before: dict[str, str], after: dict[str, str]
) -> EffectVerdict:
    check = DeclaredEffects(actor, effects, lambda: before, lambda: after)
    check.before()
    return check.after()


def test_a_failed_audit_lists_each_change_and_the_set_that_declares_them() -> None:
    after = {k: v for k, v in BASE.items() if k != "README.md"} | {"src/a.py": "edited"}
    verdict = _audit("tester", Effects(write=("out/**",)), BASE, after)
    assert not verdict.passed
    error = verdict.error
    assert error is not None
    check_error(error.to_data())
    assert error.code == "effects.outside-declared"
    assert error.details == {
        "actor": "tester",
        "changes": [
            {"path": "README.md", "change": "removed", "needs": "delete"},
            {"path": "src/a.py", "change": "modified", "needs": "write"},
        ],
    }
    assert "README.md removed (needs delete)" in error.problem
    assert "src/a.py modified (needs write)" in error.problem
    assert error.fix.endswith(
        "troupe config set actors.tester.effects.delete='[\"README.md\"]' "
        'actors.tester.effects.write=\'["out/**", "src/a.py"]\''
    )


def test_the_audit_reads_the_starting_state_before_the_run() -> None:
    reads: list[str] = []

    def before() -> dict[str, str]:
        reads.append("before")
        return dict(BASE)

    def after() -> dict[str, str]:
        reads.append("after")
        return dict(BASE)

    check = DeclaredEffects("tester", Effects(), before, after)
    check.before()
    assert reads == ["before"]
    assert check.after().passed
    assert reads == ["before", "after"]


class _Fixed:
    def __init__(self, verdict: EffectVerdict) -> None:
        self.verdict = verdict
        self.started = False

    def before(self) -> None:
        self.started = True

    def after(self) -> EffectVerdict:
        return self.verdict


def _failing(code: str, problem: str) -> EffectVerdict:
    return EffectVerdict(passed=False, error=TroupeError(code, problem=problem, fix="Fix it."))


def test_combined_checks_pass_only_when_each_passes_and_start_each() -> None:
    first, second = _Fixed(EffectVerdict(passed=True)), _Fixed(EffectVerdict(passed=True))
    combined = Combined(first, second)
    combined.before()
    assert first.started
    assert second.started
    assert combined.after().passed


def test_one_failing_check_is_its_own_error() -> None:
    failing = _failing("run.effect-missing", "Missing.")
    verdict = Combined(_Fixed(EffectVerdict(passed=True)), _Fixed(failing)).after()
    assert verdict.error == failing.error


def test_both_checks_failing_name_both_errors() -> None:
    missing = EffectVerdict(
        passed=False,
        error=TroupeError("run.effect-missing", problem="A file is missing.", fix="Look."),
    )
    audit = _audit("tester", Effects(), BASE, {**BASE, "src/a.py": "edited"})
    verdict = Combined(_Fixed(missing), _Fixed(audit)).after()
    error = verdict.error
    assert error is not None
    check_error(error.to_data())
    assert error.code == "effects.check-failed"
    assert [inner["code"] for inner in error.details["errors"]] == [
        "run.effect-missing",
        "effects.outside-declared",
    ]
    assert "A file is missing." in error.problem
    assert "src/a.py modified" in error.problem


@pytest.mark.parametrize("change", ["added", "modified", "removed"])
def test_a_change_shows_its_path_what_happened_and_the_effect(change: str) -> None:
    shown = Change("a.txt", change, "write").shown()  # type: ignore[arg-type]
    assert shown == f"a.txt {change} (needs write)"
