"""scripts/flake_campaign.py (spec: flake-hunt, the campaign requirements; design D11).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_flake_campaign_integration.py."""

from pathlib import Path

import pytest
from flake_campaign_shared import ROOT, WINDOWS, options

import flake_campaign
from flake_campaign import CampaignError, Hunt

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
