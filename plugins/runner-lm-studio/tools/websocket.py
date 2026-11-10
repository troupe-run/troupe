"""A small websocket server and client, standard library only, for the LM Studio runner's capture
tool and its fake LM Studio (lmstudio-runner design D12, D14).

Enough of RFC 6455 for LM Studio's library: the opening handshake, text and close frames, ping and
pong, and payloads of any length. No extensions, no fragmentation on send, and fragments reassembled
on receive. A connection reads and writes whole messages.
"""

import base64
import contextlib
import hashlib
import os
import socket
import struct
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
"""RFC 6455's key suffix."""

TEXT, BINARY, CLOSE, PING, PONG, CONTINUATION = 0x1, 0x2, 0x8, 0x9, 0xA, 0x0


class Closed(Exception):  # noqa: N818 - a state, not an error
    """The other side closed the connection, or it was lost."""


def accept_key(key: str) -> str:
    """The Sec-WebSocket-Accept for a client's Sec-WebSocket-Key."""
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()  # noqa: S324


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks = []
    while size:
        chunk = sock.recv(size)
        if not chunk:
            raise Closed("the connection closed")
        chunks.append(chunk)
        size -= len(chunk)
    return b"".join(chunks)


def read_head(sock: socket.socket) -> tuple[str, dict[str, str], bytes]:
    """An HTTP request or response's first line and headers (names in lower case), and any bytes
    read past them."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise Closed("the connection closed before its headers ended")
        data += chunk
    head, rest = data.split(b"\r\n\r\n", 1)
    lines = head.decode("latin-1").split("\r\n")
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return lines[0], headers, rest


@dataclass
class Connection:
    """One websocket connection. ``masked`` is true on a client's side, which must mask."""

    sock: socket.socket
    masked: bool
    pending: bytes = b""
    _send_lock: threading.Lock = field(default_factory=threading.Lock)

    def _read(self, size: int) -> bytes:
        if self.pending:
            taken, self.pending = self.pending[:size], self.pending[size:]
            if len(taken) == size:
                return taken
            return taken + _read_exact(self.sock, size - len(taken))
        return _read_exact(self.sock, size)

    def _frame(self) -> tuple[bool, int, bytes]:
        first, second = self._read(2)
        fin, opcode = bool(first & 0x80), first & 0x0F
        length = second & 0x7F
        if length == 126:
            (length,) = struct.unpack("!H", self._read(2))
        elif length == 127:
            (length,) = struct.unpack("!Q", self._read(8))
        mask = self._read(4) if second & 0x80 else None
        payload = self._read(length)
        if mask is not None:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    def receive(self) -> str:
        """The next text message. Answers pings; Closed when the other side closes."""
        parts: list[bytes] = []
        while True:
            fin, opcode, payload = self._frame()
            if opcode == CLOSE:
                with contextlib.suppress(OSError):
                    self._send(CLOSE, payload[:2])
                raise Closed("the other side closed the websocket")
            if opcode == PING:
                self._send(PONG, payload)
                continue
            if opcode == PONG:
                continue
            parts.append(payload)
            if fin:
                return b"".join(parts).decode("utf-8")

    def _send(self, opcode: int, payload: bytes) -> None:
        head = bytes([0x80 | opcode])
        mask_bit = 0x80 if self.masked else 0
        length = len(payload)
        if length < 126:
            head += bytes([mask_bit | length])
        elif length < 1 << 16:
            head += bytes([mask_bit | 126]) + struct.pack("!H", length)
        else:
            head += bytes([mask_bit | 127]) + struct.pack("!Q", length)
        if self.masked:
            mask = os.urandom(4)
            head += mask
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._send_lock:
            self.sock.sendall(head + payload)

    def send(self, text: str) -> None:
        self._send(TEXT, text.encode("utf-8"))

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._send(CLOSE, struct.pack("!H", 1000))
        with contextlib.suppress(OSError):
            self.sock.close()


def server_handshake(sock: socket.socket, headers: dict[str, str], rest: bytes) -> Connection:
    """Answer a client's opening handshake, already read, and the connection."""
    key = headers["sec-websocket-key"]
    sock.sendall(
        (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key(key)}\r\n\r\n"
        ).encode()
    )
    return Connection(sock, masked=False, pending=rest)


def connect(host: str, port: int, path: str, timeout: float = 10.0) -> Connection:
    """A client connection to ws://host:port/path."""
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(None)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    status, headers, rest = read_head(sock)
    if " 101 " not in f"{status} " or headers.get("sec-websocket-accept") != accept_key(key):
        sock.close()
        raise Closed(f"the server refused the websocket: {status}")
    return Connection(sock, masked=True, pending=rest)


Handler = Callable[[socket.socket, str, dict[str, str], bytes], None]
"""Takes an accepted socket, its request line, headers and any bytes read past them."""


class Server:
    """A threaded TCP server on 127.0.0.1 that hands each connection's request to ``handler``."""

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self._sock = socket.create_server(("127.0.0.1", 0))
        self.port: int = self._sock.getsockname()[1]
        self._open: set[socket.socket] = set()
        self._lock = threading.Lock()
        self._stopped = False
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> "Server":
        self._thread.start()
        return self

    def _serve(self) -> None:
        while not self._stopped:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with self._lock:
                self._open.add(conn)
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn: socket.socket) -> None:
        try:
            request, headers, rest = read_head(conn)
            self._handler(conn, request, headers, rest)
        except (Closed, OSError):
            pass
        finally:
            with self._lock:
                self._open.discard(conn)
            with contextlib.suppress(OSError):
                conn.close()

    def close_connections(self) -> None:
        """Drop every open connection, as a server that went away would."""
        with self._lock:
            open_ = list(self._open)
        for conn in open_:
            with contextlib.suppress(OSError):
                conn.shutdown(socket.SHUT_RDWR)
                conn.close()

    def stop(self) -> None:
        self._stopped = True
        with contextlib.suppress(OSError):
            self._sock.close()
        self.close_connections()


def http_answer(sock: socket.socket, status: str, body: bytes, extra: str = "") -> None:
    """Answer a plain HTTP request and close."""
    sock.sendall(
        (
            f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n{extra}\r\n"
        ).encode()
        + body
    )


__all__ = [
    "Closed",
    "Connection",
    "Server",
    "accept_key",
    "connect",
    "http_answer",
    "read_head",
    "server_handshake",
]
