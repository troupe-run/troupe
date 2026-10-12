"""Strict JSON for troupe's own files (event-store design D3).

Python's reader quietly accepts two things that aren't safe to accept: a key repeated in one object
(it keeps the last value) and NaN or Infinity (not JSON at all). Both are refused here, because
silently choosing a value is the quiet fall-through troupe never does (owner, 2026-10-12). The
canonical form, used for content hashes and inline payloads, is sorted keys, no spaces, UTF-8 and no
NaN.
"""

import json


class StrictJSONError(ValueError):
    """Text that isn't strict JSON."""


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            msg = f"the key {key!r} appears more than once in one object"
            raise StrictJSONError(msg)
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
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StrictJSONError(str(error)) from error


def dumps(value: object) -> str:
    """``value`` in canonical form: sorted keys, no spaces, non-ASCII kept as UTF-8, no NaN."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
