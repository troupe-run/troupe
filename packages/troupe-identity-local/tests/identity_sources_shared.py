"""What test_identity_sources.py and test_identity_sources_unit.py share."""

from troupe_identity_local import EnvSource, OsLoginSource, VcsSource

LOGIN = OsLoginSource(lookup=lambda: "ada-login")


def chain(login: OsLoginSource = LOGIN) -> list[tuple[str, EnvSource | VcsSource | OsLoginSource]]:
    """The default chain, with the OS login fixed so tests don't depend on who runs them."""
    return [("env", EnvSource()), ("vcs", VcsSource()), ("os-login", login)]
