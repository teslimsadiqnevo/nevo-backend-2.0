"""Background work runs in its own process, never the one serving requests.

19 November: the API went from 1.5s to 16s, and /openapi.json - which
touches no database at all - stalled for over 90 seconds. We serve from a
single uvicorn process, so there is one event loop, and fifteen poll loops
were sharing it and the connection pool with real traffic.

The split is decided from the platform's own DYNO rather than a config var,
because Heroku config vars are app-wide and so cannot differ between the web
and worker dynos. These tests pin that decision, including the two cases
that are easy to get wrong: a one-off `heroku run` dyno must not join in,
and a developer running locally must still get the workers.
"""

from __future__ import annotations

import pathlib

import pytest

from nevo.core.config import Settings


def _settings(monkeypatch: pytest.MonkeyPatch, dyno: str | None) -> Settings:
    if dyno is None:
        monkeypatch.delenv("DYNO", raising=False)
    else:
        monkeypatch.setenv("DYNO", dyno)
    return Settings()


@pytest.mark.parametrize(
    ("dyno", "role", "runs_workers"),
    [
        ("web.1", "web", False),
        ("web.12", "web", False),
        ("worker.1", "worker", True),
        ("worker.3", "worker", True),
        # A one-off dyno runs one command. It must not start draining the
        # same queues the worker dyno is working on.
        ("run.7872", "run", False),
        ("run.1", "run", False),
        # Local and test runs keep the old single-process behaviour, so
        # nobody needs a second terminal to see a lesson parse.
        (None, "local", True),
        ("", "local", True),
    ],
)
def test_only_the_worker_dyno_runs_background_work(
    monkeypatch: pytest.MonkeyPatch, dyno: str | None, role: str, runs_workers: bool
) -> None:
    settings = _settings(monkeypatch, dyno)
    assert settings.process_role == role
    assert settings.run_background_workers is runs_workers


def test_the_api_dyno_runs_none_of_them(monkeypatch: pytest.MonkeyPatch) -> None:
    """The point of the whole change, stated once as a single assertion."""
    assert _settings(monkeypatch, "web.1").run_background_workers is False


def test_the_image_dispatches_on_the_dyno_name() -> None:
    """A role decided in Python is no use if the image always runs uvicorn."""
    dockerfile = pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"
    text = dockerfile.read_text()
    assert "${DYNO%%.*}" in text
    assert "nevo.ops.run_workers" in text
    assert "uvicorn nevo.main:app" in text
    # The worker branch must come first: a default branch that matched
    # everything would serve uvicorn on the worker dyno.
    assert text.index("nevo.ops.run_workers") < text.index("uvicorn nevo.main:app")


def test_the_worker_entrypoint_stops_cleanly() -> None:
    """SIGTERM must reach the lifespan, or leases outlive the process."""
    from nevo.ops import run_workers

    source = pathlib.Path(run_workers.__file__).read_text()
    assert "SIGTERM" in source
    assert "async with lifespan(app)" in source
