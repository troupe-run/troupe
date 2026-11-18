"""A runtime's endpoint: where requests go, and whether a credential may be sent there
(openai-style-runner design D3; runtime-checks design D1, D8). Parsing only, with the standard
library: no I/O, and no import of the openai package, so the runner can check a run/start before
the library is loaded (openai-library design D8; review of #440).
"""

import ipaddress
import urllib.parse
from dataclasses import dataclass

RESPONSES_PATH = "/responses"
"""Where a Responses API request goes, below the runtime's endpoint."""


# Endpoints


class EndpointError(ValueError):
    """An endpoint that isn't an http or https URL the runner can send requests to."""


@dataclass(frozen=True)
class Endpoint:
    """A runtime's endpoint: the base URL that requests' paths go below, such as
    https://api.openai.com/v1."""

    url: str
    scheme: str
    host: str

    @property
    def responses_url(self) -> str:
        """Where requests go: below the endpoint, with only a single trailing / dropped, so an
        endpoint whose path is // keeps it, as has_path counts it (runtime-checks design D1)."""
        return self.url.removesuffix("/") + RESPONSES_PATH

    @property
    def has_path(self) -> bool:
        """Whether the URL has a path below its host and port: anything but a single trailing /,
        as troupe's runtime fit reads it (runtime-checks design D1)."""
        return urllib.parse.urlsplit(self.url).path not in ("", "/")

    @property
    def is_loopback(self) -> bool:
        """Whether the host is this machine: localhost, or a loopback address."""
        return is_loopback(self.host)

    def is_insecure_for(self, has_credential: bool) -> bool:
        """Whether sending a credential here would send it in the clear to another machine."""
        return has_credential and self.scheme == "http" and not self.is_loopback


def parse_endpoint(text: str) -> Endpoint:
    """``text`` as an Endpoint. Raises EndpointError naming what's wrong, never repeating an
    endpoint that may hold user info, such as a password (runtime-checks design D8, #323)."""
    shown = "The endpoint (not shown: it may hold user info)" if "@" in text else repr(text)
    try:
        parts = urllib.parse.urlsplit(text)
        host = parts.hostname or ""
        parts.port  # noqa: B018 - raises ValueError for a port that isn't a number in range
    except ValueError:
        raise EndpointError(f"{shown} isn't a URL with a host and a port in range.") from None
    if parts.username or parts.password:
        raise EndpointError(
            "The endpoint has a user name or password, which an endpoint never holds; it isn't "
            "shown."
        )
    if parts.scheme not in ("http", "https"):
        raise EndpointError(f"{shown} isn't an http or https URL.")
    if not host:
        raise EndpointError(f"{shown} names no host.")
    if parts.query or parts.fragment:
        raise EndpointError(f"{shown} has a query or fragment; an endpoint is a base URL only.")
    return Endpoint(text, parts.scheme, host)


def is_loopback(host: str) -> bool:
    """Whether ``host`` is this machine: ``localhost`` or a loopback address. A name that merely
    starts like one (127.0.0.1.example.com) isn't."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


__all__ = ["RESPONSES_PATH", "Endpoint", "EndpointError", "is_loopback", "parse_endpoint"]
