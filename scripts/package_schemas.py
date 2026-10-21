"""Copy the protocol's schemas into the troupe package (spec: protocol; config-model design D17).

    uv run scripts/package_schemas.py            make the copy what protocol/schemas/ holds
    uv run scripts/package_schemas.py --check    change nothing; exit 1 naming each difference

protocol/schemas/ is the source of truth (decision #7). troupe carries the schemas it was built
with, so an installed troupe never fetches one, and core reads them only from the copy in
packages/troupe/src/troupe/protocol/ (troupe.core.schemas). The copy is generated, never edited:
a test runs ``--check``, so the source and the copy can't drift.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "protocol" / "schemas"
COPY = ROOT / "packages" / "troupe" / "src" / "troupe" / "protocol"
COMMAND = "uv run scripts/package_schemas.py"
PATTERN = "*.schema.json"


def _files(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob(PATTERN)}


def differences(source: Path = SOURCE, copy: Path = COPY) -> list[str]:
    """Each schema the copy is missing, holds differently, or holds but the source doesn't."""
    want, have = _files(source), _files(copy)
    found = [f"{name}: missing from the copy" for name in sorted(want.keys() - have.keys())]
    found += [
        f"{name}: differs" for name in sorted(want.keys() & have.keys()) if want[name] != have[name]
    ]
    found += [f"{name}: not in protocol/schemas/" for name in sorted(have.keys() - want.keys())]
    return found


def write(source: Path = SOURCE, copy: Path = COPY) -> None:
    want, have = _files(source), _files(copy)
    for name, data in want.items():
        if have.get(name) != data:
            target = copy / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    for name in have.keys() - want.keys():
        (copy / name).unlink()
    for directory in sorted((p for p in copy.rglob("*") if p.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()


def main(argv: Sequence[str] | None = None, source: Path = SOURCE, copy: Path = COPY) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="change nothing; fail if stale")
    args = parser.parse_args(argv)
    if not args.check:
        write(source, copy)
        return 0
    found = differences(source, copy)
    for difference in found:
        print(f"package_schemas: {difference}", file=sys.stderr)
    if found:
        print(
            f"package_schemas: the troupe package's copy of protocol/schemas/ is stale. "
            f"Fix: run `{COMMAND}`, then commit it.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
