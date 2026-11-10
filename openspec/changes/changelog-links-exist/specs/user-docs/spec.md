# Spec Delta

## MODIFIED Requirements

### Requirement: The changelog page shows the release-please changelogs
The changelog page SHALL show every part that `release-please-config.json` writes a changelog for, by linking its
changelog or naming the part, and SHALL NOT copy their entries. The docs check SHALL fail when the page links a
changelog that `release-please-config.json` doesn't write, or shows a part neither way.

#### Scenario: A release PR
- **WHEN** a release pull request updates `packages/troupe/CHANGELOG.md`
- **THEN** the changelog page needs no edit, and the docs check passes

#### Scenario: A misnamed changelog
- **WHEN** the changelog page names `packages/troupe/CHANGES.md`
- **THEN** the docs check fails, naming the page, the path and the changelogs release-please writes

#### Scenario: A part left off the page
- **WHEN** `release-please-config.json` writes a changelog for `troupe-runner-ollama`, and the changelog page neither
  links that changelog nor names the part
- **THEN** the docs check fails, naming the page and the part, and saying to link its changelog or, before its first
  release, name it

## ADDED Requirements

### Requirement: The changelog page links only changelogs that exist
The changelog page SHALL link a part's changelog only once the file exists in the repository. Until a part's first
release, the page SHALL name it, without a link, as a list item that starts with its component name in code. The
docs check SHALL fail when the page links a changelog that doesn't exist. It SHALL pass when the page names a part
whose changelog exists, so a first release pull request isn't blocked.

#### Scenario: A link to a changelog not written yet
- **WHEN** `plugins/runner-ollama/CHANGELOG.md` doesn't exist, and the changelog page links it
- **THEN** the docs check fails, naming the page and the path, and saying to name `troupe-runner-ollama` without a
  link until its first release

#### Scenario: A part not released yet
- **WHEN** `plugins/runner-ollama/CHANGELOG.md` doesn't exist, and the changelog page has the list item
  `` - `troupe-runner-ollama` ``
- **THEN** the docs check passes

#### Scenario: A first release
- **WHEN** a release pull request writes `plugins/runner-ollama/CHANGELOG.md` for the part's first release, and the
  changelog page still names `troupe-runner-ollama` without a link
- **THEN** the docs check passes, and the page links the changelog in a later pull request, once the release has
  merged
