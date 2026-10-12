# Proposal

Issue: #48 (part 2 of troupe-run/infrastructure#15).

## Why

The PR template and the Bug, Feature and Decision issue forms are now org defaults, published to `troupe-run/.github`
(under `.github/`) from troupe-run/infrastructure (troupe-run/infrastructure#19, #20). GitHub uses a repository's own
templates instead of the org's, and applies the org's issue forms only to a repository with no
`.github/ISSUE_TEMPLATE/` folder of its own. So troupe still shows its stale copies, including the PR template's old
"After merge: archive the change" step, which contradicts the workflow (archive on the branch, before merging).
troupe-run/infrastructure's delivery can't remove files, so the deletion is troupe's own change.

## What Changes

- **Delete `.github/ISSUE_TEMPLATE/`**, all of it: `bug.yml`, `feature.yml`, `decision.yml` and `config.yml`. GitHub
  ignores every org form while the folder exists, even if it holds only `config.yml`.
- **Delete `.github/PULL_REQUEST_TEMPLATE.md`.**
- Nothing replaces them in troupe. The org's versions apply: the corrected PR template ("Archive the change on this
  branch before merging…"), and forms reworded for any repository. The Feature and Decision forms' label hint now
  reads "If the repository has `cap:<capability>` labels…", which still applies here, and the Decision form's
  `needs:owner` label exists in troupe.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None: repository configuration only. The change declares `skip_specs`.

## Impact

- Removes five files under `.github/`. `.github/workflows/`, `.github/guard-delivery.json` and the delivered guard
  files are untouched. Nothing in troupe refers to the removed files.
- Visible effect after merge: troupe's issue chooser shows the org's forms, and a new PR starts from the org's template.
- troupe-run/infrastructure#15 is already closed, so this PR closes #48 and references troupe-run/infrastructure#15.
