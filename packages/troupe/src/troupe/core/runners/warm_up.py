"""Warming a runner's engine outside any run (in-process-runner design D4; owner, 2026-11-14).

A runner whose table entry names ``warm_up`` arguments has work its engine can do once, before its
first run, so the run starts quickly: the mistralrs runner loads its check model, which compiles
mistral.rs's Metal kernels into macOS's cache. ``troupe init --audition`` runs it once, after
defining the actor. The runner's own check at the start of each run stays as the backstop.

The runner is started with its command and those arguments, its environment as a run's would be,
bounded by RUNNER_WARM_UP_TIMEOUT_SECONDS. It writes one JSON line: ``{"warmedUp": true,
"seconds": ...}``, ``{"warmedUp": false}`` when there's nothing to warm on this platform, or
``{"error": {...}}`` with the error its run-time check would refuse a run with. A warm-up that's cut
off keeps what it did: macOS caches each compiled library as it goes, so the next load, the first
run's check, picks up where it stopped (measured on #414).
"""

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from troupe.core import defaults, interim
from troupe.core.notices import Notice
from troupe.platform import processes
from troupe.platform.errors import OutputTooLargeError, PlatformError, ProcessTimeoutError


def warming(runner: str) -> Notice:
    """The notice that the warm-up has started, so nobody waits on it silently: it can take tens
    of seconds, and up to RUNNER_WARM_UP_TIMEOUT_SECONDS."""
    return Notice(
        "runner.warming-up",
        problem=f"Preparing the {runner} runner's engine, so its first run starts quickly. The "
        f"first time on this machine this can take a minute; it stops after "
        f"{defaults.RUNNER_WARM_UP_TIMEOUT_SECONDS:g}s.",
        fix="Nothing to do: wait for it.",
        details={"runner": runner},
    )


def _answer(stdout: bytes) -> dict[str, Any] | None:
    """The runner's one JSON line, or None when it wrote something else."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    try:
        data = json.loads(lines[0])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def warm_up(
    runner: str,
    cwd: Path,
    env: Mapping[str, str],
    *,
    timeout: float = defaults.RUNNER_WARM_UP_TIMEOUT_SECONDS,
) -> list[Notice]:
    """Warm ``runner``'s engine, if it has a warm-up: the notices that say how it went. Nothing for
    a runner without one, or one with nothing to warm on this platform. It blocks."""
    entry = interim.runner(runner)
    if not entry.warm_up:
        return []
    argv = [*interim.runner_command(runner), *entry.warm_up]
    later = (
        f"The runner's check at the start of the {runner} actor's first run finishes it; if that "
        "run passes troupe's start limit, perform it again: each try keeps what the last one "
        "compiled."
    )
    try:
        done = processes.run_to_completion(
            argv,
            cwd=cwd,
            env=interim.runner_environment(runner, env),
            timeout=timeout,
            max_output_bytes=defaults.RUNNER_WARM_UP_OUTPUT_MAX_BYTES,
            announce_after=timeout,
        )
    except ProcessTimeoutError:
        return [
            Notice(
                "runner.warm-up-cut-off",
                problem=f"Preparing the {runner} runner's engine took longer than {timeout:g}s "
                "(RUNNER_WARM_UP_TIMEOUT_SECONDS), so it was stopped.",
                fix=later,
                details={"runner": runner, "seconds": timeout},
            )
        ]
    except (OutputTooLargeError, PlatformError) as failure:
        return [
            Notice(
                "runner.warm-up-failed",
                problem=f"The {runner} runner couldn't prepare its engine: {failure}.",
                fix=later,
                details={"runner": runner},
            )
        ]
    answer = _answer(done.stdout)
    if answer is not None and answer.get("warmedUp") is False and done.returncode == 0:
        return []
    if answer is not None and answer.get("warmedUp") is True and done.returncode == 0:
        seconds = answer.get("seconds")
        took: float = 0
        # A boolean is an int, and json reads Infinity: neither is a time.
        if (
            isinstance(seconds, int | float)
            and not isinstance(seconds, bool)
            and math.isfinite(seconds)
            and seconds >= 0
        ):
            took = seconds
        return [
            Notice(
                "runner.warmed-up",
                problem=f"Prepared the {runner} runner's engine in {took:g}s, so its first run "
                "starts quickly.",
                fix="Nothing to do.",
                details={"runner": runner, "seconds": took},
            )
        ]
    given = answer.get("error") if answer is not None else None
    if isinstance(given, dict) and isinstance(given.get("problem"), str):
        fix = given.get("fix") if isinstance(given.get("fix"), str) else later
        details: dict[str, Any] = {"runner": runner}
        if isinstance(given.get("code"), str):
            details["code"] = given["code"]
        return [
            Notice(
                "runner.warm-up-failed",
                problem=f"The {runner} runner can't run here: {given['problem']}",
                fix=str(fix),
                details=details,
            )
        ]
    return [
        Notice(
            "runner.warm-up-failed",
            problem=f"The {runner} runner's warm-up exited {done.returncode} without saying how it "
            "went.",
            fix=later,
            details={"runner": runner},
        )
    ]
