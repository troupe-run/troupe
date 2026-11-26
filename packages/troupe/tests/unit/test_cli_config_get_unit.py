"""config get, sync, config drop and config keep on the command line, run in-process against a
stand-in core: the request each sends, what it prints and its exit code (spec: cli, config,
config-hand-edits; abandoned-edits design D8; unit-tests-cli-commands-config-init design D1-D2).

Each result is the protocol's own message, in the shapes the core returned for these commands in a
git theatre. Their tests that start a process, open a socket or use a git theatre are in
integration/test_cli_config*.py."""

import json
from pathlib import Path
from typing import Any

import pytest

from cli_core_stand_in import StandIn, stand_in
from troupe.core.client.messages import (
    ConfigDropResult,
    ConfigGetResult,
    ConfigKeepResult,
    ConfigSetResult,
    NoticeUpdate,
    SyncResult,
)
from troupe.core.exit_codes import ExitCode

HEAD = "sha256:6199d3e4084638ed5ebf1ea5812f65921fe9b2b889b56acdaf051910684446fc"
HASH = "sha256:bd4ff6c8ed234580034d7075d01bef61c608993623cb412d1dc4cfa6d24c913e"
CHANGE = "01M8B9EPK9S2KH0S2QJNM4DD64"
OTHER = "01M8B9ENP3W7FAYG14BG680RG5"
NOTICE = {"code": "config.waiting", "problem": "Waiting.", "fix": "Wait.", "details": {}}
ANTHROPIC = {
    "name": "anthropic",
    "endpoint": {"value": "https://api.anthropic.com", "source": "default"},
    "credential": {"env": {"source": "default", "value": "ANTHROPIC_API_KEY"}, "set": False},
    "engine": {"value": "claude", "source": "default"},
}


def _got(**fields: object) -> ConfigGetResult:
    data = {"conflicts": [], "heads": [HEAD], "notices": [], **fields}
    return ConfigGetResult.from_data(data)


def _conflict(entries: list[dict[str, Any]], *, rule: str | None = None) -> dict[str, Any]:
    conflict: dict[str, Any] = {
        "paths": [["actors", "lead", "model"], ["actors", "lead", "runtime"]],
        "changes": [
            {
                "change": CHANGE,
                "actor": {"kind": "human", "id": "ana@example.com", "source": "git-email"},
                "at": "2026-11-26T05:00:00.000Z",
                "entries": entries,
            },
            {
                "change": OTHER,
                "actor": {"kind": "unknown"},
                "at": "2026-11-26T05:01:00.000Z",
                "entries": [{"path": ["actors", "lead", "model"], "before": HASH}],
            },
        ],
    }
    return conflict if rule is None else {**conflict, "rule": rule}


@pytest.fixture
def core(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> StandIn:
    return stand_in(monkeypatch, tmp_path)


# config get


def test_get_with_a_path_prints_a_string_as_it_is(core: StandIn) -> None:
    core.reply("config-get", _got(value="scripted", notices=[NOTICE]))
    ran = core.run("config", "get", "actors.lead.runner")
    assert core.requests == [("config-get", {"path": ["actors", "lead", "runner"]})]
    assert ran.code == ExitCode.OK
    assert ran.out == ["scripted"]
    assert ran.err == ["troupe: Waiting.", "  fix: Wait."]


def test_get_prints_any_other_value_as_indented_json_keeping_non_ascii(core: StandIn) -> None:
    core.reply("config-get", _got(value={"expect": ["café.md"], "maxTurns": 7}))
    ran = core.run("config", "get")
    assert core.requests == [("config-get", {})]
    assert ran.stdout == '{\n  "expect": [\n    "café.md"\n  ],\n  "maxTurns": 7\n}\n'


def test_get_of_a_path_with_nothing_set_says_so(core: StandIn) -> None:
    core.reply("config-get", _got())
    ran = core.run("config", "get", "actors.zz")
    assert ran.code == ExitCode.OK
    assert ran.out == ["Nothing is set at actors.zz."]


def test_get_of_empty_config_says_its_empty(core: StandIn) -> None:
    core.reply("config-get", _got())
    assert core.run("config", "get").out == ["Config is empty."]


def test_get_as_json_prints_the_whole_result_on_one_line(core: StandIn) -> None:
    core.reply("config-get", _got(value="café"))
    ran = core.run("config", "get", "--json", "actors.lead.model")
    assert ran.out == [json.dumps(_got(value="café").to_data(), ensure_ascii=False)]
    assert "café" in ran.stdout


def test_get_after_its_value_lists_each_conflict_with_its_changes(core: StandIn) -> None:
    entries: list[dict[str, Any]] = [
        {"path": ["actors", "lead", "model"], "after": "m", "before": HASH},
        {"path": ["actors", "lead", "runtime"], "after": "anthropic"},
        {"path": ["actors", "lead", "character"]},
        {"path": ["actors", "star"], "renamedFrom": ["actors", "lead"]},
    ]
    core.reply("config-get", _got(value="m", conflicts=[_conflict(entries)]))
    ran = core.run("config", "get", "actors.lead.model")
    assert ran.out == [
        "m",
        "conflict at actors.lead.model, actors.lead.runtime: these changes set it differently",
        f"  change {CHANGE} by ana@example.com at 2026-11-26T05:00:00.000Z:",
        '    changed actors.lead.model to "m"',
        '    set actors.lead.runtime to "anthropic"',
        "    unset actors.lead.character",
        "    renamed actors.lead to actors.star",
        f"  change {OTHER} by someone unknown at 2026-11-26T05:01:00.000Z:",
        "    unset actors.lead.model",
    ]


def test_a_conflict_that_breaks_a_rule_names_it(core: StandIn) -> None:
    conflict = _conflict([{"path": ["actors", "lead", "model"], "after": 1}], rule="one runtime")
    core.reply("config-get", _got(conflicts=[conflict]))
    ran = core.run("config", "get")
    assert ran.out[1] == (
        "conflict at actors.lead.model, actors.lead.runtime: together these changes break a rule "
        "(one runtime)"
    )


def test_a_conflicting_value_is_shown_whole_up_to_72_characters_of_json(core: StandIn) -> None:
    exactly = "x" * 70  # 72 characters with its quotes
    longer = "é" * 71
    entries: list[dict[str, Any]] = [
        {"path": ["actors", "lead", "model"], "after": exactly},
        {"path": ["actors", "lead", "runtime"], "after": longer},
    ]
    core.reply("config-get", _got(conflicts=[_conflict(entries)]))
    ran = core.run("config", "get")
    assert ran.out[3] == f'    set actors.lead.model to "{exactly}"'
    assert ran.out[4] == (f'    set actors.lead.runtime to "{"é" * 71}... (73 characters in all)')


def test_get_resolved_lists_each_runtime_then_each_conflict(core: StandIn) -> None:
    conflict = _conflict([{"path": ["actors", "lead", "model"], "after": "m"}])
    core.reply("config-get", _got(runtimes={"anthropic": ANTHROPIC}, conflicts=[conflict]))
    ran = core.run("config", "get", "--resolved")
    assert core.requests == [("config-get", {"resolved": True})]
    assert ran.out == [
        "runtime anthropic",
        "  endpoint: https://api.anthropic.com (from default)",
        "  model: none (an actor's model, runtimes.anthropic.model or "
        "TROUPE_RUNTIME_ANTHROPIC_MODEL sets one)",
        "  credential: from ANTHROPIC_API_KEY (named by default), not set",
        "  engine: claude (from default)",
        "conflict at actors.lead.model, actors.lead.runtime: these changes set it differently",
        f"  change {CHANGE} by ana@example.com at 2026-11-26T05:00:00.000Z:",
        '    set actors.lead.model to "m"',
        f"  change {OTHER} by someone unknown at 2026-11-26T05:01:00.000Z:",
        "    unset actors.lead.model",
    ]
    assert ran.code == ExitCode.OK


def test_get_resolved_as_json_prints_the_result(core: StandIn) -> None:
    core.reply("config-get", _got(runtimes={"anthropic": ANTHROPIC}))
    ran = core.run("config", "get", "--resolved", "--json")
    assert json.loads(ran.stdout) == _got(runtimes={"anthropic": ANTHROPIC}).to_data()


# sync


def _synced(**fields: object) -> SyncResult:
    return SyncResult.from_data({"edits": [], "files": [], "notices": [], **fields})


def test_sync_with_nothing_to_do_says_so(core: StandIn) -> None:
    core.reply("sync", _synced(notices=[NOTICE]))
    ran = core.run("sync")
    assert core.requests == [("sync", {})]
    assert ran.code == ExitCode.OK
    assert ran.out == ["Nothing to do: the config files are what config says."]
    assert ran.err == ["troupe: Waiting.", "  fix: Wait."]


def test_sync_records_each_hand_edit_and_move_and_writes_each_file(core: StandIn) -> None:
    edits = [
        {
            "path": ".troupe/actors/moon.yaml",
            "entries": [
                {"path": ["actors", "moon", "model"], "after": "m"},
                {"path": ["actors", "moon"], "renamedFrom": ["actors", "star"], "before": HASH},
            ],
            "change": CHANGE,
        },
        {
            "path": ".troupe/config.yaml",
            "entries": [{"path": ["runtimes", "a", "model"], "after": "m"}],
        },
        {
            "path": ".troupe/actors/lead.yaml",
            "entries": [
                {"path": ["actors", "lead", "model"], "after": "m"},
                {"path": ["actors", "lead", "runtime"], "after": "r"},
            ],
        },
    ]
    files = [{"path": ".troupe/a.yaml", "action": "write", "reason": "r"}]
    core.reply("sync", _synced(edits=edits, files=files))
    ran = core.run("sync", "--force")
    assert core.requests == [("sync", {"force": True})]
    assert ran.code == ExitCode.OK
    assert ran.out == [
        "record .troupe/actors/moon.yaml: actors.star renamed to actors.moon by an unknown author",
        "record .troupe/config.yaml: an edit by an unknown author (1 value)",
        "record .troupe/actors/lead.yaml: an edit by an unknown author (2 values)",
        "wrote .troupe/a.yaml (r)",
    ]


def test_a_rehearsed_sync_says_what_it_would_record_and_write(core: StandIn) -> None:
    edits = [{"path": ".troupe/c.yaml", "entries": [{"path": ["a", "b"], "after": 1}]}]
    files = [{"path": ".troupe/a.yaml", "action": "remove", "reason": "r"}]
    core.reply("sync", _synced(edits=edits, files=files))
    ran = core.run("sync", "--rehearse")
    assert core.requests == [("sync", {"rehearse": True})]
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == [
        "would record .troupe/c.yaml: an edit by an unknown author (1 value)",
        "would remove .troupe/a.yaml (r)",
        "Rehearsal: nothing was recorded or written.",
    ]


def test_a_rehearsed_sync_that_only_records_edits_still_would_change(core: StandIn) -> None:
    edits = [{"path": ".troupe/c.yaml", "entries": [{"path": ["a", "b"], "after": 1}]}]
    core.reply("sync", _synced(edits=edits))
    ran = core.run("sync", "--rehearse")
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out[-1] == "Rehearsal: nothing was recorded or written."


def test_sync_shows_a_notice_sent_while_it_runs(core: StandIn) -> None:
    core.reply("sync", _synced(), NoticeUpdate.from_data({"kind": "notice", "notice": NOTICE}))
    ran = core.run("sync")
    assert ran.err == ["troupe: Waiting.", "  fix: Wait."]


# config drop and config keep


def test_drop_names_the_changes_it_dropped_and_the_segments_it_removed(core: StandIn) -> None:
    core.reply(
        "config-drop",
        ConfigDropResult.from_data(
            {
                "change": CHANGE,
                "changes": [CHANGE, OTHER],
                "segments": ["a.jsonl", "b.jsonl"],
                "rehearsed": False,
                "notices": [NOTICE],
            }
        ),
    )
    ran = core.run("config", "drop", CHANGE)
    assert core.requests == [("config-drop", {"change": CHANGE})]
    assert ran.code == ExitCode.OK
    assert ran.out == [f"Dropped 2 changes ({CHANGE}, {OTHER}): removed a.jsonl, b.jsonl."]
    assert ran.err == ["troupe: Waiting.", "  fix: Wait."]


def test_a_rehearsed_drop_says_what_it_would_remove(core: StandIn) -> None:
    core.reply(
        "config-drop",
        ConfigDropResult.from_data(
            {
                "change": CHANGE,
                "changes": [CHANGE, OTHER],
                "segments": ["a.jsonl"],
                "rehearsed": True,
                "notices": [],
            }
        ),
    )
    ran = core.run("config", "drop", "--rehearse", CHANGE)
    assert core.requests == [("config-drop", {"change": CHANGE, "rehearse": True})]
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == [
        f"Would drop 2 changes ({CHANGE}, {OTHER}): would remove a.jsonl.",
        "Rehearsal: nothing was removed.",
    ]


def test_keep_says_troupe_wont_ask_again(core: StandIn) -> None:
    core.reply(
        "config-keep",
        ConfigKeepResult.from_data({"change": CHANGE, "rehearsed": False, "notices": [NOTICE]}),
    )
    ran = core.run("config", "keep", CHANGE)
    assert core.requests == [("config-keep", {"change": CHANGE})]
    assert ran.code == ExitCode.OK
    assert ran.out == [f"Kept the changes of {CHANGE}; troupe won't ask about them again."]
    assert ran.err == ["troupe: Waiting.", "  fix: Wait."]


def test_a_rehearsed_keep_writes_nothing(core: StandIn) -> None:
    core.reply(
        "config-keep",
        ConfigKeepResult.from_data({"change": CHANGE, "rehearsed": True, "notices": []}),
    )
    ran = core.run("config", "keep", "--rehearse", CHANGE)
    assert core.requests == [("config-keep", {"change": CHANGE, "rehearse": True})]
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == [f"Would keep the changes of {CHANGE}.", "Rehearsal: nothing was written."]


# What every config command does while the core runs it


def _result(method: str) -> Any:  # noqa: ANN401
    notices = [NOTICE]
    return {
        "config-set": ConfigSetResult.from_data({"entries": [], "files": [], "notices": notices}),
        "config-get": _got(value="m", notices=notices),
        "sync": _synced(notices=notices),
        "config-drop": ConfigDropResult.from_data(
            {
                "change": CHANGE,
                "changes": [CHANGE, OTHER],
                "segments": ["a.jsonl"],
                "rehearsed": False,
                "notices": notices,
            }
        ),
        "config-keep": ConfigKeepResult.from_data(
            {"change": CHANGE, "rehearsed": False, "notices": notices}
        ),
    }[method]


SENT = {"code": "config.waiting", "problem": "Sent.", "fix": "Wait.", "details": {}}


@pytest.mark.parametrize(
    ("method", "argv", "shows_sent"),
    [
        ("config-set", ("config", "set", "actors.lead.model=m"), True),
        ("config-set", ("config", "unset", "actors.lead.model"), True),
        ("config-set", ("config", "mv", "actors.lead", "actors.star"), True),
        ("config-get", ("config", "get", "actors.lead.model"), False),
        ("sync", ("sync",), True),
        ("config-drop", ("config", "drop", CHANGE), True),
        ("config-keep", ("config", "keep", CHANGE), True),
    ],
    ids=["set", "unset", "mv", "get", "sync", "drop", "keep"],
)
def test_a_config_command_shows_notices_and_carries_on_through_ctrl_c(
    core: StandIn, method: str, argv: tuple[str, ...], shows_sent: bool
) -> None:
    sent = NoticeUpdate.from_data({"kind": "notice", "notice": SENT})
    core.reply(method, _result(method), sent, presses=1)
    ran = core.run(*argv)
    assert ran.logged == ()  # no error from the Ctrl-C handler
    assert ran.code == ExitCode.OK
    assert ran.err == [
        *(["troupe: Sent.", "  fix: Wait."] if shows_sent else []),
        "troupe: Waiting.",
        "  fix: Wait.",
    ]
    (call,) = core.calls
    assert call.session.theatre == Path.cwd()
    assert call.session.cancel.requested


def test_ctrl_c_while_set_reads_the_actors_runner_doesnt_stop_it(core: StandIn) -> None:
    core.reply("config-get", _got(value="anthropic"), presses=1)
    core.reply("config-set", ConfigSetResult.from_data({"entries": [], "files": [], "notices": []}))
    ran = core.run("config", "set", "actors.lead.options.maxTurns=7")
    assert ran.logged == ()  # no error from the Ctrl-C handler
    assert ran.code == ExitCode.OK
    assert core.requests[-1] == (
        "config-set",
        {"operations": [{"path": ["actors", "lead", "options", "maxTurns"], "value": 7}]},
    )
