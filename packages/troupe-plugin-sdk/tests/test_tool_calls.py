"""A malformed call is an error result naming the problem, and the run goes on (spec: runner-tools,
"A malformed call is an error result, not a failed run"; runner-sdk design D5)."""

from pathlib import Path

import pytest

from sdk_tools import RUN, FakeModel, as_text, call, tools_for, workspace
from troupe_plugin_sdk.effects import Effects
from troupe_plugin_sdk.events import EventNumbering
from troupe_plugin_sdk.tools import Tools

MALFORMED = [
    ("Bash", {"command": "ls"}, ["'Bash'", "Read, Write, Edit, Glob, Grep, Delete, Move"]),
    ("Write", '{"file_path": "a.txt",', ["isn't valid JSON"]),
    ("Write", "[1, 2]", ["must be a JSON object"]),
    ("Write", '{"file_path": "a", "file_path": "b", "content": ""}', ["'file_path' twice"]),
    ("Write", '{"file_path": "a", "content": NaN}', ["NaN"]),
    ("Edit", {"file_path": "a.txt", "new_string": "x"}, ["Edit needs old_string"]),
    ("Read", {"file_path": "a.txt", "encoding": "utf-8"}, ["Read doesn't take encoding"]),
    ("Read", {"file_path": 3}, ["Read's file_path must be a string"]),
    ("Read", {"file_path": "a.txt", "offset": 0}, ["Read's offset must be at least 1"]),
    ("Read", {"file_path": "a.txt", "limit": True}, ["Read's limit must be an integer"]),
    (
        "Edit",
        {"file_path": "a", "old_string": "a", "new_string": "b", "replace_all": "yes"},
        ["replace_all must be a boolean"],
    ),
]


@pytest.mark.parametrize(("name", "arguments", "says"), MALFORMED)
def test_each_malformed_call_is_an_error_result_naming_the_problem_and_nothing_changes(
    tmp_path: Path, name: str, arguments: object, says: list[str]
) -> None:
    root = workspace(tmp_path, {"a.txt": b"a\n"})
    tools = tools_for(root, Effects(write=("**",), delete=("**",), move=("**",)))

    step = call(tools, name, arguments)  # type: ignore[arg-type]

    assert step.is_error
    assert step.result.is_error
    for part in says:
        assert part in step.output
    assert sorted(p.name for p in root.iterdir()) == ["a.txt"]
    assert (root / "a.txt").read_bytes() == b"a\n"


def test_the_next_call_is_still_carried_out_after_a_malformed_one(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    tools = tools_for(root, Effects(write=("**",)))
    model = FakeModel(
        [
            ("Write", '{"file_path": "a.txt",'),
            ("Write", as_text({"file_path": "a.txt", "content": "fine"})),
        ]
    )

    model.drive(tools, EventNumbering(RUN, 65536, next_seq=1))

    assert [is_error for _, is_error in model.seen] == [True, False]
    assert (root / "a.txt").read_bytes() == b"fine"


def test_arguments_as_json_text_and_as_an_object_do_the_same(tmp_path: Path) -> None:
    root = workspace(tmp_path, {"a.txt": b"one\n"})
    tools = tools_for(root)
    as_object = call(tools, "Read", {"file_path": "a.txt"})
    as_json = call(tools, "Read", as_text({"file_path": "a.txt"}))
    assert as_object.output == as_json.output
    assert as_json.call.input_summary == '{"file_path": "a.txt"}'


def test_an_empty_call_id_is_the_runners_mistake_and_raises(tmp_path: Path) -> None:
    tools = Tools(workspace(tmp_path))
    with pytest.raises(ValueError, match="non-empty call id"):
        tools.run("", "Read", {"file_path": "a"}, EventNumbering(RUN, 1000))


def test_a_call_with_no_tool_name_is_an_error_result(tmp_path: Path) -> None:
    step = call(tools_for(workspace(tmp_path)), "", {})
    assert step.is_error
    assert step.call.tool == "(no name)"
