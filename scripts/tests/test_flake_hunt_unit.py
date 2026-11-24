"""How scripts/flake_hunt.py sets up its rounds, checked without running a hunt (spec: flake-hunt):
--workers auto is three quarters of the usable CPUs less the load and at least one, a round's
environment is the hunt's plus only its own Hypothesis directory, a round sets the stall limit
only when the hunt is given one, and a log that isn't UTF-8 is shown escaped.

Its tests that start a process, open a socket or use a git theatre are in
integration/test_flake_hunt.py."""

import os
from pathlib import Path

import pytest

import flake_hunt


def test_workers_auto_is_three_quarters_of_the_usable_cpus_less_the_load_and_at_least_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = (
        (8, 0, 6),
        (8, 2, 4),
        (10, 0, 7),
        (10, 2, 5),
        (4, 0, 3),
        (4, 3, 1),
        (1, 0, 1),
        (2, 1, 1),
    )
    for cpus, load, workers in cases:
        monkeypatch.setattr(flake_hunt, "usable_cpus", lambda cpus=cpus: cpus)
        chosen = flake_hunt.parse_options(
            ["--root", str(tmp_path), "--workers", "auto", "--load", str(load)]
        )
        assert chosen.workers == workers, (cpus, load)
    assert flake_hunt.parse_workers("5") == 5
    with pytest.raises(Exception, match="--workers must be a whole number, 1 or more, or auto"):
        flake_hunt.parse_workers("lots")


def test_a_round_gets_the_hunts_environment_plus_only_its_hypothesis_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A hunt's own tests can run inside a hunt's round, which already has the variable set.
    monkeypatch.delenv("HYPOTHESIS_STORAGE_DIRECTORY", raising=False)
    options = flake_hunt.parse_options(["--root", str(tmp_path), "--out", str(tmp_path / "out")])
    env = flake_hunt.round_environment(options, "w0r0")
    assert {name: value for name, value in env.items() if name in os.environ} == dict(os.environ)
    assert set(env) - set(os.environ) == {"HYPOTHESIS_STORAGE_DIRECTORY"}
    assert env["HYPOTHESIS_STORAGE_DIRECTORY"] == str(tmp_path / "out" / "hypothesis" / "w0r0")


def test_a_round_leaves_the_stall_limit_to_the_configuration_unless_the_hunt_is_given_one(
    tmp_path: Path,
) -> None:
    # The limit is set once, in pyproject.toml (spec: quality-check; windows-ci-hang design D1).
    base = ["--root", str(tmp_path), "--out", str(tmp_path / "out")]
    report = tmp_path / "report.xml"

    unset = flake_hunt.round_command(flake_hunt.parse_options(base), tmp_path, report)
    given = flake_hunt.round_command(
        flake_hunt.parse_options([*base, "--stall", "60"]), tmp_path, report
    )

    assert not any(part.startswith("faulthandler_timeout=") for part in unset)
    assert given[given.index("faulthandler_timeout=60") - 1] == "-o"


def test_output_that_isnt_utf_8_is_kept_as_bytes_and_shown_escaped(tmp_path: Path) -> None:
    log = tmp_path / "w0r0.log"
    log.write_bytes(b"before \xff\xfe after\n")
    assert flake_hunt.tail(log) == "before \\xff\\xfe after\n"
