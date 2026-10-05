from sqlalchemy import Enum, ForeignKeyConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def enum_values(table_name: str, column_name: str) -> list[str]:
    column = Base.metadata.tables[table_name].columns[column_name]
    assert isinstance(column.type, Enum)
    return list(column.type.enums)


def foreign_key_targets(table_name: str) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    for constraint in Base.metadata.tables[table_name].constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            for element in constraint.elements:
                targets.add((element.column.table.name, element.column.name))
    return targets


def index_column_sets(table_name: str) -> dict[str, tuple[str, ...]]:
    return {
        index.name or "": tuple(column.name for column in index.columns)
        for index in Base.metadata.tables[table_name].indexes
        if isinstance(index, Index)
    }


def test_signal_events_table_exists_with_required_columns() -> None:
    table = Base.metadata.tables["signal_events"]

    assert set(table.columns.keys()) == {
        "id",
        "student_id",
        "session_id",
        "event_type",
        "event_data",
        "timestamp",
    }
    assert isinstance(table.columns["event_data"].type, JSONB)


def test_signal_event_type_enum_is_exact() -> None:
    assert enum_values("signal_events", "event_type") == [
        "time_on_segment",
        "replay",
        "scroll",
        "simplify_trigger",
        "expand_trigger",
        "slower_trigger",
        "comprehension_response",
        "exit_attempt",
        "break_suggested",
        "break_taken",
        # "Not now", which nothing could report. Ask B40.
        "break_declined",
        "break_start",
        "break_end",
        "feeling_checkin",
        "module_boundary_reached",
        # What the child chose there: "continue" or "break". The client has
        # been emitting it and dropping it at the door, because it filters
        # every event against a copy of this list before posting.
        "module_boundary_action",
        "engagement_signal",
        "modality_suggestion_shown",
        "modality_suggestion_accepted",
        "modality_suggestion_declined",
        "modality_suggestion_ignored",
        "modality_switch_outcome",
        "modality_manual_switch",
        "calculation_step_response",
        "calculation_complete",
        "narration_played",
        "narration_replayed",
        "manipulative_piece_placed",
        "ask_nevo_question_student",
        "ask_nevo_question_teacher",
        "ask_nevo_cannot_help",
        "ask_nevo_redirect_used",
        "adaptation_suppressed",
        # The student console was dropping all of these at the door: the
        # client filters every event against a copy of this enum before
        # posting, because one unknown type refuses the whole batch. Asks
        # B12, B13 and B20.
        "media_load_failed",
        "system_busy",
        "tap_blocked",
        "session_context",
        "baseline_module_start",
        "baseline_module_complete",
        "baseline_submitted",
        "hint_offered",
        "hint_used",
        "step_up_offered",
        "step_up_accepted",
        "step_up_declined",
        "guided_question_shown",
        "guided_question_answered",
    ]


def test_signal_events_are_student_scoped() -> None:
    assert ("users", "id") in foreign_key_targets("signal_events")


def test_signal_event_query_indexes_match_ticket_contract() -> None:
    indexes = index_column_sets("signal_events")

    assert indexes["ix_signal_events_student_session"] == (
        "student_id",
        "session_id",
    )
    assert indexes["ix_signal_events_student_timestamp"] == (
        "student_id",
        "timestamp",
    )
    assert indexes["ix_signal_events_type_timestamp"] == (
        "event_type",
        "timestamp",
    )


def test_lesson_sessions_table_tracks_resume_and_counts() -> None:
    table = Base.metadata.tables["lesson_sessions"]

    assert set(table.columns.keys()) == {
        "id",
        "student_id",
        "lesson_id",
        "session_type",
        "started_at",
        "ended_at",
        "completion_status",
        "exit_position",
        "break_count",
        "proactive_adjustments_count",
        # SCRUM-178: a lesson where nothing landed is re-run at lower depth,
        # and the re-run has to know it is one and what it came from.
        "delivery_depth",
        "rerouted_from_session_id",
        "created_at",
        "updated_at",
    }
    assert enum_values("lesson_sessions", "completion_status") == [
        "in_progress",
        "completed",
        "exited",
    ]
    assert ("users", "id") in foreign_key_targets("lesson_sessions")


def test_lesson_session_indexes_support_student_and_lesson_queries() -> None:
    indexes = index_column_sets("lesson_sessions")

    assert indexes["ix_lesson_sessions_student_started_at"] == (
        "student_id",
        "started_at",
    )
    assert indexes["ix_lesson_sessions_lesson_started_at"] == (
        "lesson_id",
        "started_at",
    )
