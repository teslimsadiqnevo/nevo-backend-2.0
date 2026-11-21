"""Background work must not be allowed to starve the API's event loop.

19 November: the API went from 1.5s to 16s, and /openapi.json - which
touches no database at all - stalled for over 90 seconds. We serve from a
single uvicorn process, so there is one event loop, and fourteen poll loops
were sharing it and the connection pool with real traffic, each query
crossing the Atlantic to Frankfurt.

Two things are pinned here. First, the machinery that can move the loops to
a dyno of their own, including its default: it stays "web" on purpose,
because a worker dyno has not been bought and defaulting the other way would
silently stop every email, upload parse and post-lesson profile. Second, the
mitigation that is actually running today - fewer loops, polling far less
often - because those numbers are the fix, and a later tidy-up that "just"
restores a five-second poll would quietly undo it.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest

from nevo.content_parsing.deferred_media import DeferredMediaWorker
from nevo.core.config import Settings


def _settings(
    monkeypatch: pytest.MonkeyPatch, dyno: str | None, owner: str | None = None
) -> Settings:
    if dyno is None:
        monkeypatch.delenv("DYNO", raising=False)
    else:
        monkeypatch.setenv("DYNO", dyno)
    if owner is None:
        monkeypatch.delenv("BACKGROUND_WORKERS_DYNO", raising=False)
    else:
        monkeypatch.setenv("BACKGROUND_WORKERS_DYNO", owner)
    return Settings()


@pytest.mark.parametrize(
    ("dyno", "role"),
    [
        ("web.1", "web"),
        ("web.12", "web"),
        ("worker.1", "worker"),
        ("run.7872", "run"),
        (None, "local"),
        ("", "local"),
    ],
)
def test_the_platform_names_the_process(
    monkeypatch: pytest.MonkeyPatch, dyno: str | None, role: str
) -> None:
    assert _settings(monkeypatch, dyno).process_role == role


def test_today_the_api_dyno_still_owns_the_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default, and deliberately so: no worker dyno has been paid for.

    If this ever flips without a worker dyno running, every email, upload
    parse, media job and post-lesson profile stops with nothing to say so.
    """
    assert _settings(monkeypatch, "web.1").background_workers_dyno == "web"
    assert _settings(monkeypatch, "web.1").run_background_workers is True


def test_naming_a_worker_dyno_takes_them_off_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _settings(monkeypatch, "web.1", owner="worker").run_background_workers is False
    assert _settings(monkeypatch, "worker.1", owner="worker").run_background_workers is True


@pytest.mark.parametrize("owner", [None, "web", "worker"])
def test_a_one_off_dyno_never_drains_the_queue(
    monkeypatch: pytest.MonkeyPatch, owner: str | None
) -> None:
    """`heroku run` exists to run one command, not to pick up work."""
    assert _settings(monkeypatch, "run.7872", owner=owner).run_background_workers is False


def test_running_locally_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """No developer should need a second process to watch a lesson parse."""
    assert _settings(monkeypatch, None).run_background_workers is True
    assert _settings(monkeypatch, None, owner="worker").run_background_workers is True


def test_the_media_worker_runs_one_loop_per_medium() -> None:
    """Was two image loops and four audio loops, all waking every 5s.

    The work is bounded by the providers, not by how many pollers ask for it,
    so the extra loops bought nothing and cost the API its latency.
    """
    assert DeferredMediaWorker.CONCURRENCY == (("image", 1), ("audio", 1))
    assert sum(count for _, count in DeferredMediaWorker.CONCURRENCY) == 2
    assert DeferredMediaWorker.IDLE_SECONDS >= 20
    assert DeferredMediaWorker.RESTAMP_IDLE_SECONDS >= 300


def test_no_media_loop_sleeps_on_a_hardcoded_number() -> None:
    """The intervals are the fix, so they live in one named place."""
    for method in (DeferredMediaWorker._run, DeferredMediaWorker._run_restamps):
        source = inspect.getsource(method)
        assert "asyncio.sleep(self." in source
        assert "asyncio.sleep(5)" not in source
        assert "asyncio.sleep(10)" not in source


@pytest.mark.parametrize(
    ("module", "attribute", "floor"),
    [
        ("nevo.notifications.worker", "NotificationEmailWorker", 20),
        ("nevo.consent.worker", "ConsentDeliveryWorker", 20),
        ("nevo.learner_profiles.post_lesson_worker", "PostLessonProcessingWorker", 15),
    ],
)
def test_the_polling_workers_wait_long_enough(module: str, attribute: str, floor: int) -> None:
    import importlib

    worker = getattr(importlib.import_module(module), attribute)
    default = inspect.signature(worker.__init__).parameters["poll_seconds"].default
    assert default >= floor, f"{attribute} polls every {default}s; the API pays for that"


def test_the_image_can_still_run_the_loops_somewhere_else() -> None:
    """The worker role has to be reachable, or the switch above is a lie."""
    dockerfile = pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"
    text = dockerfile.read_text()
    assert "${DYNO%%.*}" in text
    assert "nevo.ops.run_workers" in text
    assert text.index("nevo.ops.run_workers") < text.index("uvicorn nevo.main:app")


def test_the_worker_entrypoint_stops_cleanly() -> None:
    """SIGTERM must reach the lifespan, or leases outlive the process."""
    from nevo.ops import run_workers

    source = pathlib.Path(run_workers.__file__).read_text()
    assert "SIGTERM" in source
    assert "async with lifespan(app)" in source
