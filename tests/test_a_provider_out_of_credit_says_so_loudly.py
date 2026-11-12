"""A provider that stops working says so once, where an alert can see it.

Recording the outcome of each call made /health honest, but nobody watches
/health. The audio provider ran out of credit before the 8 November demo and
the first anyone knew was a child opening a lesson with no narration.

Two things matter here. One line on the way down and one on the way back up,
so a log alert can be pointed at it without being taught to ignore a line per
call. And a failure about money told apart from a failure about the service,
because no retry clears the first one.
"""

from __future__ import annotations

import logging
from datetime import UTC

import pytest

from nevo.ops.provider_health import (
    LESSON_AUDIO,
    STALE_AFTER_HOURS,
    ProviderHealth,
    needs_a_human_with_a_card,
)


@pytest.fixture
def providers() -> ProviderHealth:
    return ProviderHealth()


@pytest.mark.parametrize(
    "detail",
    [
        "credit_balance_exhausted",
        "Your credit balance is too low",
        "insufficient funds",
        "402 Payment Required",
        "You exceeded your current quota",
        "billing hard limit reached",
        "subscription inactive",
    ],
)
def test_a_money_problem_is_recognised_as_one(detail: str) -> None:
    assert needs_a_human_with_a_card(detail)


@pytest.mark.parametrize(
    "detail",
    [
        "401 Unauthorized",
        "ReadTimeout",
        "500 Internal Server Error",
        "connection reset by peer",
        "model overloaded",
        None,
        "",
    ],
)
def test_an_ordinary_outage_is_not_mistaken_for_one(detail) -> None:
    assert not needs_a_human_with_a_card(detail)


def test_running_out_of_credit_is_logged_as_an_error_naming_the_remedy(providers, caplog) -> None:
    with caplog.at_level(logging.INFO):
        providers.record(LESSON_AUDIO, ok=False, detail="credit_balance_exhausted")

    errors = [item for item in caplog.records if item.levelno >= logging.ERROR]
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert "OUT OF CREDIT" in message
    assert LESSON_AUDIO in message
    assert "credit_balance_exhausted" in message
    # Says why waiting will not help, which is the whole difference.
    assert "no retry will clear this" in message


def test_an_ordinary_failure_is_logged_without_claiming_it_is_a_bill(providers, caplog) -> None:
    with caplog.at_level(logging.INFO):
        providers.record(LESSON_AUDIO, ok=False, detail="401 Unauthorized")

    errors = [item for item in caplog.records if item.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "OUT OF CREDIT" not in errors[0].getMessage()
    assert "Provider failing" in errors[0].getMessage()


def test_a_provider_that_keeps_failing_does_not_keep_shouting(providers, caplog) -> None:
    """Otherwise an alert has to be taught to ignore it, and then it is useless."""
    with caplog.at_level(logging.INFO):
        for _ in range(5):
            providers.record(LESSON_AUDIO, ok=False, detail="credit_balance_exhausted")

    assert len([item for item in caplog.records if item.levelno >= logging.ERROR]) == 1


def test_a_working_provider_logs_nothing(providers, caplog) -> None:
    with caplog.at_level(logging.INFO):
        for _ in range(3):
            providers.record(LESSON_AUDIO, ok=True)

    assert caplog.records == []


def test_recovery_is_said_too_so_a_stuck_alert_can_clear(providers, caplog) -> None:
    providers.record(LESSON_AUDIO, ok=False, detail="credit_balance_exhausted")
    caplog.clear()
    with caplog.at_level(logging.INFO):
        providers.record(LESSON_AUDIO, ok=True)

    assert any("Provider recovered" in item.getMessage() for item in caplog.records)


def test_failing_again_after_recovery_shouts_again(providers, caplog) -> None:
    providers.record(LESSON_AUDIO, ok=False, detail="credit_balance_exhausted")
    providers.record(LESSON_AUDIO, ok=True)
    caplog.clear()
    with caplog.at_level(logging.INFO):
        providers.record(LESSON_AUDIO, ok=False, detail="credit_balance_exhausted")

    assert len([item for item in caplog.records if item.levelno >= logging.ERROR]) == 1


def test_the_recorded_state_is_unchanged_by_any_of_this(providers) -> None:
    """The logging is additional; /health reads what it always read."""
    assert providers.state(LESSON_AUDIO) == "unknown"
    providers.record(LESSON_AUDIO, ok=False, detail="credit_balance_exhausted")
    assert providers.state(LESSON_AUDIO) == "failing"
    assert providers.last_failure(LESSON_AUDIO) == "credit_balance_exhausted"
    providers.record(LESSON_AUDIO, ok=True)
    assert providers.state(LESSON_AUDIO) == "working"
    assert providers.last_failure(LESSON_AUDIO) is None


def test_health_tells_an_administrator_which_kind_of_broken_it_is() -> None:
    from nevo import main

    source = main.__loader__.get_source(main.__name__)
    assert '"lessonAudioFailureKind"' in source
    assert '"lessonImagesFailureKind"' in source


# --- a stale failure is not a current one -----------------------------------


def _age(providers: ProviderHealth, provider: str, **delta) -> None:
    """Backdate the recorded outcome, as a quiet day would."""
    from datetime import datetime, timedelta

    outcome = providers._outcomes[provider]
    providers._outcomes[provider] = type(outcome)(
        ok=outcome.ok,
        at=datetime.now(UTC) - timedelta(**delta),
        detail=outcome.detail,
    )


def test_a_three_week_old_failure_is_not_reported_as_a_live_one(providers) -> None:
    """The fault Yinka hit on 12 November.

    state() went to "unknown" after a day while last_failure() returned the
    same sentence for ever, with no date beside it. So /health read "YarnGPT
    requests paused after QUOTA_EXCEEDED" for three weeks after the last such
    failure, which was 23 October, and he was about to rotate a working API
    key over it. Narration had been fine throughout.
    """
    providers.record(LESSON_AUDIO, ok=False, detail="QUOTA_EXCEEDED")
    _age(providers, LESSON_AUDIO, days=20)

    assert providers.state(LESSON_AUDIO) == "unknown"
    assert providers.last_failure(LESSON_AUDIO) is None, (
        "a three-week-old failure still reads as the current state"
    )


def test_a_fresh_failure_is_still_reported(providers) -> None:
    """The staleness window must not swallow a real one."""
    providers.record(LESSON_AUDIO, ok=False, detail="QUOTA_EXCEEDED")
    assert providers.state(LESSON_AUDIO) == "failing"
    assert providers.last_failure(LESSON_AUDIO) == "QUOTA_EXCEEDED"


def test_the_two_readers_go_stale_together(providers) -> None:
    """They disagreeing is what caused this, so they share one window."""
    providers.record(LESSON_AUDIO, ok=False, detail="QUOTA_EXCEEDED")
    _age(providers, LESSON_AUDIO, hours=STALE_AFTER_HOURS + 1)

    assert providers.state(LESSON_AUDIO) == "unknown"
    assert providers.last_failure(LESSON_AUDIO) is None

    providers.record(LESSON_AUDIO, ok=False, detail="QUOTA_EXCEEDED")
    _age(providers, LESSON_AUDIO, hours=STALE_AFTER_HOURS - 1)

    assert providers.state(LESSON_AUDIO) == "failing"
    assert providers.last_failure(LESSON_AUDIO) == "QUOTA_EXCEEDED"


def test_the_age_is_reported_so_a_state_is_never_read_without_it(providers) -> None:
    assert providers.last_call_at(LESSON_AUDIO) == ""
    providers.record(LESSON_AUDIO, ok=True)
    stamped = providers.last_call_at(LESSON_AUDIO)
    assert stamped and stamped.startswith("20")


def test_health_publishes_the_age(providers) -> None:
    from nevo import main

    source = main.__loader__.get_source(main.__name__)
    assert '"lessonAudioLastCallAt"' in source
    assert '"lessonImagesLastCallAt"' in source
