# Design

## Context

See proposal.md for why. The repo holds only OpenSpec, the issue and PR templates, and the licence. The structure
below was agreed in the exploration of 2026-10-11 and is recorded here because this change is the first to build on
it:

- **One repo until 1.0.** Plugins live in it as self-contained directories, so each can later move to its own repo
  with its history (`git filter-repo`).
- **Third-party code only ever runs out of process.** Out-of-process plugins (runners, stages, guests, notification
  channels) speak JSON-RPC over stdio. First-party adapters that sit deep in the house (storage, VCS, built-in
  identity sources) run in process, but each is still its own package, so `packages/troupe` stays slim and every
  port is proven by a separately packaged implementation.
- **`protocol/` is language-neutral** (JSON Schema). Python types are generated from it once there is enough schema
  to justify a generator (Decision #7); until then, hand-written types are checked against the schema by tests.

The relevant decisions are #7 (schema source of truth), #16 (scripted runner first, in the walking skeleton) and
#17 (CI on three platforms).

**Windows is supported from day one (owner, 2026-10-11).** This revises #17 and the "Windows out of scope short
term" line in the project context. The reasoning: retrofitting means rediscovering, late, every mechanism that was
chosen for POSIX and has no Windows equivalent (this change already had one: `flock` on a directory). The owner has
Windows machines to test on, and works through a separate session there when needed.

## Goals / Non-Goals

**Goals:**
- Every gate runs with one command, identically locally and in CI.
- Package boundaries are enforced by tooling, not by convention.
- The `cli` and `platform` specs are fully met on Linux, macOS and Windows. All three are required checks: a
  failure on any of them blocks a merge.
- Each mechanism is chosen because it works on all three platforms, not adapted later. Where the platforms really
  differ, the difference lives inside `platform`, and the rest of the code sees one behaviour.

**Non-Goals:**
- Any event store, daemon, runner, stage or config behaviour.
- Release packaging (PyPI, brew). That comes with the first installable release.

## Decisions

### D1. Layout and distributions

```
pyproject.toml            workspace root (not a package): members, dev tools, tool config
packages/troupe/          distribution `troupe`; src layout; console script `troupe`
  src/troupe/cli/         thin client: parsing, rendering, exit codes
  src/troupe/core/        commands, queries, errors, defaults
  src/troupe/platform/    the OS seam
plugins/README.md         the out-of-process rule; first plugin arrives with the walking skeleton
protocol/schemas/         JSON Schema; error.schema.json in this change
scripts/check.py          runs every gate (ruff, ruff format --check, mypy, lint-imports, pytest)
```

The core, house and CLI start as modules of one distribution. Splitting them into separate distributions is cheap
later, because the import contracts (D7) already keep them apart.

Alternative considered: separate distributions for core and CLI now. Rejected because it adds ceremony before
anything needs it.

### D2. CLI parser: standard-library argparse

The CLI is a thin client and should start fast. This was a measured concern in the prior art, which kept its CLI
standard-library-only. argparse can take global flags anywhere: a parent parser of global options is attached to
both the root parser and every subparser, and defaults are suppressed so a later occurrence doesn't overwrite an
earlier one. "Did you mean" hints come from `difflib`, matched against the defined subcommands and flags.

Alternatives considered:
- click or typer: options on a group must come before the subcommand, which breaks "global flags anywhere"
  without workarounds, and they add a runtime dependency.
- Python 3.14's `suggest_on_error`: it doesn't exist on 3.12.

Testing "flags anywhere" needs a subcommand, and this change defines none. The tests register a test-only
subcommand to exercise the rule. Real subcommands inherit it through the shared parent parser.

### D3. Error shape

`protocol/schemas/error.schema.json` defines:

| Field | Type | Notes |
|---|---|---|
| `code` | string | Stable, dotted id such as `usage.unknown-command`. Lets each surface phrase the error its own way. |
| `problem` | string | |
| `fix` | string | |
| `path` | string, optional | |
| `details` | object, optional | |

`code` isn't in the decided list (problem, path, fix). It's added because a surface can't rephrase an error it can't
identify. A Python error type mirrors the schema, and a test serialises every error the CLI can produce and
validates it against the schema (`jsonschema` is a dev dependency only).

### D4. Exit codes

One `IntEnum` in `troupe.core` holds the codes:
- `0` OK;
- `1` unexpected internal error;
- `2` usage error.

Later changes add codes to that table only. `docs/cli/exit-codes.md` is checked against the enum by a test, so the
documentation can't drift.

### D5. Atomic replacement

Write bytes to a temporary file in the target's directory, then:
1. flush and `fsync` it;
2. copy the original's permission bits;
3. `os.replace` it over the target;
4. `fsync` the directory on POSIX.

Any exception removes the temporary file and leaves the original untouched. Working in bytes means line endings,
BOM and encoding are never touched.

Platform differences, all inside `platform`:
- **Directory fsync** is skipped on Windows, where a directory can't be opened for fsync. On NTFS, the rename is
  journalled.
- **A target that another process has open** (an editor, or a reader in troupe itself) makes `os.replace` fail on
  Windows with a sharing violation. The replace retries with backoff, reports through the same announce callback
  as locks once `replace_announce_after` has passed, and fails with `replace.in-use` after `replace_timeout`. That
  error names the path and says to close whatever holds it. POSIX never takes this path. The test forces it on
  Windows by holding the file open from a second process.
- troupe's own reads open files briefly and close them, so they don't block a concurrent replace for long.

### D5a. Friendly paths

The home directory is abbreviated to `~` followed by the platform's own separator: `~/Projects/theatre` on POSIX,
`~\Projects\theatre` on Windows. Comparisons are case-insensitive where the file system is (Windows, and macOS by
default), so `C:\users\Martin\x` still displays as `~\x`.

### D6. Locks

- **One mechanism on every platform:** an OS-level exclusive lock on a **lock file** inside the directory being
  protected (for example `.troupe/.lock`). POSIX uses `fcntl.flock`; Windows uses `msvcrt.locking` on the file's
  first byte.
  - The OS releases the lock when the holder exits or crashes, so there's never a stale lock to clean up. The file
    only marks the place.
  - The file is empty and permanent. It's created once if missing and never deleted, because deleting it while
    another process waits races with that process.
  - It's listed in troupe's own `.gitignore` entries for `.troupe/` (added when `.troupe/` first exists, in a later
    change).
  - The owner accepted the empty file (2026-10-11), in place of the earlier preference for a lock that leaves no
    file.
- **Waiting:** the waiter polls with a non-blocking attempt, reports through a callback (which the CLI renders on
  standard error) once `lock_announce_after` has passed, and fails with `lock.timeout` after `lock_timeout`.
- **Nested acquisition:** a per-process registry of held locks, keyed by device and inode, makes a second attempt
  fail immediately with `lock.already-held`.
- **Defaults:** both durations live in `troupe.core.defaults`, the single named place for defaults until the
  `settings` capability exists. Callers can override them. Proposed defaults: announce after 1 s, give up after 30 s.

Alternatives considered:
- `flock` on the directory itself, which leaves no file. It has no Windows equivalent, so it was rejected under
  the day-one Windows goal.
- An `O_EXCL` lock file whose existence is the lock. It leaves state behind after a crash and needs stale-lock
  detection. Rejected.
- A Windows named mutex. It works, but it's a second mechanism with different semantics from POSIX. Rejected in
  favour of one mechanism.
- The `portalocker` library. It wraps the same calls, but adds a runtime dependency for about 30 lines of code.
  Rejected for now.

### D7. Import contracts (import-linter)

1. **Layers in `troupe`:** `cli` → `core` → `platform`. `platform` imports nothing else from troupe.
2. **Only `platform` imports OS-specific modules** (`fcntl`, `msvcrt`, `signal`, `termios`). Enforced as a
   forbidden contract on every other module.
3. **Plugins:** packages under `plugins/` may not import `troupe`. The contract is added with the first plugin; until
   then `plugins/README.md` states the rule.

To check that the contracts actually work, a deliberate violation is introduced once and shown to fail. Its output
is recorded in the PR.

### D8. Tooling

- **ruff:** lint, with a broad rule set (`E`, `W`, `F`, `I`, `UP`, `B`, `SIM`, `RUF`, `PT`, `N`, `ANN`, `S`), plus
  `ruff format`. Line length 100.
- **mypy:** `--strict` over `packages/*/src` and the tests.
- **pytest with hypothesis:** property tests for path display and atomic replacement.
- **Python versions:** 3.12 (the minimum) and 3.13.
- **One command:** `scripts/check.py` runs every gate. CI calls the same script, so local and CI can't diverge.

### D9. CI and branch protection

GitHub Actions runs a matrix of {ubuntu, macos, windows} × {3.12, 3.13}, each calling `scripts/check.py`. All jobs are
required, and none uses `continue-on-error`. Per-job durations are recorded on #17.

`scripts/check.py` is written in Python and run with `uv run`, not shell, so the same script runs on every
platform.

**Branch protection is not part of this change (owner, 2026-10-11).** It becomes a ruleset in a separate
organisation-as-code repo (OpenTofu, encrypted state, its own Feature issue), written once the CI job names from
this change exist. Until then `main` is unprotected, and changes still go through PRs by convention.

### D10. Contributions: DCO, not a CLA (owner, 2026-10-11)

Contributions are accepted under Apache-2.0 with a Developer Certificate of Origin sign-off on each commit
(`git commit -s`). They're checked by the [DCO GitHub App](https://github.com/dcoapp/app), which is actively
maintained, GitHub-native, and needs no signature store.

Why not a CLA:
- What a CLA adds over Apache-2.0 is mainly the right to relicense the core under more restrictive terms, or to
  dual-license a copyleft core.
- troupe's commercial plans (hosting, plus separate proprietary modules) don't need it. Apache-2.0 already allows
  closed, commercial and hosted use of contributed code.
- A CLA adds friction for contributors and reads as keeping a "rug-pull" option open.

The CLA tooling we looked at was also unmaintained or heavyweight:
- `contributor-assistant/github-action`: archived in March 2026;
- `roblox/cla-signature-bot` and `finos/cla-bot`: archived;
- EasyCLA: built for Linux Foundation projects.

The site's Licensing and Contributing pages are updated to match (troupe-run/troupe-run.github.io#1).

**Org members are exempt (owner, 2026-10-11).** `dco.yml` sets `require: members: false`. It lives in the org-wide
`troupe-run/.github` repo, which the app falls back to when a repository has no `dco.yml` of its own, so it is defined
once for every repo the app is installed on. The app then skips
the check for commits that are both authored **and cryptographically signed** by a `troupe-run` member. Members'
work belongs to HPS.GD, so a DCO adds nothing there; the check exists for outside contributions.

The owner's commits are already GPG-signed and show as verified on GitHub. The owner's org membership is private,
so the app's ability to see it is verified in task 7.2, not assumed.

The config landed on the default branch ahead of this change, first in this repo and then moved to
`troupe-run/.github`. The app reads it from the default branch, so it had to be in place before the app was
installed and the first PR checked.

## Risks / Trade-offs

- [Windows-only failures are slower to debug, because Windows isn't the owner's main machine] → All OS-specific code
  sits in one seam with its own tests, so a Windows failure points at `platform`. Reproducing it means a session on
  one of the owner's Windows machines.
- [Windows runners make CI slower] → It's free for public repos. Durations are recorded on #17, and the matrix can
  drop to one Python version on Windows if wall time becomes a problem. That would be a recorded decision.
- [argparse edge cases with flags anywhere, such as a global flag that takes a value] → One test per global-flag
  shape. There's only `--version` today, and each new global flag adds its own test.
- [`flock` on network file systems is unreliable] → Out of scope. Known as a theatre-on-NFS limitation, and noted in
  the platform docs.
- [The plugin import contract has nothing to enforce yet] → Stated in `plugins/README.md`, and added with the first
  plugin in the walking skeleton.

## Migration Plan

None. This is the first code.
