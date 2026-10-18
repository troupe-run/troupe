"""scripts/flake_campaign.py (spec: flake-hunt, the campaign requirements; design D11)."""

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from conftest import git

import flake_campaign
from flake_campaign import CampaignError, Hunt

ROOT = flake_campaign.ROOT
SCRIPT = Path(flake_campaign.__file__)
WINDOWS = sys.platform == "win32"
RUNNING = f"{sys.version_info.major}.{sys.version_info.minor}"


def options(*argv: str) -> flake_campaign.Options:
    return flake_campaign.parse_options(list(argv))


# Requirement: The agreed campaign runs from one command


def test_the_campaigns_python_versions_are_every_supported_version() -> None:
    import python_versions

    assert options().pythons == tuple(python_versions.supported(ROOT))


def test_a_malformed_bound_is_refused_before_anything_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import python_versions

    def malformed(root: Path) -> list[str]:
        raise python_versions.BoundError('pyproject.toml has requires-python = ">=3.12": ...')

    monkeypatch.setattr(python_versions, "supported", malformed)
    with pytest.raises(SystemExit) as refused:
        options()
    assert refused.value.code == 2
    assert 'requires-python = ">=3.12"' in capsys.readouterr().err


def test_the_plan_is_every_python_by_every_load_direct_then_in_docker() -> None:
    plan = options("--pythons", "3.12,3.13", "--loads", "0,2", "--docker").hunts()
    assert [hunt.name for hunt in plan] == [
        "direct-3.12-load0",
        "direct-3.12-load2",
        "direct-3.13-load0",
        "direct-3.13-load2",
        "docker-3.12-load0",
        "docker-3.12-load2",
        "docker-3.13-load0",
        "docker-3.13-load2",
    ]
    assert [hunt.name for hunt in options("--pythons", "3.12", "--loads", "2").hunts()] == [
        "direct-3.12-load2"
    ]


def test_docker_only_runs_just_the_docker_hunts_and_refuses_beside_docker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = options("--pythons", "3.12,3.13", "--loads", "0,2", "--docker-only").hunts()
    assert [hunt.name for hunt in plan] == [
        "docker-3.12-load0",
        "docker-3.12-load2",
        "docker-3.13-load0",
        "docker-3.13-load2",
    ]
    with pytest.raises(SystemExit) as refused:
        options("--docker", "--docker-only")
    assert refused.value.code == 2
    assert "not allowed with argument --docker" in capsys.readouterr().err


@pytest.mark.usefixtures("a_dir_that_exists")
def test_the_command_lines_are_what_the_design_says(tmp_path: Path) -> None:
    chosen = options(
        *["--pythons", "3.13", "--workers", "3", "--environments", str(tmp_path)],
        "a_dir_that_exists",
    )
    hunt = Hunt("3.13", 2, docker=False)
    python = tmp_path / "3.13" / ("Scripts/python.exe" if WINDOWS else "bin/python")
    out = tmp_path / "out"
    assert flake_campaign.direct_command(chosen, hunt, out) == [
        str(python),
        str(chosen.root / "scripts" / "flake_hunt.py"),
        "--out",
        str(out),
        *["--workers", "3", "--rounds", "10", "--load", "2", "a_dir_that_exists"],
    ]
    assert flake_campaign.sync_command("uv", hunt) == ["uv", "sync", "--locked", "--python", "3.13"]
    docker = Hunt("3.13", 0, docker=True)
    assert flake_campaign.build_command("docker", docker) == [
        *["docker", "build", "--quiet", "--tag", "troupe-hunt:3.13"],
        *["--build-arg", "PY=3.13", "--file", "scripts/flake_hunt.Dockerfile", "-"],
    ]
    name = flake_campaign.container("20261015t101500z", docker)
    assert name == "flake-campaign-20261015t101500z-docker-3-13-load0"
    assert flake_campaign.docker_command("docker", chosen, docker, name) == [
        *["docker", "run", "--init", "--name", name, "troupe-hunt:3.13"],
        *["--workers", "3", "--rounds", "10", "--load", "0", "a_dir_that_exists"],
    ]


@pytest.fixture
def a_dir_that_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A test path the command-line test can name: paths are checked against the root."""
    (tmp_path / "a_dir_that_exists").mkdir()
    monkeypatch.setattr(flake_campaign, "ROOT", tmp_path)
    monkeypatch.setattr(flake_campaign, "supported_pythons", lambda root: ["3.12", "3.13"])


def test_uncommitted_changes_are_listed_and_refuse_a_docker_campaign(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet", "--initial-branch=main")
    (repo / "kept.txt").write_text("one\n")
    git(repo, "add", "kept.txt")
    git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "one")
    (repo / "kept.txt").write_text("two\n")
    (repo / "new.txt").write_text("new\n")
    head, changes = flake_campaign.commit("git", repo)
    assert len(head) == 40
    assert sorted(changes) == [" M kept.txt", "?? new.txt"]
    with pytest.raises(CampaignError) as refused:
        flake_campaign.require_committed(changes)
    assert "kept.txt" in str(refused.value)
    assert "new.txt" in str(refused.value)
    assert "git stash --include-untracked" in str(refused.value)
    flake_campaign.require_committed([])


# Requirement: The campaign's selection is the OS-sensitive tests, named in one place


@pytest.mark.parametrize("pattern", flake_campaign.SELECTION)
def test_each_selection_pattern_matches_something_in_the_repository(pattern: str) -> None:
    assert flake_campaign.expand(Path(flake_campaign.__file__).resolve().parents[1], [pattern])


def test_a_pattern_that_matches_nothing_is_refused_naming_it(tmp_path: Path) -> None:
    with pytest.raises(CampaignError, match=r"'tests/test_gone_\*\.py' matches nothing"):
        flake_campaign.expand(tmp_path, ["tests/test_gone_*.py"])


def test_a_new_platform_test_file_is_selected_without_an_edit(tmp_path: Path) -> None:
    tests = tmp_path / "packages" / "troupe" / "tests"
    tests.mkdir(parents=True)
    for name in ("test_platform_files.py", "test_platform_brand_new.py", "test_other.py"):
        (tests / name).write_text("")
    assert flake_campaign.expand(tmp_path, ["packages/troupe/tests/test_platform_*.py"]) == [
        "packages/troupe/tests/test_platform_brand_new.py",
        "packages/troupe/tests/test_platform_files.py",
    ]


# Requirement: The campaign reports every hunt together


def run_a_hunt(tmp_path: Path, files: dict[str, str], rounds: int) -> Path:
    """A real hunt's results, from flake_hunt.py itself, for the report to read."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\n")
    for name, text in files.items():
        (root / name).write_text(textwrap.dedent(text), encoding="utf-8")
    out = tmp_path / "hunt"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT.parent / "flake_hunt.py"),
            *["--root", str(root), "--out", str(out), "--rounds", str(rounds)],
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    return out


def test_the_report_names_each_hunt_its_failing_tests_and_the_commit(tmp_path: Path) -> None:
    counter = tmp_path / "count"
    flaky = f"""
    from pathlib import Path

    def test_fails_on_its_second_run():
        counter = Path({str(counter)!r})
        runs = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(runs + 1))
        assert runs == 0, "the second run"
    """
    out = run_a_hunt(tmp_path, {"test_flaky.py": flaky}, rounds=2)
    found = flake_campaign.outcome_of(Hunt("3.12", 2, docker=False), 1, out)
    clean = flake_campaign.Outcome(Hunt("3.12", 0, docker=False), "clean", 0, None)
    missing = flake_campaign.outcome_of(Hunt("3.13", 0, docker=True), 125, tmp_path / "none")
    assert (found.status, missing.status) == ("failed", "didn't run")
    data = flake_campaign.report_data(
        options("--pythons", "3.12,3.13"), [clean, found, missing], "a" * 40, [], False
    )
    report = flake_campaign.report_markdown(data)
    assert f"at `{'a' * 12}`" in report
    assert "| direct-3.12-load0 |" in report
    assert "| direct-3.12-load2 |" in report
    assert "| docker-3.13-load0 |" in report
    assert "didn't run: the hunt exited 125 with no summary" in report
    assert "`test_flaky.py::test_fails_on_its_second_run` failed in 1 of 2 runs" in report
    assert "the second run" in report
    assert json.loads(json.dumps(data))["hunts"][1]["summary"]["tests"][0]["failures"] == 1


# End to end: one direct campaign, and one stopped part-way


@pytest.fixture(scope="module")
def environments(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Where the end-to-end campaigns' environments live: synced once, never the repo's."""
    return tmp_path_factory.mktemp("environments")


def campaign_command(environments: Path, out: Path, root: Path, *args: str) -> list[str]:
    return [
        sys.executable,
        str(SCRIPT),
        *["--pythons", RUNNING, "--workers", "1", "--rounds", "1"],
        *["--environments", str(environments), "--out", str(out), "--hunt-root", str(root)],
        *args,
    ]


def make_tests_root(tmp_path: Path, text: str) -> Path:
    root = tmp_path / "tests-root"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\n")
    (root / "test_it.py").write_text(textwrap.dedent(text), encoding="utf-8")
    return root


def test_a_direct_campaign_runs_end_to_end_into_a_report(
    tmp_path: Path, environments: Path
) -> None:
    venv_before = (
        sorted(p.name for p in (ROOT / ".venv").glob("*")) if (ROOT / ".venv").exists() else []
    )
    root = make_tests_root(tmp_path, "def test_passes():\n    pass\n")
    out = tmp_path / "out"
    completed = subprocess.run(
        campaign_command(environments, out, root, "--loads", "0", "test_it.py"),
        cwd=SCRIPT.parent.parent,
        capture_output=True,
        timeout=600,
        check=False,
    )
    output = completed.stdout.decode("utf-8", errors="backslashreplace")
    assert completed.returncode == 0, output + completed.stderr.decode(errors="backslashreplace")
    report = (out / "report.md").read_text(encoding="utf-8")
    assert f"| direct-{RUNNING}-load0 |" in report
    assert "| clean |" in report
    assert (environments / RUNNING).is_dir()
    data = json.loads((out / "campaign.json").read_text(encoding="utf-8"))
    assert [hunt["status"] for hunt in data["hunts"]] == ["clean"]
    if venv_before:
        assert sorted(p.name for p in (ROOT / ".venv").glob("*")) == venv_before


def test_an_interrupted_campaign_stops_its_hunt_runs_no_more_and_reports(
    tmp_path: Path, environments: Path
) -> None:
    started = tmp_path / "started"
    root = make_tests_root(
        tmp_path,
        f"""
        import time
        from pathlib import Path

        def test_hangs():
            Path({str(started)!r}).write_text("")
            time.sleep(120)
        """,
    )
    out = tmp_path / "out"
    command = campaign_command(environments, out, root, "--loads", "0,2", "test_it.py")
    if WINDOWS:
        process = subprocess.Popen(
            command,
            cwd=SCRIPT.parent.parent,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,  # type: ignore[attr-defined,unused-ignore]
        )
    else:
        process = subprocess.Popen(command, cwd=SCRIPT.parent.parent, start_new_session=True)
    try:
        deadline = time.monotonic() + 300
        while not started.exists():
            assert process.poll() is None, "the campaign ended before its hunt's test started"
            assert time.monotonic() < deadline, "the first hunt's test never started"
            time.sleep(0.1)
        if sys.platform == "win32":
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGINT)  # as a terminal's Ctrl-C reaches the group
        code = process.wait(60)
    finally:
        process.kill()
    assert code == 130
    data = json.loads((out / "campaign.json").read_text(encoding="utf-8"))
    assert data["stopped"] is True
    assert [(hunt["hunt"], hunt["status"]) for hunt in data["hunts"]] == [
        (f"direct-{RUNNING}-load0", "stopped")
    ]
    summary = data["hunts"][0]["summary"]
    assert summary is not None, "the hunt didn't write its summary before the campaign gave up"
    assert summary["stopped"] is True  # the hunt itself stopped, and said so
    assert "It was stopped part-way." in (out / "report.md").read_text(encoding="utf-8")
