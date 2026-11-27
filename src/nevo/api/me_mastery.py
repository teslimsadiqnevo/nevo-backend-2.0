"""/me Phase 5: GET /me/mastery and GET /me/progress, scoped to the learner.

Self-scoped by construction: neither takes a learner id, so neither can be
asked for someone else's.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import Field

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.me import mastery
from nevo.me.usage import current_tier

router = APIRouter(prefix="/api/v1", tags=["me"])

Level = Literal["knowing_and_understanding", "application", "analysis_and_evaluation"]
LevelState = Literal["reached", "working", "not"]


class ConceptLevelResponse(CamelResponse):
    concept_id: UUID
    concept_name: str
    #: The highest level reached, in order. Omitted until the first is.
    level: Level | None = None
    #: The next level. Omitted once analysis and evaluation is reached.
    working_towards: Level | None = None
    #: All three, for when the learner asks to see them: one entry per level
    #: something was observed at. No entry means nothing observed, not `not`.
    levels: dict[Level, LevelState] = Field(default_factory=dict)


class MasteryResponse(CamelResponse):
    concepts: list[ConceptLevelResponse]


class LevelReachedResponse(CamelResponse):
    concept_id: UUID
    concept_name: str
    level: Level
    reached_at: datetime


class ProgressResponse(CamelResponse):
    locked: bool
    #: On the free tier: the tier that unlocks progress. Omitted otherwise.
    unlocks_with: str | None = None
    window: Literal["rolling", "full"] | None = None
    since: datetime | None = None
    events: list[LevelReachedResponse] | None = None


async def _learner(session: DatabaseSession, principal) -> User:
    user = await session.get(User, principal.user_id)
    if user is None or user.role.value != "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "student_required"})
    return user


@router.get("/me/mastery", response_model=MasteryResponse, response_model_exclude_none=True)
async def my_mastery(principal: PrincipalDependency, session: DatabaseSession) -> MasteryResponse:
    learner = await _learner(session, principal)
    return MasteryResponse(
        concepts=[
            ConceptLevelResponse(
                concept_id=item.concept_id,
                concept_name=item.concept_name,
                level=item.reached,
                working_towards=item.working_towards,
                levels=item.levels or {},
            )
            for item in await mastery.concept_levels(session, learner)
        ]
    )


@router.get("/me/progress", response_model=ProgressResponse, response_model_exclude_none=True)
async def my_progress(principal: PrincipalDependency, session: DatabaseSession) -> ProgressResponse:
    """Progress across time. On the free tier, a locked body with a 200."""

    learner = await _learner(session, principal)
    tier = await current_tier(session, learner, datetime.now(UTC))
    view = await mastery.progress_for(session, learner, tier)
    if view.locked:
        return ProgressResponse(locked=True, unlocks_with=view.unlocks_with)
    return ProgressResponse(
        locked=False,
        window=view.window,
        since=view.since,
        events=[
            LevelReachedResponse(
                concept_id=item.concept_id,
                concept_name=item.concept_name,
                level=item.level,
                reached_at=item.reached_at,
            )
            for item in view.events
        ],
    )
