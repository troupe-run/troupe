## ADDED Requirements

### Requirement: A runner may use a maintained client library for its engine
A runner MAY depend on a maintained client library for its engine, and SHOULD prefer one to rebuilding the engine's
protocol by hand. The library SHALL NOT decide anything this contract or the runner's own spec decides; the
requirements that follow name what the runner keeps. The plugin SDK's own dependencies are unchanged (spec:
plugin-sdk).

#### Scenario: A runner with a library
- **WHEN** a runner plugin depends on `troupe-plugin-sdk` and `lmstudio`
- **THEN** it is installed through its own extra of `troupe-run` (spec: installation), and every requirement that
  follows applies to it

#### Scenario: A runner without one
- **WHEN** a runner plugin depends only on `troupe-plugin-sdk`
- **THEN** the requirements on a library don't apply to it, and it is in the base install

### Requirement: Retries follow troupe's named limits, not the library's
A runner that uses a client library SHALL turn off the library's own retries, and SHALL retry, back off and honour
`Retry-After` only in its own loop, within its named limits, reporting each retry as this contract requires. Any
timeout or other limit the library applies SHALL be set from one of the runner's named settings, never left to the
library's default.

#### Scenario: A server error retried
- **WHEN** the service answers every request with a 500, and the runner's retry limit is 2
- **THEN** the service receives exactly 3 requests, and the runner sends 2 `retry` events

#### Scenario: A library timeout
- **WHEN** the runner's request timeout setting is 30 seconds
- **THEN** the library is given 30 seconds, and the runner's schemas or docs name the setting and its default

### Requirement: A runner that uses a library follows no redirect and keeps the credential in its header
A runner that uses a client library SHALL NOT follow a redirect, SHALL send the credential only in the header the
service reads it from, and SHALL NOT write the credential to a log, an event, a transcript record or an error, however
the library reports what it did.

#### Scenario: A redirect
- **WHEN** the service answers a request with a 307 to another address
- **THEN** no request reaches the other address, and the run ends with an error naming the redirect

#### Scenario: A library error that quotes the request
- **WHEN** the library raises an error whose text holds the request's headers
- **THEN** no event, transcript record or log line the runner writes holds the credential

### Requirement: A runner that uses a library stops its request on cancel and end of input
On `run/cancel`, or when its standard input closes, a runner that uses a client library SHALL abandon the library's
request in flight and exit within troupe's cancel grace period, whatever the library's own timeouts are.

#### Scenario: Cancel during a held response
- **WHEN** the host cancels a run while the service holds a response open
- **THEN** the service sees its connection closed, and the runner exits within the grace period without a `result`

### Requirement: A library-backed runner's transcript holds what the library exposes
A runner that uses a client library SHALL send, as transcript records in order, each request and each response as the
library exposes them, serialised, rather than necessarily the bytes on the wire: when offered `transcript-kinds`, a
request with kind `sent` and a response with kind `received`. Its design SHALL say what that leaves out compared with
the wire (decision #319).

#### Scenario: A request and its response
- **WHEN** a run offered `transcript-kinds` makes one request through the library and gets one response
- **THEN** its transcript holds a `sent` record of the request as the runner passed it to the library, then a
  `received` record of the response as the library returned it, in order

### Requirement: A runner's dependencies are pinned and licensed compatibly with Apache-2.0
Every package a runner plugin depends on, directly or not, other than troupe's own, SHALL be pinned in the lock file,
and its declared licence SHALL be on troupe's one list of licences, in its permissive or its weak-copyleft tier. A
package with no declared licence, or one on neither tier, SHALL fail the repository's check, naming the package, the
runner, the licence found and the list's file.

#### Scenario: A permissive licence
- **WHEN** the lm-studio runner depends on `lmstudio`, declared MIT, and `msgspec`, declared BSD-3-Clause
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

### Requirement: A weak-copyleft dependency is used only unmodified, as its own package
A package whose licence is in the list's weak-copyleft tier (MPL-2.0) SHALL be installed from a package index as its
own distribution, never from a git, path or patched source, and no file in this repository SHALL carry that licence's
notice, so none of its files is vendored, copied or patched into troupe's source. Either SHALL fail the repository's
check, naming the package or the file.

#### Scenario: certifi, through an HTTP library
- **WHEN** a runner depends on `httpx`, which depends on `certifi`, declared MPL-2.0 and locked from PyPI
- **THEN** the licence check passes

#### Scenario: A weak-copyleft package from another source
- **WHEN** `certifi` is locked from a git source, or overridden in `[tool.uv.sources]`
- **THEN** `scripts/check.py` fails, naming `certifi`, its source and the weak-copyleft tier

#### Scenario: A copied file
- **WHEN** a tracked file under `packages/`, `plugins/` or `scripts/` carries the MPL-2.0 notice ("This Source Code
  Form is subject to the terms of the Mozilla Public License")
- **THEN** `scripts/check.py` fails, naming the file and saying weak-copyleft code is used only as an unmodified
  dependency
