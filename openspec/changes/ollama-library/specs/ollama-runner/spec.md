## MODIFIED Requirements

### Requirement: The Ollama runner is a self-contained plugin
The Ollama runner SHALL be an out-of-process plugin with its own package and tests. It SHALL speak only the runner
contract, using the plugin SDK's types for it, and SHALL import nothing of troupe's but the SDK. Besides the SDK, it
SHALL depend directly only on its HTTP libraries, `httpx2` and `httpcore2`, each pinned to one version. It SHALL be
installed as `troupe-run`'s `ollama` extra, not in the base install, and SHALL start no process.

#### Scenario: The plugin's imports
- **WHEN** code under `plugins/runner-ollama/` imports `troupe.core`
- **THEN** the import contract check fails

#### Scenario: The plugin's dependencies
- **WHEN** `plugins/runner-ollama/pyproject.toml` is read
- **THEN** its dependencies are `troupe-plugin-sdk`, and `httpx2` and `httpcore2` each pinned with `==`, and nothing
  else

#### Scenario: The plugin's extra
- **WHEN** `packages/troupe-run/pyproject.toml` is read
- **THEN** `troupe-runner-ollama` is in its `ollama` and `all` extras, and not in its base dependencies

## ADDED Requirements

### Requirement: The runner's HTTP client takes nothing from the environment
The runner's HTTP client SHALL reach only the run's runtime endpoint, with no proxy, and SHALL send no credential or
header it reads from the environment or from a file such as `.netrc`. It SHALL NOT follow a redirect, from the
preflight or from a chat request.

#### Scenario: Proxy and credential variables in the runner's environment
- **WHEN** the runner starts with `HTTP_PROXY`, `ALL_PROXY` and `NETRC` set, the last naming a file with a login for
  the endpoint's host, and runs against the runtime's endpoint
- **THEN** every request reaches the runtime's endpoint directly, and none carries an `Authorization` header

#### Scenario: A redirected chat request
- **WHEN** Ollama answers a chat request with a 307 to another address
- **THEN** no request reaches the other address, and the run ends with an `error` result naming the status, unretried

#### Scenario: A redirected preflight
- **WHEN** Ollama answers the preflight's version request with a 307 to another address
- **THEN** no request reaches the other address, and `run/start` is refused with `ollama.unreachable`
