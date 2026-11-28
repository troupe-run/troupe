"""Performing a flow, in process against a real git theatre: its steps run in order as one
performance, each built on the work before it, told what came before, with gates between steps
and the last step's gate landing the whole flow (spec: flows; actor-sequences design D2 to D6)."""

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from event_service_shared import recorded_lines
from gitrepo import Repo
from run_workspaces_shared import Recording, write
from runtesting import INIT, OK, Harness, committed, script
from storetesting import git_service
from troupe.core.artifacts import load_store
from troupe.core.client import messages as m
from troupe.core.config.changes import change
from troupe.core.config.projection import flush
from troupe.core.config.stream import read as read_config
from troupe.core.config.stream import record as record_config
from troupe.core.errors import TroupeError
from troupe.core.masking import MARKER
from troupe.core.runs.perform import perform
from troupe.core.workspaces import worktree_path

EVERYWHERE = {"write": ["**"]}
FAIL = {"event": {"type": "result", "status": "error", "reason": "other", "message": "no"}}
ADA = {"TROUPE_ACTOR": "human:ada@example.com"}


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return committed(tmp_path)


def actor(
    made: Harness,
    name: str,
    *steps: dict[str, Any],
    **fields: Any,  # noqa: ANN401
) -> None:
    """Define a worktree actor that may write anything and runs ``steps``."""
    made.configure(
        {
            "actor": name,
            "runner": "scripted",
            "options": script(*steps),
            "effectCheck": {"kind": "none"},
            "effects": EVERYWHERE,
            "workspace": "worktree",
            **fields,
        }
    )


def flow(made: Harness, name: str, steps: list[dict[str, Any]]) -> None:
    """Define the flow ``name`` and commit config, so the theatre's HEAD holds it."""
    store = git_service(made.repo, env={**ADA, **made.env})
    merged = read_config(store)
    entries = change(merged.config, [(["flows", name], {"steps": steps})])
    record_config(store.command(via="cli"), merged, entries, [])
    flush(made.repo.path, read_config(store).config, {})
    made.repo.commit_all("config")


def run_flow(made: Harness, name: str, direction: str | None = None) -> m.RunSummary:
    asked: dict[str, Any] = {"actor": name}
    if direction is not None:
        asked["direction"] = direction
    parsed = m.PerformRequest.from_data(asked)
    result = asyncio.run(perform(parsed, made.session(), made.send, backends=made.backends()))
    assert result.run is not None
    return result.run


def events(made: Harness, stream: str) -> list[tuple[str, dict[str, Any]]]:
    store = made.backends().event_store(made.session())
    return [
        (event.topic.split(":")[1], {**json.loads(event.state), "_lineage": event.lineage})
        for event in store.history(UUID(stream))
    ]


def runs_of(made: Harness, performance: str) -> list[str]:
    """The performance's runs, in the order their starts were sent."""
    return [
        u["runId"]
        for u in made.updates
        if u.get("kind") == "started" and u["performanceId"] == performance
    ]


def direction_of(made: Harness, run_id: str) -> str:
    [(_, started), *_] = events(made, run_id)
    artifacts = load_store("local", made.repo.path / ".troupe" / "local" / "artifacts")
    return artifacts.read(started["direction"]).decode("utf-8")


def three_steps(made: Harness) -> None:
    actor(made, "writer", INIT, write("src/a.txt", "from the writer\n"), OK)
    actor(made, "reviewer", INIT, write("src/b.txt", "from the reviewer\n"), OK)
    actor(made, "tester", INIT, write("src/c.txt", "from the tester\n"), OK)
    flow(
        made,
        "review",
        [
            {"actor": "writer"},
            {"actor": "reviewer", "direction": "Review what the writer changed."},
            {"actor": "tester"},
        ],
    )


# Requirement: Performing a flow runs its steps in order


def test_a_flow_runs_each_step_in_order_as_one_performance_and_lands_the_whole_work(
    repo: Repo,
) -> None:
    made = Harness(repo)
    three_steps(made)
    last = run_flow(made, "review", "Add the feature.")
    performance = last.performance_id
    runs = runs_of(made, performance)
    assert len(runs) == 3
    assert last.run_id == runs[-1]
    assert last.step == 3
    # The last gate kept the whole performance's work: every step's file is in the theatre.
    for name, text in (("a", "writer"), ("b", "reviewer"), ("c", "tester")):
        assert (repo.path / "src" / f"{name}.txt").read_text(encoding="utf-8") == (
            f"from the {text}\n"
        )
    [(started, start), *_, (ended, end)] = events(made, performance)
    assert started == "Performance.Started"
    assert start["performed"] == {"kind": "flow", "name": "review"}
    assert [s["actor"] for s in start["steps"]] == ["writer", "reviewer", "tester"]
    assert ended == "Performance.Ended"
    assert end["outcome"] == "completed"
    # One Performance.Started, no matter how many steps.
    assert [t for t, _ in events(made, performance)].count("Performance.Started") == 1


def test_each_steps_start_names_its_place_and_actor_in_perform_updates(repo: Repo) -> None:
    made = Harness(repo)
    three_steps(made)
    run_flow(made, "review")
    [begun] = [u for u in made.updates if u.get("kind") == "performance-started"]
    assert begun["performed"] == {"kind": "flow", "name": "review"}
    assert begun["steps"] == 3
    started = [(u["step"], u["actor"]) for u in made.updates if u.get("kind") == "started"]
    assert started == [(1, "writer"), (2, "reviewer"), (3, "tester")]


# Requirement: Each step works on the steps before it


def test_a_later_step_records_what_it_was_built_on_and_its_own_diff_beside_the_sofar(
    repo: Repo,
) -> None:
    made = Harness(repo)
    three_steps(made)
    last = run_flow(made, "review")
    first, second, third = runs_of(made, last.performance_id)
    [(_, started), *_] = events(made, second)
    assert started["workspace"]["builtOn"] == first
    [(_, started3), *_] = events(made, third)
    assert started3["workspace"]["builtOn"] == second
    ended = dict(events(made, second))["Run.Ended"]
    assert "diff" in ended["changes"]
    assert "sofar" in ended["changes"]
    # The step before's worktree is gone once the next was made from it.
    for run_id in (first, second, third):
        assert not worktree_path(repo.path, run_id).exists()


def test_a_steps_own_diff_omits_the_earlier_work_and_the_theatre_is_untouched_mid_flow(
    repo: Repo,
) -> None:
    before = (repo.path / "src" / "a.txt").read_bytes()
    made = _Watching(repo)
    three_steps(made)
    last = run_flow(made, "review")
    # While each step ran, the person's files were as they were before the flow.
    assert made.theatre == [before, before, before]
    # Each later step's worktree holds the writer's file when its runner starts (the writer's own
    # is read after it may have written it, so it proves nothing).
    assert made.worktree[1:] == [b"from the writer\n", b"from the writer\n"]
    _, second, _ = runs_of(made, last.performance_id)
    artifacts = load_store("local", repo.path / ".troupe" / "local" / "artifacts")
    changes = dict(events(made, second))["Run.Ended"]["changes"]
    own = artifacts.read(changes["diff"])
    assert b"src/b.txt" in own
    assert b"src/a.txt" not in own
    sofar = artifacts.read(changes["sofar"])
    assert b"src/a.txt" in sofar
    assert b"src/b.txt" in sofar


def test_a_rehearsal_refused_by_the_second_step_records_nothing(repo: Repo) -> None:
    made = Harness(repo)
    actor(made, "writer", INIT, OK)
    actor(made, "keyless", INIT, OK, runtime="openai", model="gpt-test")
    flow(made, "two", [{"actor": "writer"}, {"actor": "keyless"}])
    made.env = {k: v for k, v in made.env.items() if k != "OPENAI_API_KEY"}
    before = [line["topic"] for line in recorded_lines(repo.path)]
    parsed = m.PerformRequest.from_data({"actor": "two", "rehearse": True})
    with pytest.raises(TroupeError) as refused:
        asyncio.run(perform(parsed, made.session(), made.send, backends=made.backends()))
    assert refused.value.code == "runtime.credential-unset"
    assert [line["topic"] for line in recorded_lines(repo.path)] == before
    assert not [u for u in made.updates if u.get("kind") in ("performance-started", "started")]


# Requirement: Before the last step, approving lets the work go on


def test_troupe_lets_each_earlier_step_through_at_once_recording_its_approval(
    repo: Repo,
) -> None:
    made = Harness(repo)
    three_steps(made)
    last = run_flow(made, "review")
    first, *_ = runs_of(made, last.performance_id)
    history = events(made, first)
    topics = [t for t, _ in history]
    assert topics[-2:] == ["Run.Ended", "Run.ChangesApproved"]
    approved = history[-1][1]
    assert approved["role"] == "troupe"
    [approval] = approved["_lineage"]["approvals"]
    assert approval["role"] == "troupe"
    assert approved["_lineage"]["performance"] == last.performance_id


def test_a_step_that_changes_nothing_reaches_no_gate_and_the_next_goes_on(repo: Repo) -> None:
    made = Harness(repo)
    actor(made, "looker", INIT, OK)
    actor(made, "writer", INIT, write("src/a.txt", "written\n"), OK)
    flow(made, "look", [{"actor": "looker"}, {"actor": "writer"}])
    last = run_flow(made, "look")
    first, _second = runs_of(made, last.performance_id)
    assert "Run.ChangesApproved" not in [t for t, _ in events(made, first)]
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "written\n"


@pytest.mark.parametrize("approvers", [None, ["director"]], ids=["troupe first", "person first"])
def test_a_middle_step_that_changes_nothing_reaches_no_gate_and_the_last_step_runs(
    repo: Repo, approvers: list[str] | None
) -> None:
    before = (repo.path / "src" / "a.txt").read_bytes()
    made = _Watching(repo)
    actor(made, "writer", INIT, write("src/a.txt", "written\n"), OK)
    actor(made, "looker", INIT, OK)
    actor(made, "tester", INIT, write("src/c.txt", "tested\n"), OK)
    looker: dict[str, Any] = {"actor": "looker"}
    if approvers is not None:
        looker["approvers"] = approvers
    flow(made, "look", [{"actor": "writer"}, looker, {"actor": "tester"}])
    last = run_flow(made, "look")
    _, middle, third = runs_of(made, last.performance_id)
    assert last.run_id == third
    # Nothing reached the person's files before the last step ran.
    assert made.theatre == [before, before, before]
    middle_events = events(made, middle)
    topics = [t for t, _ in middle_events]
    assert "Run.ChangesApproved" not in topics
    assert "Run.CueRaised" not in topics
    assert "sofar" not in dict(middle_events)["Run.Ended"]["changes"]
    # The last step was built on the writer's work, and its gate landed both.
    [(_, started), *_] = events(made, third)
    assert started["workspace"]["builtOn"] == middle
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "written\n"
    assert (repo.path / "src" / "c.txt").read_text(encoding="utf-8") == "tested\n"
    *_, (ended, end) = events(made, last.performance_id)
    assert ended == "Performance.Ended"
    assert end["outcome"] == "completed"


def test_a_person_first_between_steps_stops_the_flow_waiting_at_that_steps_gate(
    repo: Repo,
) -> None:
    made = Harness(repo)
    three_steps(made)
    flow(
        made,
        "review",
        [
            {"actor": "writer", "approvers": ["director"]},
            {"actor": "reviewer"},
            {"actor": "tester"},
        ],
    )
    last = run_flow(made, "review")
    assert last.step == 1
    assert last.changes is not None
    assert last.changes.state == "waiting"
    assert len(runs_of(made, last.performance_id)) == 1
    [(_, start), *_] = events(made, last.run_id)
    assert start["approvers"] == {"value": ["director"], "source": "step"}
    # The performance waits with its step: it isn't ended.
    assert "Performance.Ended" not in [t for t, _ in events(made, last.performance_id)]


# Requirement: The last step's gate lands the whole flow


def test_the_last_steps_gate_is_reached_with_only_the_earlier_steps_work(repo: Repo) -> None:
    made = Harness(repo)
    actor(made, "writer", INIT, write("src/a.txt", "written\n"), OK)
    actor(made, "checker", INIT, OK)
    flow(made, "check", [{"actor": "writer"}, {"actor": "checker"}])
    last = run_flow(made, "check")
    assert last.changes is not None
    assert last.changes.state == "accepted"
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "written\n"


def test_a_failed_step_stops_the_flow_and_ends_the_performance_failed(repo: Repo) -> None:
    made = Harness(repo)
    actor(made, "writer", INIT, write("src/a.txt", "written\n"), OK)
    actor(made, "breaker", INIT, FAIL)
    actor(made, "tester", INIT, OK)
    flow(made, "broken", [{"actor": "writer"}, {"actor": "breaker"}, {"actor": "tester"}])
    last = run_flow(made, "broken")
    assert last.step == 2
    assert last.outcome == "failed"
    assert len(runs_of(made, last.performance_id)) == 2
    *_, (ended, end) = events(made, last.performance_id)
    assert ended == "Performance.Ended"
    assert end["outcome"] == "failed"
    # Nothing reached the person's files: a stopped flow's work waits to be settled whole.
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") != "written\n"


# Requirement: A step is told the performance's direction, its own, and the step before


def test_a_step_is_told_the_direction_its_own_and_the_step_before(repo: Repo) -> None:
    made = Harness(repo)
    three_steps(made)
    last = run_flow(made, "review", "Add the feature.")
    first, second, third = runs_of(made, last.performance_id)
    assert direction_of(made, first) == "Add the feature."
    told = direction_of(made, second)
    assert told.startswith("Add the feature.\n\nReview what the writer changed.")
    assert "Step 1, writer: succeeded." in told
    assert "Files it changed: src/a.txt." in told
    assert "What it said last: done" in told
    told3 = direction_of(made, third)
    assert "Step 2, reviewer: succeeded." in told3
    assert "1 writer, succeeded, 1 file: .troupe/performance/1-writer/" in told3
    assert "2 reviewer, succeeded, 1 file: .troupe/performance/2-reviewer/" in told3


# Requirement: Earlier steps' history is readable in each step's worktree


class _Watching(Recording):
    """Records what the history folder holds when each step's runner starts."""

    seen: list[list[str]]

    def __init__(self, repo: Repo) -> None:
        super().__init__(repo)
        self.seen = []
        self.held = []
        self.theatre = []
        self.worktree = []
        self.files: dict[str, bytes] = {}
        self.on_running = self._look

    def _look(self) -> None:
        [run_id] = [u["runId"] for u in self.updates if u.get("kind") == "started"][-1:]
        folder = worktree_path(self.repo.path, run_id) / ".troupe" / "performance"
        self.seen.append(
            sorted(
                str(p.relative_to(folder)).replace("\\", "/")
                for p in folder.rglob("*")
                if p.is_file()
            )
            if folder.exists()
            else []
        )
        self.theatre.append((self.repo.path / "src" / "a.txt").read_bytes())
        self.worktree.append((worktree_path(self.repo.path, run_id) / "src" / "a.txt").read_bytes())
        if folder.exists():
            self.held.extend(p.read_bytes() for p in folder.rglob("*") if p.is_file())
            self.files.update(
                {
                    str(p.relative_to(folder)).replace("\\", "/"): p.read_bytes()
                    for p in folder.rglob("*")
                    if p.is_file()
                }
            )
            brief = folder / "1-writer" / "brief.md"
            if brief.exists():
                self.brief = brief.read_text(encoding="utf-8")

    brief = ""
    held: list[bytes]
    theatre: list[bytes]
    worktree: list[bytes]


def test_each_step_can_read_the_earlier_steps_brief_diff_and_log(repo: Repo) -> None:
    made = _Watching(repo)
    three_steps(made)
    run_flow(made, "review")
    assert made.seen[0] == []
    assert made.seen[1] == ["1-writer/brief.md", "1-writer/changes.diff", "1-writer/log.md"]
    assert made.seen[2] == [
        "1-writer/brief.md",
        "1-writer/changes.diff",
        "1-writer/log.md",
        "2-reviewer/brief.md",
        "2-reviewer/changes.diff",
        "2-reviewer/log.md",
    ]
    assert made.brief.startswith("Step 1, writer: succeeded.")


def test_history_files_never_reach_the_theatre_or_a_diff(repo: Repo) -> None:
    made = Harness(repo)
    three_steps(made)
    last = run_flow(made, "review")
    assert not (repo.path / ".troupe" / "performance").exists()
    artifacts = load_store("local", repo.path / ".troupe" / "local" / "artifacts")
    ended = dict(events(made, last.run_id))["Run.Ended"]
    assert b".troupe/performance" not in artifacts.read(ended["changes"]["sofar"])


def test_a_credential_an_earlier_step_printed_is_masked_in_the_history_a_later_step_reads(
    repo: Repo,
) -> None:
    key = "sk-test/canary-0123456789abcdef"
    made = _Watching(repo)
    made.env = {**made.env, "OPENAI_API_KEY": key}
    runtime = {"runtime": "openai", "model": "gpt-test"}
    actor(made, "writer", INIT, {"echoCredential": True}, write("src/a.txt", "x\n"), OK, **runtime)
    actor(made, "reader", INIT, OK)
    flow(made, "leak", [{"actor": "writer"}, {"actor": "reader"}])
    run_flow(made, "leak")
    assert made.held, "the second step's worktree held history files"
    joined = b"".join(made.held)
    assert MARKER.encode() in joined
    for part in (key, key[:10], key[10:]):
        assert part.encode() not in joined


def test_each_history_file_holds_the_earlier_steps_brief_diff_and_log(repo: Repo) -> None:
    made = _Watching(repo)
    three_steps(made)
    last = run_flow(made, "review")
    first, *_ = runs_of(made, last.performance_id)
    artifacts = load_store("local", repo.path / ".troupe" / "local" / "artifacts")
    ended = dict(events(made, first))["Run.Ended"]
    assert made.files["1-writer/changes.diff"] == artifacts.read(ended["changes"]["diff"])
    assert made.files["1-writer/brief.md"] == (
        b"Step 1, writer: succeeded.\nFiles it changed: src/a.txt.\nWhat it said last: done\n"
    )
    log = made.files["1-writer/log.md"].decode("utf-8")
    assert "init" in log
    assert "result" in log


def test_a_steps_audit_judges_only_its_own_changes(repo: Repo) -> None:
    made = Harness(repo)
    actor(made, "writer", INIT, write("src/a.txt", "written\n"), OK)
    # May write only src/b.txt: the writer's src/a.txt, already in its worktree, isn't its effect.
    actor(
        made,
        "narrow",
        INIT,
        write("src/b.txt", "narrow\n"),
        OK,
        effects={"write": ["src/b.txt"]},
    )
    flow(made, "narrowed", [{"actor": "writer"}, {"actor": "narrow"}])
    last = run_flow(made, "narrowed")
    assert last.outcome == "succeeded"
    assert (repo.path / "src" / "b.txt").read_text(encoding="utf-8") == "narrow\n"


def test_a_flows_rehearsal_shows_every_step_and_records_nothing(repo: Repo) -> None:
    made = Harness(repo)
    three_steps(made)
    flow(
        made,
        "review",
        [
            {"actor": "writer"},
            {"actor": "reviewer", "direction": "Review it.", "approvers": ["director"]},
            {"actor": "tester"},
        ],
    )
    before = [line["topic"] for line in recorded_lines(repo.path)]
    parsed = m.PerformRequest.from_data({"actor": "review", "rehearse": True})
    result = asyncio.run(perform(parsed, made.session(), made.send, backends=made.backends()))
    rehearsal = result.rehearsal
    assert rehearsal is not None
    assert rehearsal.flow == "review"
    assert rehearsal.steps is not None
    assert [step.actor for step in rehearsal.steps] == ["writer", "reviewer", "tester"]
    assert rehearsal.actor == "writer"
    approvers = rehearsal.steps[1].approvers
    assert approvers is not None
    assert approvers.to_data() == {"value": ["director"], "source": "step"}
    # Each step's direction is its own on top of the flow's, so they differ.
    directions = [step.direction for step in rehearsal.steps]
    assert directions[1] != directions[0]
    assert [line["topic"] for line in recorded_lines(repo.path)] == before
