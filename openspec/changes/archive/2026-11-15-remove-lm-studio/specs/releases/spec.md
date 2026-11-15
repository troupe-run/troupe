## MODIFIED Requirements

### Requirement: The bundle's extras follow its dependencies' rules
Every rule for `troupe-run`'s dependencies SHALL hold for each entry in its extras as well: the bare-or-pinned form,
pins no higher than the manifest, the pinning pull request moving pins that are behind, its commit type, and the hold
on releasing while a member is bare.

#### Scenario: A pin in an extra to another subdirectory
- **WHEN** the `example` extra pins `troupe-runner-example-v0.1.0` with `#subdirectory=plugins/runner-ollama`
- **THEN** `scripts/check.py` fails, naming `troupe-runner-example`, the extra, `packages/troupe-run/pyproject.toml`
  and the expected reference

#### Scenario: A runner in an extra released
- **WHEN** a release pull request that releases `troupe-runner-example` at 0.1.1 is merged
- **THEN** the pinning pull request moves its pin to `troupe-runner-example-v0.1.1` in the `example` extra and in
  `all`, and changes nothing else

#### Scenario: A bare member in an extra
- **WHEN** the manifest gives `packages/troupe-run` 0.1.0, every base dependency is pinned, the `example` extra names
  `troupe-runner-example` bare, and the bundle's release configuration doesn't exclude its commits
- **THEN** `scripts/check.py` fails, naming `troupe-runner-example`, `release-please-config.json` and the exclusion
  to add

#### Scenario: A component's first release before its pin
- **WHEN** a release pull request first releases `troupe-plugin-sdk`, the bundle pins `troupe` and names the SDK
  bare, and the bundle's release configuration excludes its commits
- **THEN** the bundle check passes on it, and the pinning pull request after its merge pins the SDK
