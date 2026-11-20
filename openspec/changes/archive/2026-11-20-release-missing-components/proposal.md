# Proposal

## Why

Merging release pull request #263 should have released 13 components. It released 11, and the run reported success
([run](https://github.com/troupe-run/troupe/actions/runs/44650471873)). release-please parses a merged pull request's
body, writes it back out and parses it again. The first parse decodes an escaped `&lt;NAME&gt;` from commit 782d068,
so the second sees an unclosed `<NAME>` element and loses the troupe-runner-ollama and protocol blocks. The manifest on
`main` moved them to 0.1.0 and 0.2.0, but their tags were never made. Nothing noticed until the next release pull
request (#482) bumped both again, and the pinning pull request (#483) pinned a tag that doesn't exist (#484).

A release that silently skips a component breaks the promise that merging the release pull request is the release.
The guard rule that stops such text reaching a commit is troupe-run/infrastructure#364. This change makes the release
workflow notice a missing release, whatever the cause, and says how to repair one.

## What Changes

- A new script, `scripts/release_tags.py`, compares `.release-please-manifest.json` with the repository's tags. Each
  component's version (except an unreleased `0.0.0`) needs a `<component>-v<version>` tag, the component named as
  `release-please-config.json` names it. The script lists every missing tag and the repair route, and exits 1.
- The release workflow runs it after release-please on every push to `main`, including when release-please failed.
  So a missing release turns the run red, naming the tag, on the push that should have made it.
- `contributing/releasing.md` gets a section on repairing a missing release. It covers editing the merged release
  pull request's body so release-please's two parses keep the missing blocks, relabelling it `autorelease: pending`
  and re-running the release run. As a fallback, it covers creating the release by hand with the changelog
  section's notes.

Out of scope, by the owner's decision of 2026-11-20: published notes that keep their non-ASCII text when a release
pull request's body overflows (release-please cut ⚠ to U+00A0, published as U+FFFD), and a test reproducing the 0.2.0
case from the saved notes. Both are #486.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `releases`: a new requirement that every version the manifest records has its release tag, checked after each
  release run.

## Impact

- `scripts/release_tags.py` (new, standard library only), its tests in `scripts/tests/`, and its entry in
  `scripts/check-paths.toml`.
- `.github/workflows/release.yml`: a new job after `release-please`, with read-only permissions.
- `contributing/releasing.md`: the repair section.
- Until troupe-runner-ollama 0.1.0 and protocol 0.2.0 are released, the new job fails on every push to `main`.
  The repair (#263's retrigger) should run before this merges, so its merge run passes.
