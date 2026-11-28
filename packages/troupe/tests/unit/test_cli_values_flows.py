"""How `troupe config set` types a value at a flow's path, from the flow schema (spec: flows, "A
flow is a config kind of its own"; actor-sequences design D1)."""

import pytest

from troupe.cli import values
from troupe.core.errors import TroupeError


@pytest.mark.parametrize("path", [("flows",), ("flows", "review")])
def test_the_flows_and_a_flow_are_groups(path: tuple[str, ...]) -> None:
    assert values.kinds_at(path, None) == {"object"}


def test_a_flows_steps_are_a_list() -> None:
    assert values.kinds_at(("flows", "review", "steps"), None) == {"array"}


def test_steps_given_on_the_command_line_read_as_a_json_list() -> None:
    read = values.value_of(
        ("flows", "review", "steps"),
        '[{"actor": "writer"}, {"actor": "reviewer", "direction": "Review it."}]',
        runner=None,
        as_json=False,
    )
    assert read == [{"actor": "writer"}, {"actor": "reviewer", "direction": "Review it."}]


def test_a_list_that_isnt_json_is_refused_naming_the_path() -> None:
    with pytest.raises(TroupeError) as refused:
        values.value_of(
            ("flows", "review", "steps"), "writer, reviewer", runner=None, as_json=False
        )
    assert refused.value.code == "config.invalid"
    assert list(refused.value.details["path"]) == ["flows", "review", "steps"]


def test_a_path_inside_a_step_has_no_single_type_so_it_is_given_as_json() -> None:
    # A step is reached through the steps list, which no dotted path indexes: the whole list is
    # set at once, so a path below it names no single schema.
    assert values.kinds_at(("flows", "review", "steps", "0", "actor"), None) == set()


def test_a_field_a_flow_doesnt_have_has_no_type() -> None:
    assert values.kinds_at(("flows", "review", "approvers"), None) == set()
