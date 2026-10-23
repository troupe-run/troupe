"""The git adapter's named defaults, in one place (event-store design D11).

troupe.core never imports an adapter, so the git adapter's environment policy and limits live in
its own package. A caller may narrow GIT_ENVIRONMENT (EnvironmentPolicy.narrow), never widen it.
"""

from troupe.platform.processes import EnvironmentPolicy

GIT_REPOSITORY_LOCATION_VARIABLES = frozenset(
    {
        # Exactly what `git rev-parse --local-env-vars` prints (git 2.56). A test runs the installed
        # git and fails if it prints a name missing here, so a new git release can't add a leak.
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_COUNT",
        "GIT_OBJECT_DIRECTORY",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_GRAFT_FILE",
        "GIT_INDEX_FILE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_REPLACE_REF_BASE",
        "GIT_PREFIX",
        "GIT_SHALLOW_FILE",
        "GIT_COMMON_DIR",
        # Not printed by git, but repository-scoped too (the runner contract's list).
        "GIT_NAMESPACE",
    }
)
"""The variables a hook sets to point git at a particular repository. troupe must read the
theatre's own repository, so these never reach git."""

GIT_ENVIRONMENT = EnvironmentPolicy(
    names=frozenset({"HOME", "USERPROFILE", "APPDATA", "XDG_CONFIG_HOME", "PATH", "SSH_AUTH_SOCK"}),
    prefixes=("GIT_",),
    never=GIT_REPOSITORY_LOCATION_VARIABLES,
    # GIT_CONFIG_COUNT is excluded, so the numbered pairs it would enable mean nothing: drop them.
    never_prefixes=("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"),
)
"""What git receives from troupe's environment (owner, 2026-10-12): where its global and XDG config
live (HOME, and USERPROFILE and APPDATA on Windows), PATH, the SSH agent, and the user's own GIT_*
settings (GIT_SSH_COMMAND, GIT_ASKPASS, GIT_CONFIG_GLOBAL), but never the repository-location
variables. Nothing else: no tokens, keys or locale."""

GIT_TIMEOUT_SECONDS = 10.0
"""How long one git command may run before it, and everything it started, is stopped."""

GIT_ANNOUNCE_AFTER_SECONDS = 1.0
"""How long a git command runs before troupe says what it is waiting for."""

GIT_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
"""The most output one git command may write, in both streams together, before it is stopped."""

GIT_RACY_WINDOW_SECONDS = 0.1
"""How recently a file the branch token watches may have changed before a read of the branch and
HEAD is used only once (cache-vcs-state design D4). Two git operations within one timestamp tick can
leave a file's mtime, size and inode as they were, so an answer read that close to a change is read
again next time, as git does for its own index. 0.1 s is well above the tick fine timestamps come
from: about 4 ms on Linux, 16 ms on Windows, nanoseconds on APFS."""

GIT_COARSE_RACY_WINDOW_SECONDS = 2.0
"""The racy window when every watched file's mtime is a whole second, as on a file system with
coarse timestamps: FAT's are 2 s, HFS+'s 1 s."""

# Run worktrees (worktree-stage design D4). A worktree's commands read or write every file of the
# repository, so they get limits of their own; each is still announced after
# GIT_ANNOUNCE_AFTER_SECONDS.

GIT_WORKTREE_TIMEOUT_SECONDS = 600.0
"""How long one git command that makes, fills, diffs or removes a run's worktree may run."""

GIT_WORKTREE_MAX_OUTPUT_BYTES = 256 * 1024 * 1024
"""The most output one worktree command may write, such as the file list of a large repository."""

GIT_DIFF_MAX_BYTES = 1024 * 1024 * 1024
"""The largest diff a run's changes may make before capturing them fails."""
