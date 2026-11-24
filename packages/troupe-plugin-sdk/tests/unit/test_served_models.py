"""ServedModels: when a runner reports the model that answered (spec: runner-protocol, "A model
other than init's is reported as it answers" and "A served model's name has a model's shape")."""

from hypothesis import given
from hypothesis import strategies as st

from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.events import ServedModels

RUN = "00000000-0000-4000-8000-000000000001"


def test_another_model_is_a_served_model_body() -> None:
    assert ServedModels("gpt-6-luna").note("gpt-6-luna-2026-03-05") == [
        {"type": "served_model", "model": "gpt-6-luna-2026-03-05"}
    ]


def test_the_model_init_named_sends_nothing() -> None:
    assert ServedModels("gpt-6-luna").note("gpt-6-luna") == []


def test_an_empty_or_missing_name_sends_nothing() -> None:
    served = ServedModels("gpt-6-luna")
    assert served.note("") == []
    assert served.note(None) == []


def test_a_model_already_noted_sends_nothing_the_second_time() -> None:
    served = ServedModels("gpt-6-luna")
    assert served.note("m-2") == [{"type": "served_model", "model": "m-2"}]
    assert served.note("m-2") == []


def test_with_no_model_on_init_every_model_is_noted_once() -> None:
    served = ServedModels(None)
    assert served.note("m-1") == [{"type": "served_model", "model": "m-1"}]
    assert served.note("m-1") == []


def test_a_name_with_a_control_character_is_a_log_warning_showing_it_escaped() -> None:
    served = ServedModels("gpt-6-luna")
    [body] = served.note("bad\nname")
    assert body["type"] == "log"
    assert body["level"] == "warning"
    assert "can't record" in body["message"]
    assert '"bad\\nname"' in body["message"]
    assert served.note("bad\nname") == []


def test_a_name_too_long_to_record_is_a_log_warning_with_the_name_cut() -> None:
    [body] = ServedModels(None).note("m" * 10_000)
    assert body["type"] == "log"
    assert "m" * 300 not in body["message"]
    assert "bytes left out" in body["message"]


def test_a_name_of_256_characters_is_recorded() -> None:
    assert ServedModels(None).note("m" * 256) == [{"type": "served_model", "model": "m" * 256}]


@given(
    asked=st.one_of(st.none(), st.text(max_size=5)),
    names=st.lists(st.one_of(st.none(), st.text(max_size=5), st.text(min_size=250, max_size=260))),
)
def test_no_model_is_sent_twice_or_for_init_and_every_one_sent_validates(
    asked: str | None, names: list[str | None]
) -> None:
    served = ServedModels(asked)
    sent: list[str] = []
    for seq, name in enumerate(names, start=1):
        for body in served.note(name):
            if body["type"] == "served_model":
                sent.append(body["model"])
                event = p.parse_event({"runId": RUN, "seq": seq, **body})
                assert isinstance(event, p.ServedModelEvent)
            else:
                assert isinstance(p.parse_event({"runId": RUN, "seq": seq, **body}), p.LogEvent)
    assert len(sent) == len(set(sent))
    assert asked not in sent
    assert all(p.MODEL_PATTERN.match(model) for model in sent)
