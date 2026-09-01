"""What the seeded Ask Nevo prompts must tell the model.

These pin the instructions the tool loop depends on. Losing any of them turns
the assistant back into something that answers from what it was handed.
"""
import re
from pathlib import Path

MIGRATION = Path("alembic/versions/20260901_0036_ask_nevo_tool_prompts.py")
SOURCE = MIGRATION.read_text()


def prompts() -> dict[str, str]:
    namespace: dict[str, object] = {}
    # Execute only the constant assignments, not the migration body.
    body = SOURCE.split("DEACTIVATE =")[0]
    exec(compile(body, str(MIGRATION), "exec"), namespace)
    return {"student": str(namespace["STUDENT"]), "teacher": str(namespace["TEACHER"])}


def test_both_roles_are_told_to_use_their_tools() -> None:
    for prompt in prompts().values():
        assert "Use them" in prompt


def test_both_roles_are_told_to_look_up_an_unfamiliar_learner() -> None:
    for prompt in prompts().values():
        assert "find_learners" in prompt


def test_both_roles_are_told_the_code_is_the_learner_identifier() -> None:
    """The model must use the pseudonym in its answer for rehydration to work."""
    for prompt in prompts().values():
        assert "Learner-A1B2C3" in prompt
        assert "never be shown a real name" in prompt


def test_the_model_is_told_not_to_apologise_for_the_code() -> None:
    """It is replaced before the user sees it, so explaining it reads as broken."""
    for prompt in prompts().values():
        assert "never explain the code" in prompt


def test_a_refusal_is_final_rather_than_something_to_route_around() -> None:
    for prompt in prompts().values():
        assert "not_permitted" in prompt
        assert "do not try another route" in prompt


def test_answers_must_rest_on_tool_output() -> None:
    for prompt in prompts().values():
        assert "Base every claim on something a tool returned" in prompt


def test_the_shape_guidance_from_the_previous_version_survives() -> None:
    for prompt in prompts().values():
        assert "Match the shape to the answer" in prompt


def test_the_student_prompt_keeps_its_privacy_constraints() -> None:
    student = prompts()["student"]

    assert "Never reveal raw learner" in student
    assert "age-appropriately" in student


def test_the_migration_supersedes_rather_than_edits_the_previous_version() -> None:
    """Prompts are versioned; a partial unique index allows one active row."""
    assert "version = 2" in SOURCE
    assert re.search(r"active\s*=\s*false", SOURCE)
