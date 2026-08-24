from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_AFFECTIVE_DIR = ROOT / "frontend" / "affective"
HANDOFF_DOC = ROOT / "docs" / "jira" / "FRONTEND_HANDOFF_BACKEND_CONTRACT.md"
SCRUM_53_DOC = ROOT / "docs" / "jira" / "SCRUM-53.md"
SCRUM_70_DOC = ROOT / "docs" / "jira" / "SCRUM-70.md"
SCRUM_26_DOC = ROOT / "docs" / "jira" / "SCRUM-26.md"

RAW_TOUCH_TOKENS = (
    "tap_latency",
    "tap_duration",
    "aborted_gesture",
    "inter_touch_idle",
    "idle_time_between_touches",
    "scroll_pattern",
    "gesture_completion_rate",
)


def _repo_text_files(*roots: Path):
    suffixes = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".css", ".html"}
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            parts = set(path.parts)
            if ".venv" in parts or "__pycache__" in parts or ".git" in parts:
                continue
            yield path


def test_raw_touch_signals_do_not_surface_outside_client_affective_module() -> None:
    checked_files: list[Path] = []
    violations: list[str] = []

    for path in _repo_text_files(ROOT / "src" / "nevo", ROOT / "frontend"):
        if FRONTEND_AFFECTIVE_DIR in path.parents:
            continue
        checked_files.append(path)
        text = path.read_text(encoding="utf-8").casefold()
        for token in RAW_TOUCH_TOKENS:
            if token in text:
                violations.append(f"{path.relative_to(ROOT)} contains {token}")

    assert checked_files
    assert violations == []


def test_handoff_contract_uses_form_factor_neutral_dwell_name() -> None:
    text = HANDOFF_DOC.read_text(encoding="utf-8")
    normalized = " ".join(text.split()).casefold()

    assert "`interaction_dwell_time`" in text
    assert "`cursor_dwell_time`" not in text
    assert "cursor form factors" in normalized
    assert "touch form factors" in normalized
    assert "tap-down and tap-up" in normalized
    assert "do not fabricate cursor dwell" in normalized


def test_referencing_ticket_docs_record_touch_signal_exclusion_guard() -> None:
    for doc in (SCRUM_53_DOC, SCRUM_70_DOC, SCRUM_26_DOC):
        text = " ".join(doc.read_text(encoding="utf-8").split()).casefold()

        assert "raw touch signals never surface" in text
        assert "indexeddb-only" in text
        assert "deleted at session end" in text
        assert "never persisted" in text
        assert "never rendered as a visible label" in text


def test_ops_design_palette_avoids_old_status_tokens() -> None:
    design_suffixes = {".css", ".html", ".js", ".jsx", ".ts", ".tsx"}
    forbidden = ("#7fd1b5", "--good", "green", "red", "amber")
    violations: list[str] = []

    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in design_suffixes:
            continue
        parts = {part.casefold() for part in path.parts}
        name = path.name.casefold()
        if ".venv" in parts or "__pycache__" in parts or ".git" in parts:
            continue
        if "ops" not in parts and "ops" not in name and not name.startswith("j"):
            continue
        text = path.read_text(encoding="utf-8").casefold()
        for token in forbidden:
            if token in text:
                violations.append(f"{path.relative_to(ROOT)} contains {token}")

    assert violations == []
