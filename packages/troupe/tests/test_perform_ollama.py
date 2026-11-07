"""perform runs an ollama actor end to end, against a stand-in Ollama serving the plugin's
success-with-tools fixture (spec: runs, ollama-runner; local-model-runner task 8.6). The actor names
the built-in ollama runtime, which the theatre points at the stand-in (ollama-uses-runtime D7)."""

import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import jsonschema
import pytest

import ollama_stand_in
from runtesting import Harness, request, theatre
from test_perform import configured, nothing_written
from troupe.core import interim
from troupe.core.errors import TroupeError
from troupe.core.runs.aggregate import REPORTED, STARTED

FIXTURE = "success-with-tools"


def test_an_ollama_actor_succeeds_records_the_runner_and_the_engine_and_writes_its_file(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path / "theatre"))
    provenance = ollama_stand_in.provenance(FIXTURE)
    with ollama_stand_in.serving(FIXTURE) as fake:
        run = harness.perform(
            request(
                provenance["options"],
                runner="ollama",
                runtime="ollama",
                model=provenance["model"],
                runtimes={"ollama": {"endpoint": fake.url}},
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
    [start] = [
        json.loads(r.state)
        for r in harness.stores[0].history(UUID(run.run_id))
        if r.topic == STARTED
    ]
    # Spec: runs, "The Ollama runner": the run's start records the runtime and the actor's model.
    assert start["runtime"] == {
        "name": "ollama",
        "endpoint": {"value": fake.url, "source": "theatre"},
        "model": {"value": provenance["model"], "source": "actor"},
    }


def test_an_ollama_actor_recorded_with_its_model_as_an_option_isnt_performed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spec: runtimes, "The model the audition used to write" (ollama-uses-runtime design D5).
    harness = Harness(theatre(tmp_path / "theatre"))
    old = request({"model": "qwen3:4b"}, runner="ollama")
    with monkeypatch.context() as then:  # recorded under the rules before the options moved
        then.setitem(interim.RUNNERS, "ollama", replace(interim.RUNNERS["ollama"], runtime="none"))
        then.setattr(interim, "MOVED_TO_RUNTIME", {})
        then.setattr(interim, "options_validator", lambda name: jsonschema.Draft202012Validator({}))
        before = configured(harness, old)
    with pytest.raises(TroupeError) as caught:
        harness.perform(old)
    assert caught.value.code == "config.invalid"
    assert caught.value.details["path"] == ["actors", "tester", "options", "model"]
    assert caught.value.fix == (
        "Move it in one change: troupe config set actors.tester.runtime=ollama "
        "actors.tester.model=qwen3:4b 'actors.tester.options={}'"
    )
    assert nothing_written(harness, before)
