# Design

## Context

See proposal.md, Why. What exists today:

- **`release-please-config.json`** lists `protocol` (release type `simple`, component `protocol`) as a component of
  the `troupe` linked-versions group, with every `packages/*` member. `.release-please-manifest.json` has every
  component at `0.0.0`: nothing has been released yet.
- **`scripts/release_config.py`** (run as a test inside `scripts/check.py`) *requires* the protocol to be in the
  linked group, and refuses `extra-files` on the protocol's entry because "it isn't a Python package". Both rules
  flip in this change. Its tests are in `scripts/tests/workspace/test_release_config.py`.
- **release-please v17.6.0's `simple` strategy** writes `CHANGELOG.md` and updates `version.txt` with
  `createIfMissing: false` (checked in its source for this design), so a component without a `version.txt` gets
  none. Its `json` extra-file updater replaces the semver found at a JSONPath, so the value must already be a version.
- **The troupe package's copy of the schemas** is `packages/troupe/src/troupe/protocol/`, written by
  `scripts/package_schemas.py`, which only reads, writes and deletes `*.schema.json`. `troupe.core.schemas` is the one
  place core finds a schema.
- **A segment header** is `{"format":1,"segment":{"session":…,"vcs":…,"branch":…}}`, written once per segment by
  `TextStore` (`Header` → `encode_header` in `troupe_store_text/codec.py`) and read strictly by `_header`, which
  accepts exactly `{session, vcs}` or `{session, vcs, branch}`. The store-text package already imports `troupe.core`.
- **The `$schema` URL** a config file names is the constant `ACTOR_SCHEMA_URL` in `core/config/kinds.py`, with the
  major `0` written into it.
- **`troupe --version`** prints `troupe <version>` from `importlib.metadata`.

## Goals / Non-Goals

**Goals:**
- One place records the protocol version troupe ships, written only by release-please, and checked against the
  manifest so it can't drift.
- Everything that reports or writes the protocol version reads it from that place.
- An installed wheel knows its protocol version with no checkout and no network.

**Non-Goals:**
- Comparing versions when reading: a segment from a newer or older protocol is read as now. Compatibility rules
  belong with the config-migration work #140 defers.
- A `version.txt` in `protocol/`. The manifest and the tags already say the protocol's version; a third copy would
  need its own check.
- Guarding which commit types may touch `protocol/schemas/` (see Risks).

## Decisions

### D1: `protocol` leaves the linked group and keeps its entry otherwise

Remove `"protocol"` from the `troupe` group's `components`. The entry keeps `release-type: simple` and
`component: protocol`, so tags stay `protocol-v<version>`, the changelog stays `protocol/CHANGELOG.md`, and the
global `bump-minor-pre-major` and `initial-version: 0.1.0` apply to it as before.

A schema change always touches the package's copy too (the check holds them equal), so a releasable schema commit
releases both the protocol and the linked group, each at its own next version. A change only to `protocol/README.md`
releases only the protocol.

*Alternative:* a separate release-please config or workflow for the protocol. Rejected: one release pull request
for the repository is simpler, and release-please already versions components independently outside a linked group.

### D2: The recorded version is `troupe/protocol/version.json`, updated by the protocol's `extra-files`

```json
{"version": "0.0.0"}
```

The protocol's release entry gains:

```json
"extra-files": [
  {"type": "json", "path": "/packages/troupe/src/troupe/protocol/version.json", "jsonpath": "$.version"}
]
```

so the release pull request that bumps the protocol rewrites the file in the same commit as the manifest. A leading
`/` is a repository-root path, as the packages' `uv.lock` updates already use. The file sits next to the copy it
describes and ships in the wheel as package data, as the schemas do. `package_schemas.py` doesn't touch it, because it
manages only `*.schema.json`; a test pins that, so a later widening of its pattern can't delete the file.

*Alternatives:*
- *A `version.txt` copied from `protocol/` by `package_schemas.py`.* release-please would update `protocol/version.txt`
  but not the copy, so the copy check would fail on every protocol release pull request. A plain text file can't take
  a JSONPath, and the `generic` updater needs an `x-release-please-version` marker in the file.
- *A Python constant with a `generic` marker comment.* Works, but a marker in a comment is easy to break silently;
  a JSONPath either matches or fails the release.
- *The troupe `pyproject.toml`.* Not readable from an installed wheel.

### D3: The release check enforces the new shape

`scripts/release_config.py`'s `_protocol_problems` and `_group_problems` change:

- `protocol` in the linked group's components is a problem: "protocol is in the 'troupe' linked group in
  release-please-config.json, but it's released on its own: remove it from 'components'." `expected` no longer adds
  `PROTOCOL`.
- The protocol's entry must have exactly the D2 extra-file; anything else in `extra-files` is a problem naming the
  expected entry.
- `version.json` must exist, hold a JSON object with only a `version` string, and equal `manifest["protocol"]`;
  otherwise a problem names both files, both versions and the fix ("let the release pull request set it; to correct
  it, set it to the manifest's version").

These run in the existing `test_every_workspace_member_is_configured_for_release`, so `scripts/check.py` fails on any
of them. Every rule gets a known-bad test in `test_release_config.py`, replacing the two tests that assert the old
rules (`test_the_protocol_left_out_of_the_linked_group_is_named`, `test_a_protocol_entry_with_a_lock_update_is_named`).

### D4: `troupe.core.schemas.protocol_version()` is the one reader

Next to `PROTOCOL` (the copy's directory), `protocol_version()` reads `PROTOCOL / "version.json"`, cached. It accepts
only `{"version": "<major>.<minor>.<patch>"}` with no leading zeros. Anything else, including a missing file, raises
`TroupeError("schemas.protocol-version-invalid", …)`, naming the file, what it holds and the fix (reinstall troupe; in
a checkout, restore the file from git). That new code goes in `protocol/schemas/error.schema.json`'s catalogue with a
`details` schema (`path`, and `found` when the file could be read), and in core's catalogue, as the catalogue rule
requires. `protocol_major()` returns the major as an `int`.

The version is a plain `str`; nothing compares versions yet, so no version type or dependency is added.

### D5: The segment header carries `protocol`, required, format still 1

`event-record.schema.json`'s header `segment` object gains a required `protocol`, typed by a new
`$defs/protocolVersion` (string, the D4 pattern), with a description. `Header` gains `protocol: str`; `TextStore`
fills it from `protocol_version()` when it writes a segment's header; `encode_header` writes it; `_header` requires it
(`{session, vcs, protocol}` or with `branch`) and refuses a value that doesn't match the pattern, as
`events.malformed-record`.

The record `format` stays 1. Pre-1.0 there are no theatres to keep readable (owner, 2026-10-23), and bumping the
format would make every existing segment `events.unknown-format` anyway, which is no kinder than malformed.

*Alternative:* optional, absent meaning "written before the protocol was recorded". Rejected by the owner.

### D6: `--version` prints `troupe <version> (protocol <version>)`

`cli/__init__.py` appends ` (protocol {protocol_version()})`. It still needs no theatre, identity or daemon: the
read is a package-data file. If the record is broken, `--version` renders the D4 error like any other and exits with
its code, rather than printing a guess. The docs' install page shows `uv run troupe --version` without its output, so
it needs no edit; the CLI reference page is checked for any shown output.

### D7: The `$schema` URL's major comes from `protocol_major()`

`ACTOR_SCHEMA_URL` becomes a function, `actor_schema_url()`, built as
`f"https://troupe.run/protocol/{protocol_major()}/config/actor.schema.json"`, used by `projection.py` where it writes
the comment and the `$schema` key. While the protocol is 0.x the bytes troupe writes are unchanged, so no file's hash
changes. At 1.0 the URL follows the release, as the site publishes it (troupe-run/website#30); what happens to
existing files then is the deferred `troupe config update` work.

The canonical `$id`s (`ACTOR_SCHEMA`, without a major) don't change: they identify the schema in the registry, not
where it's published.

## Risks / Trade-offs

- [A commit of a non-releasable type (`docs:`, `refactor:`, `test:`) that changes `protocol/schemas/` changes the
  copy without a protocol release, so a later troupe release would ship schemas that differ from the protocol
  version it records.] → `contributing/releasing.md` says that a change to a schema is `feat`, `fix` (or breaking),
  never another type. A guard rule needs infrastructure's hooks, so it's raised as a follow-up issue in
  troupe-run/infrastructure, not built here.
- [Between releases, a checkout records the last released protocol version while its schemas may be ahead of it.]
  → Accepted: only released wheels are claimed exact, as with troupe's own `0.0.1.dev0`. The proposal, the protocol
  README and `version.json`'s neighbouring docs say so.
- [Existing segments without `protocol` become unreadable (`events.malformed-record`).] → Owner's call, pre-1.0. The
  error already names the file and line; the PR notes it.
- [release-please's `json` updater fails if the file's value isn't a version.] → `version.json` starts at `0.0.0`, and
  D3's check keeps it a version equal to the manifest's.
- [The first release pull request after this change opens with the protocol released separately.] → Expected, and
  what #140 asks. Nothing has been released yet, so there is no history to reconcile.

## Migration Plan

No data migration. Land on `main`; the next release pull request computes the protocol's version independently. To
roll back, revert the commit: the protocol rejoins the group, and since nothing has been released, nothing else
changes. Any segments written meanwhile carry `protocol`, which the reverted reader would refuse; in a dev theatre,
delete them.
