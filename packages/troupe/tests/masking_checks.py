"""Checks that a masked string holds no form of the credential, for the masking and run host
tests (host-robustness design D2)."""

import json

from troupe.core.masking import MARKER, Masker


def writings(text: str) -> list[bytes]:
    """The texts troupe can write for ``text``: as it is, and as JSON with non-ASCII kept and
    escaped."""
    return [
        text.encode("utf-8"),
        json.dumps(text, ensure_ascii=False)[1:-1].encode("utf-8"),
        json.dumps(text)[1:-1].encode("ascii"),
    ]


def forms_outside_the_marker(masker: Masker, writing: bytes) -> list[bytes]:
    """Each form of the credential in ``writing`` that isn't wholly inside a run of markers."""
    marker = MARKER.encode()
    inside: set[int] = set()
    at = writing.find(marker)
    while at != -1:
        inside.update(range(at, at + len(marker)))
        at = writing.find(marker, at + 1)
    found = []
    for form in masker.forms:
        at = writing.find(form)
        while at != -1:
            if not set(range(at, at + len(form))) <= inside:
                found.append(form)
            at = writing.find(form, at + 1)
    return found
