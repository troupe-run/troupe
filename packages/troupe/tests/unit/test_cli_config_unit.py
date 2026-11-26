"""The config command group on the command line: config with no command is refused naming the
commands it takes, and a flag a config command doesn't take is refused as an unknown flag (spec:
cli, config; config-model design D10).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_cli_config.py."""

from pathlib import Path
from typing import Any

import pytest

from cli_core_stand_in import StandIn, stand_in
from troupe.cli import COMMANDS
from troupe.cli import config as config_cli
from troupe.cli.parser import parse
from troupe.core.client.messages import ConfigGetResult, ConfigSetResult
from troupe.core.errors import TroupeError
from troupe.core.exit_codes import ExitCode

# The config group on the command line


def test_config_alone_needs_one_of_its_commands() -> None:
    with pytest.raises(TroupeError) as caught:
        parse(["config"], COMMANDS)
    assert caught.value.code == "usage.missing-argument"
    assert "set, unset, mv, get, drop or keep" in caught.value.problem


def test_a_config_commands_unknown_flag_is_refused_naming_it() -> None:
    with pytest.raises(TroupeError) as caught:
        parse(["config", "get", "--force"], COMMANDS)
    assert caught.value.code == "usage.unknown-flag"


# config set, unset and mv, run in-process against a stand-in core (unit-tests-cli-commands-config-
# init design D1-D2). Each result is the protocol's ConfigSetResult, in the shapes the core returned
# for these commands in a git theatre.

LEAD = ["actors", "lead"]
CHANGE = "01M8B9ENP3W7FAYG14BG680RG5"
HASH = "sha256:bd4ff6c8ed234580034d7075d01bef61c608993623cb412d1dc4cfa6d24c913e"
WROTE = {"path": ".troupe/actors/lead.yaml", "action": "write", "reason": "for this change"}
MOVED = [
    {"path": ".troupe/actors/star.yaml", "action": "write", "reason": "for this change"},
    {
        "path": ".troupe/actors/lead.yaml",
        "action": "remove",
        "reason": "an older version troupe wrote",
    },
]


def _set(
    entries: list[dict[str, Any]],
    files: list[dict[str, Any]] | None = None,
    *,
    notices: list[dict[str, Any]] | None = None,
    change: str | None = CHANGE,
) -> ConfigSetResult:
    data: dict[str, Any] = {"entries": entries, "files": files or [], "notices": notices or []}
    return ConfigSetResult.from_data(data if change is None else {**data, "change": change})


def _edit_notice(file: str, entries: int) -> dict[str, Any]:
    values = f"{entries} value{'s' if entries != 1 else ''}"
    return {
        "code": "config.hand-edit-recorded",
        "problem": f"troupe recorded the edit to {file}, as a change by an unknown author "
        f"({values}).",
        "fix": "Nothing to do: the file is what config says now.",
        "details": {"file": file, "entries": entries, "change": CHANGE},
    }


MOVE_NOTICE = {
    "code": "config.hand-move-recorded",
    "problem": "troupe recorded the files moved to .troupe/actors/moon.yaml as renaming "
    "actors.star to actors.moon, by an unknown author.",
    "fix": "Nothing to do: its history and runs follow it to the new name.",
    "details": {
        "file": ".troupe/actors/moon.yaml",
        "from": "actors.star",
        "to": "actors.moon",
        "change": CHANGE,
    },
}


@pytest.fixture
def core(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> StandIn:
    return stand_in(monkeypatch, tmp_path)


def test_config_set_sends_each_value_and_prints_what_it_set_changed_and_wrote(
    core: StandIn,
) -> None:
    core.reply(
        "config-set",
        _set(
            [
                {"path": [*LEAD, "model"], "after": "m", "before": HASH},
                {"path": [*LEAD, "runtime"], "after": "anthropic"},
            ],
            [WROTE],
        ),
    )
    ran = core.run("config", "set", "actors.lead.model=m", "actors.lead.runtime=anthropic")
    assert core.requests == [
        (
            "config-set",
            {
                "operations": [
                    {"path": [*LEAD, "model"], "value": "m"},
                    {"path": [*LEAD, "runtime"], "value": "anthropic"},
                ]
            },
        )
    ]
    assert ran.code == ExitCode.OK
    assert ran.out == [
        "changed actors.lead.model",
        "set actors.lead.runtime",
        "wrote .troupe/actors/lead.yaml (for this change)",
        f"recorded change {CHANGE}",
    ]
    assert ran.stderr == ""


def test_config_set_sends_its_reason_and_rehearsal(core: StandIn) -> None:
    core.reply("config-set", _set([{"path": [*LEAD, "model"], "after": "m"}], [WROTE], change=None))
    ran = core.run("config", "set", "--reason", "why not", "--rehearse", "actors.lead.model=m")
    assert core.requests == [
        (
            "config-set",
            {
                "operations": [{"path": [*LEAD, "model"], "value": "m"}],
                "reason": "why not",
                "rehearse": True,
            },
        )
    ]
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == [
        "would set actors.lead.model",
        "would write .troupe/actors/lead.yaml (for this change)",
        "Rehearsal: nothing was recorded or written.",
    ]


def test_config_set_with_no_equals_is_refused_by_position_without_repeating_it(
    core: StandIn,
) -> None:
    ran = core.run("config", "set", "actors.lead.model=m", "actors.lead.secret hunter2")
    assert ran.code == ExitCode.FAILURE
    assert ran.err == [
        "troupe: path=value 2 doesn't set anything: a value is written <path>=<value>.",
        "  fix: Write it as <path>=<value>, with no space around the =, or use troupe config "
        "unset <path> to remove a value.",
    ]
    assert "hunter2" not in ran.stderr
    assert core.calls == []


def test_a_path_ends_at_the_first_equals_outside_brackets(core: StandIn) -> None:
    core.reply("config-set", _set([]))
    core.run("config", "set", "actors.lead.model=a=b")
    assert core.requests[0][1]["operations"] == [{"path": [*LEAD, "model"], "value": "a=b"}]


def test_a_runner_option_is_typed_by_the_runner_set_in_the_same_command(core: StandIn) -> None:
    core.reply("config-set", _set([]))
    core.run("config", "set", "actors.lead.runner=anthropic", "actors.lead.options.maxTurns=7")
    assert core.requests == [
        (
            "config-set",
            {
                "operations": [
                    {"path": [*LEAD, "runner"], "value": "anthropic"},
                    {"path": [*LEAD, "options", "maxTurns"], "value": 7},
                ]
            },
        )
    ]


def test_a_runner_option_is_typed_by_the_runner_config_already_holds(core: StandIn) -> None:
    core.reply(
        "config-get",
        ConfigGetResult.from_data(
            {"conflicts": [], "heads": [HASH], "notices": [], "value": "anthropic"}
        ),
    )
    core.reply("config-set", _set([]))
    core.run("config", "set", "actors.lead.options.maxTurns=7")
    assert core.requests == [
        ("config-get", {"path": [*LEAD, "runner"]}),
        ("config-set", {"operations": [{"path": [*LEAD, "options", "maxTurns"], "value": 7}]}),
    ]


def test_a_runner_read_from_a_file_isnt_the_runner_an_option_is_typed_by(
    core: StandIn, tmp_path: Path
) -> None:
    (tmp_path / "runner.txt").write_text("anthropic", encoding="utf-8")
    core.reply(
        "config-get",
        ConfigGetResult.from_data(
            {"conflicts": [], "heads": [], "notices": [], "value": "anthropic"}
        ),
    )
    core.reply("config-set", _set([]))
    core.run("config", "set", "actors.lead.runner=@runner.txt", "actors.lead.options.maxTurns=7")
    assert [method for method, _ in core.requests] == ["config-get", "config-set"]


def test_a_value_on_an_actors_own_key_needs_no_runner(core: StandIn) -> None:
    core.reply("config-set", _set([]))
    core.run("config", "set", "actors.lead.model=m", "runtimes.mine.model=n")
    assert [method for method, _ in core.requests] == ["config-set"]


def test_config_set_as_json_sends_the_parsed_value(core: StandIn) -> None:
    core.reply("config-set", _set([]))
    core.run("config", "set", "--json", 'actors.lead.expect=["a.txt"]')
    assert core.requests[0][1]["operations"] == [{"path": [*LEAD, "expect"], "value": ["a.txt"]}]


def test_a_set_that_changes_nothing_says_config_already_holds_it(core: StandIn) -> None:
    core.reply("config-set", _set([], change=None))
    ran = core.run("config", "set", "--rehearse", "actors.lead.model=m")
    assert ran.code == ExitCode.OK
    assert ran.out == ["Nothing changed: config already holds that."]


def test_hand_edits_the_command_records_are_its_changes_too(core: StandIn) -> None:
    notices = [
        MOVE_NOTICE,
        _edit_notice(".troupe/actors/lead.yaml", 1),
        _edit_notice(".troupe/config.yaml", 3),
    ]
    core.reply("config-set", _set([], notices=notices, change=None))
    ran = core.run("config", "set", "actors.lead.model=m")
    assert ran.code == ExitCode.OK
    assert ran.out == [
        "record .troupe/actors/moon.yaml: actors.star renamed to actors.moon by an unknown author",
        "record .troupe/actors/lead.yaml: an edit by an unknown author (1 value)",
        "record .troupe/config.yaml: an edit by an unknown author (3 values)",
        "The command's own change changes nothing: config already holds that.",
    ]
    assert ran.err == [
        f"troupe: {MOVE_NOTICE['problem']}",
        f"  fix: {MOVE_NOTICE['fix']}",
        f"troupe: {notices[1]['problem']}",
        "  fix: Nothing to do: the file is what config says now.",
        f"troupe: {notices[2]['problem']}",
        "  fix: Nothing to do: the file is what config says now.",
    ]


def test_a_rehearsal_that_would_record_hand_edits_says_so_and_would_change(core: StandIn) -> None:
    core.reply("config-set", _set([], notices=[_edit_notice(".troupe/a.yaml", 2)], change=None))
    ran = core.run("config", "set", "--rehearse", "actors.lead.model=m")
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == [
        "would record .troupe/a.yaml: an edit by an unknown author (2 values)",
        "The command's own change changes nothing: config already holds that.",
        "Rehearsal: nothing was recorded or written.",
    ]


def test_hand_edits_come_before_the_commands_own_change(core: StandIn) -> None:
    other = {"code": "config.conflict-resolved", "problem": "p", "fix": "f", "details": {}}
    core.reply(
        "config-set",
        _set([{"path": [*LEAD, "model"], "after": "m"}], notices=[other, _edit_notice("f", 1)]),
    )
    ran = core.run("config", "set", "actors.lead.model=m")
    assert ran.out == [
        "record f: an edit by an unknown author (1 value)",
        "set actors.lead.model",
        f"recorded change {CHANGE}",
    ]


def test_config_unset_sends_each_path_and_prints_what_it_unset(core: StandIn) -> None:
    core.reply(
        "config-set",
        _set(
            [
                {"path": [*LEAD, "model"], "before": HASH},
                {"path": [*LEAD, "runtime"], "before": HASH},
            ],
            [WROTE],
        ),
    )
    ran = core.run(
        "config", "unset", "--reason", "gone", "actors.lead.model", "actors.lead.runtime"
    )
    assert core.requests == [
        (
            "config-set",
            {
                "operations": [
                    {"path": [*LEAD, "model"], "unset": True},
                    {"path": [*LEAD, "runtime"], "unset": True},
                ],
                "reason": "gone",
            },
        )
    ]
    assert ran.code == ExitCode.OK
    assert ran.out == [
        "unset actors.lead.model",
        "unset actors.lead.runtime",
        "wrote .troupe/actors/lead.yaml (for this change)",
        f"recorded change {CHANGE}",
    ]


def test_a_rehearsed_unset_would_change(core: StandIn) -> None:
    core.reply("config-set", _set([{"path": [*LEAD, "model"], "before": HASH}], change=None))
    ran = core.run("config", "unset", "--rehearse", "actors.lead.model")
    assert core.requests[0][1]["rehearse"] is True
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == [
        "would unset actors.lead.model",
        "Rehearsal: nothing was recorded or written.",
    ]


def test_config_mv_sends_one_rename_and_prints_it(core: StandIn) -> None:
    renamed = {"path": ["actors", "star"], "renamedFrom": LEAD, "before": HASH}
    core.reply("config-set", _set([renamed], MOVED))
    ran = core.run("config", "mv", "--reason", "better", "actors.lead", "actors.star")
    assert core.requests == [
        (
            "config-set",
            {
                "operations": [{"path": ["actors", "star"], "renamedFrom": LEAD}],
                "reason": "better",
            },
        )
    ]
    assert ran.code == ExitCode.OK
    assert ran.out == [
        "renamed actors.lead to actors.star",
        "wrote .troupe/actors/star.yaml (for this change)",
        "removed .troupe/actors/lead.yaml (an older version troupe wrote)",
        f"recorded change {CHANGE}",
    ]


def test_a_rehearsed_mv_says_what_it_would_rename_write_and_remove(core: StandIn) -> None:
    renamed = {"path": ["actors", "star"], "renamedFrom": LEAD, "before": HASH}
    core.reply("config-set", _set([renamed], MOVED[::-1], change=None))
    ran = core.run("config", "mv", "--rehearse", "actors.lead", "actors.star")
    assert core.requests[0][1] == {
        "operations": [{"path": ["actors", "star"], "renamedFrom": LEAD}],
        "rehearse": True,
    }
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == [
        "would rename actors.lead to actors.star",
        "would remove .troupe/actors/lead.yaml (an older version troupe wrote)",
        "would write .troupe/actors/star.yaml (for this change)",
        "Rehearsal: nothing was recorded or written.",
    ]


@pytest.mark.parametrize(
    ("action", "done"),
    [("write", "wrote"), ("remove", "removed"), ("finish", "finished"), ("discard", "discarded")],
)
def test_each_file_action_is_said_as_done_or_as_it_would_be(action: str, done: str) -> None:
    file = {"path": ".troupe/a.yaml", "action": action, "reason": "r"}
    assert config_cli._file_line(file) == f"{done} .troupe/a.yaml (r)"
    assert config_cli._file_line(file, rehearse=True) == f"{action} .troupe/a.yaml (r)"


def test_a_file_whose_contents_are_kept_names_where_and_whether_its_marked_resolved() -> None:
    file = {
        "path": ".troupe/a.yaml",
        "action": "write",
        "reason": "r",
        "kept": HASH,
        "resolve": True,
    }
    assert config_cli._file_line(file) == (
        f"wrote .troupe/a.yaml (r); what it held is kept as {HASH}; marked it resolved in git"
    )
    assert config_cli._file_line(file, rehearse=True) == (
        f"write .troupe/a.yaml (r); what it held is kept as {HASH}; and mark it resolved in git"
    )
    assert config_cli._file_line({**file, "resolve": False}).endswith(f"kept as {HASH}")


def test_the_path_value_refusal_names_its_rule_and_no_path() -> None:
    with pytest.raises(TroupeError) as caught:
        config_cli._assignments(["actors.lead.model"])
    assert caught.value.details == {"path": [], "rule": "a value is written <path>=<value>"}
