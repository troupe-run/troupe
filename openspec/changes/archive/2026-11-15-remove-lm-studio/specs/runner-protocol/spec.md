## MODIFIED Requirements

### Requirement: A runner may use a maintained client library for its engine
A runner MAY depend on a maintained client library for its engine, and SHOULD prefer one to rebuilding the engine's
protocol by hand. The library SHALL NOT decide anything this contract or the runner's own spec decides; the
requirements that follow name what the runner keeps. The plugin SDK's own dependencies are unchanged (spec:
plugin-sdk).

#### Scenario: A runner with a library
- **WHEN** a runner plugin depends on `troupe-plugin-sdk` and its engine's client library
- **THEN** it is installed through its own extra of `troupe-run` (spec: installation), and every requirement that
  follows applies to it

#### Scenario: A runner without one
- **WHEN** a runner plugin depends only on `troupe-plugin-sdk`
- **THEN** the requirements on a library don't apply to it, and it is in the base install

### Requirement: A runner's dependencies are pinned and licensed compatibly with Apache-2.0
Every package a runner plugin depends on, directly or not, other than troupe's own, SHALL be pinned in the lock file,
and its declared licence SHALL be on troupe's one list of licences, in its permissive or its weak-copyleft tier. A
package with no declared licence, or one on neither tier, SHALL fail the repository's check, naming the package, the
runner, the licence found and the list's file.

#### Scenario: A permissive licence
- **WHEN** a runner depends on a library declared MIT, which depends on one declared BSD-3-Clause
- **THEN** the licence check passes

#### Scenario: A licence not on the list
- **WHEN** a runner's dependency declares GPL-3.0-only
- **THEN** `scripts/check.py` fails, naming the package, the runner, `GPL-3.0-only` and the list's file

#### Scenario: No declared licence
- **WHEN** a runner's dependency declares no licence in its metadata
- **THEN** `scripts/check.py` fails, naming the package and the runner, and saying no licence was found

#### Scenario: Runners with no dependency beyond the SDK
- **WHEN** every runner plugin depends only on `troupe-plugin-sdk`
- **THEN** the licence check passes, having checked no package
