"""perform runs an ollama actor end to end, against a stand-in Ollama serving the plugin's
success-with-tools fixture (spec: runs, ollama-runner; local-model-runner task 8.6)."""

import json
from pathlib import Path
from uuid import UUID

import ollama_stand_in
from runtesting import Harness, request, theatre
from troupe.core.runs.aggregate import REPORTED

FIXTURE = "success-with-tools"


def test_an_ollama_actor_succeeds_records_the_runner_and_the_engine_and_writes_its_file(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path / "theatre"))
    provenance = ollama_stand_in.provenance(FIXTURE)
    with ollama_stand_in.serving(FIXTURE) as fake:
        run = harness.perform(
            request(
                {**provenance["options"], "endpoint": fake.url},
                runner="ollama",
                direction=provenance["direction"],
                effects=provenance["effects"],
                effectCheck={"kind": "files", "paths": ["out/hello.txt"]},
            )
        ).run
    assert run.outcome == "succeeded"
    assert run.runner.reported is not None
    assert run.runner.reported.name == "ollama"
    reported = [
        json.loads(r.state)["event"]
        for r in harness.stores[0].history(UUID(run.run_id))
        if r.topic == REPORTED
    ]
    assert reported[0]["engine"] == {
        "name": "ollama",
        "version": provenance["ollamaVersion"],
        "model": provenance["model"],
    }
    assert reported[-1]["type"] == "result"
    written = harness.repo.path / "out" / "hello.txt"
    assert written.read_text(encoding="utf-8").startswith("hello")
