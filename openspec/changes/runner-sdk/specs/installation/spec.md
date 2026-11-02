# Spec Delta

## MODIFIED Requirements

### Requirement: Core declares no dependency only for distribution
The `troupe` package's dependencies SHALL NOT name any other workspace member except `troupe-plugin-sdk`, whose
runner contract types core uses. Only `troupe-run` brings the adapters and plugins into an install. A core dependency
on any other workspace member SHALL fail the repository's check, naming it.

#### Scenario: Core depends on an adapter
- **WHEN** `packages/troupe/pyproject.toml` lists `troupe-vcs-git` as a dependency
- **THEN** `scripts/check.py` fails, naming `troupe-vcs-git`, the file, and `troupe-run` as where it belongs

#### Scenario: Core depends on the plugin SDK
- **WHEN** `packages/troupe/pyproject.toml` lists `troupe-plugin-sdk`, bare
- **THEN** the bundle check passes

## ADDED Requirements

### Requirement: A pinned component's released workspace dependencies are pinned too
When the bundle pins a component that depends on another workspace member that has released, the bundle SHALL pin
that member too, so an install of the bundle's tag never looks it up on a package index. The check SHALL fail
otherwise, naming both and the file.

#### Scenario: Core pinned, the released SDK bare
- **WHEN** `troupe-run` pins `troupe`, core depends on the SDK, the manifest gives the SDK 0.1.0, and `troupe-run`
  names `troupe-plugin-sdk` bare
- **THEN** `scripts/check.py` fails, naming `troupe-plugin-sdk`, `troupe` and `packages/troupe-run/pyproject.toml`

#### Scenario: The SDK not yet released
- **WHEN** `troupe-run` pins `troupe` and names `troupe-plugin-sdk` bare, and the manifest gives the SDK 0.0.0
- **THEN** the check passes
