"""The eventsourcing library's own recorder test suite, run unmodified against the text store
(spec: event-store, "The store meets the library's recorder contract").

Nothing is skipped and nothing is replaced. Each test case gets a new theatre in a temporary
directory, with the plain filesystem VCS adapter (the git adapter's cases are in test_store_git.py).
"""

import tempfile
from pathlib import Path

from eventsourcing.persistence import InfrastructureFactory
from eventsourcing.tests.persistence import (
    AggregateRecorderTestCase,
    ApplicationRecorderTestCase,
    InfrastructureFactoryTestCase,
    NonInterleavingNotificationIDsBaseCase,
    ProcessRecorderTestCase,
    TrackingRecorderTestCase,
)
from eventsourcing.utils import Environment

from troupe.core.vcs import load_vcs
from troupe_store_text import (
    TextAggregateRecorder,
    TextApplicationRecorder,
    TextFactory,
    TextProcessRecorder,
    TextTrackingRecorder,
    open_store,
)
from troupe_store_text.store import TextStore


class _Theatre:
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)  # type: ignore[attr-defined]
        super().setUp()  # type: ignore[misc]

    def store(self) -> TextStore:
        theatre = Path(self._directory.name)
        return open_store(theatre, load_vcs("files", theatre))


class TestAggregateRecorder(_Theatre, AggregateRecorderTestCase):
    def create_recorder(self) -> TextAggregateRecorder:
        return TextAggregateRecorder(self.store())


class TestApplicationRecorder(_Theatre, ApplicationRecorderTestCase[TextApplicationRecorder]):
    def create_recorder(self) -> TextApplicationRecorder:
        return TextApplicationRecorder(self.store())

    def test_insert_subscribe(self) -> None:
        """Opt in to the library's subscription case, which isn't collected by default."""
        self.optional_test_insert_subscribe()


class TestNonInterleaving(_Theatre, NonInterleavingNotificationIDsBaseCase):
    def create_recorder(self) -> TextApplicationRecorder:
        return TextApplicationRecorder(self.store())


class TestTrackingRecorder(_Theatre, TrackingRecorderTestCase):
    def create_recorder(self) -> TextTrackingRecorder:
        return TextTrackingRecorder(self.store())


class TestProcessRecorder(_Theatre, ProcessRecorderTestCase):
    def create_recorder(self) -> TextProcessRecorder:
        return TextProcessRecorder(self.store())


class _CustomTrackingRecorder(TextTrackingRecorder):
    pass


class TestFactory(InfrastructureFactoryTestCase[TextFactory]):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.env = Environment("TestCase")
        self.env[InfrastructureFactory.PERSISTENCE_MODULE] = "troupe_store_text"
        self.env[TextFactory.THEATRE] = self._directory.name
        super().setUp()

    def expected_factory_class(self) -> type[TextFactory]:
        return TextFactory

    def expected_aggregate_recorder_class(self) -> type[TextAggregateRecorder]:
        return TextAggregateRecorder

    def expected_application_recorder_class(self) -> type[TextApplicationRecorder]:
        return TextApplicationRecorder

    def expected_tracking_recorder_class(self) -> type[TextTrackingRecorder]:
        return TextTrackingRecorder

    def tracking_recorder_subclass(self) -> type[TextTrackingRecorder]:
        return _CustomTrackingRecorder

    def expected_process_recorder_class(self) -> type[TextProcessRecorder]:
        return TextProcessRecorder


del AggregateRecorderTestCase
del ApplicationRecorderTestCase
del NonInterleavingNotificationIDsBaseCase
del TrackingRecorderTestCase
del ProcessRecorderTestCase
del InfrastructureFactoryTestCase
