"""Replay saved source PDFs through v1 parsing on an isolated local database.

SOURCE_DATABASE_URL is read-only. STAGING_DATABASE_URL must point to localhost.
The rejected text stays in the staging database's restricted safety record.
"""

import argparse
import asyncio
import os
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.wiring import build_ai_gateway
from nevo.api.frontend_unblockers import _extract_text
from nevo.content_parsing.entities import ContentParseRequest, ParsedLessonSegment
from nevo.content_parsing.repositories import SqlAlchemyContentParsingRepository
from nevo.content_parsing.service import ContentParsingService
from nevo.db.models.safety import ContentSafetyEvent
from nevo.domain.intelligence.vocabulary import LessonSourceType

SOURCES = {
    "food-chains": UUID("5815fe01-a7f3-47f8-bf2a-ddd74ed55ccd"),
    "separation-of-mixtures": UUID("410c9ec6-6451-4f99-90e7-234453f53f81"),
}
STAGING_TEACHER_ID = UUID("a8d763a1-f89c-4dde-9322-53a583128959")


class ParseWithoutOptionalRewrites(ContentParsingService):
    async def _generate_segment_depth(
        self, segment: ParsedLessonSegment, *args: object, **kwargs: object
    ) -> ParsedLessonSegment:
        return segment


async def run(label: str, count: int, source_url: str, staging_url: str) -> None:
    parsed = urlparse(staging_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("STAGING_DATABASE_URL must point to a local PostgreSQL database")
    if not source_url or source_url == staging_url:
        raise SystemExit("Provide distinct SOURCE_DATABASE_URL and STAGING_DATABASE_URL")

    source = await asyncpg.connect(source_url, ssl="require")
    try:
        async with source.transaction(readonly=True):
            row = await source.fetchrow(
                "SELECT filename, content FROM upload_source_blobs WHERE upload_id = $1",
                SOURCES[label],
            )
            prompt_hash = await source.fetchval(
                "SELECT md5(system_template || user_template) FROM ai_prompt_templates "
                "WHERE name = 'content_parse.default' AND active"
            )
    finally:
        await source.close()
    if row is None or not row["filename"].lower().endswith(".pdf"):
        raise SystemExit("The expected saved PDF source was not found")

    engine = create_async_engine(staging_url, pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as connection:
            local_hash = await connection.exec_driver_sql(
                "SELECT md5(system_template || user_template) FROM ai_prompt_templates "
                "WHERE name = 'content_parse.default' AND active"
            )
            local_hash = local_hash.scalar_one()
        if local_hash != prompt_hash:
            raise SystemExit("Staging and production active parse prompts differ")

        settings = AiGatewaySettings(safety_policy_v2_enabled=False)
        gateway = build_ai_gateway(sessions, settings)
        if not gateway.configured or not gateway.safety_guard.configured:
            raise SystemExit("Local AI generation and safety keys must be configured")
        if gateway.safety_guard._policy_v2:
            raise SystemExit("This reproducer must use v1 safety decisions")
        parser = ParseWithoutOptionalRewrites(
            repository=SqlAlchemyContentParsingRepository(sessions), ai_gateway=gateway
        )
        source_text = _extract_text(row["filename"], bytes(row["content"]))
        request = ContentParseRequest(
            title=row["filename"].rsplit(".", 1)[0],
            source_type=LessonSourceType.PDF,
            source_text=source_text,
            source_metadata={"subject": "Science", "sourceFile": row["filename"]},
        )
        for number in range(1, count + 1):
            started = datetime.now(UTC)
            try:
                parsed_lesson = await parser.parse(
                    request=request, requested_by_user_id=STAGING_TEACHER_ID
                )
                result = f"stored:{parsed_lesson.status.value}"
            except Exception as error:
                cause = error.__cause__
                if isinstance(cause, httpx.HTTPStatusError):
                    detail = f"http_{cause.response.status_code}"
                else:
                    detail = type(cause).__name__ if cause else "none"
                result = f"error:{type(error).__name__}:{detail}"
            async with sessions() as session:
                events = (
                    await session.scalars(
                        select(ContentSafetyEvent)
                        .where(ContentSafetyEvent.created_at >= started)
                        .order_by(ContentSafetyEvent.created_at)
                    )
                ).all()
            blocked = [
                event
                for event in events
                if event.phase.startswith("output:") and event.action in {"block", "safeguard"}
            ]
            print(
                f"{label} run={number}/{count} result={result} "
                f"source_checks={sum(event.phase == 'lesson_source' for event in events)} "
                f"output_checks={sum(event.phase.startswith('output:') for event in events)} "
                f"generated_blocks={len(blocked)} "
                f"captured={sum(event.review_material is not None for event in blocked)} "
                f"event_ids={','.join(str(event.id) for event in blocked)}",
                flush=True,
            )
            if number < count:
                await asyncio.sleep(10)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=tuple(SOURCES))
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        raise SystemExit("--runs must be between 1 and 10")
    asyncio.run(
        run(
            args.source,
            args.runs,
            os.environ.get("SOURCE_DATABASE_URL", ""),
            os.environ.get("STAGING_DATABASE_URL", ""),
        )
    )


if __name__ == "__main__":
    main()
