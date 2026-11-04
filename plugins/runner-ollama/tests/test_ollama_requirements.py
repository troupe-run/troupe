"""The runner's platform requirements are published data, and the check reads them (spec:
ollama-runner, "The runner publishes its platform requirements as data"; local-model-runner design
D16)."""

import json
from pathlib import Path

import pytest

from troupe_runner_ollama.requirements import (
    Requirement,
    RequirementsError,
    check,
    load,
    parse,
)

OLLAMA = Requirement("ollama", "0.12.6", "why")


def test_the_published_requirement_is_ollama_0_12_6_for_truncate_and_shift() -> None:
    (requirement,) = load()
    assert requirement.name == "ollama"
    assert requirement.minimum == "0.12.6"
    assert requirement.wanted == ">= 0.12.6"
    assert "truncate" in requirement.why
    assert "shift" in requirement.why


@pytest.mark.parametrize(
    ("found", "met"),
    [
        ("0.12.5", False),
        ("0.12.6", True),
        ("0.12.6.0", True),
        ("0.12.10", True),
        ("0.40.14", True),
        ("1.0", True),
        ("0.12.6-rc1", False),
        ("0.12.7-rc1", True),
        ("0.9.99", False),
    ],
)
def test_a_reported_version_is_compared_part_by_part_as_numbers(found: str, met: bool) -> None:
    assert (check(OLLAMA, found) is None) is met


@pytest.mark.parametrize("found", ["", "latest", "v0.12.6", "0.12.x", "0..12", "0.12.6 beta"])
def test_a_version_the_runner_cant_read_doesnt_meet_it(found: str) -> None:
    unmet = check(OLLAMA, found)
    assert unmet is not None
    assert unmet.found == found
    assert "can't read" in unmet.problem


def test_no_version_found_doesnt_meet_it_and_found_is_left_out() -> None:
    unmet = check(OLLAMA, None)
    assert unmet is not None
    assert unmet.found is None


def test_an_old_version_names_both_versions() -> None:
    unmet = check(OLLAMA, "0.12.5")
    assert unmet is not None
    assert unmet.problem == "ollama 0.12.5 is older than 0.12.6"


@pytest.mark.parametrize(
    ("data", "named"),
    [
        ({"requires": [{"name": "ollama", "minimum": "0.12.6", "why": "w", "max": "1"}]}, "max"),
        ({"requires": [{"name": "ollama", "minimum": "soon", "why": "w"}]}, "minimum"),
        ({"requires": [{"name": "ollama", "why": "w"}]}, "minimum"),
        ({"requires": [{"name": "", "minimum": "1", "why": "w"}]}, "name"),
        ({"requires": ["ollama"]}, "requires[0]"),
        ({"requires": [], "extra": 1}, "requires"),
        ([], "requires"),
    ],
)
def test_a_malformed_requirement_is_refused_naming_whats_wrong(data: object, named: str) -> None:
    with pytest.raises(RequirementsError, match=named.replace("[", r"\[").replace("]", r"\]")):
        parse(data)


def test_the_check_reads_the_data_not_a_version_in_code(tmp_path: Path) -> None:
    published = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "src"
            / "troupe_runner_ollama"
            / "requirements.json"
        ).read_text(encoding="utf-8")
    )
    published["requires"][0]["minimum"] = "0.50.0"
    copy = tmp_path / "requirements.json"
    copy.write_text(json.dumps(published), encoding="utf-8")
    (requirement,) = load(copy)
    unmet = check(requirement, "0.40.14")
    assert unmet is not None
    assert unmet.requirement.wanted == ">= 0.50.0"
