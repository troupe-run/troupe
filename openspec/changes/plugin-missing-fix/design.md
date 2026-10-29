# Design

## Context

See proposal.md, "Why". `plugin_schemas_directory(package)` finds a plugin's `schemas/` directory with
`importlib.util.find_spec`, without importing it, and raises `schemas.plugin-missing` when there's none. Today the only
packages it's asked about come from `interim.RUNNERS` (the scripted and Claude Code runners), and every one of them is
a dependency of `troupe-run`, so a missing one means a broken or partial install, or a checkout that hasn't been
synced.

The install command exists in one form, built by `scripts/install_check.py`'s `TEMPLATE`. The docs check
(`scripts/tests/workspace/test_install_docs.py`) holds every copy in `README.md` and `docs/opening-night/install.md`
to that form. `scripts/` isn't part of the installed package, so core can't build the command from it. The install
page is published at `https://troupe.run/docs/opening-night/install/` (the README already links to its sibling pages
in that form).

## Goals / Non-Goals

**Goals:**
- The fix is something the person can do, whether troupe came from `uv tool install` of `troupe-run` or from a clone.
- The test fails if the fix's wording regresses to checkout-only advice, or if the page it links to moves.

**Non-Goals:**
- Changing the error code, `details`, or exit code, so no change to `error.schema.json` or `errors.py`.
- Rewording the other `schemas.plugin-missing` refusal (an installed plugin that doesn't publish a named schema). It's
  for the plugin's author, and its fix already fits them.
- Missing plugins `troupe-run` doesn't bring, which only arise once plugins are named in config (#38).

## Decisions

### D1. One fix that names both cases, not a guess at which install this is

The fix reads, in full:

> Reinstall troupe with the install command at https://troupe.run/docs/opening-night/install/, which brings every
> runner troupe knows. If you run troupe from a checkout of troupe, run uv sync there instead.

The rest of today's fix ("A plugin publishes its schemas in its package's schemas/ directory, installed with it.") is
dropped: it explains the mechanism, not what to do, and the problem line already says what's missing.

*Alternative:* tell the two cases apart and give only the one that applies, for example by reading the `troupe`
distribution's `direct_url.json` (`uv sync` installs workspace members editable; `uv tool install` from git records
`vcs_info`). Rejected for now: it's a heuristic about how packaging tools record installs, so it can be wrong (a
`pip install -e` elsewhere, a wheel built from a clone, a future uv change), and a wrong guess sends the person to the
one remedy that doesn't fit. The project constraint is "refuse rather than guess"; naming both costs one sentence and
is right in every case. If the owner prefers detection, it's a change to this one function and its test, not to the
spec's wording of the requirement ("a fix that is right however troupe was installed").

### D2. Link to the install page; don't repeat the command

The installation spec requires every copy of the install command to match the one form the install check runs, and
the docs check only looks at the docs pages. A command written into core's message would be a third copy nothing
checks, with a ref (`main`, or a commit) that may not be the one the person installed. A link to the page keeps the
command in one place and lets the page explain refs and Python versions.

The address is one named constant in `troupe.core.schemas`, `INSTALL_PAGE`, so the test and any later message share
it.

### D3. A test ties the link to the page in `docs/`

The docs site maps `docs/<section>/<page>.md` to `https://troupe.run/docs/<section>/<page>/`. A test in
`test_schemas.py` takes `INSTALL_PAGE`, checks it starts with `https://troupe.run/docs/` and ends with `/`, and asserts
the corresponding `docs/…/<page>.md` exists in the repository, naming the address when it doesn't. Moving or renaming
the install page then fails troupe's own tests instead of quietly breaking the fix.

## Risks / Trade-offs

- [The published site lags `docs/` or is down] → The test checks the source page, not the live site; that's the same
  guarantee the README's links get. The fix still says what to do ("reinstall troupe", "uv sync") without the link.
- [The fix is longer than one remedy] → Two short sentences; the person picks the one that matches how they got
  troupe, which they know and troupe can only guess.
