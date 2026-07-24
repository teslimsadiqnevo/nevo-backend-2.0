from nevo.db.models.content import ContentParseRun, Lesson, LessonSegment


def test_lessons_and_segments_are_mapped() -> None:
    assert Lesson.__tablename__ == "lessons"
    assert ContentParseRun.__tablename__ == "content_parse_runs"
    assert LessonSegment.__tablename__ == "lesson_segments"

    lesson_columns = {column.name for column in Lesson.__table__.columns}
    assert {
        "school_id",
        "created_by_user_id",
        "source_type",
        "source_reference",
        "status",
    }.issubset(lesson_columns)

    segment_columns = {column.name for column in LessonSegment.__table__.columns}
    assert {
        "content_type",
        "sequence_order",
        "available_modalities",
        "comprehension_checkpoints",
        "text_variant",
        "visual_variant",
        "audio_variant",
        "interactive_variant",
        "calculation_variant",
        "needs_review",
    }.issubset(segment_columns)
