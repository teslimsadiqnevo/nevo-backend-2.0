"""Correct two reported scientific reversals; renewed teacher sign-off is required."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.safety import POLICY_VERSION
from nevo.ai_gateway.wiring import build_ai_gateway
from nevo.core.config import get_settings
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.session import create_engine, create_session_factory

REPLACEMENTS = {
    (
        "A partially permeable membrane has tiny holes that are small enough to let small "
        "water molecules through, but large enough to stop larger particles, such as "
        "sugar molecules, from passing through."
    ): (
        "A partially permeable membrane lets small water molecules pass through but "
        "prevents larger particles, such as sugar molecules, from passing through."
    ),
    (
        "The soil around the roots contains a more concentrated solution than the cell "
        "sap inside the root hair cells, so water moves in."
    ): (
        "The cell sap inside the root hair cells is more concentrated than the water "
        "in the soil, so water moves from the soil into the root hair cells by osmosis."
    ),
}


async def main():
    engine = create_engine(get_settings().database_url)
    sessions = create_session_factory(engine)
    gateway = build_ai_gateway(sessions, AiGatewaySettings())
    count = 0
    try:
        async with sessions() as session:
            lesson = await session.get(Lesson, UUID("3367de9d-be40-4704-8a95-7a197b9824dc"))
            rows = list(
                await session.scalars(
                    select(LessonSegment).where(LessonSegment.lesson_id == lesson.id)
                )
            )
        for row in rows:
            variants = dict(row.depth_variants or {})
            expanded = dict(variants.get("expanded") or {})
            original = expanded.get("body", "")
            revised = original
            for old, new in REPLACEMENTS.items():
                revised = revised.replace(old, new)
            if revised == original:
                continue
            await gateway.check_content(
                revised,
                requester_user_id=lesson.created_by_user_id,
                phase="output:corrected_depth_variant",
            )
            expanded.update(
                body=revised,
                reviewStatus="pending",
                reviewedAt=None,
                reviewedBy=None,
                reviewedByName=None,
                safetyPolicyVersion=POLICY_VERSION,
                correctionNote=(
                    "Scientific relationship corrected; please review the revised wording."
                ),
                correctedAt=datetime.now(UTC).isoformat(),
            )
            variants["expanded"] = expanded
            async with sessions.begin() as session:
                current = await session.get(LessonSegment, row.id, with_for_update=True)
                if current.depth_variants != row.depth_variants:
                    raise RuntimeError("Variant changed during correction; refusing overwrite")
                current.depth_variants = variants
                current.needs_review = True
                current.review_reasons = list(
                    dict.fromkeys(
                        [
                            *(current.review_reasons or []),
                            "depth_variant_review_required",
                        ]
                    )
                )
            count += 1
        print(json.dumps({"corrected": count, "teacherApprovalRequired": count}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
