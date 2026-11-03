# Spec Delta

## ADDED Requirements

### Requirement: The SDK reads the declaration from run start
The SDK SHALL turn a `run/start`'s `effects`, `workspace` and `scratch` into one immutable declaration a runner can
apply, refusing a malformed pattern with a protocol error naming the effect and the pattern. Its patterns SHALL be
the ones the contract's schema accepts, no more and no fewer.

#### Scenario: A run start with write declared
- **WHEN** a runner reads a `run/start` whose `effects.write` is `["out/**"]`
- **THEN** the declaration allows writing `out/a.txt`, not `src/a.txt`, and allows no delete or move

#### Scenario: A malformed pattern in run start
- **WHEN** a runner reads a `run/start` whose `effects.delete` holds `../x`
- **THEN** reading it raises a protocol error naming `delete` and `../x`

### Requirement: Runners plug in their own way of applying the declaration
The SDK SHALL define a framework-free interface for translating a declaration into a runner's own form, and SHALL
give every implementation the same normalised view of it: each effect's patterns as absolute patterns with `/`
between their parts, rooted at the workspace, and the scratch directory, in the same form on every platform. Each
implementation SHALL say which `init` value it reports. The SDK's own tools SHALL be the `checked` implementation.

#### Scenario: A pattern on Windows
- **WHEN** the workspace is `C:\work\theatre` and `write` declares `out/**`
- **THEN** the normalised pattern is `/c/work/theatre/out/**`

#### Scenario: Two runners, one declaration
- **WHEN** the SDK's tools and a runner's own translation are given the same declaration
- **THEN** both see the same normalised patterns and the same scratch directory
