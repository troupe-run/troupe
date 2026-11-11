"""A package index on 127.0.0.1 for the install check's network tests (install-check-network-retries
design D5).

It serves one hand-built pure-Python wheel, whose console script prints a line, under uv's simple
index layout. Its project page can be told to answer a status, such as 503 or 404, for its first
requests, and it counts the requests each path receives, so a test can see how often uv asked.
Nothing reaches the network.
"""

import base64
import hashlib
import io
import threading
import zipfile
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJECT = "troupe-index-probe"
"""The project the index serves. Its console script has the same name."""
VERSION = "1.0"
PRINTED = "the probe ran"
"""What the console script prints."""
_MODULE = "troupe_index_probe"
WHEEL = f"{_MODULE}-{VERSION}-py3-none-any.whl"
PAGE = f"/simple/{PROJECT}/"
"""The project's page: the path uv asks first, and the one a test makes fail."""

_SOURCES = {
    f"{_MODULE}/__init__.py": f"def main() -> None:\n    print({PRINTED!r})\n",
    f"{_MODULE}-{VERSION}.dist-info/METADATA": (
        f"Metadata-Version: 2.1\nName: {PROJECT}\nVersion: {VERSION}\n"
    ),
    f"{_MODULE}-{VERSION}.dist-info/WHEEL": (
        "Wheel-Version: 1.0\nGenerator: local_index\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    ),
    f"{_MODULE}-{VERSION}.dist-info/entry_points.txt": (
        f"[console_scripts]\n{PROJECT} = {_MODULE}:main\n"
    ),
}


def _digest(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def wheel() -> bytes:
    """The wheel's bytes, with a RECORD of every file in it."""
    buffer = io.BytesIO()
    record = f"{_MODULE}-{VERSION}.dist-info/RECORD"
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        lines = []
        for name, text in _SOURCES.items():
            data = text.encode()
            archive.writestr(name, data)
            lines.append(f"{name},sha256={_digest(data)},{len(data)}")
        lines.append(f"{record},,")
        archive.writestr(record, "\n".join(lines) + "\n")
    return buffer.getvalue()


@dataclass
class Index:
    """The running index: its URL, what its page answers first, and the requests it received."""

    url: str
    failures: list[int] = field(default_factory=list)
    """Statuses the project's page answers, one per request, before it serves the page. A status
    left here when a test ends was never asked for."""
    always: int | None = None
    """A status the project's page answers to every request, when set."""
    requests: Counter[str] = field(default_factory=Counter)
    """Requests by path; a HEAD request's path is prefixed `HEAD `. Only a GET of the project's
    page is answered from `failures` or `always`."""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def answer(self, path: str) -> int | None:
        """Count a request, and say what status it gets instead of the page, if any."""
        with self._lock:
            self.requests[path] += 1
            if path != PAGE:
                return None
            if self.always is not None:
                return self.always
            return self.failures.pop(0) if self.failures else None


@contextmanager
def serving(failures: Sequence[int] = (), always: int | None = None) -> Iterator[Index]:
    """An index on 127.0.0.1 on a free port, stopped afterwards. Its project's page answers each of
    `failures` in turn before it serves the page, or `always` to every request."""
    data = wheel()
    page = (
        f'<!DOCTYPE html><html><body><a href="/files/{WHEEL}#sha256='
        f'{hashlib.sha256(data).hexdigest()}">{WHEEL}</a></body></html>'
    ).encode()
    index: Index

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._respond(body=True)

        def do_HEAD(self) -> None:
            """uv asks for a wheel's headers before it downloads it."""
            self._respond(body=False)

        def _respond(self, body: bool) -> None:
            path = self.path.split("?", 1)[0]
            status = index.answer(path if body else f"HEAD {path}")
            if status is not None:
                self._send(status, "text/plain", b"not now\n", body)
            elif path == PAGE:
                self._send(200, "text/html", page, body)
            elif path == f"/files/{WHEEL}":
                self._send(200, "application/octet-stream", data, body)
            else:
                self._send(404, "text/plain", b"not here\n", body)

        def _send(self, status: int, kind: str, content: bytes, body: bool) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            if body:
                self.wfile.write(content)

        def log_message(self, format: str, *args: object) -> None:
            """Quiet: the requests are counted instead."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address[:2]
    index = Index(url=f"http://{host!s}:{port}/simple", failures=list(failures), always=always)
    thread = threading.Thread(target=server.serve_forever, name="local-index", daemon=True)
    thread.start()
    try:
        yield index
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
