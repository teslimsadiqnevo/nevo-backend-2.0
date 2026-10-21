"""Remove legacy boilerplate; restore the demo's observation from its original upload."""

import argparse
import asyncio
import json
import re
from collections import Counter
from uuid import UUID

from sqlalchemy import select

from nevo.api.frontend_unblockers import _extract_text
from nevo.content_parsing.activity import source_activity_observations
from nevo.core.config import get_settings
from nevo.db.models.content import LessonSegment
from nevo.db.models.product import UploadJob, UploadSourceBlob
from nevo.db.session import create_engine, create_session_factory

OSMOSIS = UUID("3367de9d-be40-4704-8a95-7a197b9824dc")
UPLOAD = UUID("f797428f-2674-4584-81f6-919b28110e5d")
PREVIOUS_DEMO_OUTCOME = (
    "Observe that the yam strip in plain water has absorbed water by osmosis, becoming firmer "
    "and slightly longer, while the yam strip in salt water has lost water by osmosis, "
    "becoming softer and shorter."
)


def clean_structure(value):
    if isinstance(value, list):
        return [clean_structure(item) for item in value]
    if not isinstance(value, dict):
        return value
    value = {key: clean_structure(item) for key, item in value.items()}
    if value.get("type") == "activity" and "steps" in value:
        value = source_activity_observations(value, None)
    return value


async def main(apply=False):
    engine = create_engine(get_settings().database_url)
    counts = Counter()
    try:
        async with create_session_factory(engine).begin() as session:
            for row in await session.scalars(select(LessonSegment)):
                original = row.interactive_variant
                cleaned = source_activity_observations(original, None)
                if cleaned != original:
                    counts["activity_observations_cleaned"] += 1
                    if apply:
                        row.interactive_variant = cleaned
                if row.lesson_id == OSMOSIS and row.sequence_order == 4:
                    blob = await session.get(UploadSourceBlob, UPLOAD)
                    if blob is None:
                        raise ValueError("Original Osmosis upload missing; no observation invented")
                    source = _extract_text(blob.filename, blob.content)
                    match = re.search(
                        r"What you should see:\s*(.*?)\s*Practice questions", source, re.S
                    )
                    if match is None or len((original or {}).get("steps", [])) != 6:
                        raise ValueError("Demo source/steps changed; manual review required")
                    authored = " ".join(match.group(1).split())
                    if original.get("outcome") not in {PREVIOUS_DEMO_OUTCOME, authored}:
                        raise ValueError(
                            "Demo outcome changed; refusing to overwrite a possible edit"
                        )
                    restored = {
                        **{k: v for k, v in cleaned.items() if k != "inProgress"},
                        "outcome": authored,
                    }
                    if restored != original:
                        counts["osmosis_authored_outcome_restored"] += 1
                        if apply:
                            row.interactive_variant = restored
                    counts["osmosis_steps_preserved"] = 6
            for job in await session.scalars(select(UploadJob)):
                cleaned = clean_structure(job.structure)
                if cleaned != job.structure:
                    counts["staged_structures_cleaned"] += 1
                    if apply:
                        job.structure = cleaned
            if not apply:
                await session.rollback()
        print(json.dumps({"applied": apply, "counts": dict(counts)}, sort_keys=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
