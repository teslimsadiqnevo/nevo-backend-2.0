from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_local_intelligence_layers_do_not_call_ai_gateway() -> None:
    local_modules = (
        ROOT / "src" / "nevo" / "intelligence" / "adaptation.py",
        ROOT / "src" / "nevo" / "intelligence" / "accommodations.py",
        ROOT / "src" / "nevo" / "intelligence" / "breaks.py",
        ROOT / "src" / "nevo" / "mastery" / "engine.py",
        ROOT / "src" / "nevo" / "scheduler" / "fsrs.py",
    )
    forbidden = (
        "AiGenerationRequest",
        "AiGatewayService",
        "prompt_name=",
        ".generate(",
    )

    violations: list[str] = []
    for path in local_modules:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                violations.append(f"{path.relative_to(ROOT)} contains {token}")

    assert violations == []


def test_model_routing_docs_record_haiku_sonnet_and_batch_rules() -> None:
    text = (ROOT / "docs" / "jira" / "AI_MODEL_ROUTING.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(text.split()).casefold()

    assert "claude-haiku-4-5" in text
    assert "claude-sonnet" in text
    assert "opus" in normalized
    assert "prompt caching is enabled by default" in normalized
    assert "batch" in normalized
    assert "intelligence layer stays local" in normalized
