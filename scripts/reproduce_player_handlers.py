"""Exercise reported handlers against stored data with every write rolled back."""

import argparse
import asyncio
import json
import traceback
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.api.auth import AuthPrincipal
from nevo.api.intelligence import AdaptRequest, AdaptResponse, adapt_lesson
from nevo.api.product_learning import ProgressWrite, save_lesson_progress
from nevo.api.response_models import LessonProgressResponse
from nevo.core.config import get_settings
from nevo.db.models.account import User
from nevo.db.models.content import LessonSegment
from nevo.db.models.signal_event import LessonSession
from nevo.db.session import create_engine
from nevo.intelligence.adaptation import (
    SqlAlchemyLearnerProfileRepository,
    rule_based_adaptation_plan,
)


class RollbackSession(AsyncSession):
    async def commit(self):
        await self.flush()


async def main(student_name="nura"):
    engine = create_engine(get_settings().database_url)
    sessions = async_sessionmaker(engine, class_=RollbackSession, expire_on_commit=False)
    try:
        async with sessions() as session:
            sitting = await session.scalar(
                select(LessonSession)
                .join(User, User.id == LessonSession.student_id)
                .where(
                    LessonSession.lesson_id == UUID("3367de9d-be40-4704-8a95-7a197b9824dc"),
                    User.first_name.ilike(student_name),
                )
                .order_by(LessonSession.started_at.desc())
                .limit(1)
            )
            if sitting is None:
                print("No reported sitting found")
                return
            student_id, session_id, lesson_id = sitting.student_id, sitting.id, sitting.lesson_id
        principal = AuthPrincipal(student_id, "student", uuid4())
        for action in ("progress", "adapt"):
            async with sessions() as session:
                try:
                    if action == "progress":
                        result = await save_lesson_progress(
                            lesson_id,
                            ProgressWrite(sessionId=session_id, status="completed"),
                            principal,
                            session,
                            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
                        )
                        LessonProgressResponse.model_validate(result)
                    else:
                        sitting = await session.get(LessonSession, session_id)
                        sitting.ended_at = None
                        sitting.completion_status = "in_progress"
                        await session.flush()
                        rows = list(
                            await session.scalars(
                                select(LessonSegment)
                                .where(LessonSegment.lesson_id == lesson_id)
                                .order_by(LessonSegment.sequence_order)
                            )
                        )
                        payload = AdaptRequest(
                            lessonId=lesson_id,
                            sessionId=session_id,
                            mode="in_lesson",
                            segments=[
                                {
                                    "id": str(row.id),
                                    "segmentType": "explanation",
                                    "availableModalities": ["text"],
                                }
                                for row in rows
                            ],
                            signals={"currentSegmentId": str(rows[0].id)},
                        )

                        class Engine:
                            async def adapt(self, *, request, requested_by_user_id):
                                profile = await SqlAlchemyLearnerProfileRepository(
                                    sessions
                                ).get_profile(student_id)
                                return rule_based_adaptation_plan(request=request, profile=profile)

                        response = await adapt_lesson(payload, principal, Engine(), session)
                        AdaptResponse.model_validate(response)
                    print(action, "PASS (rolled back)")
                except Exception as error:
                    print(
                        json.dumps(
                            {
                                "action": action,
                                "errorType": type(error).__name__,
                                "message": str(error)[:300],
                                "frames": [
                                    f"{frame.name}:{frame.lineno}"
                                    for frame in traceback.extract_tb(error.__traceback__)
                                ],
                            }
                        )
                    )
                finally:
                    await session.rollback()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--student-name", default="nura")
    asyncio.run(main(parser.parse_args().student_name))
