"""Config paths on the command line: brackets for a key that holds a dot, read the same way by
every config command and shown in the form they're typed (spec: config, "Every config command reads
a path the same way", "A config path is shown in the form it is typed", "A malformed config path is
refused"; config-path-dotted-keys design D3, D4).

No config key can hold a dot until model prices exist (#292): actor and runtime names can't. So a
dotted key reaches the core here as a name it refuses, and the error's ``details.path`` shows what
the command read.
"""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from gitrepo import Repo
from protocol_schemas import check_error
from runtesting import ADA, theatre
from storetesting import git_service
from troupe.cli import config as cli_config
from troupe.cli import main
from troupe.cli.commands import _call
from troupe.cli.render import render_error
from troupe.core.config import aggregate
from troupe.core.errors import TroupeError

STEPS = '[{"exit": 0}]'
PRICE = ["runtimes", "openai", "prices", "gpt-4.1", "input"]


class Seen:
    """What a command sent the core and the error it ended with, if any."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.errors: list[TroupeError] = []

    @property
    def error(self) -> TroupeError:
        assert len(self.errors) == 1, self.errors
        check_error(self.errors[0].to_data())
        return self.errors[0]


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> Seen:
    found = Seen()

    def calling(method: str, params: dict[str, Any], *rest: Any) -> dict[str, Any]:  # noqa: ANN401
        found.requests.append((method, params))
        return _call(method, params, *rest)

    def rendering(error: TroupeError) -> str:
        found.errors.append(error)
        return render_error(error)

    monkeypatch.setattr("troupe.cli.config._call", calling)
    monkeypatch.setattr("troupe.cli.render_error", rendering)
    return found


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    made = theatre(tmp_path)
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def _changes(repo: Repo) -> int:
    return len(git_service(repo).history(aggregate.STREAM))


# Requirement: Every config command reads a path the same way


def test_set_at_a_bracketed_runtime_name_reaches_the_core_as_that_key(
    repo: Repo, seen: Seen
) -> None:
    code, _, _ = cli("config", "set", "runtimes[my.rt].endpoint=http://localhost:9")
    assert code == 1
    assert seen.error.code == "config.invalid"
    assert seen.error.details["path"] == ["runtimes", "my.rt"]
    assert seen.requests[0][1]["operations"][0]["path"] == ["runtimes", "my.rt", "endpoint"]


def test_unset_sends_a_bracketed_key_as_one_key(repo: Repo, seen: Seen) -> None:
    cli("config", "unset", "runtimes.openai.prices[gpt-4.1]")
    method, params = seen.requests[0]
    assert method == "config-set"
    assert params["operations"] == [
        {"path": ["runtimes", "openai", "prices", "gpt-4.1"], "unset": True}
    ]


def test_get_at_a_bracketed_key_with_nothing_set_names_it_in_brackets(
    repo: Repo, seen: Seen
) -> None:
    code, out, _ = cli("config", "get", "runtimes[my.rt]")
    assert code == 0
    assert seen.requests[0][1]["path"] == ["runtimes", "my.rt"]
    assert out == "Nothing is set at runtimes[my.rt].\n"


def test_an_equals_sign_inside_brackets_is_part_of_the_key(repo: Repo, seen: Seen) -> None:
    code, _, _ = cli("config", "set", "actors[a=b].runner=scripted")
    assert code == 1
    assert seen.error.code == "config.invalid"
    assert seen.error.details["path"] == ["actors", "a=b"]
    assert seen.requests[0][1]["operations"][0] == {
        "path": ["actors", "a=b", "runner"],
        "value": "scripted",
    }


def test_a_value_from_a_file_at_a_bracketed_key_is_read_as_the_files_json(
    repo: Repo, seen: Seen
) -> None:
    (repo.path / "runtime.json").write_text('{"endpoint": "http://localhost:9"}')
    code, _, _ = cli("config", "set", "runtimes[my.rt]=@runtime.json")
    assert code == 1
    assert seen.requests[0][1]["operations"][0] == {
        "path": ["runtimes", "my.rt"],
        "value": {"endpoint": "http://localhost:9"},
    }
    assert seen.error.details["path"] == ["runtimes", "my.rt"]


def test_resolved_values_for_a_bracketed_runtime_name_are_the_plain_names(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-canary-0123456789")
    plain = cli("config", "get", "--resolved", "runtimes.openai")
    bracketed = cli("config", "get", "--resolved", "runtimes[openai]")
    assert plain[0] == 0
    assert bracketed == plain


def test_a_runner_set_in_brackets_types_that_actors_options_in_the_same_command(
    repo: Repo,
) -> None:
    # The options' type comes from the runner's schema, found from the runner set alongside
    # them: with no runner found, the steps would be refused as having no one type.
    code, out, err = cli(
        "config",
        "set",
        "actors[tester].runner=scripted",
        'actors.tester.effects.write=["out/**"]',
        'actors.tester.expect=["out/hello.txt"]',
        f"actors.tester.options.script.steps={STEPS}",
    )
    assert code == 0, err
    assert "set actors.tester.options.script.steps" in out


def test_text_with_no_equals_outside_brackets_sets_nothing(repo: Repo, seen: Seen) -> None:
    code, _, _ = cli("config", "set", "actors[a=b]")
    assert code == 1
    assert seen.error.code == "config.invalid"
    assert seen.error.details == {
        "path": ["actors", "a=b"],
        "rule": "a value is written <path>=<value>",
    }
    assert seen.requests == []


# Requirement: A config path is shown in the form it is typed


def test_a_plain_key_set_in_brackets_is_shown_plain(repo: Repo) -> None:
    code, out, err = cli(
        "config",
        "set",
        "actors[tester].runner=scripted",
        'actors[tester].effects.write=["out/**"]',
        'actors[tester].expect=["out/hello.txt"]',
        f"actors[tester].options.script.steps={STEPS}",
    )
    assert code == 0, err
    assert [line for line in out.splitlines() if line.startswith("set ")] == [
        "set actors.tester.effects.write",
        "set actors.tester.expect",
        "set actors.tester.options.script.steps",
        "set actors.tester.runner",
    ]


def test_an_entry_at_a_key_that_holds_a_dot_is_shown_in_brackets() -> None:
    shown = io.StringIO()
    cli_config._render_change(
        {"entries": [{"path": PRICE, "after": 2}, {"path": PRICE[:4]}], "files": []},
        shown,
        rehearse=False,
    )
    assert shown.getvalue().splitlines() == [
        "set runtimes.openai.prices[gpt-4.1].input",
        "unset runtimes.openai.prices[gpt-4.1]",
    ]


def test_a_conflict_at_a_key_that_holds_a_dot_is_shown_in_brackets() -> None:
    lines = cli_config._conflict_lines({"paths": [PRICE], "changes": []})
    assert lines == [
        "conflict at runtimes.openai.prices[gpt-4.1].input: these changes set it differently"
    ]


def test_an_error_from_the_core_names_a_bracketed_key_in_brackets(repo: Repo, seen: Seen) -> None:
    cli("config", "set", "runtimes[my.rt].endpoint=http://localhost:9")
    assert seen.error.problem.startswith("runtimes[my.rt]: ")
    assert "Unset runtimes[my.rt]," in seen.error.fix


# Requirement: A malformed config path is refused


@pytest.mark.parametrize(
    "argv",
    [
        ("config", "unset", "runtimes.openai.prices[gpt-4.1"),
        ("config", "set", "a[b\\=1"),
        ("config", "set", "a[b\\.c]=1"),
        ("config", "set", "runtimes.openai.prices.gpt-4\\.1.input=2"),
        ("config", "set", "actors..runner=scripted"),
        ("config", "set", "actors.=scripted"),
        ("config", "unset", ".actors"),
        ("config", "get", "a[]"),
        ("config", "get", ""),
        ("config", "set", "a[b]c=1"),
        ("config", "unset", "a.[b]"),
        ("config", "get", "a]b"),
        ("config", "get", "--resolved", "runtimes[openai"),
        ("config", "set", "a[b"),
    ],
)
def test_a_malformed_path_is_refused_before_anything_is_recorded(
    repo: Repo, seen: Seen, argv: tuple[str, ...]
) -> None:
    before = _changes(repo)
    code, out, err = cli(*argv)
    assert code == 1
    assert seen.error.code == "config.path-malformed"
    assert seen.error.details["rule"] in err
    assert out == ""
    assert seen.requests == []
    assert _changes(repo) == before


def test_resolved_for_an_unknown_bracketed_runtime_names_it_in_brackets_in_the_fix(
    repo: Repo, seen: Seen
) -> None:
    code, _, _ = cli("config", "get", "--resolved", "runtimes[my.rt]")
    assert code == 1
    assert seen.error.details["path"] == ["runtimes", "my.rt"]
    assert "troupe config set runtimes[my.rt].endpoint=" in seen.error.fix


# A model whose name holds a dot, priced on its own (task 5.3: prices came with #292).

GPT_41 = '{"input": 2, "cacheRead": 0.5, "cacheWrite": 0, "output": 8}'
GPT_5_MINI = '{"input": 0.25, "cacheRead": 0.025, "cacheWrite": 0, "output": 2}'


def test_a_model_whose_name_holds_a_dot_is_priced_changed_and_unpriced_on_its_own(
    repo: Repo, seen: Seen
) -> None:
    assert cli("config", "set", f"runtimes.openai.prices.gpt-5-mini={GPT_5_MINI}")[0] == 0
    code, out, err = cli("config", "set", f"runtimes.openai.prices[gpt-4.1]={GPT_41}")
    assert code == 0, err
    assert seen.requests[-1][1]["operations"][0]["path"] == PRICE[:4]
    assert "set runtimes.openai.prices[gpt-4.1].input\n" in out
    prices = json.loads(cli("config", "get", "runtimes.openai.prices", "--json")[1])["value"]
    assert prices == {"gpt-5-mini": json.loads(GPT_5_MINI), "gpt-4.1": json.loads(GPT_41)}

    code, out, err = cli("config", "set", "runtimes.openai.prices[gpt-4.1].output=9")
    assert code == 0, err
    assert out.startswith("changed runtimes.openai.prices[gpt-4.1].output\n")
    got = cli("config", "get", "runtimes.openai.prices[gpt-4.1].output")
    assert got[1] == "9.0\n"  # a rate is a number, so the CLI reads 9 as 9.0

    code, out, err = cli("config", "unset", "runtimes.openai.prices[gpt-4.1]")
    assert code == 0, err
    assert out.startswith("unset runtimes.openai.prices[gpt-4.1]\n")
    prices = json.loads(cli("config", "get", "runtimes.openai.prices", "--json")[1])["value"]
    assert prices == {"gpt-5-mini": json.loads(GPT_5_MINI)}
