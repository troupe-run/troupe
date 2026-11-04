"""A run's credential: where a runner finds it (spec: runner-protocol, "The credential's value is in
the runner's environment as TROUPE_RUNTIME_CREDENTIAL"; runtimes design D5).

troupe never puts the credential's value in ``run/start``, which it records. When the run's runtime
has one, ``run/start`` says so (``runtime.credential``) and the value is in the runner's environment
as ``TROUPE_RUNTIME_CREDENTIAL``. A runner sends it only to the runtime's endpoint, and never back
to troupe.
"""

from collections.abc import Mapping

from troupe_plugin_sdk.runner import RunStartParams

CREDENTIAL_VARIABLE = "TROUPE_RUNTIME_CREDENTIAL"
"""The one variable a runner reads its runtime's credential from."""


class CredentialError(Exception):
    """``run/start`` and the runner's environment disagree about the credential. The message says
    which way, and never holds the value."""


def runtime_credential(params: RunStartParams, environ: Mapping[str, str]) -> str | None:
    """The run's credential, or None when its runtime has none or it has no runtime.

    Refused when ``run/start`` says there's a credential and ``environ`` has none (or an empty
    one), and when there's a value but ``run/start`` says there's none: either is a host that
    doesn't keep the contract, and a runner shouldn't guess which side is right."""
    value = environ.get(CREDENTIAL_VARIABLE, "")
    expected = params.runtime is not None and params.runtime.credential
    if expected and not value:
        raise CredentialError(
            f"run/start says the runtime has a credential, but {CREDENTIAL_VARIABLE} isn't set"
        )
    if not expected and value:
        raise CredentialError(
            f"{CREDENTIAL_VARIABLE} is set, but run/start says the run has no credential"
        )
    return value or None
