"""Talking to a Responses API service: the runner's only network I/O (openai-style-runner design
D3).

Requests go through the standard library's urllib, which honours HTTPS_PROXY and NO_PROXY and the
platform's TLS trust store (or SSL_CERT_FILE and SSL_CERT_DIR). Redirects are refused, never
followed, so neither the credential nor the conversation reaches a host the runtime didn't name. A
loopback endpoint never goes through a proxy, which couldn't reach this machine's own server.

Which endpoints are safe to send a credential to is decided here too, beside how they're reached.

    call = Call(endpoint, body, credential)
    response = call.open()       # or raises StatusError / NetworkError
    for line in response.lines(): ...
    call.abort()                 # from any thread: a blocked read wakes and raises AbortedError
"""

import contextlib
import http.client
import ipaddress
import socket
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from troupe_runner_openai import NAME, __version__
from troupe_runner_openai.defaults import (
    CONNECT_TIMEOUT_SECONDS,
    ERROR_BODY_MAX_BYTES,
    STREAM_LINE_MAX_BYTES,
    STREAM_TIMEOUT_SECONDS,
)

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
        return self.url.rstrip("/") + RESPONSES_PATH

    @property
    def is_loopback(self) -> bool:
        """Whether the host is this machine: localhost, or a loopback address."""
        return is_loopback(self.host)

    def is_insecure_for(self, has_credential: bool) -> bool:
        """Whether sending a credential here would send it in the clear to another machine."""
        return has_credential and self.scheme == "http" and not self.is_loopback


def parse_endpoint(text: str) -> Endpoint:
    """``text`` as an Endpoint. Raises EndpointError naming what's wrong."""
    try:
        parts = urllib.parse.urlsplit(text)
        host = parts.hostname or ""
        parts.port  # noqa: B018 - raises ValueError for a port that isn't a number in range
    except ValueError as error:
        raise EndpointError(f"{text!r} isn't a URL: {error}.") from None
    if parts.scheme not in ("http", "https"):
        raise EndpointError(f"{text!r} isn't an http or https URL.")
    if not host:
        raise EndpointError(f"{text!r} names no host.")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise EndpointError(
            f"{text!r} has a query, fragment or user name; an endpoint is a base URL only."
        )
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


# Failures


class StatusError(Exception):
    """The service answered with a status other than 2xx, redirects included."""

    def __init__(self, status: int, headers: Mapping[str, str], body: bytes) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.headers = dict(headers)
        """By lower-case name."""
        self.body = body


class NetworkError(Exception):
    """The request didn't get a whole answer: it couldn't connect, timed out, or the stream broke.
    The message says which, in words a person can act on."""


class AbortedError(Exception):
    """The call was aborted from another thread."""


# Calls


class _Opened:
    """The socket a call connected, kept so the stream timeout can be set on it and another thread
    can shut it down. urllib drops the connection's own reference once the response's headers have
    arrived (the response keeps reading through it), so it's captured as it connects."""

    def __init__(self) -> None:
        self.sock: socket.socket | None = None


class _HTTPConnection(http.client.HTTPConnection):
    opened: _Opened | None = None

    def connect(self) -> None:
        super().connect()
        if self.opened is not None:
            self.opened.sock = self.sock


class _HTTPSConnection(http.client.HTTPSConnection):
    opened: _Opened | None = None

    def connect(self) -> None:
        super().connect()
        if self.opened is not None:
            self.opened.sock = self.sock


class _HTTP(urllib.request.HTTPHandler):
    def __init__(self, opened: _Opened) -> None:
        super().__init__()
        self._opened = opened

    def _connection(self, host: str, /, **kwargs: Any) -> http.client.HTTPConnection:  # noqa: ANN401
        connection = _HTTPConnection(host, **kwargs)
        connection.opened = self._opened
        return connection

    def http_open(self, request: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(self._connection, request)


class _HTTPS(urllib.request.HTTPSHandler):
    def __init__(self, opened: _Opened) -> None:
        self._tls = ssl.create_default_context()
        super().__init__(context=self._tls)
        self._opened = opened

    def _connection(self, host: str, /, **kwargs: Any) -> http.client.HTTPConnection:  # noqa: ANN401
        connection = _HTTPSConnection(host, **kwargs)
        connection.opened = self._opened
        return connection

    def https_open(self, request: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(self._connection, request, context=self._tls)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect, so urllib raises it as an HTTPError instead of following it and
    resending the Authorization header."""

    def redirect_request(self, *_: Any) -> None:  # noqa: ANN401
        return None


class Response:
    """A streamed 2xx response."""

    def __init__(self, call: "Call", response: http.client.HTTPResponse) -> None:
        self._call = call
        self._response = response
        self.status = response.status
        self.headers = {name.lower(): value for name, value in response.getheaders()}

    def lines(self) -> Iterator[str]:
        """Each line of the body, without its line ending, as it arrives. Raises NetworkError when
        the stream goes silent for the stream timeout, breaks, holds a line too long or that isn't
        UTF-8, and AbortedError when the call is aborted."""
        while True:
            try:
                line = self._response.readline(STREAM_LINE_MAX_BYTES + 1)
            except TimeoutError:
                self._call.raise_if_aborted()
                raise NetworkError(
                    f"The service sent nothing for {self._call.stream_timeout:g} seconds."
                ) from None
            except (OSError, http.client.HTTPException, ValueError) as error:
                self._call.raise_if_aborted()
                raise NetworkError(f"The response's stream broke: {_words(error)}.") from None
            self._call.raise_if_aborted()
            if not line:
                return
            if len(line) > STREAM_LINE_MAX_BYTES:
                raise NetworkError(
                    f"A line of the response's stream is longer than {STREAM_LINE_MAX_BYTES} bytes."
                )
            try:
                text = line.decode("utf-8")
            except UnicodeDecodeError:
                raise NetworkError("A line of the response's stream isn't UTF-8.") from None
            yield text.removesuffix("\n").removesuffix("\r")

    def close(self) -> None:
        self._response.close()


class Call:
    """One request to a runtime's endpoint. ``abort`` may be called from any thread."""

    def __init__(
        self,
        endpoint: Endpoint,
        body: bytes,
        credential: str | None,
        connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
        stream_timeout: float = STREAM_TIMEOUT_SECONDS,
    ) -> None:
        self.endpoint = endpoint
        self.stream_timeout = stream_timeout
        self._connect_timeout = connect_timeout
        self._body = body
        self._credential = credential
        self._opened = _Opened()
        self._aborted = threading.Event()

    def open(self) -> Response:
        """Send the request and return the streamed response once its status is 2xx. Raises
        StatusError for any other status, NetworkError when there's no answer, and AbortedError."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": f"troupe-runner-{NAME}/{__version__}",
        }
        if self._credential:
            headers["Authorization"] = f"Bearer {self._credential}"
        request = urllib.request.Request(  # noqa: S310 - the scheme is checked: http or https
            self.endpoint.responses_url, data=self._body, headers=headers, method="POST"
        )
        proxies = urllib.request.ProxyHandler({} if self.endpoint.is_loopback else None)
        opener = urllib.request.build_opener(
            proxies, _HTTP(self._opened), _HTTPS(self._opened), _NoRedirect()
        )
        self.raise_if_aborted()
        try:
            response = opener.open(request, timeout=self._connect_timeout)
        except urllib.error.HTTPError as error:
            self.raise_if_aborted()
            body = _read_some(error)
            raise StatusError(
                error.code, {k.lower(): v for k, v in error.headers.items()}, body
            ) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as error:
            self.raise_if_aborted()
            raise NetworkError(_connect_words(self.endpoint, error)) from None
        if self._opened.sock is not None:
            self._opened.sock.settimeout(self.stream_timeout)
        self.raise_if_aborted()
        return Response(self, response)

    def abort(self) -> None:
        """Stop the call: a blocked connect or read wakes and raises AbortedError."""
        self._aborted.set()
        sock = self._opened.sock
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    @property
    def aborted(self) -> bool:
        return self._aborted.is_set()

    def raise_if_aborted(self) -> None:
        if self._aborted.is_set():
            raise AbortedError


def _read_some(error: urllib.error.HTTPError) -> bytes:
    try:
        return error.read(ERROR_BODY_MAX_BYTES)
    except (OSError, http.client.HTTPException, ValueError):
        return b""


def _words(error: BaseException) -> str:
    text = str(error) or type(error).__name__
    return text.rstrip(".")


def _connect_words(endpoint: Endpoint, error: BaseException) -> str:
    if isinstance(error, ValueError):
        # Its text can quote a header, credential included: say only that the request was refused.
        return f"The request to {endpoint.url} couldn't be made: a value in it was refused."
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, str):
        return f"Couldn't reach {endpoint.url}: {reason.rstrip('.')}."
    if isinstance(reason, TimeoutError | socket.timeout):
        return f"Connecting to {endpoint.url} timed out."
    if isinstance(reason, ssl.SSLCertVerificationError):
        return (
            f"{endpoint.url}'s TLS certificate couldn't be verified ({_words(reason)}). If it's "
            "signed by an authority this machine's Python doesn't know, set SSL_CERT_FILE or "
            "SSL_CERT_DIR to its certificates."
        )
    return f"Couldn't reach {endpoint.url}: {_words(reason)}."


__all__ = [
    "RESPONSES_PATH",
    "AbortedError",
    "Call",
    "Endpoint",
    "EndpointError",
    "NetworkError",
    "Response",
    "StatusError",
    "is_loopback",
    "parse_endpoint",
]
