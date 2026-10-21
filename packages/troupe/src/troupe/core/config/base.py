"""The base of config's generated models (config-model design D11).

The models in ``troupe.core.config.models`` are generated from the config schemas by
``scripts/generate_models.py``, which names this class as their base. Each is closed and frozen,
like the schemas. Validate with ``strict=True`` (``parse`` does), so that strictness reaches the
generated root models too: a string is never read as a number, nor a number as a boolean. Patterns
use Python's regular expressions, as the jsonschema library that checks the same schemas does, so
the two agree on every pattern (a model accepts exactly what its schema accepts).

A field given as null is refused, never read as absent: config's schemas accept null nowhere
(spec: protocol, "Absent fields are left out, never sent as null"), but the generated models type
an optional field as ``X | None``.
"""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, model_validator


class StrictModel(BaseModel):
    """A closed, frozen model, validated strictly."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, regex_engine="python-re")

    @model_validator(mode="before")
    @classmethod
    def _no_nulls(cls, data: Any) -> Any:  # noqa: ANN401 - JSON data, checked by the model
        if isinstance(data, dict):
            nulls = [key for key, value in data.items() if value is None]
            if nulls:
                msg = f"{nulls[0]!r} is null: a field with nothing to say is left out"
                raise ValueError(msg)
        return data

    @classmethod
    def parse(cls, data: Any) -> Self:  # noqa: ANN401 - JSON data, checked by the model
        """``data``, which must be exactly what the model's schema accepts."""
        return cls.model_validate(data, strict=True)
