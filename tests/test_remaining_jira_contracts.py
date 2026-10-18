from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from nevo.api.frontend_unblockers import BaselineTrialsRequest, submit_baseline_trials
from nevo.consent.repositories import SqlAlchemyConsentRepository
from nevo.content_parsing.service import (
    _interactive_variant,
    _modules_from_payload,
    _segment_from_payload,
)
from nevo.db.models.consent_assurance import AgeCheck
from nevo.domain.consent.vocabulary import AgeCheckState


@pytest.mark.asyncio
async def test_motor_samples_correct_only_the_current_device():
    payload = BaselineTrialsRequest(
        sessionId="baseline",
        formFactor="tablet_touch",
        motorSamplesMs=[10000, 10000, 100, 100, 100, 100, 100, 100],
        trials=[
            {"dimension": "ps", "correct": True, "responseTimeMs": 400},
            {"dimension": "ps", "correct": True, "responseTimeMs": 500},
        ],
    )
    desktop = {"motorBaselineMs": 900, "scoredSampleCount": 6, "missCount": 0}
    session = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                baseline_profile={"motor_baselines": {"desktop_cursor": desktop}}
            )
        ),
        execute=AsyncMock(),
        commit=AsyncMock(),
    )
    result = await submit_baseline_trials(
        payload, SimpleNamespace(user_id=uuid4(), role="student"), session
    )
    assert result.baseline_profile["motor_baseline_ms"] == 100
    assert result.baseline_profile["motor_scored_sample_count"] == 6
    assert result.baseline_profile["motor_baselines"]["desktop_cursor"] == desktop
    assert result.engine_config["pacing"]["responseTimeTargetMs"] == 350


@pytest.mark.asyncio
async def test_no_motor_baseline_is_uncorrected_and_never_borrowed():
    payload = BaselineTrialsRequest(
        sessionId="baseline",
        formFactor="phone_touch",
        trials=[{"dimension": "ps", "correct": True, "responseTimeMs": 700}],
    )
    session = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                baseline_profile={"motor_baselines": {"tablet_touch": {"motorBaselineMs": 100}}}
            )
        ),
        execute=AsyncMock(),
        commit=AsyncMock(),
    )
    result = await submit_baseline_trials(
        payload, SimpleNamespace(user_id=uuid4(), role="student"), session
    )
    assert "motor_baseline_ms" not in result.baseline_profile
    assert result.baseline_profile["motor_latency_status"] == "uncorrected_no_baseline"
    assert result.engine_config["pacing"]["responseTimeTargetMs"] == 700


def test_generated_lesson_text_and_activities_are_honest():
    segment = _segment_from_payload(
        {
            "body": "Pushes change motion.",
            "text_variant": {
                "authoredBy": "person",
                "keyPoints": ["Pushes change motion.", "Force moves objects."],
                "keyTerms": [{"term": "force", "definition": "A push or pull."}],
            },
            "interactive_variant": {
                "steps": [{"id": "push", "instruction": "Push a toy car."}],
                "outcome": "The car moves.",
            },
        },
        sequence_order=1,
    )
    assert segment.text_variant["authoredBy"] == "nevo"
    assert segment.text_variant["keyPoints"] == ["Force moves objects."]
    assert segment.interactive_variant["type"] == "activity"
    assert _interactive_variant({"prompt": "What is force?", "options": ["A", "B"]}, "") is None


def test_modules_follow_the_proposed_boundaries_or_stay_absent():
    segments = [SimpleNamespace(segment_key="intro"), SimpleNamespace(segment_key="practice")]
    payload = {
        "modules": [
            {
                "title": "Start",
                "segmentKeys": ["intro"],
                "recap": "We met force.",
                "preview": "Try it.",
            },
            {"title": "Try", "segmentKeys": ["practice"]},
        ]
    }
    modules = _modules_from_payload(payload, segments)
    assert [module.segment_keys for module in modules] == [("intro",), ("practice",)]
    assert modules[0].recap == "We met force."
    assert _modules_from_payload({"modules": payload["modules"][:1]}, segments) == []
    assert _modules_from_payload({}, segments) == []


@pytest.mark.asyncio
async def test_parent_resubmission_cannot_clear_a_recorded_date_difference():
    school_date = date(2016, 1, 1)
    check = AgeCheck(
        state=AgeCheckState.MISMATCH,
        school_date_of_birth=school_date,
        parent_date_of_birth=date(2016, 2, 1),
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(date_of_birth=school_date)),
        scalar=AsyncMock(return_value=check),
        flush=AsyncMock(),
    )
    state = await SqlAlchemyConsentRepository._run_age_check(
        session,
        school_id=uuid4(),
        student_id=uuid4(),
        parent_date_of_birth=school_date,
        now=datetime.now(UTC),
    )
    assert state is AgeCheckState.MISMATCH
    assert check.parent_date_of_birth == school_date
