"""Helpers that test_perform_failed_audit.py shares with other test modules."""

from runtesting import Harness
from troupe_plugin_sdk.messages import Message


class RemovesThenCancels(Harness):
    """A person who removes README.md from the theatre once the run's first event arrives, then
    cancels the run."""

    done: bool = False

    def send(self, update: Message) -> None:
        super().send(update)
        if not self.done and update.to_data().get("kind") == "event":
            (self.repo.path / "README.md").unlink()
            self.cancel.request()
            self.done = True
