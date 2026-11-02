# Spec Delta

## ADDED Requirements

### Requirement: Dependabot proposes no version for a workspace member
A workspace member's version moves only through its own release, so Dependabot SHALL ignore every workspace member in
troupe's `uv` update entry, whatever a package index holds under its name. Each member's name SHALL be matched by an
ignore in that entry of the delivered `.github/dependabot.yml` that covers every version, and the repository's check
SHALL fail when one isn't.

#### Scenario: Dependabot's scheduled run
- **WHEN** Dependabot's `uv` job runs in troupe and PyPI has a release named `troupe`, or named like another member
- **THEN** the job proposes no update to a workspace member and fails for none

#### Scenario: Every member is covered
- **WHEN** `scripts/check.py` runs on the repository as it is
- **THEN** the check passes, every member's name matched by an ignore in the `uv` entry

#### Scenario: A member named outside the ignores
- **WHEN** a workspace member's name is matched by no ignore in the `uv` entry
- **THEN** `scripts/check.py` fails, naming the member, `.github/dependabot.yml`, and that the ignore is added in
  troupe-run/infrastructure's Dependabot policy

#### Scenario: An ignore that covers only some versions
- **WHEN** the only ignore matching a member's name also limits the versions or update types it ignores
- **THEN** `scripts/check.py` fails for that member, as if nothing matched it

#### Scenario: Names are compared as packaging compares them
- **WHEN** an ignore's name differs from a member's only in case, or in `-`, `_` and `.`
- **THEN** it matches that member, and a `*` in it matches any run of characters

#### Scenario: No uv entry to read
- **WHEN** `.github/dependabot.yml` is missing, can't be parsed, or has no `uv` entry for `/`
- **THEN** `scripts/check.py` fails, naming the file and what it lacks, and doesn't pass for want of anything to check
