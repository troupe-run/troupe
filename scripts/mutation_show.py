"""`mutmut show` for many mutants in one process (#404, mutation-survivor-diffs design D1).

mutation_run.py runs it with mutmut's own interpreter (the `python` beside the `mutmut` it runs),
in mutmut's working directory, after `mutmut run`. It reads a JSON object from stdin, each mutated
file's path (as mutmut names it, under `src/`) to the mutants it wants, and writes a JSON object
from each mutant's name to exactly what `mutmut show <name>` prints: mutmut's own header line and
its own diff, from mutmut's own functions. Only the work `mutmut show` repeats for every mutant is
gone: starting Python and importing mutmut, and walking every `.meta` file to find the mutant
(`find_mutant`). It reads results and source text only: no mutant runs.

mutation_locator_check.py's `show-equal` checks the output equals real `mutmut show` for every
survivor of a real unit; run it again whenever scripts/mutation.json moves mutmut to a new version.
"""

import json
import sys
from pathlib import Path


def render(wanted: dict[str, list[str]]) -> dict[str, str]:
    """What `mutmut show` prints for each wanted mutant, file by file."""
    from mutmut.__main__ import status_by_exit_code  # type: ignore[import-not-found]
    from mutmut.mutation.data import SourceFileMutationData  # type: ignore[import-not-found]
    from mutmut.mutation.diff_apply import get_diff_for_mutant  # type: ignore[import-not-found]

    shown: dict[str, str] = {}
    for path, names in wanted.items():
        results = SourceFileMutationData(path=Path(path))
        results.load()
        for name in names:
            if name not in results.exit_code_by_key:
                raise SystemExit(f"mutation_show: {path} has no mutant {name}")
            status = status_by_exit_code[results.exit_code_by_key[name]]
            # `mutmut show` prints the header, then the diff: two print() calls.
            diff = get_diff_for_mutant(name, path=Path(path))
            shown[name] = f"# {name}: {status}\n{diff}\n"
    return shown


def main() -> int:
    wanted = json.load(sys.stdin)
    if not isinstance(wanted, dict) or not all(
        isinstance(names, list) and all(isinstance(n, str) for n in names)
        for names in wanted.values()
    ):
        print("mutation_show: stdin must be an object of path to a list of mutant names")
        return 2
    json.dump(render(wanted), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
