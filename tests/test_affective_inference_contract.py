from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "frontend" / "affective" / "affective_inference.js"
DOC = ROOT / "docs" / "jira" / "AFFECTIVE_INFERENCE_ENGINE.md"


def source() -> str:
    return MODULE.read_text(encoding="utf-8")


def test_affective_engine_is_client_side_only() -> None:
    text = source()

    assert "indexedDB.open" in text
    assert "indexedDB.deleteDatabase(DB_NAME)" in text
    forbidden_transport = (
        "fetch(",
        "XMLHttpRequest",
        "sendBeacon",
        "WebSocket",
        "EventSource",
        "localStorage",
        "sessionStorage",
    )
    for token in forbidden_transport:
        assert token not in text


def test_affective_states_and_touch_contract_are_declared() -> None:
    text = source()

    for state in ("neutral", "anxiety", "boredom", "frustration", "confusion"):
        assert state in text
    for form_factor in ("tablet_touch", "desktop_cursor", "mobile_touch"):
        assert form_factor in text
    for signal in (
        "tap_latency",
        "tap_duration",
        "aborted_gesture",
        "inter_touch_idle",
        "scroll_pattern",
        "gesture_completion_rate",
    ):
        assert signal in text
    assert "cursor_dwell_time" not in text


def test_affective_engine_has_no_backend_route_or_database_model() -> None:
    backend_files = [
        path
        for path in (ROOT / "src" / "nevo").rglob("*.py")
        if path.name != "__init__.py"
    ]
    backend_text = "\n".join(
        path.read_text(encoding="utf-8") for path in backend_files
    )

    assert "affective" not in backend_text.casefold()
    assert "Affective" not in backend_text


def test_documentation_records_the_non_persistence_boundary() -> None:
    text = DOC.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "does not receive, persist, or infer" in normalized
    assert "cleanupAffectiveSession()" in text
    assert "productive confusion" in text.casefold()
    assert "motor_baseline_ms" in text
    assert "attention_d_prime" in text
