"""Compare lesson-only safety verdicts on the same synthetic labelled cases.

Run from the repository root with PYTHONPATH=src. No child chat, panel answer,
roster data, or uploaded school document is read by this script.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from nevo.ai_gateway.safety import ContentSafetyGuard, SafetyBlocked, SafetyUnavailable

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evaluations" / "lesson_safety_cases.json"


class ObservedClient(httpx.AsyncClient):
    def __init__(self):
        super().__init__(timeout=30)
        self.verdict = None

    async def post(self, *args, **kwargs):
        response = await super().post(*args, **kwargs)
        if response.is_success:
            body = response.json()
            tools = [part for part in body.get("content", []) if part.get("type") == "tool_use"]
            self.verdict = tools[0].get("input") if tools else None
        return response


async def current_checker(case, client, key):
    client.verdict = None
    guard = ContentSafetyGuard(
        api_key=key,
        base_url=os.getenv("AI_ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
        model=os.getenv("AI_ANTHROPIC_MODEL", "claude-haiku-4-5"),
        version=os.getenv("AI_ANTHROPIC_VERSION", "2023-06-01"),
        client=client,
    )
    try:
        await guard.check(case["text"], phase=case["phase"])
        outcome = "allow"
    except SafetyBlocked:
        outcome = "withhold"
    except SafetyUnavailable:
        outcome = "error"
    return outcome, client.verdict


async def openai_checker(case, client, key):
    response = await client.post(
        "https://api.openai.com/v1/moderations",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "omni-moderation-latest", "input": case["text"]},
    )
    response.raise_for_status()
    result = response.json()["results"][0]
    return ("withhold" if result["flagged"] else "allow"), {
        "categories": [name for name, flagged in result["categories"].items() if flagged],
        "scores": result["category_scores"],
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("current", "openai"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    key = os.getenv("AI_ANTHROPIC_API_KEY" if args.provider == "current" else "OPENAI_API_KEY")
    if not key:
        raise SystemExit(f"{args.provider} key is not configured locally")
    cases = json.loads(CASES.read_text())
    rows = []
    async with ObservedClient() as client:
        for case in cases:
            try:
                if args.provider == "current":
                    actual, detail = await current_checker(case, client, key)
                else:
                    actual, detail = await openai_checker(case, client, key)
            except (httpx.HTTPError, KeyError, ValueError) as error:
                actual, detail = "error", {"errorType": type(error).__name__}
            rows.append({
                "id": case["id"], "label": case["label"], "actual": actual,
                "matched": actual == case["label"], "detail": detail,
            })
            print(f"{case['id']}: {actual}", flush=True)
    summary = {
        "provider": args.provider,
        "dataset": str(CASES.relative_to(ROOT)),
        "labelStatus": "provisional; requires Lydia review",
        "cases": len(rows),
        "falseBlocks": sum(row["label"] == "allow" and row["actual"] == "withhold" for row in rows),
        "unsafeMisses": sum(row["label"] == "withhold" and row["actual"] == "allow" for row in rows),
        "errors": sum(row["actual"] == "error" for row in rows),
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
