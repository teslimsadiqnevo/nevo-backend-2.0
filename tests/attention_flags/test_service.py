import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from nevo.attention_flags.service import (
    AttentionDetectionContext,
    AttentionFlagDetectionService,
    AttentionFlagDraft,
    AttentionFlagRecord,
    InterventionRecommendationRecord,
    SessionEngagementSnapshot,
    detect_attention_flag,
    parse_recommendation_response,
)
from nevo.domain.attention_flags.vocabulary import AttentionFlagType

STUDENT_ID = UUID("00000000-0000-4000-8000-000000000001")
REQUESTER_ID = UUID("00000000-0000-4000-8000-000000000002")
FLAG_ID = UUID("00000000-0000-4000-8000-000000000003")
RECOMMENDATION_ID = UUID("00000000-0000-4000-8000-000000000004")
CALL_ID = UUID("00000000-0000-4000-8000-000000000005")


@dataclass
class FakeGateway:
    response_text: str

    async def generate(self, request: object) -> object:
        self.request = request
        return SimpleNamespace(text=self.response_text, call_id=CALL_ID)


class FakeRepository:
    def __init__(self, context: AttentionDetectionContext) -> None:
        self.context = context
        self.flag: AttentionFlagDraft | None = None
        self.recommendation_call_id: UUID | None = None

    async def load_detection_context(
        self,
        *,
        student_id: UUID,
    ) -> AttentionDetectionContext:
        assert student_id == STUDENT_ID
        return self.context

    async def create_attention_flag(
        self,
        draft: AttentionFlagDraft,
    ) -> AttentionFlagRecord:
        self.flag = draft
        return AttentionFlagRecord(
            id=FLAG_ID,
            student_id=draft.student_id,
            flag_type=draft.flag_type,
            description=draft.description,
        )

    async def create_intervention_recommendation(
        self,
        *,
        attention_flag_id: UUID,
        student_id: UUID,
        recommendation_text: str,
        ai_gateway_call_id: UUID | None,
    ) -> InterventionRecommendationRecord:
        assert attention_flag_id == FLAG_ID
        assert student_id == STUDENT_ID
        assert recommendation_text == "Offer a brief check-in and reduce pace."
        self.recommendation_call_id = ai_gateway_call_id
        return InterventionRecommendationRecord(
            id=RECOMMENDATION_ID,
            attention_flag_id=attention_flag_id,
            student_id=student_id,
            recommendation_text=recommendation_text,
            ai_gateway_call_id=ai_gateway_call_id,
        )

    async def create_escalation(
        self,
        *,
        student_id: UUID,
        teacher_id: UUID,
        teacher_note: str,
        attention_flag_id: UUID | None = None,
    ) -> UUID:
        raise AssertionError("not used")


def snapshots(*scores: float) -> tuple[SessionEngagementSnapshot, ...]:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    return tuple(
        SessionEngagementSnapshot(
            session_id=UUID(f"00000000-0000-4000-8000-{index + 10:012d}"),
            started_at=start + timedelta(days=index),
            engagement_score=score,
            event_count=3,
        )
        for index, score in enumerate(scores)
    )


def test_detect_attention_flag_finds_standard_engagement_decline() -> None:
    flag = detect_attention_flag(
        student_id=STUDENT_ID,
        sessions=snapshots(0.82, 0.78, 0.55, 0.52),
    )

    assert flag is not None
    assert flag.flag_type is AttentionFlagType.ENGAGEMENT_DECLINE
    assert flag.baseline_score == 0.8
    assert flag.current_score == 0.535
    assert len(flag.session_ids) == 2


def test_detect_attention_flag_prioritizes_sudden_change() -> None:
    flag = detect_attention_flag(
        student_id=STUDENT_ID,
        sessions=snapshots(0.8, 0.82, 0.79, 0.3),
    )

    assert flag is not None
    assert flag.flag_type is AttentionFlagType.SUDDEN_CHANGE
    assert flag.current_score == 0.3
    assert len(flag.session_ids) == 1


def test_detect_attention_flag_returns_none_without_pattern() -> None:
    flag = detect_attention_flag(
        student_id=STUDENT_ID,
        sessions=snapshots(0.72, 0.7, 0.69, 0.71),
    )

    assert flag is None


@pytest.mark.asyncio
async def test_evaluate_student_creates_flag_and_recommendation() -> None:
    repository = FakeRepository(
        AttentionDetectionContext(
            student_id=STUDENT_ID,
            sessions=snapshots(0.8, 0.82, 0.79, 0.3),
        )
    )
    gateway = FakeGateway(
        json.dumps(
            {
                "recommendation_text": "Offer a brief check-in and reduce pace.",
            }
        )
    )
    service = AttentionFlagDetectionService(
        repository=repository,
        gateway=gateway,  # type: ignore[arg-type]
    )

    outcome = await service.evaluate_student(
        student_id=STUDENT_ID,
        requested_by_user_id=REQUESTER_ID,
    )

    assert outcome.status == "flagged"
    assert outcome.attention_flag_id == FLAG_ID
    assert outcome.recommendation_id == RECOMMENDATION_ID
    assert outcome.flag_type is AttentionFlagType.SUDDEN_CHANGE
    assert repository.recommendation_call_id == CALL_ID


def test_parse_recommendation_response_accepts_markdown_json() -> None:
    text = parse_recommendation_response(
        """
        ```json
        {"recommendation_text":"Try a two-minute reset before the next segment."}
        ```
        """
    )

    assert text == "Try a two-minute reset before the next segment."
