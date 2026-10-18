from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as Row
from uuid import uuid4

import pytest

from nevo.api.frontend_unblockers import BASELINE_DIMENSIONS
from nevo.api.insights import _progress_narrative
from nevo.api.lesson_contracts import ComprehensionCheckpoint
from nevo.content_parsing.answers import answer_matches
from nevo.db.models.learner_profile import LearnerProfile, LearnerProfileHistory
from nevo.domain.learner_profiles.vocabulary import CANONICAL_PROFILE_DIMENSIONS
from nevo.domain.signal_events.vocabulary import SignalEventType as Event
from nevo.intelligence.baseline import build_baseline_profile, reduce_trials
from nevo.intelligence.runtime_evidence import derive_runtime_evidence
from scripts.backfill_depth_rewrites import missing_depths


def test_account_settings_refuse_learning_style_storage():
    from fastapi import HTTPException

    from nevo.api.product_admin import merge_preferences

    with pytest.raises(HTTPException) as error:
        merge_preferences({}, {"nested": {"preferredModality": "visual"}})
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "learning_style_not_stored"
    assert merge_preferences({}, {"avatarTone": "violet"}) == {"avatarTone": "violet"}


def test_generated_text_cannot_reintroduce_a_learning_style_label():
    from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy

    policy = ZeroTagCompliancePolicy()
    assert not policy.inspect("This child is a visual learner.").allowed
    assert not policy.inspect("The auditory_preference is strong.").allowed
    assert policy.inspect("The diagram helped with this question.").allowed


def test_depth_delivery_retains_annotations_and_withholds_unreviewed_backfill():
    from nevo.api.lesson_contracts import depth_payloads

    annotation = {
        "keyTerms": [{"term": "fraction", "definition": "A part of a whole"}],
        "equationCallouts": [{"equation": "a + b = c", "label": "Sum"}],
    }
    values = {
        "simplified": {"body": "A part.", "reviewStatus": "pending"},
        "expanded": {"body": "A part of the original whole."},
    }
    teacher = depth_payloads(values, annotation)
    assert teacher["simplified"]["equationCallouts"][0]["equation"] == "a + b = c"
    child = depth_payloads(values, annotation, for_student=True)
    assert "simplified" not in child
    assert child["expanded"]["keyTerms"][0]["term"] == "fraction"


def test_depth_rewrite_cannot_drop_a_source_equation():
    from nevo.content_parsing.depth import accept

    source = "An equation connects the quantities.\nx + y = z\n" + "Read the parts carefully. " * 12
    assert accept("An equation connects quantities.", source=source, shorter=True) is None


@pytest.mark.parametrize(
    "answer,key", [("0.5", "1/2"), ("50%", ".5"), ("2/4", ".50"), ("-0.5", "-1/2")]
)
def test_equivalent_numeric_answers(answer, key):
    assert answer_matches(answer, {"answerKey": key, "answerType": "numeric"}) is True


def test_alternative_answers_survive_delivery_and_marking():
    question = ComprehensionCheckpoint(
        id="q", prompt="Name it", answerKey="colour", acceptedAnswers=["color"]
    )
    payload = question.model_dump(by_alias=True)
    assert payload["acceptedAnswers"] == ["color"]
    assert answer_matches(" Color ", payload) is True
    assert answer_matches("unknown", payload) is False
    assert answer_matches('__import__("os")', {"answerKey": 1}) is False
    assert answer_matches("1/0", {"answerKey": 1}) is False
    assert answer_matches(True, {"answerKey": "1/1", "answerType": "numeric"}) is False
    assert answer_matches(True, {"answerKey": 1, "answerType": "numeric"}) is False


def test_no_stored_style_dimensions_remain():
    for model in (LearnerProfile, LearnerProfileHistory):
        assert not any("preference" in column.name for column in model.__table__.columns)
    assert not any("preference" in name for name in CANONICAL_PROFILE_DIMENSIONS)


def test_calculation_delivery_does_not_offer_text_as_its_opening_mode():
    from nevo.api.lesson_contracts import segment_modalities

    assert segment_modalities("calculation", ["text", "audio", "visual"], {"steps": []}) == [
        "interactive",
        "visual",
    ]


def test_warmup_only_rotates_the_six_supported_dimensions():
    assert BASELINE_DIMENSIONS == ("wmc", "ps", "reading", "ans", "attention", "domain")


def test_partial_recalibration_preserves_other_dimensions_and_settings():
    previous = {
        "reading_wpm": 88,
        "attention_span_minutes": 9,
        "working_memory_capacity": 4,
        "processing_speed": 3,
        "comprehension_accuracy": 0.82,
        "subject_placements": {"maths": 0.7},
    }
    held = {
        "reading": {"targetWordsPerMinute": 88},
        "support": {"initialScaffoldLevel": "light"},
        "pacing": {"attentionWindowMinutes": 9, "responseTimeTargetMs": 2500},
    }
    result, config = build_baseline_profile(
        session_id="warmup",
        features=reduce_trials([{"dimension": "ps", "correct": True, "responseTimeMs": 1000}]),
        previous_profile=previous,
        previous_engine_config=held,
    )
    assert result["processing_speed"] == 5
    for key in previous.keys() - {"processing_speed"}:
        assert result[key] == previous[key]
    assert config["reading"] == held["reading"]
    assert config["support"] == held["support"]
    assert config["pacing"]["attentionWindowMinutes"] == 9


def test_reading_speed_is_derived_not_a_fixed_measurement():
    for duration, expected in [(20_000, 60), (10_000, 120)]:
        features = reduce_trials(
            [
                {
                    "dimension": "reading",
                    "correct": True,
                    "readingWordCount": 20,
                    "responseTimeMs": duration,
                }
            ]
        )
        profile, _ = build_baseline_profile(session_id="reading", features=features)
        assert profile["reading_wpm"] == expected
    profile, _ = build_baseline_profile(
        session_id="missing",
        features=reduce_trials(
            [{"dimension": "reading", "correct": True, "responseTimeMs": 10000}]
        ),
    )
    assert "reading_wpm" not in profile


@pytest.mark.parametrize(
    "stored,expected",
    [
        (None, {"simplified", "expanded"}),
        ({"simplified": None}, {"simplified", "expanded"}),
        ({"simplified": {"body": "valid"}, "expanded": None}, {"expanded"}),
        ({"simplified": {"body": "valid"}, "expanded": {"body": "valid"}}, set()),
    ],
)
def test_backfill_handles_nulls_and_partial_variants(stored, expected):
    assert missing_depths(stored) == expected


def test_progress_copy_is_not_selected_by_a_mastery_band():
    texts = [
        _progress_narrative(
            mastery_average=value,
            concept_count=2,
            practice_count=3,
            lesson_count=1,
            subject="Maths",
        )
        for value in (0.2, 0.6, 0.9)
    ]
    assert texts[0] == texts[1] == texts[2]


def test_server_evidence_combines_marked_answers_and_permitted_events():
    now = datetime.now(UTC)
    current = Row(id=uuid4(), segment_key="s")
    old_session = uuid4()

    def event(indicator, value, when=now, sitting=None):
        return Row(
            event_type=Event.ENGAGEMENT_SIGNAL,
            timestamp=when,
            session_id=sitting,
            event_data={"indicator": indicator, "value": value},
        )

    result = derive_runtime_evidence(
        attempts=[Row(correct=False, response_time_ms=6000)] * 3,
        events=[event("focus_drop", 180000), event("task_switch", 3)],
        historical_attempts=[Row(correct=True, response_time_ms=2000)] * 4,
        historical_events=[event("steady_progress", 180000, sitting=old_session)],
        baseline={},
        current=current,
        now=now,
        started_at=now - timedelta(minutes=5),
    )
    assert result["comprehension_score"] == 0
    assert result["session_average_comprehension"] == 100
    assert result["accuracy_below_baseline"] is True
    assert result["response_time_below_baseline"] is True
    assert result["engagement_score"] == 0
    assert result["engagement_baseline"] == 1
    assert result["engagement_below_baseline_seconds"] == 180


def test_time_alone_is_not_comprehension_or_disengagement():
    now = datetime.now(UTC)
    result = derive_runtime_evidence(
        attempts=[],
        events=[],
        historical_attempts=[],
        historical_events=[],
        baseline={},
        current=None,
        now=now,
        started_at=now - timedelta(seconds=30),
    )
    assert result["engagement_score"] is None
    assert result["comprehension_score"] is None
    assert result["accuracy_below_baseline"] is False
