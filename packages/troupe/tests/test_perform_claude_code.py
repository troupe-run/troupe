"""perform runs a claude-code actor end to end, with a stand-in claude first on PATH (spec: runs;
claude-code-runner design D12)."""

import json
from pathlib import Path
from uuid import UUID

import claude_stand_in
from runtesting import Harness, request, theatre
from troupe.core.runs.aggregate import REPORTED

FAKE_SECRET = "s3cret"  # noqa: S105 - a stand-in value, checked for where it never arrives


def test_a_claude_code_actor_succeeds_and_records_the_runner_and_the_engine(
    tmp_path: Path,
) -> None:
    record = tmp_path / "record.json"
    bin_dir = tmp_path / "bin"
    claude_stand_in.install(
        bin_dir, fixture=claude_stand_in.fixture("success-with-tools"), record=str(record)
    )
    harness = Harness(theatre(tmp_path / "theatre"))
    harness.env = {**harness.env, "PATH": str(bin_dir), "AWS_SECRET_ACCESS_KEY": FAKE_SECRET}
    run = harness.perform(request({}, runner="claude-code")).run
    assert run.outcome == "succeeded"
    assert run.runner.reported is not None
    assert (run.runner.reported.name, run.runner.reported.version) == ("claude-code", "0.0.1.dev0")
    reported = [
        json.loads(r.state)["event"]
        for r in harness.stores[0].history(UUID(run.run_id))
        if r.topic == REPORTED
    ]
    assert reported[0]["engine"] == {
        "name": "claude-code",
        "version": "2.1.296",
        "model": "claude-haiku-5-5",
    }
    assert reported[-1]["type"] == "result"
    seen = claude_stand_in.wait_for_record(record, "env")["env"]
    assert seen["PATH"] == str(bin_dir)
    assert "AWS_SECRET_ACCESS_KEY" not in seen
