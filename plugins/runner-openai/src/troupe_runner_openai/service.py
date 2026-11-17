"""The one module that uses the openai package: talking to a Responses API service (openai-library
design D1-D4a).

Everything the library would decide for itself, the runner decides here instead:

- **Its HTTP client** is the runner's own ``httpx2.Client``: it follows no redirect (the library's
  own client follows them), its timeouts are the runner's named settings (the library's default is
  ten minutes), and its transport counts each line of a response as it arrives, refusing one past
  STREAM_LINE_MAX_BYTES before more is buffered (design D4a). It asks for no compression, and
  refuses a response sent encoded anyway, whose decoded lines the transport couldn't count. Proxies
  and certificates are read as urllib reads them: ``HTTPS_PROXY`` and ``NO_PROXY`` through the
  standard library, no proxy for an endpoint on this machine, and the platform's trust store or
  ``SSL_CERT_FILE``/``SSL_CERT_DIR``.
- **Its retries** are off (``max_retries=0``): the runner retries in its own loop (exchange.py).
- **Its credential** is the runtime's, given explicitly, or none: with none, the library gets a
  placeholder it never sends, since every request omits ``Authorization`` (design D2).
- **Its headers.** Each request leaves with only the headers it needs (SENT_HEADERS) and the
  runner's own User-Agent: the library's telemetry headers never reach the service.
- **Its environment.** The library reads ``OPENAI_*`` variables for whatever it isn't given, so
  the runner removes every one from its own environment before it builds the client (library.py).

The rest of the runner sees plain data: a request's parameters as a dict, each stream event as the
library parsed it (``to_dict``), and one of a closed set of failures (failures.py). Which endpoints
are safe to send a credential to is decided here too, beside how they're reached.
"""

import contextlib
import ipaddress
import json
import re
import ssl
import urllib.parse
import urllib.request
import zlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx2
import openai

from troupe_runner_openai import NAME, __version__
from troupe_runner_openai.defaults import (
    CONNECT_TIMEOUT_SECONDS,
    ERROR_BODY_MAX_BYTES,
    STREAM_LINE_MAX_BYTES,
    STREAM_TIMEOUT_SECONDS,
    WRITE_TIMEOUT_SECONDS,
)
from troupe_runner_openai.failures import (
    NetworkError,
    NotAStreamError,
    Opened,
    ServiceError,
    StatusError,
    UnreadableError,
)
from troupe_runner_openai.library import clear_library_environment

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


# The line cap, beneath the library (design D4a)

_LINE_END: Final = re.compile(rb"[\r\n]")


class LineTooLongError(httpx2.ReadError):
    """A line of a response's body ran past the runner's cap. The library reports it as a broken
    connection, which the runner retries as a network failure."""


class _CappedStream(httpx2.SyncByteStream):
    """A response's body, read through as it arrives, with the bytes since the last line ending
    counted, so a line past ``limit`` is refused as soon as it is."""

    def __init__(self, inner: httpx2.SyncByteStream, limit: int) -> None:
        self._inner = inner
        self._limit = limit
        self._run = 0
        """Bytes since the last line ending."""

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._inner:
            self._count(chunk)
            yield chunk

    def _count(self, chunk: bytes) -> None:
        start = 0
        for end in _LINE_END.finditer(chunk):
            self._check(self._run + end.start() - start)
            self._run, start = 0, end.end()
        self._run += len(chunk) - start
        self._check(self._run)

    def _check(self, length: int) -> None:
        if length > self._limit:
            raise LineTooLongError(
                f"A line of the response is longer than {self._limit} bytes, the runner's limit "
                "(STREAM_LINE_MAX_BYTES)."
            )

    def close(self) -> None:
        self._inner.close()


class EncodedResponseError(httpx2.ReadError):
    """A response sent with a Content-Encoding, though the runner asked for none. Its decoded
    lines can't be counted beneath the client, which decodes above the transport, so it's refused
    before its body is read. The library reports it as a broken connection, which the runner retries
    as a network failure."""


class _TruncatedStream(httpx2.SyncByteStream):
    """A response's body, read through until ``limit`` bytes, then ended: the rest is never
    read. For a body the runner reads whole (an error, or a 2xx that isn't a stream), which a line
    cap alone doesn't bound (review of #440)."""

    def __init__(self, inner: httpx2.SyncByteStream, limit: int) -> None:
        self._inner = inner
        self._limit = limit

    def __iter__(self) -> Iterator[bytes]:
        left = self._limit
        try:
            for chunk in self._inner:
                if len(chunk) >= left:
                    if left:
                        yield chunk[:left]
                    return
                left -= len(chunk)
                yield chunk
        finally:
            self._inner.close()

    def close(self) -> None:
        self._inner.close()


def _read_whole(response: httpx2.Response) -> bool:
    """Whether the runner reads ``response``'s body whole: an error, or a 2xx whose Content-Type
    is present and isn't a stream. Every other body is a stream, read line by line."""
    if not 200 <= response.status_code < 300:
        return True
    said = response.headers.get("content-type")
    return said is not None and said.partition(";")[0].strip().lower() != STREAM_TYPE


SENT_HEADERS: Final = frozenset(
    {
        "accept",
        "accept-encoding",
        "authorization",
        "connection",
        "content-length",
        "content-type",
        "host",
        "transfer-encoding",
        "user-agent",
    }
)
"""The only request headers the runner sends, by lower-case name: what the request needs. Every
other header the library or its client adds (its X-Stainless-* telemetry, naming the OS, CPU,
Python and package versions, and any it adds later) is removed before the request leaves (owner,
2026-11-18; openai-library design D3)."""

USER_AGENT: Final = f"troupe-runner-{NAME}/{__version__}"
"""The User-Agent each request carries, in place of the library's: the runner and its version, as
before the library."""


def _only_needed_headers(request: httpx2.Request) -> None:
    """Strip ``request`` to SENT_HEADERS, with the runner's own User-Agent."""
    for name in [name for name in request.headers if name.lower() not in SENT_HEADERS]:
        del request.headers[name]
    request.headers["User-Agent"] = USER_AGENT


class _CappedTransport(httpx2.BaseTransport):
    """A transport whose every streamed response's body goes through _CappedStream, whose every
    body read whole stops at ``body_limit`` bytes, and which refuses a successful response sent
    encoded: the cap counts the bytes as they arrive, which for an encoded body aren't the bytes
    the library's decoder buffers (review of #440)."""

    def __init__(self, inner: httpx2.BaseTransport, limit: int, body_limit: int) -> None:
        self._inner = inner
        self._limit = limit
        self._body_limit = body_limit

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        _only_needed_headers(request)
        response = self._inner.handle_request(request)
        encoding = response.headers.get("content-encoding", "").strip().lower()
        if encoding not in ("", "identity"):
            if not 200 <= response.status_code < 300:
                # An error's status still counts: its body is read raw, bounded, and decoded only
                # within that bound, so the run ends for the service's own reason (review of #440).
                return _bounded_error(response, encoding, request, self._body_limit)
            response.close()
            raise EncodedResponseError(
                f"The service sent its response encoded ({_cut_header(encoding)}), though the "
                "runner asks for none (Accept-Encoding: identity), so its lines can't be held to "
                "the runner's limit (STREAM_LINE_MAX_BYTES).",
                request=request,
            )
        assert isinstance(response.stream, httpx2.SyncByteStream)  # noqa: S101 - a sync client's
        if _read_whole(response):
            response.stream = _TruncatedStream(response.stream, self._body_limit)
        else:
            response.stream = _CappedStream(response.stream, self._limit)
        return response

    def close(self) -> None:
        self._inner.close()


_ZLIB_WINDOWS: Final = {"gzip": 47, "x-gzip": 47, "deflate": 15}
"""zlib's window bits for each encoding it can decode: 47 reads a gzip or zlib header, 15 zlib."""


def _bounded_error(
    response: httpx2.Response, encoding: str, request: httpx2.Request, limit: int
) -> httpx2.Response:
    """A non-2xx sent encoded, as a plain response: at most ``limit`` bytes read from the wire,
    decoded into at most as many bytes where zlib can, and kept as sent where it can't."""
    raw = bytearray()
    assert isinstance(response.stream, httpx2.SyncByteStream)  # noqa: S101 - a sync client's
    try:
        for chunk in response.stream:
            raw += chunk
            if len(raw) >= limit:
                break
    finally:
        response.close()
    body = bytes(raw[:limit])
    window = _ZLIB_WINDOWS.get(encoding)
    if window is not None:
        # Kept as sent when it won't decode: the status still says what happened.
        with contextlib.suppress(zlib.error):
            body = zlib.decompressobj(window).decompress(body, limit)
    headers = [(k, v) for k, v in response.headers.items() if k.lower() != "content-encoding"]
    return httpx2.Response(
        response.status_code,
        headers=headers,
        content=body,
        request=request,
        extensions=response.extensions,
    )


def _cut_header(value: str, limit: int = 100) -> str:
    return value if len(value) <= limit else f"{value[:limit]}…"


def proxy_for(endpoint: Endpoint) -> str | None:
    """The proxy a request to ``endpoint`` goes through, as urllib chooses it: none for this
    machine or a host NO_PROXY names, else the scheme's from HTTPS_PROXY or HTTP_PROXY."""
    if endpoint.is_loopback or urllib.request.proxy_bypass(endpoint.host):
        return None
    return urllib.request.getproxies().get(endpoint.scheme)


# The client

NO_CREDENTIAL: Final = "no-credential"
"""What the library is given as its key for a runtime with no credential: it won't build a client
without one. Never sent: every such request omits Authorization (design D2)."""

STREAM_TYPE: Final = "text/event-stream"
"""The media type a streamed response is sent as, which the runner asks for."""


class Service:
    """One run's connection to its service."""

    def __init__(
        self,
        endpoint: Endpoint,
        credential: str | None,
        *,
        connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
        stream_timeout: float = STREAM_TIMEOUT_SECONDS,
        write_timeout: float = WRITE_TIMEOUT_SECONDS,
        line_max_bytes: int = STREAM_LINE_MAX_BYTES,
        body_max_bytes: int = ERROR_BODY_MAX_BYTES,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        """``transport`` stands in for the network beneath the line cap, for tests; by default
        it's an HTTP transport with urllib's proxy and the platform's certificates."""
        clear_library_environment()
        self.endpoint = endpoint
        self.stream_timeout = stream_timeout
        timeout = httpx2.Timeout(
            connect=connect_timeout, read=stream_timeout, write=write_timeout, pool=connect_timeout
        )
        if transport is None:
            transport = httpx2.HTTPTransport(
                verify=ssl.create_default_context(), trust_env=False, proxy=proxy_for(endpoint)
            )
        self._http = httpx2.Client(
            transport=_CappedTransport(transport, line_max_bytes, body_max_bytes),
            # No compression, as urllib asked for none: the line cap counts bytes as they
            # arrive, so they must be the bytes the library reads (review of #440).
            headers={"Accept-Encoding": "identity"},
            trust_env=False,
            follow_redirects=False,
            timeout=timeout,
        )
        self._client = openai.OpenAI(
            api_key=credential or NO_CREDENTIAL,
            base_url=endpoint.url,
            max_retries=0,
            timeout=timeout,
            http_client=self._http,
        )
        self._headers: dict[str, Any] = {} if credential else {"Authorization": openai.Omit()}

    def close(self) -> None:
        self._http.close()

    def stream(self, params: Mapping[str, Any]) -> Opened:
        """Send one request, streamed, and return its response once its status is in. Raises
        StatusError, NotAStreamError or NetworkError; the events it yields raise NetworkError for a
        stream that breaks and UnreadableError for an event whose data isn't JSON."""
        try:
            stream = self._client.responses.create(**params, extra_headers=self._headers)
        except openai.APIStatusError as error:
            raise StatusError(
                error.status_code, error.response.headers, _body(error.response)
            ) from None
        except (openai.APIConnectionError, httpx2.HTTPError) as error:
            raise NetworkError(self._said(error)) from None
        response = stream.response
        headers = {name.lower(): value for name, value in response.headers.items()}
        said = headers.get("content-type")
        if said is not None and said.partition(";")[0].strip().lower() != STREAM_TYPE:
            broke = None
            try:
                body = _body(response)
            except (httpx2.HTTPError, openai.APIError) as error:
                body, broke = b"", self._said(error)
            finally:
                stream.close()
            raise NotAStreamError(response.status_code, headers, said, body, broke)
        return Opened(response.status_code, headers, self._events(stream))

    def _events(self, stream: Any) -> Iterator[Any]:  # noqa: ANN401 - the library's Stream
        """Each event of ``stream`` as a dict, as the service sent it, with the library's failures
        as the runner's (design D4)."""
        try:
            for event in stream:
                # The library validates nothing: a field in a shape its models don't expect is
                # kept as sent, and its serialiser's warning about it isn't wanted (design D9).
                # Data that isn't an object comes as it was sent, for the reader to refuse.
                if isinstance(event, openai.BaseModel):
                    yield event.to_dict(mode="json", warnings=False)
                else:
                    yield event
        except (openai.APIConnectionError, httpx2.HTTPError) as error:
            raise NetworkError(self._said(error)) from None
        except openai.APIError as error:
            # An event whose data has a top-level error: the library raises it rather than
            # yielding it. It's the response's failure, as an error event is.
            body = error.body if isinstance(error.body, dict) else {"message": error.message}
            yield {"type": "error", "error": body}
        except UnicodeDecodeError:
            raise NetworkError("A line of the response's stream isn't UTF-8.") from None
        except json.JSONDecodeError as error:
            raise UnreadableError(
                f"An event in the response's stream isn't JSON: {error.doc[:200]!r}."
            ) from None
        finally:
            stream.close()

    def _said(self, error: BaseException) -> str:
        """A network failure in words a person can act on, from the library's error or its
        cause."""
        url = self.endpoint.url
        cause = _cause(error)
        if isinstance(cause, LineTooLongError | EncodedResponseError):
            return str(cause)
        if isinstance(cause, httpx2.LocalProtocolError):
            # Its text can quote a header, credential included: say only that the request was
            # refused, as the runner always has.
            return f"The request to {url} couldn't be made: a value in it was refused."
        if not isinstance(cause, httpx2.HTTPError):
            # Not the network's: its text isn't known to be safe to repeat, so only its kind is.
            return f"The request to {url} failed ({type(cause).__name__})."
        if isinstance(cause, httpx2.ConnectTimeout | httpx2.PoolTimeout):
            return f"Connecting to {url} timed out."
        if isinstance(cause, httpx2.TimeoutException):
            return f"The service sent nothing for {self.stream_timeout:g} seconds."
        verify = _find(error, ssl.SSLCertVerificationError)
        if verify is not None:
            return (
                f"{url}'s TLS certificate couldn't be verified ({_words(verify)}). If it's signed "
                "by an authority this machine's Python doesn't know, set SSL_CERT_FILE or "
                "SSL_CERT_DIR to its certificates."
            )
        if isinstance(cause, httpx2.ConnectError):
            return f"Couldn't reach {url}: {_words(cause)}."
        return f"The response's stream broke: {_words(cause)}."


def _cause(error: BaseException) -> BaseException:
    """The HTTP client's error under the library's, or ``error`` itself."""
    if isinstance(error, httpx2.HTTPError):
        return error
    inner = error.__cause__ or error.__context__
    return inner if isinstance(inner, httpx2.HTTPError) else error


def _find(error: BaseException, kind: type[ssl.SSLCertVerificationError]) -> BaseException | None:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, kind):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def _body(response: httpx2.Response) -> bytes:
    """A response's body read whole, which the library has read or reads now: at most
    ERROR_BODY_MAX_BYTES, where the transport stopped reading it."""
    return response.read()


def _words(error: BaseException) -> str:
    text = str(error) or type(error).__name__
    return text.rstrip(".")


__all__ = [
    "NO_CREDENTIAL",
    "RESPONSES_PATH",
    "SENT_HEADERS",
    "USER_AGENT",
    "EncodedResponseError",
    "Endpoint",
    "EndpointError",
    "LineTooLongError",
    "NetworkError",
    "NotAStreamError",
    "Opened",
    "Service",
    "ServiceError",
    "StatusError",
    "UnreadableError",
    "is_loopback",
    "parse_endpoint",
    "proxy_for",
]
