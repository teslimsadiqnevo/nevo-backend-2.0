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

import pytest

from nevo.ops.provider_health import (
    LESSON_AUDIO,
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
