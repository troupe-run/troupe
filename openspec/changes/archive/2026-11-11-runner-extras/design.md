# Design: runner-extras

## Context

See proposal.md, "Why". The current state that shapes the approach:

- `packages/troupe-run/pyproject.toml` lists every workspace member in `dependencies`, bare or pinned at
  `<component>-v<version>`. Five scripts read that list, each with its own `project.get("dependencies", [])`:
  `scripts/bundle.py` (membership, core's dependencies, released workspace dependencies), `scripts/pin_bundle.py` (the
  pinning pull request), `scripts/release_config.py` (the bare-member release hold, twice) and
  `scripts/install_check.py` (every component pinned at a tag).
- Core turns a runner name into a command only through `troupe.core.interim.RUNNERS`. Each `Runner` entry has its
  command, package, environment and runtime. `interim.runner()` refuses an unknown name with `runner.unknown`. A
  known runner whose package is missing fails later, and differently in each place: `schemas.plugin-missing` when its
  options schema is read (config, init), or `could-not-start` when `python -m <package>` can't import it (perform).
  `schemas.plugin-missing`'s fix says the install "brings every runner troupe knows".
- Config checks the whole config on every change and every merge (`kinds.check`, which runs `actor_problems` for
  every actor, including its options against its runner's schema). Perform runs `kinds.check_actor` for the performed
  actor and then `interim.runner_command`.
- `troupe init --audition --runner <name> --rehearse` already checks that the runner is known, builds its example
  actor and checks it against the runner's options schema, all without writing anything.
- No shipped runner depends on anything but the SDK. #291 (LM Studio, `lmstudio`, which pulls in the compiled
  `msgspec`), #331 (`openai`, which pulls in `jiter` and pydantic) and #332 (`ollama`, which pulls in pydantic) are
  the first that will.
- The CLI's text output of a refusal prints its problem, path and fix, not its code.

## Goals / Non-Goals

**Goals:**

- The extras mechanism works end to end with no runner in an extra yet. Its checks are tested with fixture
  manifests and a fixture runner entry, so #291 only has to add its extra, its table entry and its page row.
- One reading of "the bundle's requirements" that every script shares, so the extras can't be checked by some rules
  and missed by others.
- One refusal, `runner.not-installed`, wherever a known runner's package is missing.

**Non-Goals:**

- No runner moves into an extra. That's #291, #331 and #332.
- No per-extra CI legs (see D9).
- No change to the plugin SDK's dependencies, or to the runner contract's wire format. The transcript record kinds
  are #294's (transcript-record-kinds, archived on main): a library-backed runner labels a request `sent` and a
  response `received`, holding what the library exposes rather than wire bytes, as decision #319 accepts.

## Decisions

### D1. An extra is named after its runner, not its library

The owner settled this on 2026-11-07 ("just be consistent", recorded on #333:
https://github.com/troupe-run/troupe/issues/333#issuecomment-6707600948). Each extra is named exactly after its
runner, giving `troupe-run[lm-studio]`, `[openai]`, `[ollama]`, plus `[all]`. That's the name an actor's `runner`
gives and `troupe init --audition --runner` takes, so a refusal can name the extra without a lookup table. #291's
change (`lmstudio-runner`) already writes `lm-studio`.

- *Alternative: the library's name* (`[lmstudio]`). Rejected. Two runners can share a library (an OpenRouter runner
  on `openai`), a runner can change library without its users changing their install, and a person who reads
  `runner: lm-studio` in config shouldn't have to know which package backs it.

### D2. Base or extra follows from the plugin's own dependencies

A plugin whose `[project] dependencies` is exactly `troupe-plugin-sdk` is a base dependency of `troupe-run`. Any
other plugin is in its runner's extra and in `all`, and isn't a base dependency. `scripts/bundle.py` enforces both
directions. This is the decision's rejection of "a judgement call each time" turned into a check. It also means
#331 and #332, by adding their library, are made by the check to move their runner into an extra in the same pull
request.

### D3. One reader of the bundle's requirements

A function in `scripts/release_config.py` (which `bundle.py`, `pin_bundle.py` and `install_check.py` already import)
yields every requirement string in `troupe-run`'s `dependencies` and in each `[project.optional-dependencies]` extra,
with where it came from (`dependencies` or `extra <name>`), so messages can name the extra. The five reads in
Context switch to it. `pin_bundle.py` rewrites pins by their reference text, and the same pin text appears in an
extra and in `all`, so both move together. Its test pins that.

- *Alternative: a separate set of checks for extras.* Rejected. The releases rules would then have two
  implementations that could drift, which is what the releases delta's single requirement exists to prevent.

### D4. `all` lists each runner again, rather than referring to the other extras

`all = ["troupe-runner-lm-studio @ git+…", …]`, each entry identical to its own extra's. The check enforces that
`all` is exactly the union of the other extras and that the entries are identical (installation, "The all extra
installs every runner").

- *Alternative: a self-referencing extra* (`all = ["troupe-run[lm-studio,openai]"]`). Rejected. A tag installed with
  `--no-sources` from a git URL would have to resolve `troupe-run` itself, and an index lookup for it is exactly what
  `--no-sources` installs must never do. It's also a second, different shape for the pin checks to understand.
- Today `all = []`. Task 1.1 confirms uv installs an empty extra, and the extras form with `--no-sources` and a git
  URL, before anything depends on them.

### D5. Core's runner table says whether each runner is in an extra, and the check keeps it in step

`Runner` gains `in_extra: bool`. The extra's name is always the runner's name (D1), so no name is stored, as the
owner's comment asks. The refusal names `troupe-run[<runner>]` when `in_extra` is true, and the reinstall fix
otherwise.
`scripts/bundle.py` fails when the table and `troupe-run`'s extras disagree in either direction (runs delta, "The
table and the bundle agree"). It finds the table without importing core, by reading the module's source, as it
already reads the manifests.

- *Alternative: core reads `troupe-run`'s installed metadata (`Provides-Extra`) at runtime.* Rejected. troupe runs
  without `troupe-run` installed (a checkout of core alone, the tests), the installation spec forbids core depending on
  the bundle, and metadata lookups would add an import-time cost and a failure mode to every refusal.
- *Alternative: store the extra's name* (`extra: str | None`). Rejected. It would only repeat the runner's name, and
  the owner's rule is that there's no table from runner to extra.

### D6. "Installed" means the package can be found, without importing it

`importlib.util.find_spec(runner.package) is not None`, as `schemas.plugin_schemas_directory` already does. A new
`interim.installed_runner(name)` returns the entry or raises `runner.not-installed`. `runner_command`,
`options_schema`, `options_validator` and `audition()` call it. `interim.runner()` stays the name-only lookup (the
environment and runtime facts don't need the package).

`runner.not-installed` is a new catalogued code. Its details are closed: `runner`, `package` and, for a runner in an extra, `extra`;
absent for a base runner, since shipped schemas allow no `null`. From config, its details also carry the actor's runner path as a list, as `config.invalid`'s do, and its
problem starts with it; the error's own `path` stays a file's, as the error schema says (review of #338). Its fix is: for an extra, "install `troupe-run[<extra>]` with the command
at <install page>, in place of the command you installed troupe with"; for a base runner, the current
`schemas.plugin-missing` fix with "which brings every runner troupe knows" removed. `schemas.plugin-missing` stays for
a plugin installed without its `schemas/` directory, with the same wording fix. Adding the code is a protocol change
(`feat(protocol)`), released as the protocol's next minor version by the existing release rules.

### D7. Config refuses only changes that touch the actor, and skips the options check otherwise

`actor_problems` gets the set of actors the change touches. For an actor on a known runner that isn't installed:
if the change touches it and leaves it on that runner, the check raises `runner.not-installed`, with the actor's
path. If the change removes the actor whole, or moves it to another runner, the actor is checked as usual
(against the new runner, or not at all). Otherwise, for whole-config checks of other changes and merges, its actor
schema and effects are checked and its options are skipped. Perform's `check_actor` treats the performed actor as
touched, so run start raises `runner.not-installed` before `runner_command` and before anything is recorded.
Rehearsing follows the same path.

- *Alternative: refuse whenever any actor's runner isn't installed.* Rejected. One teammate's `lm-studio` actor,
  committed to the theatre, would block every config command, and every merge, for everyone without that extra,
  including changes to their own actors. Skipping only the check that can't run, and refusing any use of that actor,
  loses no data and guesses nothing.
- *Alternative: a merge on a machine without the runner is a conflict.* Rejected for the same reason. The options are
  checked the next time the actor is set or performed where its runner is installed. This is the one place a check is
  deferred rather than run. The config delta states it, so it isn't silent in the spec.

### D8. Init refuses an uninstalled runner up front, and names an installed runner's extra

`audition()` calls `installed_runner`, so `troupe init --audition --runner <name>` (rehearsed or not) is refused
before anything is made, as `runner.unknown` already is. For an installed runner with an extra, `cli/init.py`'s
`_step_notes` adds one note to the perform step: the runner comes with `troupe-run[<extra>]`, and whoever runs this
theatre elsewhere installs that (the install page's address). Core puts the extra in the perform step's data (an
optional `extra`, from the table's `in_extra`), and the CLI only phrases it, since the CLI is a thin client and the run
server will want the same fact. There's no runner-specific branch.

### D9. The install check installs the base and then `[all]`, in the same leg

After the base install, its `--version` check and the scripted performance, `scripts/install_check.py` (a) rehearses
an audition, in a scratch repository with a local identity, for each runner the table puts in an extra, and
expects a refusal whose fix names `troupe-run[<extra>]` (the text output carries no code, see Context). Then it (b)
installs the extras form with `all` into a second tool directory and rehearses an audition on every runner in the
table, each of which must exit with the "would change" code. The extras and the table are read from the commit under
test (`git show <sha>:…`), as `bundle_pyproject` already reads the bundle. `--hosted` does the same against the tag,
so the release install check covers a published tag's extras unchanged.

This answers the #291 session's point about compiled dependencies (`msgspec`, `jiter`, pydantic-core). Every
runner's dependencies are installed on Linux, macOS and Windows, on every supported Python, in one resolution. If
`all` resolves and installs on a leg, each extra on its own does too, since a solution for all of them is a solution
for any of them.

- *Alternative: a leg per extra.* Rejected. It multiplies the platform-by-Python matrix by the number of extras,
  and checks nothing that `all` doesn't.
- *Cost:* a second install per leg. Today it's the same packages, so uv's cache makes it cheap. With real extras,
  task 6.4 records the measured time on each platform from the job logs.

### D10. The extras form of the documented command

`uv tool install [--no-sources ]"troupe-run[<extras>] @ git+https://github.com/troupe-run/troupe@<ref>#subdirectory=packages/troupe-run"`.
`install_check.TEMPLATE` gets an optional extras part, and `command()` takes the extras. The docs check
(in `scripts/tests/workspace/test_install_docs.py`, where the install-command checks live) accepts either form, applies the same ref rules to both, refuses an extra `troupe-run`
doesn't have, and checks that the install page's list of extras is exactly `troupe-run`'s. The extras form goes on
the install page between the release-please markers, so a release moves its tag too. The README keeps only the plain
form.

### D11. The licence check reads the lock and the installed metadata

A new `scripts/runner_licences.py`, run by `scripts/check.py` with the bundle check, does the following:

- For each plugin under `plugins/`, it walks `uv.lock` from the plugin's package through its dependencies,
  skipping workspace members. That gives every non-troupe package a runner pulls in, each necessarily at a locked
  version, which is the "pinned in the lock file" half. `uv sync --locked`, already in the check, keeps the lock
  current.
- For each package found, it reads the licence from the installed distribution's metadata in the check's own
  environment. The dev group installs every plugin, so every runner's dependencies are present. It reads
  `License-Expression`, else a single SPDX-like `License` value, else `License :: OSI Approved :: …` classifiers mapped
  to SPDX ids.
- It compares each against `scripts/licences.toml`, the one list, in two tiers (D13). The permissive tier is
  Apache-2.0, MIT, BSD-2-Clause, BSD-3-Clause, ISC and PSF-2.0. The weak-copyleft tier is MPL-2.0. The
  licence is read as an SPDX expression, with `AND` binding tighter than `OR` and parentheses grouping. An `OR`
  reaches the best tier of its sides, and an `AND` the worst of its parts. A `WITH` exception, or anything it can't
  parse, reaches no tier, so it fails safe (review of #338).

A package that's missing, has no licence or has one on neither tier fails, naming the package, the runner, what was
found and `scripts/licences.toml`. Today it checks nothing, and fixture locks and metadata test it. Adding a licence
to either tier is a reviewed one-line change, not something this change pre-approves.

### D13. Weak-copyleft licences are a second tier, allowed only unmodified

The owner decided this on 2026-11-07 (https://github.com/troupe-run/troupe/issues/333#issuecomment-6707703235), from
the #291 session's finding. `httpx` and `httpcore` depend on `certifi` (MPL-2.0), so `lmstudio` (#291), `openai`
(#331) and `ollama` (#332) all pull it in. Weak-copyleft licences, which is only MPL-2.0 for now, are allowed only as
unmodified dependencies, installed as separate packages, and never vendored, copied or patched into troupe's
source. MPL-2.0 binds only changes to its own files, so troupe's Apache-2.0 licence is unaffected. The ASF's
"category B" treats it the same way.

The licence check enforces both conditions:

- **Installed as its own package.** A weak-copyleft package's `uv.lock` entry must have a registry source, and the
  root's `[tool.uv.sources]` must not override it. A git, path or direct-URL source is how a patched copy would get
  in.
- **Not copied into the source.** No tracked file under `packages/`, `plugins/` or `scripts/` may carry the MPL-2.0
  notice ("This Source Code Form is subject to the terms of the Mozilla Public License"). The list names each
  weak-copyleft licence's notice beside it, so a later entry brings its own notice to search for.

The rest of `lmstudio`'s tree is already in the permissive tier: httpx-ws, anyio, wsproto and h11 (MIT), msgspec
and idna (BSD-3-Clause), sniffio (MIT OR Apache-2.0) and typing-extensions (PSF-2.0).

- *Rejected (owner): an exception for `certifi` by name.* Every other MPL-2.0 package would need one of its own.
- *Rejected (owner): keeping MPL-2.0 out.* It would rule out all three libraries and reopen #319's route for #291.
- *Not caught:* a weak-copyleft file pasted in with its notice removed. Removing the notice is itself a breach of
  the licence. The check catches the honest mistake (vendoring a file as it is), and review covers the rest.

### D12. Where the guarantees are written

The runner-protocol spec holds the guarantees, as requirements, once. A requirement is what binds and what each
runner's tests are written against. `contributing/runners.md` gets a "Runners with client libraries" section. It
links to those requirements rather than restating them, says each library-backed runner's design names how it keeps
each one, and gives the steps for adding an extra: the plugin's dependency, the extra and `all`, the table's `extra`,
the release hold while the plugin is bare, the install page's list, and the licence list if needed. Every one of
those steps has a check that fails when it's missed.

## Risks / Trade-offs

- [uv rejects an empty extra, or the extras form with a git URL and `--no-sources`] → task 1.1 tries both before
  anything is built on them. If either fails, the design changes before the code does.
- [The skipped options check (D7) lets a merge combine options that a runner would refuse] → the actor can't be
  performed or changed anywhere until its options are checked, and the first `set` or `perform` where the runner is
  installed refuses with the options' problem. No run starts on unchecked options.
- [Classifier-only licence metadata maps to the wrong SPDX id] → the mapping is a small table in the same file as the
  list, tested against real classifiers, and an unmapped classifier fails rather than passes.
- [The mechanism ships without a real extra, so a gap only shows up in #291] → every check is tested with fixture
  extras (an `lm-studio` entry in a fixture manifest and table). #291 waits for this to merge, and its pull request
  is the end-to-end proof. Its install-check legs exercise (a) and (b) for real.
- [The install check's refusal match is on text, not the code] → it matches `troupe-run[<extra>]` in the fix and the
  failure exit code. Core's own tests check the code itself.

## Migration Plan

No user data changes. Existing installs keep every runner, since all four are SDK-only and stay in the base. When
#291, #331 or #332 moves a runner into an extra, that pull request's changelog says a plain install no longer has
it, and the install page's list shows the extra. Rolling back is reverting the commits. No release format or event
changes.
