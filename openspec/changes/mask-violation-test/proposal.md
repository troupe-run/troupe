# Proposal

## Why

#459: `test_every_valid_line_is_read_and_no_string_it_keeps_holds_the_credential` fails, every time, on an example
Hypothesis found: a one-letter credential (`"r"`) and a line two of whose keys mask to the same text. The run host
raises the right violation, but the test looks for the unmasked phrase "same once the run's credential". The host
masks the whole sentence, troupe's own words too, because the sentence names the runner's keys and no string troupe
keeps may hold the credential. With a one-letter credential, troupe's words hold it, so the phrase reads
"same once the [credential]un's c[credential]edential". The saved example fails every local commit in a worktree whose
check found it.

## What Changes

- The test's violation branch checks the phrase with the credential put back where it was masked, in the sentence
  after the problem's fixed prefix, instead of matching the masked text.
- It also checks what the masking is for: in that sentence, the credential is in no form outside a marker. Before, the
  branch didn't check that at all.
- Hypothesis's example from #459 is pinned with `@example`, so it runs on every machine, not only where the database
  saved it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. The run host's behaviour doesn't change; the test is corrected to what the host already does
(`skip_specs: true`).

## Impact

`packages/troupe/tests/test_run_host.py` only.
