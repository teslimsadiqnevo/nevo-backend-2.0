"""Measure what a Simplify and Expand version and the picture check cost, on real lessons.

The upload has never been priced. This runs both on lessons already in the
database and prints tokens and dollars at published rates, so the number is a
measurement rather than an estimate.

    python scripts/measure_upload_cost.py

Needs DATABASE_URL and AI_ANTHROPIC_API_KEY. Writes nothing. Spends about $0.15.
"""

import asyncio
import base64
import json
import os
import sys
import time
import uuid

import asyncpg
import httpx

from nevo.visuals.service import REVIEW_SCHEMA

try:
    from dotenv import load_dotenv
except ImportError:
    pass
else:
    load_dotenv(".env")
DB = os.environ["DATABASE_URL"].replace("postgresql+asyncpg", "postgresql").split("?")[0]
KEY = os.environ.get("AI_ANTHROPIC_API_KEY")
if not KEY:
    sys.exit("Set AI_ANTHROPIC_API_KEY first.")
HEADERS = {"x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
API = "https://api.anthropic.com/v1/messages"

HAIKU = ("claude-haiku-4-5", 1.0, 5.0)  # model, $ per M input, $ per M output
OPUS = ("claude-opus-4-8", 5.0, 25.0)

# Real 8-9 segment lessons already in the database.
LESSONS = [
    "8ce0f6e8-ee95-4df3-aa1b-f588465d41d5",
    "e77bf0b4-380c-4af8-a061-ef64c3ff3df3",
    "7b187d41-57af-4260-8e8a-a40fda98cabf",
]

VARIANT_SYSTEM = (
    "You rewrite one segment of a school lesson two ways for a child, keeping the "
    "teacher's curriculum.\n"
    "simplified: the same material at a lower reading load. Shorter sentences, plainer "
    "words, simpler syntax. Drop nothing: every fact, number, example and step in the "
    "original must still be there.\n"
    "expanded: the same concept explained further, with more worked development. You may "
    "add an analogy or everyday scenario. Add no new topic and teach nothing beyond what "
    "the segment covers.\n"
    'Return only JSON: {"simplified": "...", "expanded": "..."}'
)

REVIEW_SYSTEM = (
    "You review images used to teach children. Approve an image only if it is "
    "factually correct, numerically exact, clearly readable, relevant to the "
    "lesson, and age-appropriate. Reject anything misleading, mislabelled, "
    "cluttered, or decorative rather than instructional. When rejecting, state "
    "the specific correction the illustrator must make."
)


def cost(model: tuple[str, float, float], usage: dict) -> float:
    return usage["input_tokens"] / 1e6 * model[1] + usage["output_tokens"] / 1e6 * model[2]


async def variants(http: httpx.AsyncClient, body: str) -> tuple[dict, dict]:
    response = await http.post(
        API,
        headers=HEADERS,
        json={
            "model": HAIKU[0],
            "max_tokens": 4096,
            "system": VARIANT_SYSTEM,
            "messages": [{"role": "user", "content": body}],
        },
    )
    data = response.json()
    if "usage" not in data:
        sys.exit(f"Anthropic error: {data}")
    text = data["content"][0]["text"]
    return data["usage"], json.loads(text[text.find("{") : text.rfind("}") + 1])


async def review(http: httpx.AsyncClient, image_url: str, lesson_text: str) -> dict:
    image = (await http.get(image_url)).content
    response = await http.post(
        API,
        headers=HEADERS,
        json={
            "model": OPUS[0],
            "max_tokens": 1024,
            "system": REVIEW_SYSTEM,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64.b64encode(image).decode(),
                            },
                        },
                        {
                            "type": "text",
                            "text": "Review this image against the lesson content below.\n\n"
                            f"Lesson content: {lesson_text}",
                        },
                    ],
                }
            ],
            "output_config": {"format": {"type": "json_schema", "schema": REVIEW_SCHEMA}},
        },
    )
    data = response.json()
    if "usage" not in data:
        sys.exit(f"Anthropic error: {data}")
    return data["usage"]


async def main() -> None:
    db = await asyncpg.connect(DB, ssl="require", statement_cache_size=0)
    async with httpx.AsyncClient(timeout=180) as http:
        print("TEXT VERSIONS (Haiku 4.5, one call per segment)")
        totals = []
        for lesson_id in LESSONS:
            rows = await db.fetch(
                "select body from lesson_segments where lesson_id=$1 order by sequence_order",
                uuid.UUID(lesson_id),
            )
            started = time.time()
            results = await asyncio.gather(*(variants(http, row["body"]) for row in rows))
            usage_in = sum(u["input_tokens"] for u, _ in results)
            usage_out = sum(u["output_tokens"] for u, _ in results)
            lesson_cost = sum(cost(HAIKU, u) for u, _ in results)
            body = sum(len(row["body"]) for row in rows)
            simple = sum(len(v["simplified"]) for _, v in results)
            expanded = sum(len(v["expanded"]) for _, v in results)
            totals.append(lesson_cost)
            print(
                f"  {lesson_id[:8]}: {len(rows)} segments, body {body} chars -> "
                f"simplified {simple}, expanded {expanded}; "
                f"{usage_in} in / {usage_out} out tokens; ${lesson_cost:.4f}; "
                f"{time.time() - started:.0f}s"
            )
        print(f"  average per lesson: ${sum(totals) / len(totals):.4f}")

        print("\nPICTURE CHECK (Opus 4.8, real stored images)")
        rows = await db.fetch(
            "select body, visual_variant->>'imageUrl' url from lesson_segments "
            "where visual_variant->>'imageUrl' is not null limit 3"
        )
        checks = []
        for row in rows:
            usage = await review(http, row["url"], row["body"])
            checks.append(cost(OPUS, usage))
            tokens = f"{usage['input_tokens']} in / {usage['output_tokens']} out tokens"
            print(f"  {tokens}; ${checks[-1]:.4f}")
        print(f"  average per check: ${sum(checks) / len(checks):.4f}")


asyncio.run(main())
