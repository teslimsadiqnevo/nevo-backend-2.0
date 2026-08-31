"""Which lessons a confirmed upload should produce."""
from nevo.api.product_learning import _structure_lessons


def test_a_split_unit_produces_one_entry_per_lesson() -> None:
    structure = {
        "lessonId": "L1",
        "modules": [{"title": "M1", "segmentIds": ["a"]}],
        "lessons": [
            {"lessonId": "L1", "title": "Part one", "modules": [{"segmentIds": ["a", "b"]}]},
            {"lessonId": "L2", "title": "Part two", "modules": [{"segmentIds": ["c"]}]},
        ],
    }

    entries = _structure_lessons(structure)

    assert len(entries) == 2
    assert [entry["title"] for entry in entries] == ["Part one", "Part two"]


def test_an_unsplit_upload_still_produces_one_lesson() -> None:
    """A console that has not adopted lessons[] must keep working."""
    structure = {"lessonId": "L1", "modules": [{"title": "M1", "segmentIds": ["a", "b"]}]}

    entries = _structure_lessons(structure)

    assert len(entries) == 1
    assert entries[0]["lessonId"] == "L1"
    assert entries[0]["modules"] == [{"title": "M1", "segmentIds": ["a", "b"]}]


def test_an_empty_lessons_list_falls_back_rather_than_dropping_the_lesson() -> None:
    structure = {"lessonId": "L1", "modules": [{"segmentIds": ["a"]}], "lessons": []}

    entries = _structure_lessons(structure)

    assert len(entries) == 1
    assert entries[0]["lessonId"] == "L1"


def test_non_object_entries_are_ignored() -> None:
    structure = {
        "lessonId": "L1",
        "modules": [],
        "lessons": ["nonsense", {"lessonId": "L1", "modules": []}],
    }

    entries = _structure_lessons(structure)

    assert entries == [{"lessonId": "L1", "modules": []}]


def test_a_structure_with_no_modules_at_all_is_tolerated() -> None:
    entries = _structure_lessons({"lessonId": "L1"})

    assert entries == [{"lessonId": "L1", "modules": []}]
