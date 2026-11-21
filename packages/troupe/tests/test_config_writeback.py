"""Surgical write-back (spec: config-files, "Write-back changes only what it must", "A write-back
that wouldn't read as config says is refused"; hand-edit-sweep design D6)."""

from pathlib import Path
from typing import Any

import pytest

from configtesting import TESTER
from troupe.core.config.reading import read_values
from troupe.core.config.writeback import write_back
from troupe.core.errors import TroupeError

FIELDS: dict[str, Any] = {k: v for k, v in TESTER.items() if k != "character"}
PATH = "actors/tester.yaml"

FORMATTED = """\
# The tester: written by hand.
expect:   # what it must write
    - out/hello.txt   # the one file

# runner below, on purpose
runner: scripted   # offline
effects: {write: ["out/**"]}
options:
  script:
    onCancel: end
    steps:
      - event: {type: init, runner: {name: scripted, version: "0"}, tools: []}
"""


def _formatted() -> tuple[bytes, dict[str, Any]]:
    data = FORMATTED.encode()
    return data, read_values(PATH, data).values


def _unchanged_lines(before: str, after: str, touched: set[str]) -> None:
    """Every line of ``before`` that holds none of ``touched`` is in ``after``, in order."""
    kept = [line for line in before.splitlines() if not any(t in line for t in touched)]
    remaining = iter(after.splitlines())
    for line in kept:
        assert any(line == other for other in remaining), f"lost or changed: {line!r}"


def test_a_changed_scalar_keeps_its_comment_and_every_other_line() -> None:
    data, values = _formatted()
    out = write_back(PATH, data, {**values, "runner": "claude-code"}).decode()
    assert "runner: claude-code   # offline\n" in out
    assert out.replace("runner: claude-code", "runner: scripted") == FORMATTED


def test_a_new_key_goes_after_the_last_key_the_schema_puts_before_it() -> None:
    data, values = _formatted()
    out = write_back(PATH, data, {**values, "model": "m"}).decode()
    # model comes after effects and workspace in the schema; effects is the last such key here,
    # and options (before model in the schema) is the file's last entry: model follows options.
    assert out == FORMATTED + "model: m\n"


def test_a_new_key_before_every_existing_one_goes_first() -> None:
    data = b"# top\nmodel: m\n"
    out = write_back("runtimes/openai.yaml", data, {"endpoint": "http://x", "model": "m"})
    assert out == b"# top\nendpoint: http://x\nmodel: m\n"


def test_a_removed_key_takes_only_its_own_lines() -> None:
    data, values = _formatted()
    out = write_back(PATH, data, {k: v for k, v in values.items() if k != "effects"}).decode()
    assert out == FORMATTED.replace('effects: {write: ["out/**"]}\n', "")


def test_a_block_list_is_replaced_whole_and_the_lines_around_it_stay() -> None:
    data, values = _formatted()
    out = write_back(PATH, data, {**values, "expect": ["a", "b"]}).decode()
    assert "expect:\n  - a\n  - b\n" in out
    assert "# the one file" not in out
    _unchanged_lines(FORMATTED, out, {"expect", "out/hello.txt"})
    assert read_values(PATH, out.encode()).values["expect"] == ["a", "b"]


def test_a_flow_collection_is_replaced_in_flow_style() -> None:
    data, values = _formatted()
    out = write_back(PATH, data, {**values, "effects": {"write": ["out/**", "log/**"]}}).decode()
    assert "effects: {write: [out/**, log/**]}\n" in out
    _unchanged_lines(FORMATTED, out, {"effects"})


def test_a_change_inside_a_block_group_touches_only_that_key() -> None:
    data, values = _formatted()
    options = {"script": {**values["options"]["script"], "onCancel": "error"}}
    out = write_back(PATH, data, {**values, "options": options}).decode()
    assert out == FORMATTED.replace("onCancel: end", "onCancel: error")


def test_a_new_key_inside_a_group_goes_in_sorted_order() -> None:
    data = b"options:\n    b: 1\n    d: 2\nrunner: scripted\n"
    current = read_values(PATH, data).values
    out = write_back(PATH, data, {**current, "options": {"b": 1, "c": 3, "d": 2}})
    assert out == b"options:\n    b: 1\n    c: 3\n    d: 2\nrunner: scripted\n"


def test_crlf_files_get_crlf_lines() -> None:
    data = b"runner: scripted\r\nexpect: []\r\n"
    out = write_back(PATH, data, {"runner": "scripted", "expect": [], "model": "m"})
    assert out == b"runner: scripted\r\nexpect: []\r\nmodel: m\r\n"


def test_a_file_with_no_final_newline_gets_one_before_a_new_key() -> None:
    out = write_back(PATH, b"runner: scripted", {"runner": "scripted", "model": "m"})
    assert out == b"runner: scripted\nmodel: m\n"


def test_a_block_scalar_changed_is_replaced_as_its_whole_entry() -> None:
    data = b"model: |\n  long\n  text\nrunner: scripted\n"
    out = write_back(PATH, data, {"model": "short", "runner": "scripted"})
    assert out == b"model: short\nrunner: scripted\n"


def test_a_groups_new_last_key_and_a_new_key_after_the_group_keep_their_order() -> None:
    # Found by the property test: both inserts land at the end of the file.
    data = b"effects:  # note\n  sa: 'sb'\n"
    out = write_back(PATH, data, {"effects": {"sx": "sz"}, "workspace": "theatre"})
    assert out == b"effects:  # note\n  sx: sz\nworkspace: theatre\n"


def test_unchanged_values_return_the_file_byte_for_byte() -> None:
    data, values = _formatted()
    assert write_back(PATH, data, values) == data


def test_a_character_is_replaced_whole() -> None:
    assert write_back("actors/tester.md", b"Old\n", {"character": "New."}) == b"New."


def test_a_write_back_that_wouldnt_read_as_config_says_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from troupe.core.config import writeback

    monkeypatch.setattr(writeback, "_scalar", lambda value: "wrong")
    data, values = _formatted()
    with pytest.raises(TroupeError) as caught:
        write_back(PATH, data, {**values, "runner": "claude-code"})
    assert caught.value.code == "config.write-back-failed"
    assert caught.value.details == {"file": ".troupe/actors/tester.yaml"}
    assert "troupe sync --force" in caught.value.fix


# The property: generated formatted files and random changes (design D6).

from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from troupe.core.config.projection import FIELD_ORDER  # noqa: E402

KEYS = list(FIELD_ORDER[1:])
words = st.text(alphabet="abcdxyz", min_size=1, max_size=6).map(lambda w: "s" + w)
scalars = st.one_of(words, st.integers(min_value=0, max_value=999), st.booleans())
lists = st.lists(scalars, min_size=1, max_size=3)
groups = st.dictionaries(words, st.one_of(scalars, lists), min_size=1, max_size=3)
values = st.one_of(scalars, lists, groups)


def _scalar_text(value: object, quote: int) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return [str(value), f"'{value}'", f'"{value}"'][quote]


@st.composite
def formatted(draw: st.DrawFn) -> tuple[bytes, dict[str, Any]]:
    """A file a person might have written: any key order, comments, blank lines, indentation,
    quoting, flow or block collections, and either line ending."""
    chosen = draw(st.dictionaries(st.sampled_from(KEYS), values, min_size=1))
    order = draw(st.permutations(list(chosen)))
    newline = draw(st.sampled_from(["\n", "\r\n"]))
    lines: list[str] = []
    if draw(st.booleans()):
        lines.append("# written by hand")
    for key in order:
        value = chosen[key]
        if draw(st.booleans()):
            lines.append("")
        if draw(st.booleans()):
            lines.append(f"# about {key}")
        comment = "  # note" if draw(st.booleans()) else ""
        if isinstance(value, dict | list) and draw(st.booleans()):
            if isinstance(value, list):
                inner = ", ".join(_scalar_text(v, 0) for v in value)
                lines.append(f"{key}: [{inner}]{comment}")
            else:
                inner = ", ".join(
                    f"{k}: [{', '.join(_scalar_text(i, 0) for i in v)}]"
                    if isinstance(v, list)
                    else f"{k}: {_scalar_text(v, 0)}"
                    for k, v in value.items()
                )
                lines.append(f"{key}: {{{inner}}}{comment}")
        elif isinstance(value, list):
            indent = " " * draw(st.sampled_from([0, 2, 4]))
            lines.append(f"{key}:{comment}")
            lines += [f"{indent}- {_scalar_text(v, draw(st.integers(0, 2)))}" for v in value]
        elif isinstance(value, dict):
            indent = " " * draw(st.sampled_from([2, 4]))
            lines.append(f"{key}:{comment}")
            for k, v in value.items():
                if isinstance(v, list):
                    lines.append(f"{indent}{k}: [{', '.join(_scalar_text(i, 0) for i in v)}]")
                else:
                    lines.append(f"{indent}{k}: {_scalar_text(v, draw(st.integers(0, 2)))}")
        else:
            lines.append(f"{key}: {_scalar_text(value, draw(st.integers(0, 2)))}{comment}")
    data = newline.join(lines).encode() + newline.encode()
    return data, read_values(PATH, data).values


@st.composite
def changed(draw: st.DrawFn, current: dict[str, Any]) -> dict[str, Any]:
    target = dict(current)
    for key in list(target):
        action = draw(st.sampled_from(["keep", "keep", "change", "remove"]))
        if action == "change":
            target[key] = draw(values)
        elif action == "remove" and len(target) > 1:
            del target[key]
    for key in draw(st.lists(st.sampled_from(KEYS), max_size=2)):
        target.setdefault(key, draw(values))
    return target


def _entry_texts(data: bytes) -> dict[str, str]:
    """Each top-level key's own text: its lines, from its key to the end of its value."""
    from ruamel.yaml import YAML

    from troupe.core.config.writeback import _end, _line_end, _line_start

    text = data.decode()
    node = YAML(typ="rt").compose(text)
    return {
        key.value: text[
            _line_start(text, key.start_mark.index) : _line_end(text, _end(text, value))
        ]
        for key, value in node.value
    }


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data())
def test_write_back_keeps_every_untouched_entry_and_reads_as_the_target(
    data: st.DataObject,
) -> None:
    original, current = data.draw(formatted())
    target = data.draw(changed(current))
    refused: TroupeError | None = None
    try:
        out = write_back(PATH, original, target)
    except TroupeError as error:
        refused = error
    if refused is not None:
        assert refused.code == "config.write-back-failed"  # never a wrong file
        return
    assert read_values(PATH, out).values == target
    after = out.decode()
    for key, text in _entry_texts(original).items():
        if key in target and current.get(key) == target[key]:
            assert text in after, f"{key}'s lines changed"


# The files a write makes, and the check before replacing one (design D6, D10).


def test_targets_write_a_persons_file_back_and_render_troupes_whole() -> None:
    from troupe.core.config.projection import render
    from troupe.core.config.writeback import targets

    data, values = _formatted()
    config = {"actors": {"tester": {**values, "model": "m"}, "qa": {**values}}}
    files = targets(config, {PATH: data}, {PATH})
    assert files[PATH] == data + b"model: m\n"
    assert files["actors/qa.yaml"] == render(config)["actors/qa.yaml"]


def test_a_file_changed_after_the_sweep_read_it_is_refused_and_left_alone(tmp_path: Path) -> None:
    from troupe.core.config.projection import Action, Plan, execute

    troupe_dir = tmp_path / ".troupe"
    (troupe_dir / "actors").mkdir(parents=True)
    target = troupe_dir / PATH
    target.write_bytes(b"what the sweep read\n")
    plan_ = Plan((Action(PATH, "write", "for this change", b"what troupe writes\n"),))
    target.write_bytes(b"saved by the person meanwhile\n")
    with pytest.raises(TroupeError) as caught:
        execute(troupe_dir, plan_, {PATH: b"what the sweep read\n"})
    assert caught.value.code == "config.file-changing"
    assert target.read_bytes() == b"saved by the person meanwhile\n"


def test_a_file_still_as_the_sweep_read_it_is_replaced(tmp_path: Path) -> None:
    from troupe.core.config.projection import Action, Plan, execute

    troupe_dir = tmp_path / ".troupe"
    (troupe_dir / "actors").mkdir(parents=True)
    (troupe_dir / PATH).write_bytes(b"read\n")
    plan_ = Plan((Action(PATH, "write", "for this change", b"new\n"),))
    execute(troupe_dir, plan_, {PATH: b"read\n"})
    assert (troupe_dir / PATH).read_bytes() == b"new\n"
