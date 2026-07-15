import json
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from nevo.domain.learner_profiles.vocabulary import (
    ChannelPreferenceStrength,
    ConfidenceLevel,
)
from nevo.learner_profiles.profile_updates import (
    PostLessonProfileUpdateService,
    ProfileAttentionFlagDraft,
    ProfileDimensionRecommendation,
    ProfileDimensionState,
    ProfileUpdateRecord,
    ProfileUpdateResponseError,
    ProfileUpdateStatus,
    SessionProfileUpdateContext,
    detect_sudden_change,
    parse_profile_update_response,
)

STUDENT_ID = UUID("00000000-0000-4000-8000-000000000001")
SESSION_ID = UUID("00000000-0000-4000-8000-000000000002")
REQUESTER_ID = UUID("00000000-0000-4000-8000-000000000003")
PROFILE_ID = UUID("00000000-0000-4000-8000-000000000004")
HISTORY_ID = UUID("00000000-0000-4000-8000-000000000005")
FLAG_ID = UUID("00000000-0000-4000-8000-000000000006")


@dataclass
class FakeGateway:
    response_text: str

    async def generate(self, request: object) -> object:
        self.request = request
        return SimpleNamespace(text=self.response_text)


class FakeRepository:
    def __init__(self, context: SessionProfileUpdateContext) -> None:
        self.context = context
        self.applied: tuple[ProfileDimensionRecommendation, ...] = ()
        self.flag: ProfileAttentionFlagDraft | None = None

    async def load_context(
        self,
        *,
        student_id: UUID,
        lesson_session_id: UUID,
    ) -> SessionProfileUpdateContext:
        assert student_id == STUDENT_ID
        assert lesson_session_id == SESSION_ID
        return self.context

    async def apply_recommendations(
        self,
        *,
        context: SessionProfileUpdateContext,
        recommendations: object,
        changed_by: UUID,
        change_reason: str,
        evaluated_at: datetime,
    ) -> ProfileUpdateRecord:
        self.applied = tuple(recommendations)
        assert context is self.context
        assert changed_by == REQUESTER_ID
        assert change_reason
        assert evaluated_at.tzinfo is not None
        return ProfileUpdateRecord(
            profile_id=PROFILE_ID,
            history_id=HISTORY_ID,
            version=3,
        )

    async def create_attention_flag(
        self,
        *,
        context: SessionProfileUpdateContext,
        flag: ProfileAttentionFlagDraft,
    ) -> UUID:
        assert context is self.context
        self.flag = flag
        return FLAG_ID


def profile_context(
    profile: dict[str, ProfileDimensionState] | None = None,
) -> SessionProfileUpdateContext:
    return SessionProfileUpdateContext(
        student_id=STUDENT_ID,
        lesson_session_id=SESSION_ID,
        learner_profile_id=PROFILE_ID,
        current_profile=profile
        or {
            "cognitive_load_threshold": ProfileDimensionState(
                value=3,
                confidence=ConfidenceLevel.MEDIUM,
            ),
        },
        session_summary={
            "event_count": 2,
            "event_type_counts": {"replay": 2},
        },
        event_count=2,
    )


@pytest.mark.asyncio
async def test_update_after_lesson_applies_gateway_recommendations() -> None:
    gateway = FakeGateway(
        json.dumps(
            {
                "updates": [
                    {
                        "dimension": "cognitive_load_threshold",
                        "value": 4,
                        "confidence": "medium",
                        "rationale": "More replays than usual.",
                    }
                ],
                "rationale": "Session evidence supports a small adjustment.",
            }
        )
    )
    repository = FakeRepository(profile_context())
    service = PostLessonProfileUpdateService(
        repository=repository,
        gateway=gateway,  # type: ignore[arg-type]
    )

    outcome = await service.update_after_lesson(
        student_id=STUDENT_ID,
        lesson_session_id=SESSION_ID,
        requested_by_user_id=REQUESTER_ID,
    )

    assert outcome.status is ProfileUpdateStatus.UPDATED
    assert outcome.profile_id == PROFILE_ID
    assert outcome.history_id == HISTORY_ID
    assert outcome.dimensions == ("cognitive_load_threshold",)
    assert repository.applied[0].value == 4


@pytest.mark.asyncio
async def test_update_after_lesson_flags_sudden_change() -> None:
    gateway = FakeGateway(
        json.dumps(
            {
                "updates": [
                    {
                        "dimension": "visual_spatial_preference",
                        "value": "low",
                        "confidence": "medium",
                        "rationale": "Session pattern moved away from visuals.",
                    }
                ]
            }
        )
    )
    repository = FakeRepository(
        profile_context(
            {
                "visual_spatial_preference": ProfileDimensionState(
                    value=ChannelPreferenceStrength.STRONG,
                    confidence=ConfidenceLevel.HIGH,
                ),
            }
        )
    )
    service = PostLessonProfileUpdateService(
        repository=repository,
        gateway=gateway,  # type: ignore[arg-type]
    )

    outcome = await service.update_after_lesson(
        student_id=STUDENT_ID,
        lesson_session_id=SESSION_ID,
        requested_by_user_id=REQUESTER_ID,
    )

    assert outcome.status is ProfileUpdateStatus.FLAGGED
    assert outcome.flag_id == FLAG_ID
    assert repository.applied == ()
    assert repository.flag == ProfileAttentionFlagDraft(
        dimension="visual_spatial_preference",
        current_value="strong",
        recommended_value="low",
        rationale="Session pattern moved away from visuals.",
    )


def test_parse_profile_update_response_accepts_dict_updates() -> None:
    recommendations, rationale = parse_profile_update_response(
        """
        ```json
        {
          "updates": {
            "auditory_preference": {
              "value": "moderate",
              "confidence": "medium"
            }
          },
          "rationale": "Audio signals increased."
        }
        ```
        """
    )

    assert rationale == "Audio signals increased."
    assert recommendations == (
        ProfileDimensionRecommendation(
            dimension="auditory_preference",
            value=ChannelPreferenceStrength.MODERATE,
            confidence=ConfidenceLevel.MEDIUM,
            rationale=None,
        ),
    )


def test_parse_profile_update_response_rejects_invalid_json() -> None:
    with pytest.raises(ProfileUpdateResponseError):
        parse_profile_update_response("not-json")


def test_detect_sudden_change_ignores_low_confidence_baseline() -> None:
    flag = detect_sudden_change(
        current_profile={
            "cognitive_load_threshold": ProfileDimensionState(
                value=1,
                confidence=ConfidenceLevel.MEDIUM,
            )
        },
        recommendations=(
            ProfileDimensionRecommendation(
                dimension="cognitive_load_threshold",
                value=5,
                confidence=ConfidenceLevel.MEDIUM,
            ),
        ),
    )

    assert flag is None
