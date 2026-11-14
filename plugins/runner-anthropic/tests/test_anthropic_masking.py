"""The credential, and a service's masked echo of it, never reach troupe (spec: anthropic-runner,
"A service's echo of the credential is masked", "The credential goes only in the Authorization
header"; design D4).

These check the Mask itself. That every event, record and error the runner sends goes through it
is the runner tests' to show, with the canary."""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from anthropic_harness import CANARY
from troupe_runner_anthropic.masking import MASK, Mask


def test_the_exact_credential_is_masked_wherever_it_appears() -> None:
    mask = Mask(CANARY)
    assert mask(f"Bearer {CANARY}") == f"Bearer {MASK}"
    assert mask(f"x-api-key: {CANARY}") == f"x-api-key: {MASK}"
    assert mask(f"x{CANARY}y{CANARY}") == f"x{MASK}y{MASK}"


def test_a_401_that_quotes_part_of_the_key_is_masked() -> None:
    """Scenario "A 401 that quotes part of the key"."""
    message = "invalid x-api-key: sk-ant-ca*********6789. Check your key."
    assert Mask(CANARY)(message) == f"invalid x-api-key: {MASK}. Check your key."


def test_a_masked_echo_inside_a_json_error_body_is_masked() -> None:
    body = (
        '{"type":"error","error":{"type":"authentication_error",'
        '"message":"invalid x-api-key sk-ant-ca*********6789"}}'
    )
    masked = Mask(CANARY)(body)
    assert json.loads(masked)["error"]["message"] == f"invalid x-api-key {MASK}"


def test_an_echo_inside_json_text_is_masked_and_the_text_is_still_json() -> None:
    record = json.dumps({"record": json.dumps({"message": "key sk-ant-ca****6789."})})
    masked = Mask(CANARY)(record)
    assert json.loads(json.loads(masked)["record"]) == {"message": f"key {MASK}."}


@pytest.mark.parametrize(
    "token",
    ["sk-ant-ca****", "****6789", "sk-a*", "sk-ant-api03-****...6789", "sk-ant-ca*********6789:"],
    ids=repr,
)
def test_an_echo_starting_or_ending_like_the_key_with_stars_is_masked(token: str) -> None:
    masked = Mask(CANARY)(f"key {token} refused")
    assert masked.startswith(f"key {MASK}")
    assert masked.endswith(" refused")
    assert "*" not in masked


@pytest.mark.parametrize(
    "text",
    [
        "sk-ant- without stars",
        "a ****** rating",
        "glob src/**/*.py",
        "sk-other-****9999",
        "sk-ant-other-key-without-the-ends",
    ],
)
def test_text_that_isnt_an_echo_of_the_key_is_left_alone(text: str) -> None:
    assert Mask(CANARY)(text) == text


def test_a_word_ending_in_eight_or_more_of_the_keys_first_characters_is_masked_as_a_cut() -> None:
    """Every Anthropic key starts sk-ant-, so seven characters say nothing; from eight on, a word
    ending in the key's start is taken as the key cut short, without stars."""
    assert Mask(CANARY)("sk-ant-c without stars") == f"{MASK} without stars"
    assert Mask(CANARY)("sk-ant-ca without stars") == f"{MASK} without stars"
    assert Mask(CANARY)("said:sk-ant-canary-01…") == f"said:{MASK}…"


def test_a_short_credential_is_masked_only_whole() -> None:
    mask = Mask("abc123")
    assert mask("token abc123 used") == f"token {MASK} used"
    assert mask("abc1*** and ***c123") == "abc1*** and ***c123"


def test_no_credential_changes_nothing() -> None:
    assert Mask(None)("sk-ant-ca****6789 Bearer x") == "sk-ant-ca****6789 Bearer x"
    assert Mask("")("anything") == "anything"


def test_every_string_in_a_json_value_is_masked_keys_included() -> None:
    value = {CANARY: [f"a {CANARY}", 1, None, {"k": "sk-ant-ca**6789"}], "n": 2.5, "t": True}
    assert Mask(CANARY).json(value) == {
        MASK: [f"a {MASK}", 1, None, {"k": MASK}],
        "n": 2.5,
        "t": True,
    }


def test_the_mask_doesnt_show_the_credential_in_its_repr() -> None:
    assert CANARY not in repr(Mask(CANARY))


@given(
    credential=st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=0x2FF), min_size=1, max_size=40
    ),
    before=st.text(max_size=60),
    after=st.text(max_size=60),
)
def test_no_masked_text_holds_the_credential_whatever_surrounds_it(
    credential: str, before: str, after: str
) -> None:
    masked = Mask(credential)(before + credential + after)
    assert credential not in masked or credential in MASK


def test_a_text_cut_inside_the_key_keeps_none_of_its_start() -> None:
    """A message cut to a limit inside the key keeps only its start, which the whole-value match
    misses; the start is masked too, however the text was cut (the SDK's cut, the exchange's, or
    a plain slice)."""
    from troupe_plugin_sdk.events import cut
    from troupe_runner_anthropic.exchange import _cut

    text = "a service said " + CANARY + " and more" * 40
    for limit in range(len("a service said ") + 8, len(text)):
        for kept in (cut(text, limit + 40), _cut(text, limit), text[:limit]):
            assert CANARY[:8] not in Mask(CANARY)(kept), (limit, kept)
