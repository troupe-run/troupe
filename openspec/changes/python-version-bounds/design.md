# Design

## Context

See proposal.md for why. Today, every one of the nine `pyproject.toml` files says `requires-python = ">=3.12"`,
`.github/workflows/ci.yml` tests `["3.12", "3.13"]`, ruff's `target-version` is `py312`, mypy's `python_version`
is `"3.12"`, and there's no `.python-version`. `scripts/release_config.py` sets the pattern for repository checks:
standard library only, run as a test inside `scripts/check.py`, and each problem names the file to fix.

uv 0.13.1 was tried against a project with `requires-python = ">=3.12,<3.14"`:

- `uv run --python 3.14`, `UV_PYTHON=3.15 uv run`, and a `.python-version` of 3.15 are all refused with
  `incompatible with the project's Python requirement: >=3.12, <3.14`.
- An existing `.venv` on an incompatible version is replaced on the next `uv run`, not used.
- With a PEP 723 header (`# /// script`), `uv run <script>` runs in isolation and doesn't create or sync `.venv`.
- `UV_PROJECT_ENVIRONMENT=.venvs/3.13 uv run --python 3.13 ...` builds `.venvs/3.13`, and later runs on either
  version reuse their own environments.

## Goals / Non-Goals

**Goals:**

- One place declares the supported versions: the root's `requires-python`. Everything else is checked against it.
- Switching a run to another supported version takes one command, costs nothing after the first run, and never
  disturbs another version's environment.

**Non-Goals:**

- Part 2 of #104: adding 3.14 and 3.15 to CI and widening the bound.
- Guarding interpreters that bypass uv, such as `python3.15 scripts/check.py` with a hand-made environment. uv is
  the documented way in, and a published wheel's `Requires-Python` covers installers.
- The guard's CI job (`guard.yml`, `uv run --no-project`), which belongs to troupe-run/infrastructure.

## Decisions

### D1. The root's `requires-python` is the single source; everything else is checked against it

The supported minors are derived from the root's bound: `>=3.12,<3.14` gives 3.12 and 3.13. Members, the CI matrix,
`.python-version`, ruff's `target-version` and mypy's `python_version` must agree with it, and the check names the
file that doesn't.

*Alternatives:* derive the members' bounds at build time (uv and hatchling can't inherit `requires-python` from the
workspace root, and a published package has to carry its own), or generate the CI matrix from the bound (it's
static YAML, and a generator adds a step to forget). Checking keeps each file readable as it is and makes a mismatch
loud.

### D2. Only `>=3.X,<3.Y` is accepted

`packaging` isn't a dev dependency and the check is standard library only, so the bound is parsed against a strict
form: `>=3.X,<3.Y` with optional spaces, and X < Y. Anything else (`~=3.12`, `>=3.12`, `!=`, a patch version) is an
error naming `pyproject.toml` and the expected form, never interpreted. An upper bound is required: no upper bound is
exactly the problem this change fixes.

### D3. The CI matrix is read from one line, strictly

`ci.yml`'s matrix line is `python: ["3.12", "3.13"]`. The check finds exactly one line matching
`python: [ ... ]` anywhere in the file (today only the matrix has one) and reads the quoted versions. Quoting is
required because, unquoted, YAML reads 3.10 as the number 3.1. Zero matches, more than one, or an entry
that isn't a quoted `3.N` is an error naming `ci.yml` and the expected shape. The check doesn't fall back to "no
versions".

*Alternative:* add PyYAML as a dev dependency. Rejected for one line of a file we control, and because the check
stays standard library only, like `release_config.py`. If the matrix ever moves to a block list, the check fails
and says so, and that's when to revisit.

### D4. `.python-version` holds the lowest supported minor, `3.12`

It holds the lowest supported version because that's the version most likely to reject newer syntax or library
calls, so plain `uv run` catches them locally. Holding a minor (`3.12`) rather than a patch (`3.12.14`) lets uv use
whichever 3.12 patch is installed. CI is unaffected: `setup-uv`'s `python-version` input sets `UV_PYTHON`, which
overrides `.python-version`. Task 1.4 confirms this in the 3.13 jobs' logs.

### D5. `scripts/on.py VERSION COMMAND...` selects a version, in an environment of its own

`on.py` has a PEP 723 header with no dependencies, so `uv run scripts/on.py` runs it in isolation, without syncing
the default `.venv`. It:

1. Validates `VERSION` as `3.N`. A malformed version is refused, showing the form.
2. Reads the supported versions through `python_versions` (D1). A version outside them is refused, listing the
   supported versions and the bound. It doesn't pass the version on to uv to refuse.
3. Runs `uv run --python VERSION COMMAND...` with `UV_PROJECT_ENVIRONMENT=<repo>/.venvs/VERSION`, from the
   repository root, passes its exit code through, and forwards the command's arguments unchanged.

`.venvs/` is added to `.gitignore`. `.venvs/` and the tool caches also need to stay out of ruff's and pytest's
discovery. Task 3.2 checks this.

*Alternatives:*

- Plain `uv run --python 3.13`. It uses one `.venv` for every version, so every switch rebuilds it, and two
  terminals on different versions overwrite each other's environment.
- Telling people to set `UV_PYTHON` and `UV_PROJECT_ENVIRONMENT` themselves. That's two variables to keep in step
  by hand: the "messing around" the owner asked to avoid.
- Editing `.python-version`. It's tracked, so every switch dirties the tree, and it's one version per checkout.

The name `on.py` reads as "run on 3.13". It's cheap to rename before merge.

### D6. The check is `scripts/python_versions.py`, run as a test

It follows `release_config.py`: a `problems(root) -> list[str]` function, tested by breaking each property in a copy
of the real files and asserting on the exact message, plus a test that the real repository has no problems. It also
exposes `supported(root)` for `on.py`, so the bound is parsed in one place.

## Risks / Trade-offs

- **A published upper bound can't be taken back.** After a release, resolvers refuse new Pythons for that release,
  or fall back to an older release without the cap. troupe hasn't published a release, so the cap costs nothing now.
  From the first release on, each newly supported version ships with a raised cap, and D1's check makes the CI
  matrix and the cap move together.
- **Developers on 3.14 or later find their `.venv` replaced** by a 3.12 one on the next `uv run`. That's the
  intended refusal, and uv installs 3.12 if it's missing. → The README says so.
- **`.venvs/` grows** with one environment per version tried. → It's ignored and safe to delete, and the README
  says so.
- **D3's line match is strict on purpose.** A cosmetic reformat of `ci.yml` fails the check. → The message names
  the shape it expects.
- **Testing 3.14 before Part 2 isn't possible.** `on.py` refuses it, because uv would refuse it anyway. On
  2026-10-15 the owner decided that 3.14 and 3.15 come with Part 2's own change, and that `on.py` has no opt-in for
  unsupported versions. Once Part 2 widens the bound, `on.py 3.14` works with no change to `on.py`.

## Migration Plan

Merge, then run `uv sync` once. Nothing to roll back beyond reverting the commit: no data or release changes.
