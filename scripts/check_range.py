"""Decide which revisions CI's `changes` job diffs (spec: quality-check; ci-check-scope D1).

Usage: python3 scripts/check_range.py ACTION BEFORE BASE HEAD CONCLUSION

ACTION is the pull_request event's action, BEFORE the previous head's sha (empty when the event
has none), BASE and HEAD the pull request's shas, and CONCLUSION the previous head's `check`
conclusion (empty when there's none). Prints the revisions for `git diff --name-only`, which split
on the space:

- `<before> <head>` when a push adds to a pull request whose previous head passed `check`: the two
  trees, compared directly, so only what this push changed decides
- `<base>...<head>` otherwise: every path the pull request changes

A malformed input is refused, naming it, and exits 1, so the legs run the full check.

Standard library only: it runs with the runner's python3, before anything is installed.
"""

import re
import sys

SHA = re.compile(r"[0-9a-f]{40}\Z")
ACTIONS = ("opened", "reopened", "synchronize")
"""The pull_request actions CI runs on (the event's default types)."""


class RangeError(ValueError):
    pass


def _sha(name: str, value: str) -> str:
    if not SHA.match(value):
        raise RangeError(f"{name} `{value}` isn't a sha: it must be 40 lowercase hex characters.")
    return value


def revisions(action: str, before: str, base: str, head: str, conclusion: str) -> str:
    """What to diff: the push alone when its previous head passed `check`, else the whole PR."""
    if action not in ACTIONS:
        raise RangeError(f"action `{action}` isn't one CI runs on: {', '.join(ACTIONS)}.")
    base, head = _sha("BASE", base), _sha("HEAD", head)
    if action == "synchronize":
        before = _sha("BEFORE", before)
        if conclusion == "success":
            return f"{before} {head}"
    elif before:
        _sha("BEFORE", before)
    return f"{base}...{head}"


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(
            f"check_range: expected 5 arguments (ACTION BEFORE BASE HEAD CONCLUSION), got "
            f"{len(argv)}. Fix: pass the event's action, the previous head, the base, the head "
            "and the previous head's `check` conclusion, each possibly empty but present.",
            file=sys.stderr,
        )
        return 1
    try:
        print(revisions(*argv))
    except RangeError as error:
        print(f"check_range: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
