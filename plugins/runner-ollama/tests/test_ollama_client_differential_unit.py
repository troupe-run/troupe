"""Closing the Ollama client shuts down the socket that TLS moved a connection onto, not only the
first one, checked with local socket pairs standing in for the connection (ollama-library design
D4, D8).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_ollama_client_differential.py."""

import socket
import ssl
from typing import Any

import httpcore2

from troupe_runner_ollama.client import (
    _RecordedStream,
    _Sockets,
)


class _PlainStream(httpcore2.NetworkStream):
    """A stream over one socket, standing in for httpcore2's own after its TLS handshake."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    def get_extra_info(self, info: str) -> Any:  # noqa: ANN401
        return self.sock if info == "socket" else None


class _Upgrading(_PlainStream):
    """A connection whose TLS handshake gives a stream on another socket, as wrap_socket does."""

    def __init__(self, sock: socket.socket, upgraded: socket.socket) -> None:
        super().__init__(sock)
        self.upgraded = upgraded

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore2.NetworkStream:
        return _PlainStream(self.upgraded)


def test_close_shuts_down_the_socket_tls_wraps_a_connection_in() -> None:
    # TLS hands the connection to a new socket; close has to shut that one, not only the first.
    sockets = _Sockets()
    plain, plain_peer = socket.socketpair()
    upgraded, upgraded_peer = socket.socketpair()
    with plain, plain_peer, upgraded, upgraded_peer:
        sockets.add(plain)
        stream = _RecordedStream(_Upgrading(plain, upgraded), sockets)
        stream.start_tls(ssl.create_default_context(), "ollama.example")
        sockets.close()
        upgraded_peer.settimeout(5)
        assert upgraded_peer.recv(1) == b""  # the peer sees the upgraded socket shut down
