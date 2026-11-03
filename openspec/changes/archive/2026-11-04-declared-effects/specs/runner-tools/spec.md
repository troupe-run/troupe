# Spec Delta

## MODIFIED Requirements

### Requirement: Paths are workspace-relative
Every path a tool takes SHALL be relative to the workspace, with `/` between its parts, or an absolute path inside the
run's scratch directory. Any other absolute path, and a path that's empty, contains `..`, a `\` (other than in a
scratch path on Windows), a `:` (other than a scratch path's drive on Windows) or a control character, SHALL be
refused with an error result naming the path.

#### Scenario: An absolute path
- **WHEN** a model calls `Read` with `file_path` `/etc/passwd`
- **THEN** the result is an error saying paths are relative to the workspace or inside the scratch directory, naming
  it, and nothing is read

#### Scenario: A path that climbs out
- **WHEN** a model calls `Read` with `file_path` `src/../../secret.txt`
- **THEN** the result is an error naming the path, and nothing is read

#### Scenario: A Windows-style path
- **WHEN** a model calls `Write` with `file_path` `src\main.py`, on any platform
- **THEN** the result is an error saying to use `/`, and nothing is written

#### Scenario: A scratch path that climbs out
- **WHEN** a model calls `Write` with `file_path` the scratch directory followed by `/../escape.txt`
- **THEN** the result is an error naming the path, and nothing is written

### Requirement: The repository's metadata is out of reach
No tool SHALL read, list, search, change or remove anything under a `.git` entry at the workspace's top level,
whatever the effects allow. No tool SHALL change or remove anything under a `.troupe` entry at the workspace's top
level, whatever the effects allow; reading it is allowed. `Glob` and `Grep` SHALL leave `.git` out of their results.

#### Scenario: Writing into .git
- **WHEN** an actor declares `write` for `**` and a model calls `Write` on `.git/config`
- **THEN** the result is an error naming the path, and nothing is written

#### Scenario: Searching everything
- **WHEN** a model calls `Grep` with no `path`
- **THEN** no match under `.git` is returned

#### Scenario: Writing into .troupe
- **WHEN** an actor declares `write` for `**` and a model calls `Write` on `.troupe/actors/lead.yaml`
- **THEN** the result is an error saying `.troupe/` is troupe's own, and nothing is written

#### Scenario: Moving out of .troupe
- **WHEN** an actor declares `move` for `**` and a model moves `.troupe/events/a.jsonl` to `a.jsonl`
- **THEN** the result is an error naming `.troupe/events/a.jsonl`, and nothing is moved

## ADDED Requirements

### Requirement: The scratch directory needs no effect
Every tool SHALL work on paths inside the run's scratch directory without any declared effect: `Write`, `Edit`,
`Delete` and `Move` within it SHALL be carried out for a read-only actor. A `Move` between the scratch directory and
the workspace SHALL need the effect its workspace end needs: `write` for the destination when moving in, `delete` for
the source when moving out. A link inside the scratch directory that resolves outside it SHALL be refused, as in the
workspace.

#### Scenario: A read-only actor writes to scratch
- **WHEN** an actor declares no effects and a model writes `notes.txt` under the scratch directory's absolute path
- **THEN** the file is written there, and nothing in the workspace changes

#### Scenario: Moving a scratch file into the workspace
- **WHEN** an actor declares `write` for `out/**` and a model moves a scratch file to `out/report.md`
- **THEN** the file is moved, and the move into `src/report.md` would be an error naming the `write` effect

#### Scenario: No scratch directory given
- **WHEN** a runner makes the tools without a scratch directory and a model writes an absolute path
- **THEN** the result is an error saying the run has no scratch directory, and nothing is written

### Requirement: Tool definitions tell the model where it may work
The tool definitions SHALL say that paths are relative to the workspace, and name the scratch directory's absolute
path as somewhere to keep temporary files, when the run has one.

#### Scenario: The Write tool's description
- **WHEN** a runner asks the SDK for its tool definitions with a scratch directory
- **THEN** `Write`'s description names the scratch directory's path, and says temporary files go there
