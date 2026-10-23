# Spec Delta

## ADDED Requirements

### Requirement: A file can be cloned copy-on-write
The platform seam SHALL clone a file copy-on-write where the filesystem supports it: `clonefile` on macOS, the
`FICLONE` reflink on Linux, and `CopyFile2` on Windows, which block-clones on a Dev Drive or ReFS. Where the clone
isn't supported it SHALL fall back to a plain copy. Either way it SHALL keep the file's bytes and executable bit, copy
a symbolic link as a link, and report which mechanism it used.

#### Scenario: A clone on APFS
- **WHEN** a file on an APFS volume is cloned
- **THEN** the copy has the same bytes and mode, and the mechanism reported is `clonefile`

#### Scenario: A filesystem that can't clone
- **WHEN** a file is cloned on a Linux filesystem that refuses `FICLONE`, such as ext4 or tmpfs
- **THEN** it is copied instead, with the same bytes and mode, and the mechanism reported is `copy`

#### Scenario: A symbolic link
- **WHEN** a symbolic link is cloned on a platform where the theatre has symbolic links
- **THEN** the copy is a symbolic link to the same target, and the target isn't read

#### Scenario: An executable file
- **WHEN** an executable file is cloned on Linux or macOS
- **THEN** the copy is executable too

### Requirement: A clone never overwrites
Cloning a file SHALL fail when the destination already exists, and SHALL leave the existing file as it was. A clone
that fails part-way SHALL leave no destination file.

#### Scenario: The destination exists
- **WHEN** a file is cloned to a path that already holds a file
- **THEN** the clone fails, naming the path, and the existing file is unchanged
