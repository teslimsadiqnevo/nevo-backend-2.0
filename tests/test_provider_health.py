"""Health tells the difference between a key being set and a call working.

/health reported lessonImages: configured and lessonAudio: configured through
three days in which every image call came back "credit_balance_exhausted" and
every audio call came back 401. Configured means a key is present. It says
nothing about whether the provider accepts it, so the one screen an
administrator looks at was green while the feature was entirely dead.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

from nevo.ops.provider_health import (
    LESSON_AUDIO,
    LESSON_IMAGES,
    STALE_AFTER_HOURS,
    Outcome,
    ProviderHealth,
)


def test_nothing_known_is_unknown_and_not_working() -> None:
    """A restart genuinely does not know yet, and must not claim otherwise."""

    health = ProviderHealth()

    assert health.state(LESSON_IMAGES) == "unknown"
    assert health.state(LESSON_IMAGES) != "working"


def test_a_refused_call_reads_as_failing_and_keeps_the_reason() -> None:
    health = ProviderHealth()

    health.record(LESSON_IMAGES, ok=False, detail="429 credit_balance_exhausted")

    assert health.state(LESSON_IMAGES) == "failing"
    assert "credit_balance_exhausted" in (health.last_failure(LESSON_IMAGES) or "")


def test_a_later_success_clears_it() -> None:
    health = ProviderHealth()

    health.record(LESSON_AUDIO, ok=False, detail="401")
    health.record(LESSON_AUDIO, ok=True)

    assert health.state(LESSON_AUDIO) == "working"
    assert health.last_failure(LESSON_AUDIO) is None


def test_yesterday_does_not_vouch_for_today() -> None:
    health = ProviderHealth()
    stale = datetime.now(UTC) - timedelta(hours=STALE_AFTER_HOURS + 1)
    health._outcomes[LESSON_AUDIO] = Outcome(ok=True, at=stale)

    # A quiet night is not an outage, but an old success is not a report.
    assert health.state(LESSON_AUDIO) == "unknown"


def test_the_two_providers_are_tracked_apart() -> None:
    health = ProviderHealth()

    health.record(LESSON_IMAGES, ok=False, detail="no credit")
    health.record(LESSON_AUDIO, ok=True)

    assert health.state(LESSON_IMAGES) == "failing"
    assert health.state(LESSON_AUDIO) == "working"


def test_the_parse_records_both_outcomes() -> None:
    from nevo.content_parsing.service import ContentParsingService

    source = inspect.getsource(ContentParsingService)

    # Recorded on success as well as failure, or a provider that fixed itself
    # would read as failing for ever.
    assert "PROVIDERS.record(LESSON_AUDIO, ok=True)" in source
    assert "PROVIDERS.record(LESSON_IMAGES, ok=True)" in source
    assert "PROVIDERS.record(LESSON_AUDIO, ok=False" in source
    assert "PROVIDERS.record(LESSON_IMAGES, ok=False" in source


def test_health_reports_it_separately_from_configured() -> None:
    from nevo.main import health

    source = inspect.getsource(health)

    # Both, because they answer different questions.
    assert '"lessonImages"' in source
    assert "lessonImagesLastCall" in source
    assert "lessonAudioLastCall" in source
