"""Strict JSON for troupe's own files (event-store design D3).

Python's reader quietly accepts two things that aren't safe to accept: a key repeated in one object
(it keeps the last value) and NaN or Infinity (not JSON at all). Both are refused here, because
silently choosing a value is the quiet fall-through troupe never does (owner, 2026-10-12). The
canonical form, used for content hashes and inline payloads, is sorted keys, no spaces, UTF-8 and no
NaN.
"""

import json


class StrictJSONError(ValueError):
    """Text that isn't strict JSON.

    ``str(error)`` is for troupe's own files, and may name a key from the text. ``rule`` says what's
    wrong in words that hold none of the text, and ``line`` and ``column`` say where, when known, so
    a value a person typed can be refused without repeating it (config-set-json-redacts design D2).
    """

    def __init__(
        self,
        message: str,
        *,
        rule: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        super().__init__(message)
        self.rule = message if rule is None else rule
        self.line = line
        self.column = column


DUPLICATE_KEY = "a key appears more than once in one object"


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            msg = f"the key {key!r} appears more than once in one object"
            raise StrictJSONError(msg, rule=DUPLICATE_KEY)
        data[key] = value
    return data


def _no_non_finite(constant: str) -> object:
    msg = f"{constant} isn't a JSON number"
    raise StrictJSONError(msg)


def loads(text: str | bytes) -> object:
    """Parse ``text`` as JSON, refusing duplicate keys and NaN or Infinity."""
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_non_finite)
    except StrictJSONError:
        raise
    except UnicodeDecodeError as error:
        raise StrictJSONError(
            str(error), rule=f"its bytes can't be read as text (at byte {error.start + 1})"
        ) from error
    except json.JSONDecodeError as error:
        # The decoder's messages are fixed words, except the pure-Python one for a bad escape,
        # which adds ": '<character>'" from the text: the words before ": " hold none of it.
        rule = error.msg.split(": ", 1)[0]
        raise StrictJSONError(
            str(error), rule=rule, line=error.lineno, column=error.colno
        ) from error


def dumps(value: object) -> str:
    """``value`` in canonical form: sorted keys, no spaces, non-ASCII kept as UTF-8, no NaN."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
