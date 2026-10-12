"""The store across processes (spec: event-store, "Versions are unique within a stream" and
"Writers wait for each other, bounded and announced"; design D10)."""

import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

from eventsourcing.persistence import Notification

from gitrepo import make_repo
from storetesting import event
from troupe.core.files import directory_lock
from troupe.core.vcs import load_vcs
from troupe_store_text import TextApplicationRecorder, open_store
from troupe_store_text.store import shared_store
from troupe_vcs_git import GitAdapter

CHILD = """
import sys, time
from pathlib import Path
from uuid import UUID
sys.path.insert(0, {tests!r})
from eventsourcing.persistence import IntegrityError
from storetesting import event
from troupe.core.errors import TroupeError
from troupe.core.vcs import load_vcs
from troupe_store_text.store import TextStore

theatre = Path({theatre!r})
go = Path({go!r})
while not go.exists():
    time.sleep(0.005)
store = TextStore(
    theatre,
    load_vcs("files", theatre),
    lock_timeout={timeout},
    lock_announce_after=0.1,
    on_wait=lambda path, waited: print("waiting", path, flush=True),
)
try:
    store.insert([event(UUID({stream!r}), {version}, by={who!r})])
except IntegrityError:
    print("integrity-error", flush=True)
except TroupeError as error:
    print(error.code, flush=True)
else:
    print("recorded", flush=True)
"""

TESTS = str(Path(__file__).resolve().parents[2] / "troupe" / "tests")


def child(
    theatre: Path,
    go: Path,
    stream: str,
    *,
    version: int = 1,
    timeout: float = 30.0,
    who: str = "child",
) -> subprocess.Popen[str]:
    code = CHILD.format(
        tests=TESTS,
        theatre=str(theatre),
        go=str(go),
        stream=stream,
        version=version,
        timeout=timeout,
        who=who,
    )
    return subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def test_two_processes_racing_for_one_version_give_exactly_one_integrity_error(
    tmp_path: Path,
) -> None:
    stream = str(uuid4())
    go = tmp_path / "go"
    racers = [child(tmp_path, go, stream, who=f"racer-{i}") for i in range(2)]
    time.sleep(0.5)
    go.touch()
    outcomes = sorted(racer.communicate(timeout=60)[0].strip() for racer in racers)
    assert outcomes == ["integrity-error", "recorded"]
    store = open_store(tmp_path, load_vcs("files", tmp_path))
    assert len(store.history(UUID(stream))) == 1


def test_a_writer_waiting_for_another_process_announces_it_and_times_out(
    tmp_path: Path,
) -> None:
    local = tmp_path / ".troupe" / "local"
    local.mkdir(parents=True)
    go = tmp_path / "go"
    go.touch()
    with directory_lock(local):
        waiting = child(tmp_path, go, str(uuid4()), timeout=1.0)
        out, err = waiting.communicate(timeout=60)
    assert "waiting" in out, err
    assert out.strip().endswith("lock.timeout"), err


def test_another_processs_write_wakes_this_processs_subscription(tmp_path: Path) -> None:
    store = shared_store(tmp_path, lambda: load_vcs("files", tmp_path), poll_seconds=0.05)
    recorder = TextApplicationRecorder(store)
    received: list[Notification] = []
    with recorder.subscribe(gt=0) as subscription:

        def first() -> None:
            received.append(next(subscription))

        reader = threading.Thread(target=first, daemon=True)
        reader.start()
        go = tmp_path / "go"
        go.touch()
        writer = child(tmp_path, go, str(uuid4()))
        assert writer.communicate(timeout=60)[0].strip() == "recorded"
        reader.join(timeout=10)
        subscription.stop()
    assert [n.id for n in received] == [1]


def test_recording_in_a_git_theatre_leaves_no_lock_or_local_file_for_git_to_see(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    store = open_store(repo.path, GitAdapter(repo.path, source=repo.env))
    store.insert([event(uuid4(), 1)])
    status = repo.git("status", "--porcelain", "--untracked-files=all", "--ignored=no")
    paths = {line[3:] for line in status.splitlines()}
    assert ".troupe/.gitignore" in paths
    assert any(p.startswith(".troupe/events/") and p.endswith(".jsonl") for p in paths)
    assert not any("local" in p or p.endswith(".lock") for p in paths)
