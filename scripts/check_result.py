"""Judge CI's check legs for the one required `check` (spec: quality-check; ci-check-scope D3).

Usage: python3 scripts/check_result.py LEGS CHANGES SCOPE

LEGS is the matrix job's result, CHANGES the `changes` job's result, and SCOPE its `scope` answer
(empty when it gave none). GitHub reports a skipped matrix job under its unexpanded name, so the
legs can't be required themselves: this passes when every leg passed, or when they were all skipped
because `changes` answered that nothing needs checking (only skipped paths changed, or on a push to
main, the merge queue passed the commit: ci-once-per-commit design D1), and fails on anything else.

Standard library only: it runs with the runner's python3, before anything is installed.
"""

import sys

RESULTS = ("success", "failure", "cancelled", "skipped")
"""What GitHub reports as a job's result (`needs.<job>.result`)."""


def judge(legs: str, changes: str, scope: str) -> tuple[bool, str]:
    """Whether `check` passes, and one line saying why."""
    if legs not in RESULTS:
        return False, f"the legs' result `{legs}` isn't one of {', '.join(RESULTS)}."
    if legs == "success":
        return True, "every leg passed."
    if legs == "skipped":
        if changes == "success" and scope == "none":
            return True, (
                "the legs were skipped: `changes` answered that nothing needs checking (only "
                "skipped paths changed, or the merge queue passed this commit; its log says which)."
            )
        return False, (
            f"the legs were skipped without a reason to skip them (changes: `{changes}`, scope: "
            f"`{scope}`). Only a `changes` job that succeeded and answered `none` may skip them."
        )
    return False, f"the legs' result is `{legs}`: see the failing leg's log."


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            f"check_result: expected 3 arguments (LEGS CHANGES SCOPE), got {len(argv)}. "
            "Fix: pass the legs' result, the `changes` job's result and its `scope` output.",
            file=sys.stderr,
        )
        return 1
    passed, reason = judge(*argv)
    print(f"check: {'passed' if passed else 'failed'}, {reason}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
