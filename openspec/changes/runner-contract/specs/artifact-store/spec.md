# Spec Delta

## Purpose

Content-addressed storage for run artifacts that are too large or too sensitive for git, such as raw transcripts,
so that lineage can reference them by hash and any copy can be verified.

## ADDED Requirements

### Requirement: Artifacts are addressed by their SHA-256 hash
Storing an artifact SHALL return its reference, `sha256:` followed by the lowercase hex SHA-256 of its exact bytes.
The same bytes SHALL always produce the same reference.

#### Scenario: Reference is the content hash
- **WHEN** an artifact is stored
- **THEN** its reference is `sha256:` followed by the SHA-256 of its bytes

#### Scenario: Storing the same bytes twice
- **WHEN** the same bytes are stored twice
- **THEN** both calls return the same reference and the store holds one copy

### Requirement: Artifacts can be written as a stream
The store SHALL accept an artifact written incrementally, without holding it all in memory, and SHALL return its
reference when the writer finishes. An artifact SHALL become readable only once it is complete.

#### Scenario: Large streamed artifact
- **WHEN** an artifact of many megabytes is written in small pieces
- **THEN** the reference returned is the SHA-256 of all the pieces in order

#### Scenario: Unfinished artifact is not readable
- **WHEN** a streamed artifact has not been finished
- **THEN** no reference for it can be read from the store

### Requirement: Reads are verified
Reading an artifact SHALL check its bytes against its reference. A mismatch SHALL be an error naming the reference,
the path and the fix; corrupted bytes SHALL NOT be returned.

#### Scenario: Stored file was altered
- **WHEN** an artifact's stored file has been changed after it was stored
- **THEN** reading it fails with an error naming the reference and the path

#### Scenario: Missing artifact
- **WHEN** a reference that is not in the store is read
- **THEN** the read fails with an error naming the reference and saying it is not in this store

### Requirement: The local store stays out of version control
The local store SHALL keep its files out of git by itself, without the user editing any of their own files, and
SHALL NOT change any file outside its own directory. This SHALL hold wherever its caller puts it, including under a
directory that is already ignored.

#### Scenario: Store inside a git repository
- **WHEN** artifacts are stored in a local store inside a git working tree
- **THEN** `git status` shows none of the store's files

### Requirement: Writes are atomic and leave nothing behind on failure
Storing an artifact SHALL be atomic: the store SHALL hold either the complete artifact or nothing for it. A failed
or abandoned write SHALL leave no partial artifact readable.

#### Scenario: Write abandoned part-way
- **WHEN** a streamed write is abandoned before it finishes
- **THEN** no artifact is readable for the partial bytes and the store's temporary file is removed

### Requirement: The store is a port
Code that stores or reads artifacts SHALL depend only on the store's interface, so another store can replace the
local one without changing callers. The local store's location SHALL be given by its caller.

#### Scenario: Run host uses any store
- **WHEN** the run host is given an in-memory store in a test instead of the local store
- **THEN** runs store and reference their transcripts the same way

### Requirement: Stores are separately packaged and found by name
Each artifact store other than the core's in-memory one SHALL be its own package, registered under the
`troupe.artifacts` entry point group, and SHALL be found by its name. The local store SHALL be registered as
`local`. The core SHALL NOT import a store package directly.

#### Scenario: Local store found by name
- **WHEN** the store named `local` is asked for with a root directory
- **THEN** a local store at that root is returned, from its own package

#### Scenario: Unknown store name
- **WHEN** a store name that no installed package registers is asked for
- **THEN** the request fails with an error naming the store and the stores that are installed

#### Scenario: Core does not import a store package
- **WHEN** code in the core imports the local store's package
- **THEN** the import contract check fails
