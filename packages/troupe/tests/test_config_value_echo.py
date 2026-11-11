"""A config value refused for its shape is repeated nowhere: not by config set, unset or get, in
standard output, standard error or the client message (spec: config, "A refused config value is
repeated nowhere"; effects, "A pattern that can't be meant is refused"; config-set-json-redacts,
#374).

Each test drives troupe.cli.main and captures the error the CLI renders, which is the client
message the core sent, or the error the CLI raised before sending anything.
"""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from gitrepo import Repo
from protocol_schemas import check_error
from runtesting import ADA, theatre
from troupe.cli import main
from troupe.cli.render import render_error
from troupe.core.errors import TroupeError

CANARY = "q7ZxW9pL4vR2canary"
WITH_PASSWORD = f"https://user:{CANARY}@example.com/v1"
STEPS = '[{"exit": 0}]'


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    made = theatre(tmp_path)
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made


@pytest.fixture
def errors(monkeypatch: pytest.MonkeyPatch) -> list[TroupeError]:
    """Every error the CLI renders."""
    found: list[TroupeError] = []

    def rendering(error: TroupeError) -> str:
        found.append(error)
        return render_error(error)

    monkeypatch.setattr("troupe.cli.render_error", rendering)
    return found


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def _tester() -> None:
    code, _, err = cli(
        "config",
        "set",
        "actors.tester.runner=scripted",
        'actors.tester.effects.write=["out/**"]',
        'actors.tester.expect=["out/hello.txt"]',
        f"actors.tester.options.script.steps={STEPS}",
    )
    assert code == 0, err


def _refused(errors: list[TroupeError], code: str, *argv: str) -> tuple[str, dict[str, Any]]:
    """Run ``argv``, which must be refused with ``code``, and check none of the canary is in what
    it wrote or in the client message. Returns standard error and the client message."""
    status, out, err = cli(*argv)
    assert status != 0
    [error] = errors
    message = error.to_data()
    check_error(message)
    assert message["code"] == code
    for shown in (out, err, json.dumps(message)):
        assert CANARY not in shown
        assert "example.com" not in shown
    return err, message


def test_json_that_isnt_json_never_repeats_it(repo: Repo, errors: list[TroupeError]) -> None:
    err, message = _refused(
        errors,
        "config.invalid",
        "config",
        "set",
        "--json",
        f"runtimes.box.endpoint={WITH_PASSWORD}",
    )
    assert "runtimes.box.endpoint isn't JSON: Expecting value (line 1, column 1)" in err
    assert message["details"]["path"] == ["runtimes", "box", "endpoint"]
    assert (message["details"]["line"], message["details"]["column"]) == (1, 1)


@pytest.mark.parametrize(
    ("assignment", "path"),
    [
        pytest.param(f"actors.tester.options.replayDelays={CANARY}", "replayDelays", id="boolean"),
        pytest.param(f"runtimes.box.prices[m].input={WITH_PASSWORD}", "input", id="number"),
        pytest.param(f'actors.tester.expect=["{WITH_PASSWORD}"', "expect", id="list"),
        pytest.param(f"actors.tester.options.script={WITH_PASSWORD}", "script", id="group"),
        pytest.param(f"actors.tester.options.nope={WITH_PASSWORD}", "nope", id="no single type"),
    ],
)
def test_a_value_that_isnt_the_paths_type_is_never_repeated(
    repo: Repo, errors: list[TroupeError], assignment: str, path: str
) -> None:
    _tester()
    err, message = _refused(errors, "config.invalid", "config", "set", assignment)
    assert path in err
    assert message["details"]["path"][-1] == path


def test_a_value_file_that_isnt_yaml_never_repeats_its_text(
    repo: Repo, errors: list[TroupeError]
) -> None:
    _tester()
    (repo.path / "options.yaml").write_text(
        f"script:\n  steps: [1, 2\n  key: {WITH_PASSWORD}\n", encoding="utf-8"
    )
    err, message = _refused(
        errors, "config.invalid", "config", "set", "actors.tester.options=@options.yaml"
    )
    assert "options.yaml isn't YAML troupe can read (line 3, column" in err
    assert message["details"]["line"] == 3


def test_a_value_outside_the_schemas_list_is_never_repeated(
    repo: Repo, errors: list[TroupeError]
) -> None:
    _tester()
    err, _ = _refused(
        errors, "config.invalid", "config", "set", f"actors.tester.workspace={CANARY}"
    )
    assert "actors.tester.workspace: it must be one of 'worktree', 'theatre'" in err


def test_a_malformed_path_before_a_value_never_repeats_the_value(
    repo: Repo, errors: list[TroupeError]
) -> None:
    err, message = _refused(
        errors, "config.path-malformed", "config", "set", f"runtimes.box.endpoint.={WITH_PASSWORD}"
    )
    assert '"runtimes.box.endpoint.=" isn\'t a config path' in err
    assert message["details"]["text"] == "runtimes.box.endpoint.="


@pytest.mark.parametrize("command", ["unset", "get"])
def test_a_value_given_to_unset_or_get_is_never_repeated(
    repo: Repo, errors: list[TroupeError], command: str
) -> None:
    err, message = _refused(
        errors, "config.path-malformed", "config", command, f"runtimes.box.endpoint={WITH_PASSWORD}"
    )
    assert "a key that holds = is written in brackets" in err
    assert message["details"]["text"] == "runtimes.box.endpoint="


def test_an_effect_pattern_holding_a_password_is_never_repeated(
    repo: Repo, errors: list[TroupeError]
) -> None:
    _tester()
    err, message = _refused(
        errors,
        "config.invalid",
        "config",
        "set",
        "--json",
        f'actors.tester.effects.write=["out/**", "{WITH_PASSWORD}"]',
    )
    assert "actors.tester.effects.write: item 2 has a '\\' or ':'" in err
    assert message["details"]["path"] == ["actors", "tester", "effects", "write"]


def test_a_name_is_still_named(repo: Repo, errors: list[TroupeError]) -> None:
    # A value that has passed its shape check, when the rule is about that name (design D3).
    _tester()
    code, _, err = cli("config", "set", "actors.tester.runtime=nowhere")
    assert code != 0
    assert "there's no runtime named 'nowhere'" in err
    assert "troupe config set runtimes.nowhere.endpoint=<url>" in err


@pytest.mark.parametrize(
    ("assignment", "says"),
    [
        pytest.param(
            f'runtimes.box={{"endpoint": "https://example.org/v1", "{WITH_PASSWORD}": 1}}',
            "runtimes.box: it holds 1 field the runtime schema doesn't define",
            id="a runtime's field",
        ),
        pytest.param(
            f'actors.tester.options={{"script": {{"steps": {STEPS}}}, "{WITH_PASSWORD}": 1}}',
            "actors.tester.options: it holds 1 field the scripted runner's options schema",
            id="an option",
        ),
        pytest.param(
            f'runtimes={{"{WITH_PASSWORD}": {{"endpoint": "https://example.org/v1"}}}}',
            "runtimes: it holds a runtime whose name isn't one",
            id="a runtime's name",
        ),
        pytest.param(
            f'actors={{"{WITH_PASSWORD}": {{"runner": "scripted"}}}}',
            "actors: it holds an actor whose name isn't one",
            id="an actor's name",
        ),
    ],
)
def test_a_key_inside_a_json_group_is_never_repeated(
    repo: Repo, errors: list[TroupeError], assignment: str, says: str
) -> None:
    # A key inside the value is part of it (design D7; review of #384).
    _tester()
    err, _ = _refused(errors, "config.invalid", "config", "set", "--json", assignment)
    assert says in err


def test_an_unknown_field_typed_as_a_path_is_still_named(
    repo: Repo, errors: list[TroupeError]
) -> None:
    _tester()
    code, _, err = cli("config", "set", "--json", 'actors.tester.runnr="scripted"')
    assert code != 0
    assert "actors.tester.runnr: there's no such field" in err


def test_an_uncovered_expect_path_holding_a_password_is_never_repeated(
    repo: Repo, errors: list[TroupeError]
) -> None:
    # A theatre path's shape check lets a URL through (review of #384).
    _tester()
    err, message = _refused(
        errors,
        "config.invalid",
        "config",
        "set",
        f'actors.tester.expect=["out/hello.txt", "https://user:{CANARY}@example.com/x"]',
    )
    assert "actors.tester.expect: expect's item 2 isn't covered" in err
    assert message["details"]["path"] == ["actors", "tester", "expect"]
