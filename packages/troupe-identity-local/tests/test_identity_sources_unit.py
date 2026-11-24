"""The default identity chain with the filesystem adapter, which has no VCS identity, so the OS
login is used (spec: identity).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_identity_sources.py."""

from pathlib import Path

from identity_sources_shared import chain
from troupe.core.identity import IdentityContext, resolve_identity
from troupe.core.vcs import load_vcs


def test_the_filesystem_adapter_has_no_vcs_identity_so_the_os_login_is_used(
    tmp_path: Path,
) -> None:
    context = IdentityContext(env={}, vcs=load_vcs("files", tmp_path))
    assert resolve_identity(context, sources=chain()).source == "os-login"
