"""Random sequences of record, commit, switch, merge and delete-file on a real repository
(spec: event-store, notification ids; design D5, D7).

After every step, on the branch checked out:
- notification ids are dense from 1;
- no id already issued on this branch names a different event, unless the step reported that the
  order was rebuilt;
- every visible event is ordered exactly once;
- git never reports a conflict in .troupe/events/.
"""

import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from gitrepo import Repo, make_repo
from storetesting import event, segments
from troupe.core.errors import TroupeError
from troupe_store_text.store import TextStore
from troupe_vcs_git import GitAdapter

STREAMS = [UUID(int=n) for n in range(1, 4)]
BRANCHES = ["main", "a", "b"]


class Theatre(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.root = Path(tempfile.mkdtemp())
        self.repo: Repo = make_repo(self.root)
        self.counter = 0
        self.issued: dict[str, list[str]] = {}
        self.rebuilt = False
        self.record(
            STREAMS[0]
        )  # writes .troupe/.gitignore and .gitattributes once, for every branch
        self.repo.commit_all("start")
        for branch in BRANCHES[1:]:
            self.repo.git("branch", branch)

    def teardown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def store(self) -> TextStore:
        return TextStore(self.repo.path, GitAdapter(self.repo.path, source=self.repo.env))

    def branch(self) -> str:
        return self.repo.git("symbolic-ref", "--short", "HEAD").strip()

    def record(self, stream: UUID) -> None:
        writer = self.store()
        self.counter += 1
        version = max((r.version for r in writer.history(stream)), default=0) + 1
        try:
            writer.insert([event(stream, version, step=self.counter)])
        except TroupeError as error:
            # A fork from a merge, or a parent deleted with its file: refused, as designed.
            if error.code not in {"events.stream-forked", "events.missing-parent"}:
                raise
        self.rebuilt = self.rebuilt or any(
            n.code == "events.order-rebuilt" for n in writer.notices()
        )

    @rule(stream=st.sampled_from(STREAMS))
    def record_an_event(self, stream: UUID) -> None:
        self.record(stream)

    @rule()
    def commit(self) -> None:
        self.repo.commit_all(f"commit {self.counter}")

    @rule(branch=st.sampled_from(BRANCHES))
    def switch(self, branch: str) -> None:
        self.repo.git("switch", "-q", branch)

    @rule(other=st.sampled_from(BRANCHES))
    def merge(self, other: str) -> None:
        if other != self.branch():
            self.repo.git("merge", "-q", "--no-edit", other)

    @rule(data=st.data())
    def delete_an_uncommitted_segment(self, data: st.DataObject) -> None:
        untracked = self.repo.git("ls-files", "--others", "--", ".troupe/events").split()
        if untracked:
            (self.repo.path / data.draw(st.sampled_from(sorted(untracked)))).unlink()

    @invariant()
    def the_order_holds(self) -> None:
        # Each value is read once per step: every read runs git, and a second read of the same
        # repository sees the same answer (shorten-slow-tests design D2).
        reader = self.store()
        branch = self.branch()
        listed = list(reader.notifications(1, 100_000, None, ()))
        ids = [r.id for _, r in listed]
        numbers = [n for n, _ in listed]
        rebuilt = self.rebuilt or any(n.code == "events.order-rebuilt" for n in reader.notices())
        self.rebuilt = False
        assert numbers == list(range(1, len(ids) + 1))
        assert len(set(ids)) == len(ids)
        visible = {r.id for stream in STREAMS for r in reader.history(stream)}
        assert set(ids) == visible
        before = self.issued.get(branch, [])
        if not rebuilt:
            assert ids[: len(before)] == before
        self.issued[branch] = ids
        assert self.repo.git("diff", "--name-only", "--diff-filter=U", "--", ".troupe") == ""
        assert all(path.suffix == ".jsonl" for path in segments(self.repo.path))


# The longest test in the suite (about 20 s locally), and it can't get much shorter as it is: almost
# all of it is git, run by every rule and by the store's refresh on each read the invariant needs.
# Fewer examples or steps would trade away coverage, which needs a reason of its own (#84).
Theatre.TestCase.settings = settings(
    max_examples=8,
    stateful_step_count=12,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
TestTheatre = Theatre.TestCase
