"""Tests for the run host that need no running runner: a runner command that doesn't exist could not
start and has no audit, a masked transcript record is framed so it validates and decodes to the
masked bytes, and every valid runner line is read with no kept string holding the credential,
while keys that masking would merge are a protocol violation (spec: actor-runners,
runner-protocol).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_run_host.py."""

import base64
import json
from pathlib import Path

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from masking_checks import forms_outside_the_marker, writings
from protocol_schemas import validator_for
from run_host_shared import STORED_RECORD, _audit, _code, _run
from troupe.core.masking import MARKER, Masker
from troupe.core.runners import host as host_module
from troupe.core.runners.host import framed_record
from troupe.core.runners.outcome import Ending, Outcome
from troupe_plugin_sdk import runner as p


def test_a_runner_command_that_does_not_exist_could_not_start(tmp_path: Path) -> None:
    ran = _run(tmp_path, argv=["troupe-no-such-runner"])
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.COULD_NOT_START, "runner.start-failed")
    assert ran.outcome.error is not None
    assert "troupe-no-such-runner" in ran.outcome.error.problem
    assert ran.outcome.transcript is None
    assert ran.outcome.ending is Ending.NEVER_STARTED


def test_a_runner_that_couldnt_be_started_has_no_audit(tmp_path: Path) -> None:
    ran = _run(tmp_path, argv=["troupe-no-such-runner"], audit=_audit(tmp_path))
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.COULD_NOT_START, "runner.start-failed")
    assert ran.outcome.audit is None
    assert "audit" not in ran.outcome.to_data()


@settings(max_examples=200, deadline=None)
@given(
    kind=st.sampled_from(p.TRANSCRIPT_KINDS),
    # The host refuses a lone surrogate before a record is masked or framed (design D3).
    before=st.text(st.characters(codec="utf-8")),
    after=st.text(st.characters(codec="utf-8")),
    secret=st.sampled_from(["sk-test-canary-0123456789", 'sk-"q/uo\\teé-canary']),
    embed=st.booleans(),
)
def test_a_masked_text_record_framed_validates_and_decodes_to_the_masked_bytes(
    kind: p.TranscriptKind, before: str, after: str, secret: str, embed: bool
) -> None:
    masked = Masker(secret).text(before + (secret if embed else "") + after).encode()
    line = json.loads(framed_record(kind, masked, base64_=False))
    validator_for(STORED_RECORD).validate(line)
    assert line["kind"] == kind
    assert "encoding" not in line
    assert line["record"].encode("utf-8") == masked
    assert not embed or secret not in line["record"]


@settings(max_examples=200, deadline=None)
@given(kind=st.sampled_from(p.TRANSCRIPT_KINDS), data=st.binary())
def test_a_masked_byte_record_framed_validates_and_decodes_to_the_masked_bytes(
    kind: p.TranscriptKind, data: bytes
) -> None:
    masked = Masker("sk-test-canary-0123456789").bytes(data + b"sk-test-canary-0123456789")
    line = json.loads(framed_record(kind, masked, base64_=True))
    validator_for(STORED_RECORD).validate(line)
    assert (line["kind"], line["encoding"]) == (kind, "base64")
    assert base64.b64decode(line["record"]) == masked
    assert masked.endswith(b"[credential]")


VISIBLE = st.characters(min_codepoint=0x21, max_codepoint=0x7E)
PROTOCOL_WORDS = '{"jsonrpc":"2.0","method":"run/transcript","params":{"runId":"r","record":'
"""The fixed text of the lines below, which a credential inside would mask."""
JSON_OUTSIDE_STRINGS = set("{}[],:0123456789.eE+-")
"""What JSON writes outside its strings, in the messages below (no numbers or literals)."""


@st.composite
def runner_lines(draw: st.DrawFn) -> tuple[str, bytes]:
    """A credential, and a valid run/transcript line whose strings (keys included) are built from
    pieces of it, escapes and other text, each string written with or without non-ASCII escaped
    and with or without / escaped."""
    credential = draw(st.text(VISIBLE, min_size=1, max_size=16))
    cut = draw(st.integers(0, len(credential)))
    piece = st.sampled_from(
        [
            *(credential, credential[:cut], credential[cut:], credential[1:]),
            *("\n", "\t", "\\", '"', "/", "é", "\U0001f600", "\x00", "[credential]"),
        ]
    ) | st.text(VISIBLE, max_size=4)
    strings = st.lists(piece, max_size=6).map("".join)

    def write(text: str) -> str:
        written = json.dumps(text, ensure_ascii=draw(st.booleans()))
        return written.replace("/", "\\/") if draw(st.booleans()) else written

    extra = draw(st.dictionaries(strings, strings, max_size=3))
    params = '"runId": "r", "record": ' + write(draw(strings))
    for key, value in extra.items():
        if key not in ("runId", "record"):
            params += f", {write(key)}: {write(value)}"
    line = '{"jsonrpc": "2.0", "method": "run/transcript", "params": {' + params + "}}"
    return credential, line.encode("utf-8")


MERGING_KEYS = (
    "0",
    b'{"jsonrpc": "2.0", "method": "run/transcript", "params": {"runId": "r", "record": "", '
    b'"0": "", "\xc3\xa9": ""}}',
)
"""A credential, and a line two of whose keys mask to the same text."""


def _keys(value: object) -> int:
    if isinstance(value, dict):
        return len(value) + sum(_keys(item) for item in value.values())
    if isinstance(value, list):
        return sum(_keys(item) for item in value)
    return 0


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for key, item in value.items() for s in [key, *_strings(item)]]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


@settings(max_examples=500, deadline=None)
@given(runner_lines())
@example(MERGING_KEYS)
@example(  # a one-letter credential is in troupe's own words, which are masked too (#459)
    (
        "r",
        b'{"jsonrpc": "2.0", "method": "run/transcript", '
        b'"params": {"runId": "r", "record": "", "r": "", "rr": ""}}',
    )
)
@example(
    (
        "nsecret-token-0123456789",
        b'{"jsonrpc":"2.0","method":"run/transcript",'
        b'"params":{"runId":"r","record":"\\nsecret-token-0123456789"}}',
    )
)
def test_every_valid_line_is_read_and_no_string_it_keeps_holds_the_credential(
    case: tuple[str, bytes],
) -> None:
    credential, line = case
    mask = Masker(credential)
    raw = json.loads(line)
    if _keys(mask.data(raw)) < _keys(raw):
        # The one violation a valid line can be: masking would merge two keys, losing a value.
        with pytest.raises(host_module._Violation) as raised:
            host_module.parse_runner_line(mask, line, 1)
        # The sentence after the problem's fixed prefix names the runner's keys, so it is masked
        # whole, troupe's own words too: a one-letter credential masks letters of them (#459).
        # Put back, they read as written; masked, the credential is in no form outside a marker.
        problem = raised.value.error.problem
        _, sentence = problem.split(": ", 1)
        assert "same once the run's credential" in sentence.replace(MARKER, credential), problem
        for writing in writings(sentence):
            assert not forms_outside_the_marker(mask, writing), (sentence, writing)
        return
    message, kept = host_module.parse_runner_line(mask, line, 1)  # otherwise never a violation
    # The same message, each string masked: masking reads, never re-reads, the line. The record
    # is masked as a record, so one that is JSON stays JSON (transcript-masking design D4).
    record = raw["params"]["record"]
    assert _strings(message) == [
        mask.record(s) if s is record else mask.text(s) for s in _strings(raw)
    ]
    for text in _strings(message):
        for writing in writings(text):
            assert not forms_outside_the_marker(mask, writing), (text, writing)
    # The kept line is the line, or the message written out; both read back as the message. A
    # form only across JSON's own syntax needs a credential of it (design, non-goals).
    assert json.loads(kept) == message
    if '"' not in credential and not set(credential) <= JSON_OUTSIDE_STRINGS:
        assert not forms_outside_the_marker(mask, kept)
    # The protocol's own words are read as themselves unless the credential is in them.
    if credential not in PROTOCOL_WORDS:
        assert p.parse_message(message).method == "run/transcript"


def test_two_keys_that_masking_would_make_one_are_a_violation_not_a_merge() -> None:
    # Found by a flake hunt of the property test above: with a credential of 0, the key "é" is
    # written as \u00e9 in ASCII JSON, so it masks to [credential] as the key "0" does.
    line = MERGING_KEYS[1]
    with pytest.raises(host_module._Violation) as raised:
        host_module.parse_runner_line(Masker(MERGING_KEYS[0]), line, 1)
    assert "same once the run's credential is masked" in raised.value.error.problem


@pytest.mark.parametrize(
    ("credential", "line"),
    [
        (
            "qz",
            b'{"jsonrpc":"2.0","method":"run/transcript","params":'
            b'{"qz":1,"[credential]":2,"runId":"r","record":"x"}}',
        ),
        (
            "qz",
            b'{"jsonrpc":"2.0","method":"run/transcript","params":'
            b'{"runId":"r","record":"x","qz":1,"[credential]":2}}',
        ),
        (
            "params",
            b'{"jsonrpc":"2.0","method":"run/transcript","params":{"runId":"r","record":"x"},'
            b'"[credential]":1}',
        ),
    ],
    ids=["before the record, which is last", "after the record", "after params"],
)
def test_keys_that_mask_to_one_around_a_record_are_a_violation_not_a_crash(
    credential: str, line: bytes
) -> None:
    # Review of #439: masking the record apart from the message must not assume masking kept
    # every key; two that merge are the protocol violation they were before.
    with pytest.raises(host_module._Violation) as raised:
        host_module.parse_runner_line(Masker(credential), line, 1)
    assert "same once the run's credential is masked" in raised.value.error.problem
