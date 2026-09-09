"""Ask Nevo tool layer: authorization first, then behaviour.

The model is an untrusted caller. Every identifier it supplies has to be
resolved against the asking user's own accessible set, so these tests are
mostly about what a tool refuses.
"""
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from nevo.ai_gateway.privacy import AiPrivacyGuard
from nevo.ask_nevo.directory import DirectoryEntry, PseudonymDirectory
from nevo.ask_nevo.tools import (
    NOT_FOUND,
    NOT_PERMITTED,
    TOOL_SCHEMAS,
    ToolContext,
    execute_tool,
)
from nevo.domain.accounts.vocabulary import UserRole
from nevo.domain.ask_nevo.vocabulary import AskNevoRole

AMARA = UUID("aaaaaaaa-0000-4000-8000-000000000001")
DARA = UUID("aaaaaaaa-0000-4000-8000-000000000002")
OUTSIDER = UUID("bbbbbbbb-0000-4000-8000-000000000009")


def directory(*students: tuple[UUID, str]) -> PseudonymDirectory:
    return PseudonymDirectory(
        tuple(
            DirectoryEntry(
                student_id=student_id,
                pseudonym=AiPrivacyGuard.pseudonym(student_id),
                display_name=name,
            )
            for student_id, name in students
        )
    )


def context(directory_: PseudonymDirectory) -> ToolContext:
    return ToolContext(session=None, actor=None, directory=directory_)  # type: ignore[arg-type]


# --- the pseudonym boundary ------------------------------------------------


def test_a_learner_in_scope_resolves() -> None:
    book = directory((AMARA, "Amara Okafor"))

    entry = book.resolve(AiPrivacyGuard.pseudonym(AMARA))

    assert entry is not None
    assert entry.student_id == AMARA


def test_a_learner_outside_the_actors_scope_does_not_resolve() -> None:
    """The whole authorization model rests on this."""
    book = directory((AMARA, "Amara Okafor"))

    assert book.resolve(AiPrivacyGuard.pseudonym(OUTSIDER)) is None


def test_an_invented_pseudonym_does_not_resolve() -> None:
    book = directory((AMARA, "Amara Okafor"))

    assert book.resolve("Learner-DEADBEEF") is None
    assert book.resolve("") is None


def test_resolution_ignores_case_and_padding() -> None:
    book = directory((AMARA, "Amara Okafor"))
    code = AiPrivacyGuard.pseudonym(AMARA)

    assert book.resolve(f"  {code.lower()}  ") is not None


# --- tool authorization ----------------------------------------------------


async def test_learner_overview_refuses_a_learner_out_of_scope() -> None:
    result = await execute_tool(
        context(directory((AMARA, "Amara Okafor"))),
        "get_learner_overview",
        {"learner": AiPrivacyGuard.pseudonym(OUTSIDER)},
    )

    assert result == NOT_PERMITTED


async def test_recent_flags_refuses_a_learner_out_of_scope() -> None:
    result = await execute_tool(
        context(directory((AMARA, "Amara Okafor"))),
        "get_recent_flags",
        {"learner": AiPrivacyGuard.pseudonym(OUTSIDER)},
    )

    assert result == NOT_PERMITTED


async def test_class_overview_refuses_an_unparseable_id() -> None:
    result = await execute_tool(
        context(directory()), "get_class_overview", {"class_id": "not-a-uuid"}
    )

    assert result == NOT_FOUND


async def test_an_unknown_tool_is_reported_not_raised() -> None:
    result = await execute_tool(context(directory()), "drop_all_tables", {})

    assert result["error"] == "unknown_tool"


async def test_bad_arguments_are_reported_not_raised() -> None:
    """A refusal has to be a value, so the model can explain it."""
    result = await execute_tool(
        context(directory()), "get_learner_overview", {"learner": None}
    )

    assert result == NOT_PERMITTED


# --- find_learners ---------------------------------------------------------


async def test_find_learners_lists_only_the_actors_own_scope() -> None:
    book = directory((AMARA, "Amara Okafor"), (DARA, "Dara Ibrahim"))

    result = await execute_tool(context(book), "find_learners", {})

    codes = {item["learner"] for item in result["learners"]}
    assert codes == {AiPrivacyGuard.pseudonym(AMARA), AiPrivacyGuard.pseudonym(DARA)}
    assert result["total"] == 2


async def test_find_learners_never_returns_a_real_name() -> None:
    book = directory((AMARA, "Amara Okafor"))

    result = await execute_tool(context(book), "find_learners", {})

    assert "Amara" not in str(result)
    assert "Okafor" not in str(result)


async def test_find_learners_filters_by_code() -> None:
    book = directory((AMARA, "Amara Okafor"), (DARA, "Dara Ibrahim"))
    code = AiPrivacyGuard.pseudonym(AMARA)

    result = await execute_tool(context(book), "find_learners", {"query": code})

    assert [item["learner"] for item in result["learners"]] == [code]


async def test_a_student_actor_sees_only_themselves() -> None:
    """Built from the accessible set, so a student's directory has one entry."""
    book = directory((AMARA, "Amara Okafor"))

    result = await execute_tool(context(book), "find_learners", {})

    assert result["total"] == 1


# --- rehydration -----------------------------------------------------------


def test_rehydrate_restores_names_only_on_the_way_out() -> None:
    book = directory((AMARA, "Amara Okafor"))
    code = AiPrivacyGuard.pseudonym(AMARA)

    assert book.rehydrate(f"{code} is secure on halves.") == "Amara Okafor is secure on halves."


def test_rehydrate_handles_several_learners_in_one_answer() -> None:
    book = directory((AMARA, "Amara Okafor"), (DARA, "Dara Ibrahim"))
    answer = (
        f"{AiPrivacyGuard.pseudonym(AMARA)} is ahead of "
        f"{AiPrivacyGuard.pseudonym(DARA)}."
    )

    assert book.rehydrate(answer) == "Amara Okafor is ahead of Dara Ibrahim."


def test_rehydrate_leaves_an_unknown_code_alone() -> None:
    """Better a visible code than a wrong name."""
    book = directory((AMARA, "Amara Okafor"))

    assert book.rehydrate("Learner-UNKNOWN did well.") == "Learner-UNKNOWN did well."


def test_a_learner_with_no_name_still_reads_naturally() -> None:
    book = PseudonymDirectory(
        (
            DirectoryEntry(
                student_id=AMARA,
                pseudonym=AiPrivacyGuard.pseudonym(AMARA),
                display_name="This learner",
            ),
        )
    )

    assert book.rehydrate(f"{AiPrivacyGuard.pseudonym(AMARA)} is fine.") == "This learner is fine."


# --- schemas ---------------------------------------------------------------


def test_every_tool_schema_is_well_formed() -> None:
    for schema in TOOL_SCHEMAS:
        assert schema["name"]
        assert schema["description"]
        assert schema["input_schema"]["type"] == "object"
        assert "properties" in schema["input_schema"]


def test_every_declared_tool_is_executable() -> None:
    """A schema with no handler would be a tool the model can call into nothing."""
    from nevo.ask_nevo.tools import _HANDLERS

    declared = {schema["name"] for schema in TOOL_SCHEMAS}

    assert declared == set(_HANDLERS)


async def test_a_tool_that_falls_over_refuses_rather_than_raising() -> None:
    """One broken lookup must not take the whole answer with it."""
    actor = SimpleNamespace(id=uuid4(), school_id=None, role=UserRole.STUDENT)
    ctx = ToolContext(
        session=None,  # type: ignore[arg-type]
        actor=actor,
        directory=directory(),
        role=AskNevoRole.STUDENT,
    )

    result = await execute_tool(ctx, "get_my_progress", {})

    assert result["error"] == "unavailable"


async def test_a_tool_is_refused_to_a_role_that_was_not_offered_it() -> None:
    """The offered list is a convenience; the gate is checked on execution."""
    actor = SimpleNamespace(id=uuid4(), school_id=None, role=UserRole.STUDENT)
    ctx = ToolContext(
        session=None,  # type: ignore[arg-type]
        actor=actor,
        directory=directory(),
        role=AskNevoRole.STUDENT,
    )

    result = await execute_tool(ctx, "get_recent_flags", {})

    assert result["error"] == "not_permitted"


def test_the_tool_descriptions_tell_the_model_names_are_unavailable() -> None:
    finder = next(item for item in TOOL_SCHEMAS if item["name"] == "find_learners")

    assert "never see real names" in finder["description"]


@pytest.mark.parametrize("tool", [item["name"] for item in TOOL_SCHEMAS])
def test_no_tool_takes_a_school_id(tool: str) -> None:
    """School scope comes from the actor, never from an argument."""
    schema = next(item for item in TOOL_SCHEMAS if item["name"] == tool)

    assert "school_id" not in schema["input_schema"]["properties"]


# --- what a teacher should never be shown ----------------------------------


def test_the_learner_payload_exposes_no_internals() -> None:
    """The model narrates whatever it is handed.

    A teacher told about a "profile version" learns nothing and starts
    doubting the data, so those fields must not be in the payload at all
    rather than relying on the prompt to suppress them.
    """
    import inspect

    from nevo.ask_nevo import tools

    body = inspect.getsource(tools._get_learner_overview)

    for leaked in ("profile.version", "observed_event_count", "last_evaluated_at"):
        assert leaked not in body, leaked


def test_the_learner_payload_says_whether_a_profile_exists_in_plain_words() -> None:
    import inspect

    from nevo.ask_nevo import tools

    body = inspect.getsource(tools._get_learner_overview)

    assert "has_learning_profile" in body
    assert "Not enough lessons yet" in body


def test_session_outcomes_are_plain_words_not_status_tokens() -> None:
    from nevo.ask_nevo.tools import _session_outcome
    from nevo.domain.signal_events.vocabulary import LessonCompletionStatus

    assert _session_outcome(LessonCompletionStatus.COMPLETED) == "finished"
    assert _session_outcome(LessonCompletionStatus.IN_PROGRESS) == "still open"
    assert _session_outcome(LessonCompletionStatus.EXITED) == "left early"


def test_every_completion_status_has_plain_words() -> None:
    """A new status must not surface as a raw token."""
    from nevo.ask_nevo.tools import _session_outcome
    from nevo.domain.signal_events.vocabulary import LessonCompletionStatus

    for status in LessonCompletionStatus:
        assert _session_outcome(status) != "unknown", status


def test_dates_read_the_way_a_teacher_would_say_them() -> None:
    from datetime import UTC, datetime

    from nevo.ask_nevo.tools import _date

    assert _date(datetime(2026, 8, 28, 9, 30, tzinfo=UTC)) == "28 August"
    assert _date(None) is None


def test_each_asker_is_offered_only_tools_that_can_work_for_them() -> None:
    """Every role used to get the same six, so a learner was handed
    get_class_overview - a tool that can only ever refuse for them."""
    from nevo.ask_nevo.tools import schemas_for

    for role in AskNevoRole:
        offered = {schema["name"] for schema in schemas_for(role)}
        assert offered, role

    student = {s["name"] for s in schemas_for(AskNevoRole.STUDENT)}
    parent = {s["name"] for s in schemas_for(AskNevoRole.PARENT)}
    teacher = {s["name"] for s in schemas_for(AskNevoRole.TEACHER)}
    admin = {s["name"] for s in schemas_for(AskNevoRole.ADMIN)}

    # A learner and a parent never reach the roster.
    for roster_tool in ("find_learners", "get_class_overview", "get_recent_flags"):
        assert roster_tool not in student
        assert roster_tool not in parent

    # A parent's tools are about their own children and nothing else.
    assert parent == {"get_my_children", "get_child_progress"}

    # A teacher does not get the school-wide administrative reads.
    assert "get_school_overview" not in teacher
    assert "get_consent_status" not in teacher
    assert {"get_school_overview", "get_consent_status"} <= admin


def test_the_offered_schemas_carry_no_gating_to_the_model() -> None:
    """`roles` is ours; sending it would just be noise in the tool definition."""
    from nevo.ask_nevo.tools import schemas_for

    for schema in schemas_for(AskNevoRole.ADMIN):
        assert set(schema) == {"name", "description", "input_schema"}


def test_no_tool_lets_a_learner_name_someone_else() -> None:
    """A student's tools take no learner argument at all - they are about the
    asker, so there is nothing to point somewhere else."""
    from nevo.ask_nevo.tools import schemas_for

    for schema in schemas_for(AskNevoRole.STUDENT):
        properties = schema["input_schema"]["properties"]
        assert "learner" not in properties, schema["name"]
        assert "student_id" not in properties, schema["name"]
        assert "class_id" not in properties, schema["name"]
