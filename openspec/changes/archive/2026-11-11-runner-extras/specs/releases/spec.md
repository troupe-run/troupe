## ADDED Requirements

### Requirement: The bundle's extras are pinned like its dependencies
Every rule for `troupe-run`'s dependencies SHALL hold for each entry in its extras as well: the bare-or-pinned form,
pins no higher than the manifest, the pinning pull request moving pins that are behind, its commit type, the hold on
releasing while a member is bare, and pinning a pinned component's released workspace dependencies.

#### Scenario: A pin in an extra to another subdirectory
- **WHEN** the `lm-studio` extra pins `troupe-runner-lm-studio-v0.1.0` with `#subdirectory=plugins/runner-ollama`
- **THEN** `scripts/check.py` fails, naming `troupe-runner-lm-studio`, the extra, `packages/troupe-run/pyproject.toml`
  and the expected reference

#### Scenario: A runner in an extra released
- **WHEN** a release pull request that releases `troupe-runner-lm-studio` at 0.1.1 is merged
- **THEN** the pinning pull request moves its pin to `troupe-runner-lm-studio-v0.1.1` in the `lm-studio` extra and in
  `all`, and changes nothing else

#### Scenario: A bare member in an extra
- **WHEN** the manifest gives `packages/troupe-run` 0.1.0, every base dependency is pinned, the `lm-studio` extra names
  `troupe-runner-lm-studio` bare, and the bundle's release configuration doesn't exclude its commits
- **THEN** `scripts/check.py` fails, naming `troupe-runner-lm-studio`, `release-please-config.json` and the exclusion
  to add

#### Scenario: An extra's runner pins the released SDK bare
- **WHEN** the `lm-studio` extra pins `troupe-runner-lm-studio`, the manifest gives the SDK 0.1.0, and `troupe-run`
  names `troupe-plugin-sdk` bare
- **THEN** `scripts/check.py` fails, naming `troupe-plugin-sdk`, `troupe-runner-lm-studio` and the file
