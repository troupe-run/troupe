# Design

## Context

See proposal.md, "Why". What shapes the approach:

- **Core finds its adapters by entry point** (`troupe.store`, `troupe.vcs`, `troupe.identity`, `troupe.stages`,
  `troupe.artifacts`), and its import contracts forbid importing them. **It starts its runners as
  `sys.executable -m <module>`** (`troupe.core.interim.RUNNERS`, until #38 replaces it). So every adapter and runner must
  be installed into troupe's own environment. Today the adapters depend on `troupe`, and `troupe` depends on none of
  them.
- **uv honours the root's workspace sources for a git subdirectory install.** This was tried on 2026-10-29 with uv
  0.11 against a `git+file://` clone of this repository. A scratch bundle package (then called `troupe-app`) whose dependencies were the eight
  bundled packages by bare name, with no sources of its own, installed all nine distributions from that one commit.
  The installed `troupe --version` ran, and the runner and adapter modules imported. The same check passed for a long
  `uv tool install troupe --with <pkg @ url>` command (×8), and for core depending on the eight itself.
- **`uv tool install` links only the named package's own executables**, not its dependencies'. `--with-executables-from`
  exists, but it makes the command longer.
- **No tag exists**, and #139 holds the release PR until 0.1.0's last issue closes. Installing from a tag is #189.

## Goals / Non-Goals

**Goals:**

- One copy-pasteable command, the same in sh and PowerShell, installs a troupe that can run an actor.
- What the bundle must contain is derived from the workspace, so a new adapter or runner can't be forgotten.
- The documented command, not an approximation of it, runs in CI on every platform and Python.

**Non-Goals:**

- Installing by release tag, and checking each release's tag (#189).
- PyPI, standalone executables, or anything for non-technical users (#143).
- Changing how core finds adapters or starts runners. #38 replaces the runner table, and the bundle's contents get
  another look then.

## Decisions

### D1. A separate bundle package, `troupe-run`, rather than core depending on its adapters

`packages/troupe-run/` is a distribution whose dependencies are `troupe` and every other workspace member, by bare name.
The root's `[tool.uv.sources]` already maps each name to its workspace member, so installing it from a commit installs
everything from that commit.

The owner chose this on 2026-10-29. Alternatives:

- **Core depends on the eight.** It works, and the command could name `packages/troupe`. But it makes a dependency
  cycle (each adapter depends on `troupe`), and core's metadata would name packages it's forbidden to import, only so
  it can be distributed.
- **`--with` for each package.** No packaging change, but nine URLs each repeat the ref, and quoting differs between
  sh and PowerShell.

It lives under `packages/` because it's released with core. So the existing `releases` requirements put it in the
linked group and give it a changelog, with no new rule. Its module, `troupe_run`, holds only a docstring: `uv_build`
needs a module, and nothing imports it.

**The name** is `troupe-run` (owner, 2026-10-29). It's the name people see in `uv tool list`, `uv tool upgrade` and
`uv tool uninstall`, and it ties the install to the troupe.run domain and the troupe-run org. Its tag is
`troupe-run-v<version>`, and its module is `troupe_run`. `troupe` is taken by core, and renaming core is out of scope.
Other names considered were `troupe-app`, `troupe-bundle` and `troupe-cli`. `troupe-cli` is wrong, because the bundle
holds more than the command line. The cost of `troupe-run`: "run" is also troupe's word for one actor's run, so the
name can read as "a troupe run". People type it only to install, upgrade or uninstall, and the docs give those commands
in full. A later rename costs one edit to the name in the one place it's held (D3), plus the package directory.

### D2. The bundle declares its own `troupe` command, pointing at core's

`[project.scripts] troupe = "troupe.cli:main"`, the same target as core's. A check compares the two targets, so they
can't drift apart. Both packages then install a `troupe` script into the tool's environment, and both scripts are the
same. In the trial, uv installed it without a warning, and linked one `troupe` onto the path.

The alternative is `--with-executables-from troupe` in the documented command. That keeps one script per environment,
but it makes the command longer, and someone who leaves the flag out gets an install with no `troupe` command on their
path.

### D3. The install command lives in one named place

`scripts/install_check.py` holds the command as a template, `uv tool install "git+{repository}@{ref}#subdirectory=
packages/troupe-run"`, and the repository URL `https://github.com/troupe-run/troupe`. The script uses the template to run
the install. A docs test (tagged `docs`) finds every `uv tool install` line in `README.md` and under `docs/`, and fails
unless the line is the template with that repository URL and one of the refs the page documents: `main`, or the
`<commit>` placeholder. The failure names the page, the line and the expected command.

The README isn't under `docs/`, so changing it runs the full check, which includes this test.

### D4. The install check runs the documented command against the commit, from a `git+file` URL

```text
uv run scripts/install_check.py [--ref <commit>] [--python <version>]
```

The check:

1. Makes a temporary directory, and points `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR` at it. The developer's own tools and
   path are never touched, and the directory is removed at the end.
2. Runs the template with `{repository}` set to `git+file://` and the checkout's root, `{ref}` set to the given commit
   (default `HEAD`, resolved to a SHA first), and `--python` when one is given.
3. Runs the installed `troupe --version`, checks that it names the version in core's `pyproject.toml`.
4. In a new git repository in the temporary directory, with a local git identity: makes `.troupe/`, sets a scripted
   actor that writes a file, commits, sets `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true`, and runs
   `troupe perform`. It checks for `run <id> succeeded`. This is the "Your first performance" path, so it proves the
   install can start a runner and record a run, not just print a version.

Each subprocess has a timeout, a named constant at the top of the script, because nothing bounds a test or script
otherwise. A failure names the step, the command and its output.

Why `git+file` rather than the GitHub URL: the commit under test may be a pull request's merge commit, or one that
was never pushed, and the check must work offline from GitHub. The mechanics are the same (uv clones, checks out the
ref, builds from the subdirectory, applies the workspace sources). Only the host isn't exercised, and #189's
release check runs the hosted URL against each tag.

**The check isn't a gate in `scripts/check.py`.** Run before a commit, `HEAD` is the previous commit, so it would check
the wrong tree, and it needs the network for the first resolution. CI runs it.

### D5. CI runs it in each check leg, after a full check

A step after "Check" in `check-legs` runs `uv run scripts/install_check.py --ref ${{ github.sha }} --python
${{ matrix.python }}`, only when `check-args` is empty (the full check). That covers Linux, macOS and Windows, and every
supported Python, and the step is part of the `check` result, which is already required. A scoped run (only docs, or
one adapter's tests) skips it. The bundle's contents can change only through a `pyproject.toml`, and a change to any
`pyproject.toml` runs the full check.

A separate job was considered. It would need its own path filter and its own entry in `check`'s aggregation, for no
gain. `actions/checkout`'s shallow clone holds `github.sha`, and git can clone from a shallow repository. CI's first run
confirmed it (PR #192, run 40863498888, 2026-10-29). The step passed on all 12 legs, with no fallback needed. It took
2 to 3 s on Linux, 7 to 8 s on macOS and 12 to 15 s on Windows, well inside the minute that would move it to one Python
per platform.

### D6. The bundle's contents are checked against the workspace

A test in `scripts/tests/workspace/` reads the workspace members from the root `pyproject.toml`'s globs. It fails when
`troupe-run`'s dependencies aren't exactly `troupe` plus every other member except `troupe-run` itself, naming each
missing or extra name and `packages/troupe-run/pyproject.toml`. A second test fails when core's dependencies name any
workspace member, naming it and `troupe-run` as where it belongs. A third fails when the two `troupe` script targets
differ, naming both. They sit beside the release configuration's tests, which already read every package's
`pyproject.toml`.

Exactly, not "at least": the bundle exists to be the full set, and an extra name could only be a typo or something that
isn't in the workspace.

### D7. The docs say install from `main` or a commit, and that no release exists yet

The README's "nothing to install yet" becomes a short **Install** section: there's no release yet, and the command
installs the latest `main`, or a given commit in place of `main`. troupe needs Python 3.12 to 3.15, and uv downloads one
if it's needed. The section also covers `uv tool update-shell` when the path isn't set up, and `uv tool uninstall
troupe-run`. `docs/opening-night/install.md` says the same at more length. The decided points stay. The "isn't decided
yet (#38)" paragraph is replaced with #139's decision. Reaching non-technical users is #143, and installing by tag is #189.

Upgrading was checked during apply (task 4.2, 2026-10-29, uv 0.11, in a scratch clone). With troupe installed from a
branch, `uv tool upgrade troupe-run` fetched the branch's newer tip, and moved all nine packages to it. Running the install
command again with another commit replaced the install, without `--reinstall`. So the docs give `uv tool upgrade
troupe-run` for an install from `main`, and the install command with another commit for moving to that commit.

### D8. The issue links follow #139's split

| Page | Today | After |
|---|---|---|
| `the-company/escalation.md` | reaching a role is part of gates and escalations, in #62 | reaching a role comes with roles, in #148 |
| `the-company/gates-and-decisions.md` | gates are addressed to roles (#62), and how a gate is defined is open in #61 | the first gates (#62) go to whoever runs troupe, addressing them to roles is #148, and defining a gate is #62 |
| `the-company/flows.md` | forking, joining, swarming and looping are all open in #124 | the first flow, a sequence, is #124; fork and join #145, loops #146, swarms #147 |
| `stagecraft/route-decisions.md` | how a gate is defined (#62) | unchanged, plus how gates and escalations reach a role's holder (#148) |
| `stagecraft/read-the-lineage.md` | `approvals` fills in once gates exist (#62) | unchanged: still true |
| `stagecraft/build-a-flow.md` | how a flow is written in config is open in #124 | unchanged: #124 settles what every flow builds on |

Each issue's current title and body are read again at apply time, before its link is edited.

## Risks / Trade-offs

- **[The bundle's version doesn't describe its plugins.]** Plugins version on their own, so `troupe-run` 0.1.x doesn't
  say which runner versions it brought. → Installs are by commit for now, and the commit pins everything. #189 decides
  what a tag install means.
- **[Two packages install the same `troupe` script.]** A future uv could warn or refuse. → D2's check keeps the targets
  equal, and the install check would fail in CI first. The fallback is `--with-executables-from troupe`.
- **[`git+file` doesn't prove the GitHub URL works.]** → The template is shared, so only the host differs. #189's
  release check uses the hosted URL.
- **[The install check adds time to every full CI leg.]** → It reuses setup-uv's cache, and the trial installed in
  about a second once cached. If it adds more than a minute to a leg, it moves to one Python per platform, and that's
  recorded here.
- **[A shallow checkout can't serve the commit to uv.]** → If CI's first run shows it, the leg's checkout gets
  `fetch-depth: 0`, or the check clones with `--depth`, recorded here.

## Migration Plan

Nothing to migrate: nobody has installed troupe outside a clone. Developers' `uv sync` gains the bundle as a workspace
member. Rollback is reverting the change.
