"""The credential, and a service's masked echo of it, never reach troupe (spec: openai-runner,
"A service's echo of the credential is masked"; design D11)."""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from troupe_runner_openai.masking import MASK, Mask

CANARY = "sk-canary-0123456789"


def test_the_exact_credential_is_masked_wherever_it_appears() -> None:
    mask = Mask(CANARY)
    assert mask(f"Bearer {CANARY}") == f"Bearer {MASK}"
    assert mask(f"x{CANARY}y{CANARY}") == f"x{MASK}y{MASK}"


def test_a_401_that_quotes_part_of_the_key_is_masked() -> None:
    message = "Incorrect API key provided: sk-cana*********6789. You can find your API key at"
    assert (
        Mask(CANARY)(message) == f"Incorrect API key provided: {MASK}. You can find your API key at"
    )


def test_a_masked_echo_inside_a_json_body_is_masked() -> None:
    body = '{"error": {"message": "Incorrect API key provided: sk-cana****6789", "code": null}}'
    assert Mask(CANARY)(body) == (
        '{"error": {"message": "Incorrect API key provided: ' + MASK + '", "code": null}}'
    )


def test_an_echo_inside_json_text_is_masked_and_the_text_is_still_json() -> None:
    record = json.dumps({"kind": "body", "body": json.dumps({"message": "key sk-cana****6789."})})
    masked = Mask(CANARY)(record)
    assert json.loads(json.loads(masked)["body"]) == {"message": f"key {MASK}."}


@pytest.mark.parametrize(
    "token",
    ["sk-cana****", "****6789", "sk-c*", "sk-proj-****...6789"],
    ids=repr,
)
def test_an_echo_starting_or_ending_like_the_key_with_stars_is_masked(token: str) -> None:
    assert Mask(CANARY)(f"key {token} refused") == f"key {MASK} refused"


@pytest.mark.parametrize(
    "text", ["sk-cana without stars", "a ****** rating", "glob src/**/*.py", "sk-other-****9999"]
)
def test_text_that_isnt_an_echo_of_the_key_is_left_alone(text: str) -> None:
    assert Mask(CANARY)(text) == text


def test_a_short_credential_is_masked_only_whole() -> None:
    mask = Mask("abc123")
    assert mask("token abc123 used") == f"token {MASK} used"
    assert mask("abc1*** and ***c123") == "abc1*** and ***c123"


def test_no_credential_changes_nothing() -> None:
    assert Mask(None)("sk-cana****6789 Bearer x") == "sk-cana****6789 Bearer x"
    assert Mask("")("anything") == "anything"


def test_every_string_in_a_json_value_is_masked_keys_included() -> None:
    value = {CANARY: [f"a {CANARY}", 1, None, {"k": "sk-cana**6789"}], "n": 2.5}
    assert Mask(CANARY).json(value) == {MASK: [f"a {MASK}", 1, None, {"k": MASK}], "n": 2.5}


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
    from troupe_plugin_sdk.events import cut
    from troupe_runner_openai.exchange import _cut

    text = "a service said " + CANARY + " and more" * 40
    for limit in range(len("a service said ") + 8, len(text)):
        for kept in (cut(text, limit + 40), _cut(text, limit), text[:limit]):
            assert CANARY[:8] not in Mask(CANARY)(kept), (limit, kept)
