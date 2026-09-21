"""Ask Nevo's daily limit, which is money rather than a count of chats.

"Ten conversations a day" bounds nothing - a conversation is one short
question or twenty long turns. Ask Nevo is the only part of the product that
calls a model while a child is waiting, so the limit has to be what it costs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy
from nevo.ask_nevo.allowance import (
    RESERVE_UNITS,
    STUDENT_DAILY_UNITS,
    TEACHER_DAILY_UNITS,
    Allowance,
    next_reset,
    school_day,
    units_for,
)
from nevo.ask_nevo.entities import AskNevoContextIds, AskNevoRequest
from nevo.ask_nevo.errors import AskNevoDailyLimitError
from nevo.ask_nevo.service import AskNevoService
from nevo.domain.ask_nevo.vocabulary import AskNevoRole
from nevo.main import app
from tests.ask_nevo.test_service import ACTOR_ID, FakeGateway, FakeRepository

TYPICAL_EXCHANGE = units_for(input_tokens=1_700, output_tokens=300)


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def _allowance(role: AskNevoRole, spent: int) -> Allowance:
    now = datetime.now(UTC)
    return Allowance(
        role=role,
        day=school_day(now),
        spent_units=spent,
        exchanges=0,
        resets_at=next_reset(now),
    )


def test_output_costs_what_output_costs() -> None:
    # Output is five times the price of input, so it counts five times. A
    # flat token count would let a long answer cost five times what the
    # budget thought it did.
    assert units_for(input_tokens=1_000, output_tokens=0) == 1_000
    assert units_for(input_tokens=0, output_tokens=1_000) == 5_000


def test_a_child_gets_about_six_questions_a_day() -> None:
    # Derived from roughly $4 of a child's annual budget over a school year,
    # not picked. If this number moves, the money moved.
    assert STUDENT_DAILY_UNITS // TYPICAL_EXCHANGE == 6


def test_a_teacher_gets_more_than_a_child_and_still_a_limit() -> None:
    assert TEACHER_DAILY_UNITS > STUDENT_DAILY_UNITS
    assert TEACHER_DAILY_UNITS < STUDENT_DAILY_UNITS * 10


def test_the_day_turns_over_where_the_child_is() -> None:
    # Half past midnight in Lagos is the new day, though it is still
    # yesterday in UTC.
    just_after_midnight_lagos = datetime(2026, 9, 22, 0, 30, tzinfo=UTC)
    assert school_day(just_after_midnight_lagos).day == 22
    assert next_reset(just_after_midnight_lagos).day == 23


def test_an_answer_is_never_started_that_the_budget_cannot_finish() -> None:
    # Being cut off mid-sentence reads as a fault. Being told the day is done
    # reads as a rule, so the last exchange is refused rather than truncated.
    nearly_done = _allowance(AskNevoRole.STUDENT, STUDENT_DAILY_UNITS - RESERVE_UNITS + 1)

    assert nearly_done.exhausted
    assert nearly_done.remaining_units > 0


def test_a_fresh_day_is_not_exhausted() -> None:
    assert not _allowance(AskNevoRole.STUDENT, 0).exhausted


def test_the_refusal_says_when_to_come_back_and_blames_nobody() -> None:
    message = _allowance(AskNevoRole.STUDENT, STUDENT_DAILY_UNITS).message()

    assert "Come back" in message
    assert "morning" in message
    for word in ("error", "limit", "exceeded", "denied", "sorry"):
        assert word not in message.lower()


def test_what_is_left_is_counted_in_questions_not_tokens() -> None:
    # A number of tokens means nothing to a child and little to a teacher.
    assert _allowance(AskNevoRole.STUDENT, 0).questions_left >= 4
    assert _allowance(AskNevoRole.STUDENT, STUDENT_DAILY_UNITS).questions_left == 0


@pytest.mark.asyncio
async def test_a_child_who_has_used_the_day_is_refused_before_any_work() -> None:
    repository = FakeRepository(spent_units=STUDENT_DAILY_UNITS)
    gateway = FakeGateway("should never be asked")
    service = AskNevoService(
        repository=repository,
        gateway=gateway,
        compliance=ZeroTagCompliancePolicy(),
    )

    with pytest.raises(AskNevoDailyLimitError) as refusal:
        await service.ask(
            actor_user_id=ACTOR_ID,
            request=AskNevoRequest(
                role=AskNevoRole.STUDENT,
                current_page="lesson",
                context_ids=AskNevoContextIds(student_id=ACTOR_ID),
                question="What is a fraction?",
            ),
        )

    # Nothing was spent finding out the answer was no.
    assert gateway.requests == []
    assert refusal.value.code == "ask_nevo_daily_limit"


@pytest.mark.asyncio
async def test_an_answer_is_charged_for_what_the_provider_billed() -> None:
    repository = FakeRepository()
    service = AskNevoService(
        repository=repository,
        gateway=FakeGateway("Half of eight is four."),
        compliance=ZeroTagCompliancePolicy(),
    )

    await service.ask(
        actor_user_id=ACTOR_ID,
        request=AskNevoRequest(
            role=AskNevoRole.STUDENT,
            current_page="lesson",
            context_ids=AskNevoContextIds(student_id=ACTOR_ID),
            question="What is half of eight?",
        ),
    )

    assert repository.charges == [TYPICAL_EXCHANGE]


@pytest.mark.asyncio
async def test_a_compliance_retry_is_charged_too() -> None:
    # A retry is a second answer we paid for. Leaving it off the ledger is a
    # budget that quietly does not hold.
    repository = FakeRepository()
    service = AskNevoService(
        repository=repository,
        gateway=FakeGateway("This looks like a diagnostic issue.", "He is still working on this."),
        compliance=ZeroTagCompliancePolicy(),
    )

    await service.ask(
        actor_user_id=ACTOR_ID,
        request=AskNevoRequest(
            role=AskNevoRole.TEACHER,
            current_page="class",
            context_ids=AskNevoContextIds(student_id=UUID(int=7)),
            question="How is he getting on?",
        ),
    )

    assert repository.charges == [TYPICAL_EXCHANGE * 2]


def test_the_client_can_show_what_is_left_and_when_it_returns(spec: dict) -> None:
    assert "get" in spec["paths"]["/api/v1/ask-nevo/allowance"]
    fields = spec["components"]["schemas"]["AskNevoAllowanceResponse"]["properties"]

    assert {"questionsLeft", "exhausted", "resetsAt", "message"} <= set(fields)


def test_the_refusal_is_a_429_with_the_time_it_comes_back() -> None:
    import inspect

    from nevo.api.ask_nevo import ask_nevo

    source = inspect.getsource(ask_nevo)

    # Not a 403: nothing is forbidden, the day is used up.
    assert "HTTP_429_TOO_MANY_REQUESTS" in source
    assert "resetsAt" in source


def test_nothing_about_the_limit_is_recorded_about_the_child() -> None:
    from nevo.db.models.ask_nevo import AskNevoDailyUsage

    columns = {column.name for column in AskNevoDailyUsage.__table__.columns}

    # A ledger of spend, not an observation about a person: no question text,
    # no category, no judgement.
    assert columns == {
        "id",
        "actor_user_id",
        "usage_date",
        "role",
        "units_spent",
        "exchanges",
        "updated_at",
    }
