# Proposal

## Why

The protocol evolves separately from troupe's packages and from the docs, so it should be released on its own
(owner, 2026-10-21, on #60). Today `protocol` is in the `troupe` linked-versions group, so its version is just the
release it shipped in, and it releases whenever any core package does. Since #60 the troupe package carries a
generated copy of `protocol/schemas/`, but nothing in the package says which protocol release that copy is, so an
installed troupe, a file it writes, and a person reading either can't tell. troupe-run/troupe#140 asks for both
halves; troupe-run/website#30 publishes each `protocol-v*` tag under `troupe.run/protocol/<version>/`.

## What Changes

- **The protocol has its own version.** `protocol` leaves the `troupe` linked group in `release-please-config.json`.
  It releases, tagged `protocol-v<version>`, only when a releasable commit changes `protocol/`. It keeps release
  type `simple`, its own `protocol/CHANGELOG.md` and the pre-1.0 rules (first release 0.1.0, breaking bumps minor).
- **The troupe package records the protocol version it ships**, in `troupe/protocol/version.json` next to its copy
  of the schemas. The protocol's release-please entry updates that file in the release pull request (an
  `extra-files` JSON update), so the version moves with the protocol's manifest entry and never by hand.
- **The release check holds it all in place.** `scripts/release_config.py` now fails when `protocol` is in the
  linked group, when its entry doesn't update `version.json`, or when `version.json` disagrees with the manifest's
  `protocol` version, naming the file and the fix. It replaces today's rules that require the opposite.
- **Core reads the version in one place.** `troupe.core.schemas` gains `protocol_version()`, read from the
  package's `version.json`. A malformed or missing file is an error naming the file, never a default.
- **Event segments say which protocol wrote them.** Each segment header gains a required `protocol` field: the
  protocol version of the troupe that wrote the segment. A header without one is a malformed record. **BREAKING**
  for segments written before this change: pre-1.0, and there are no theatres to migrate (owner, 2026-10-23: "not
  optional, since we're pre 1.0"). The record `format` stays 1.
- **`troupe --version` prints both versions**, for example `troupe 0.4.0 (protocol 0.2.1)`.
- **The major in a config file's `$schema` URL comes from the recorded version**, instead of a second hard-coded
  `0`. Nothing changes while the protocol is 0.x.
- **Docs follow:** `contributing/releasing.md`, the changelog page (`docs/backstage/changelog.md`) and
  `protocol/README.md` describe the protocol's own releases, tags and site paths.

Out of scope: the site's side (troupe-run/website#30); fetching schemas at runtime (the package carries them);
migrating config across a breaking protocol change (#140, "Later"); acting on the header's version when reading,
such as refusing a segment from a newer protocol.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `releases`: the protocol leaves the linked group and has its own version; a protocol release updates the version
  the troupe package records; the release check enforces both.
- `protocol`: the troupe package records which protocol version its copy of the schemas is, and core reads it from
  there.
- `event-store`: a segment header names the protocol version that wrote it, and a header without one is malformed.
- `cli`: `troupe --version` prints the protocol version alongside troupe's.
- `config-files`: the major-version path a config file names comes from the protocol version troupe carries.

## Impact

- `release-please-config.json` (linked group, protocol's `extra-files`); `.release-please-manifest.json` unchanged.
- `scripts/release_config.py` and `scripts/tests/workspace/test_release_config.py`.
- `packages/troupe/src/troupe/protocol/version.json` (new, `{"version": "0.0.0"}` until the first protocol release);
  `scripts/package_schemas.py` leaves it alone, since it only manages `*.schema.json`.
- `packages/troupe/src/troupe/core/schemas.py` (`protocol_version()`), `core/config/kinds.py` and `cli/values.py`
  (the `$schema` URL), `cli/__init__.py` (`--version`).
- `protocol/schemas/event-record.schema.json` (header gains `protocol`) and its package copy;
  `packages/troupe-store-text/src/troupe_store_text/codec.py` and `store.py` (write and read the field); test
  fixtures that hand-write segment headers.
- Docs: `contributing/releasing.md`, `docs/backstage/changelog.md`, `protocol/README.md`, `contributing/event-store.md`
  if it shows a header.
- No new dependency.
