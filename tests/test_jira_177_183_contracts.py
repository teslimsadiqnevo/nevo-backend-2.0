"""Contracts raised from the student console on 26 September."""

from __future__ import annotations

import inspect

from nevo.api.auth import SessionResponse
from nevo.api.lesson_contracts import CalculationVariant
from nevo.api.product_auth import (
    SHARED_DEVICE_AVATARS,
    SHARED_DEVICE_COLOURWAYS,
    SHARED_DEVICE_SHAPES,
)
from nevo.api.product_learning import ProgressWrite, save_lesson_progress
from nevo.api.response_models import LessonProgressResponse, LessonSessionResponse, PinIssueResponse
from nevo.content_parsing.service import _validated_calculation_variant
from nevo.db.base import Base


def calculation() -> dict[str, object]:
    return {
        "fullEquation": "3/5 + 1/5",
        "answer": "4/5",
        "scaffold": {
            "kind": "bar",
            "parts": 5,
            "rows": 1,
            "marks": [3, 1],
            "labels": ["3/5", "1/5"],
        },
        "steps": [
            {
                "stepId": "s1",
                "stepNumber": 1,
                "prompt": "How many fifths altogether?",
                "expectedInput": "numeric",
                "input": "number",
                "targets": [4],
                "answer": 4,
                "assembles": "3/5 + 1/5 = ?/5",
                "hint": "Add the pieces.",
                "confirmationText": "Four fifths.",
                "visualUpdate": "Shade four pieces.",
                "equationState": "3/5 + 1/5 = 4/5",
            },
            {
                "stepId": "s2",
                "stepNumber": 2,
                "prompt": "Choose the fraction.",
                "expectedInput": "selection",
                "input": "choice",
                "targets": ["4/5", "3/5"],
                "answer": "4/5",
                "options": [
                    {"value": "4/5", "label": "4/5"},
                    {"value": "3/5", "label": "3/5"},
                ],
                "assembles": "3/5 + 1/5 = 4/5",
                "hint": "Keep the denominator.",
                "confirmationText": "That is it.",
                "visualUpdate": "Hold four shaded pieces.",
                "equationState": "3/5 + 1/5 = 4/5",
            },
        ],
        "completionStatement": "You combined like fractions.",
        "scaffoldImage": {"imageUrl": "https://wrong.example/scaffold.png"},
    }


def test_calculation_payload_is_renderer_ready_and_drops_generated_scaffold_images() -> None:
    payload, review = _validated_calculation_variant(calculation())
    assert review is None
    assert payload is not None
    assert payload["expression"] == "3/5 + 1/5"
    assert payload["scaffold"] == {
        "kind": "bar",
        "parts": 5,
        "rows": 1,
        "marks": [3, 1],
        "labels": ["3/5", "1/5"],
    }
    assert payload["steps"][0]["input"] == "number"
    assert payload["steps"][0]["assembles"] == "3/5 + 1/5 = ?/5"
    assert "scaffoldImage" not in payload
    CalculationVariant.model_validate(payload)


def test_lower_depth_route_is_typed_without_a_score() -> None:
    session_fields = LessonSessionResponse.model_fields
    progress_fields = LessonProgressResponse.model_fields
    assert {"depth", "rerouted_from_session_id"} <= set(session_fields)
    assert {"result_state", "reroute"} <= set(progress_fields)
    assert not ({"score", "percentage", "correct_count"} & set(progress_fields))
    payload = ProgressWrite.model_validate(
        {
            "sessionId": "00000000-0000-0000-0000-000000000001",
            "status": "completed",
            "resultState": "nothing_landed",
        }
    )
    assert payload.result_state == "nothing_landed"
    source = inspect.getsource(save_lesson_progress)
    assert 'delivery_depth="lower"' in source
    assert "rerouted_from_session_id=lesson_session.id" in source


def test_pin_delivery_responses_carry_the_length() -> None:
    assert PinIssueResponse.model_fields["pin_length"].default == 4
    assert "pin_length" in SessionResponse.model_fields
    assert "pin_change_required" in SessionResponse.model_fields


def test_shared_device_identity_has_eighteen_unique_combinations_and_a_db_guard() -> None:
    assert len(SHARED_DEVICE_SHAPES) == 6
    assert len(SHARED_DEVICE_COLOURWAYS) == 3
    assert len(SHARED_DEVICE_AVATARS) == len(set(SHARED_DEVICE_AVATARS)) == 18
    table = Base.metadata.tables["shared_device_profiles"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("device_id", "avatar_shape", "avatar_colourway") in unique_columns
