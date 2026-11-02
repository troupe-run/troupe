# Spec Delta

## Purpose

Capability: `cap:actor-runners`, `cap:plugins`

How troupe's own runners carry out a model's tool calls in the workspace: which tools there are, how each call is
checked against the actor's declared effects and kept inside the workspace, and how calls and results are reported
to the model and recorded as run events.

## ADDED Requirements

### Requirement: The tools are file tools, with no shell
The SDK SHALL offer exactly seven tools: `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Delete` and `Move`. Each SHALL
come with a definition a runner can give its model: its name, a description and a closed JSON Schema for its input.
There SHALL be no tool that runs a command.

#### Scenario: The definitions a runner offers
- **WHEN** a runner asks the SDK for its tool definitions
- **THEN** it gets the seven tools, each with a name, a description and an input schema whose objects are closed

#### Scenario: A model asks for a shell
- **WHEN** a model calls a tool named `Bash`
- **THEN** the result is an error naming `Bash` as unknown and listing the seven tools, and nothing runs

### Requirement: Each tool's input
Tools SHALL take these inputs: `Read` `file_path`, optional `offset` and `limit` (lines); `Write` `file_path`,
`content`; `Edit` `file_path`, `old_string`, `new_string`, optional `replace_all`; `Glob` `pattern`, optional `path`;
`Grep` `pattern`, optional `path` and `glob`; `Delete` `file_path`; `Move` `source`, `destination`.

#### Scenario: An Edit call's input
- **WHEN** a model calls `Edit` with `file_path`, `old_string` and `new_string`
- **THEN** the call validates against `Edit`'s input schema

### Requirement: A malformed call is an error result, not a failed run
A call SHALL be answered with an error result when its tool is unknown, its input isn't a JSON object (or text that
parses as one), or the input breaks the tool's schema. The error SHALL name the problem and the field, and the run
SHALL go on.

#### Scenario: Input that isn't JSON
- **WHEN** a model calls `Write` with the arguments text `{"file_path": "a.txt",`
- **THEN** the result is an error saying the input isn't valid JSON, and the next call is still carried out

#### Scenario: A missing field
- **WHEN** a model calls `Edit` without `old_string`
- **THEN** the result is an error naming `Edit` and `old_string`, and no file changes

#### Scenario: An unknown field
- **WHEN** a model calls `Read` with `file_path` and `encoding`
- **THEN** the result is an error naming `encoding` as a field `Read` doesn't take

### Requirement: Paths are workspace-relative
Every path a tool takes SHALL be relative to the workspace, with `/` between its parts. A path that's absolute,
empty, contains `..`, a `\`, a `:` or a control character SHALL be refused with an error result naming the path.

#### Scenario: An absolute path
- **WHEN** a model calls `Read` with `file_path` `/etc/passwd`
- **THEN** the result is an error saying paths are relative to the workspace, and nothing is read

#### Scenario: A path that climbs out
- **WHEN** a model calls `Read` with `file_path` `src/../../secret.txt`
- **THEN** the result is an error naming the path, and nothing is read

#### Scenario: A Windows-style path
- **WHEN** a model calls `Write` with `file_path` `src\main.py`, on any platform
- **THEN** the result is an error saying to use `/`, and nothing is written

### Requirement: A link can't lead out of the workspace
A path that resolves, through a symbolic link or junction, to somewhere outside the workspace SHALL be refused with an
error result, whichever tool is called and whatever the effects allow.

#### Scenario: A link to outside the workspace
- **WHEN** `notes` in the workspace links to a directory outside it, and a model calls `Read` on `notes/a.txt`
- **THEN** the result is an error naming the path, and nothing outside the workspace is read

### Requirement: The repository's metadata is out of reach
No tool SHALL read, list, search, change or remove anything under a `.git` entry at the workspace's top level,
whatever the effects allow. `Glob` and `Grep` SHALL leave it out of their results.

#### Scenario: Writing into .git
- **WHEN** an actor declares `write` for `**` and a model calls `Write` on `.git/config`
- **THEN** the result is an error naming the path, and nothing is written

#### Scenario: Searching everything
- **WHEN** a model calls `Grep` with no `path`
- **THEN** no match under `.git` is returned

### Requirement: Effects are declared as path patterns
An actor's declared effects SHALL be three lists of workspace-relative path patterns: `write`, `delete` and `move`.
A pattern SHALL match with `*` within one part, `**` across parts and `?` for one character. A malformed pattern SHALL
be an error naming it, never ignored.

#### Scenario: A pattern for a directory's files
- **WHEN** an actor declares `write` for `src/**`
- **THEN** `src/a.py` and `src/pkg/b.py` match it, and `tests/a.py` and `src` don't

#### Scenario: A malformed pattern
- **WHEN** a declaration's `delete` list has `/tmp/**`
- **THEN** making the declaration fails, naming `delete`, the pattern and that patterns are workspace-relative

### Requirement: With nothing declared, an actor is read-only
With no effects declared, `Read`, `Glob` and `Grep` SHALL work anywhere in the workspace, and every `Write`, `Edit`,
`Delete` and `Move` SHALL be refused.

#### Scenario: Writing with nothing declared
- **WHEN** an actor declares no effects and a model calls `Write` on `out/hello.txt`
- **THEN** the result is an error, and `out/hello.txt` doesn't exist

#### Scenario: Reading with nothing declared
- **WHEN** an actor declares no effects and a model calls `Read` on `README.md`
- **THEN** the result is the file's text

### Requirement: Writing needs the write effect
`Write` and `Edit` SHALL be carried out only when the path they change matches a `write` pattern. Neither `delete` nor
`move` SHALL allow writing.

#### Scenario: Writing where it's declared
- **WHEN** an actor declares `write` for `out/**` and a model calls `Write` on `out/hello.txt`
- **THEN** the file is written

#### Scenario: Editing where it isn't
- **WHEN** an actor declares `write` for `out/**` and a model calls `Edit` on `src/a.py`
- **THEN** the result is an error, and `src/a.py` is unchanged

### Requirement: Deleting and moving need effects of their own
`Delete` SHALL be carried out only when its path matches a `delete` pattern. `Move` SHALL be carried out only when
both its source and its destination match a `move` pattern. `write` SHALL allow neither.

#### Scenario: Deleting with only write declared
- **WHEN** an actor declares `write` for `**` and a model calls `Delete` on `out/old.txt`
- **THEN** the result is an error, and `out/old.txt` still exists

#### Scenario: Moving to a destination that isn't declared
- **WHEN** an actor declares `move` for `drafts/**` and a model moves `drafts/a.md` to `docs/a.md`
- **THEN** the result is an error, and `drafts/a.md` is where it was

#### Scenario: Moving within what's declared
- **WHEN** an actor declares `move` for `drafts/**` and a model moves `drafts/a.md` to `drafts/old/a.md`
- **THEN** the file is moved

### Requirement: A refusal names the effect it needs
A call refused by the effects SHALL be an error result that names the tool, the path and the effect the call would
need. Nothing SHALL change in the workspace, and the run SHALL go on.

#### Scenario: A refused Write
- **WHEN** an actor declares no effects and a model calls `Write` on `out/a.txt`
- **THEN** the result is an error naming `Write`, `out/a.txt` and the `write` effect

### Requirement: Effects are checked on the path that would change
The effects SHALL be checked against the workspace-relative path the call would actually change, after links inside
the workspace are followed, not only the path the model gave.

#### Scenario: A link to an undeclared directory
- **WHEN** an actor declares `write` for `out/**`, `out/link` links to `src`, and a model writes `out/link/a.py`
- **THEN** the result is an error naming the `write` effect for `src/a.py`, and nothing is written

### Requirement: Reading and searching
`Read` SHALL return a UTF-8 file's lines from `offset` (default the first), at most `limit` of them. `Glob` SHALL
return the paths matching its pattern, sorted. `Grep` SHALL return each line matching its regular expression as path,
line number and text. A file that isn't UTF-8 SHALL be an error for `Read` and skipped by `Grep`.

#### Scenario: Reading part of a file
- **WHEN** a model calls `Read` on a 100-line file with `offset` 10 and `limit` 5
- **THEN** the result is lines 10 to 14, each with its line number

#### Scenario: Finding a pattern
- **WHEN** a model calls `Grep` with `pattern` `def main` and `glob` `**/*.py`
- **THEN** the result lists each Python file's matching lines with their paths and line numbers, and nothing else

#### Scenario: Reading a binary file
- **WHEN** a model calls `Read` on a file that isn't valid UTF-8
- **THEN** the result is an error saying the file isn't text

### Requirement: Writing and editing
`Write` SHALL create or replace the whole file, creating missing parent directories, so the file is never left half
written. `Edit` SHALL replace `old_string` with `new_string` in an existing file, and SHALL be an error when
`old_string` isn't found, or is found more than once without `replace_all`.

#### Scenario: Writing a new file in a new directory
- **WHEN** an actor declares `write` for `out/**` and a model writes `out/new/a.txt`
- **THEN** `out/new/a.txt` exists with exactly the content given

#### Scenario: An ambiguous edit
- **WHEN** `old_string` occurs twice in the file and `replace_all` isn't set
- **THEN** the result is an error saying it occurs 2 times, and the file is unchanged

### Requirement: Deleting and moving
`Delete` SHALL remove one file, and SHALL be an error for a directory or a missing file. `Move` SHALL move one file,
creating the destination's missing parent directories, and SHALL be an error when the destination already exists.

#### Scenario: Deleting a directory
- **WHEN** an actor declares `delete` for `**` and a model calls `Delete` on `src`, a directory
- **THEN** the result is an error saying only files can be deleted, and `src` is unchanged

#### Scenario: Moving onto an existing file
- **WHEN** a model moves `a.txt` to `b.txt`, which exists, with `move` declared for both
- **THEN** the result is an error, and both files are unchanged

### Requirement: A failing call is an error result
A call that's allowed but can't be carried out, such as reading a missing file, SHALL be an error result saying
why. The run SHALL go on.

#### Scenario: Reading a missing file
- **WHEN** a model calls `Read` on `missing.txt`
- **THEN** the result is an error saying `missing.txt` doesn't exist

### Requirement: Results are capped by named limits
What a tool returns to the model SHALL be capped by named limits, each with its default in one place, which a runner
can lower: the bytes `Read` returns, the paths `Glob` returns, the matches `Grep` returns. A capped result SHALL say
it was cut, and how to get the rest.

#### Scenario: A large file
- **WHEN** a model reads a file larger than the read limit
- **THEN** the result holds the lines that fit, and says where it stopped and that `offset` reads on

### Requirement: Only regular files of a bounded size are loaded
`Read` and `Edit` SHALL refuse, with an error result, a path that isn't a regular file, and a file larger than the
named file limit, before reading any of it. `Grep` SHALL skip both kinds and say how many it skipped. No call SHALL
hold a whole file larger than its limit in memory, or wait on a pipe or device.

#### Scenario: Reading a file over the limit
- **WHEN** a model calls `Read` on a file larger than the file limit
- **THEN** the result is an error giving the file's size and the limit, and the file isn't read

#### Scenario: A named pipe in the workspace
- **WHEN** a model calls `Read` on a named pipe, or `Grep` over a directory holding one
- **THEN** `Read` is an error saying it isn't a regular file, `Grep` skips it and counts it, and neither blocks

### Requirement: Each call and result is a pair of run events
Each call SHALL be recorded as a `tool_call` event (its call id, the tool's name, and a summary of its input), then a
`tool_result` event with the same call id, whether it was an error, a summary of its output and the full output's
size in bytes. Their `seq` SHALL continue the run's.

#### Scenario: An allowed call
- **WHEN** a runner whose last event had `seq` 4 runs a `Read` call with id `c1`
- **THEN** the SDK records a `tool_call` with `seq` 5 and `callId` `c1`, then a `tool_result` with `seq` 6,
  `callId` `c1` and `isError` false

#### Scenario: A refused call
- **WHEN** a `Delete` call with id `c2` is refused by the effects
- **THEN** a `tool_call` for `c2` is recorded, then a `tool_result` for `c2` with `isError` true

### Requirement: Run events fit the run's limits
Each event's summary SHALL be cut to the summary limit, and further if needed so the whole event fits run start's
`eventMaxBytes`. `outputBytes` SHALL be the full output's UTF-8 size, whatever was cut.

#### Scenario: A large output
- **WHEN** `Grep` returns 200 KB of matches and `eventMaxBytes` is 65536
- **THEN** the `tool_result` event's encoded size is at most 65536 bytes, and its `outputBytes` is the full size
