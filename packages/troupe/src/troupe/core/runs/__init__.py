"""Runs: recording a run of an actor, and reading runs back (spec: runs; perform-status-logs
design D8 to D13)."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from troupe.core.client.dispatch import Method


def methods() -> "Mapping[str, Method]":
    """The commands and queries runs offer through the client protocol, by name."""
    return {}
