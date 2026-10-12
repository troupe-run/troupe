"""Reading segments incrementally (spec: event-store; design D4).

A segment is ``events/<session>.jsonl``: a header line, then batches of event lines. A segment is
only ever appended to, so a reader keeps its place and reads only the bytes it hasn't seen. A batch
is visible only when all of its lines are present: a write that was interrupted leaves at most an
incomplete batch at the end of a segment, which is left out. Anything malformed elsewhere is an
error naming the file and line.
"""

from dataclasses import dataclass, field
from pathlib import Path

from troupe_store_text.codec import Header, Record, decode, malformed


@dataclass
class Segment:
    """What has been read of one segment file so far."""

    path: Path
    header: Header | None = None
    records: list[Record] = field(default_factory=list)
    """Every event in a complete batch, in file order."""
    offset: int = 0
    """Bytes consumed: the end of the last complete line."""
    lines: int = 0
    """Complete lines consumed."""
    open_batch: list[Record] = field(default_factory=list)
    """The lines of a batch whose remaining lines haven't been read (yet)."""
    partial: bool = False
    """Whether bytes follow the last complete line: a line still being written, or torn."""

    @property
    def session(self) -> str:
        return self.path.stem

    @property
    def incomplete(self) -> bool:
        """Whether the segment ends in a batch that isn't (yet) whole."""
        return bool(self.open_batch) or self.partial

    def read_more(self, size: int) -> list[Record]:
        """Read what was appended since the last read, up to ``size`` bytes; return the events of
        batches completed by it."""
        with self.path.open("rb") as handle:
            handle.seek(self.offset)
            data = handle.read(max(size - self.offset, 0))
        end = data.rfind(b"\n") + 1
        self.partial = end < len(data)
        added: list[Record] = []
        start = 0
        while start < end:
            stop = data.index(b"\n", start) + 1
            self.lines += 1
            added.extend(self._take(data[start:stop]))
            start = stop
        self.offset += end
        return added

    def _take(self, raw: bytes) -> list[Record]:
        decoded = decode(raw, self.path, self.lines)
        if isinstance(decoded, Header):
            if self.lines != 1:
                raise malformed(self.path, self.lines, "a header can only be the first line")
            self.header = decoded
            return []
        if self.header is None:
            raise malformed(self.path, self.lines, "a segment must start with its header")
        if self.open_batch and decoded.batch_id != self.open_batch[0].batch_id:
            first = self.open_batch[0]
            raise malformed(
                first.path,
                first.line,
                f"batch {first.batch_id} has {len(self.open_batch)} of its {first.batch_size} "
                "lines, and another batch follows it, so it isn't an interrupted write at the end",
            )
        expected = len(self.open_batch)
        if decoded.batch_index != expected or (
            self.open_batch and decoded.batch_size != self.open_batch[0].batch_size
        ):
            raise malformed(
                self.path,
                self.lines,
                f"expected line {expected} of batch {decoded.batch_id}, found line "
                f"{decoded.batch_index} of {decoded.batch_size}",
            )
        self.open_batch.append(decoded)
        if len(self.open_batch) < decoded.batch_size:
            return []
        complete, self.open_batch = self.open_batch, []
        self.records.extend(complete)
        return complete
