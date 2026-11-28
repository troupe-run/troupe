"""Helpers that test_run_notices.py shares with other test modules."""

from uuid import uuid4

from runtesting import INIT, PERFORMANCE, STAGE, Harness
from storetesting import git_service
from troupe.core.runs.aggregate import (
    Run,
)
from troupe.core.runs.perform import lease_dir

# Requirement: Status reads runs from a projection (a run's recorded notices)

SILENT = {
    "code": "run.silent",
    "problem": "The run has sent no event for 30s.",
    "fix": "Wait, or cancel the run if it seems stuck.",
    "details": {"seconds": 30.0},
}


def interrupted_with_a_notice(harness: Harness) -> str:
    """A run whose start, init and a run.silent notice are recorded, with no end, and whose lease
    in this clone nobody holds: its perform was killed after it fell silent."""
    store = git_service(harness.repo)
    run_id = str(uuid4())
    run = Run(
        run_id=run_id,
        actor="tester",
        runner_requested="scripted",
        stage=STAGE,
        effect_check={"kind": "none"},
        direction="sha256:" + "a" * 64,
        config=["sha256:" + "b" * 64],
        workspace={"kind": "theatre"},
        on_context_full={"value": "fail", "source": "default"},
        step=1,
    )
    person = store.command(via="cli", performance=PERFORMANCE)
    person.record(run.collect_events())
    run.report(0, {**INIT["event"], "effects": "checked", "runId": run_id, "seq": 0})
    store.command(via="runner", performance=PERFORMANCE).record(run.collect_events())
    run.notice(SILENT)
    person.record(run.collect_events())
    lease_dir(harness.repo.path, run_id).mkdir(parents=True)
    return run_id
