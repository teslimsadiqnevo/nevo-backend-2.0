from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from nevo.api.lesson_review import BulkReviewRequest, _bulk_approve, _hash


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["completed", "completed_with_review"])
async def test_finished_lessons_can_receive_bulk_rewrite_signoff(state):
    segment = SimpleNamespace(depth_variants={"simplified": {"body": "A clearer version."}})
    lesson = SimpleNamespace(id=uuid4(), status=state)
    actor = SimpleNamespace(id=uuid4(), first_name="Test", last_name="Teacher", email=None)
    material = [{"body": "A clearer version."}]
    session = SimpleNamespace(scalar=AsyncMock(return_value=None), add=Mock(), commit=AsyncMock())
    with (
        patch(
            "nevo.api.lesson_review._review_material",
            AsyncMock(return_value=([], [segment], [], material)),
        ),
        patch("nevo.api.lesson_review._review_result", AsyncMock(return_value="approved")),
    ):
        response = await _bulk_approve(
            session,
            lesson,
            actor,
            BulkReviewRequest(expectedContentHash=_hash(material)),
            "rewrites",
        )
    assert response == "approved"
    assert segment.depth_variants["simplified"]["reviewStatus"] == "approved"
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["processing", "failed"])
async def test_incomplete_lessons_cannot_receive_bulk_signoff(state):
    session = SimpleNamespace(add=Mock(), commit=AsyncMock())
    with patch(
        "nevo.api.lesson_review._review_material", AsyncMock(return_value=([], [object()], [], []))
    ):
        with pytest.raises(HTTPException) as caught:
            await _bulk_approve(
                session,
                SimpleNamespace(status=state),
                None,
                BulkReviewRequest(expectedContentHash="0" * 64),
                "rewrites",
            )
    assert caught.value.detail["code"] == "lesson_not_ready_for_review"
    session.add.assert_not_called()
