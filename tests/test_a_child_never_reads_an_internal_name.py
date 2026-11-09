"""No child sees a concept key on their result screen.

Finishing Heat Transfer, Chidi read "You explored conductorVsInsulator,
convectionMechanism, radiationAbsorptionReflection, radiationProperties and
radiationVsConvection today", with five ticked rows of the same keys.

The model is asked for the name of an idea and usually writes one - "Energy
transfer in food chains". Sometimes it writes an identifier instead. Fixed on
the way out as well as on the way in, because the lessons already stored have
these in them and a child should stop seeing them today.
"""

from __future__ import annotations

import itertools

import pytest

from nevo.content_parsing.concept_names import readable_concept_name

#: The five Chidi actually read.
HEAT_TRANSFER = (
    "conductorVsInsulator",
    "convectionMechanism",
    "radiationAbsorptionReflection",
    "radiationProperties",
    "radiationVsConvection",
)


@pytest.mark.parametrize("key", HEAT_TRANSFER)
def test_nothing_chidi_read_survives_the_read(key: str) -> None:
    out = readable_concept_name(key)
    assert out != key
    assert "_" not in out
    # No capital in the middle of a word, which is what made them look like code.
    assert not any(left.islower() and right.isupper() for left, right in itertools.pairwise(out))


def test_the_five_read_as_a_sentence_a_child_can_follow() -> None:
    names = [readable_concept_name(key) for key in HEAT_TRANSFER]
    assert names == [
        "Conductor vs insulator",
        "Convection mechanism",
        "Radiation absorption reflection",
        "Radiation properties",
        "Radiation vs convection",
    ]


@pytest.mark.parametrize(
    "key,expected",
    [
        ("average_speed_calculation_practice", "Average speed calculation practice"),
        ("periodGroupDefinition", "Period group definition"),
        ("stack_pitfall", "Stack pitfall"),
        ("membership_vs_subset", "Membership vs subset"),
        ("evaporationDiagram", "Evaporation diagram"),
        ("identifying_acids_and_bases", "Identifying acids and bases"),
    ],
)
def test_the_other_keys_found_in_stored_lessons(key: str, expected: str) -> None:
    assert readable_concept_name(key) == expected


@pytest.mark.parametrize(
    "written",
    [
        "Energy transfer in food chains",
        "Kahn's Algorithm Execution",
        "divide-and-conquer recurrence from code",
        "Set operator pitfall: membership vs subset",
        "ASCII Bit Width",
        "Density",
        "Plant sinks",
    ],
)
def test_a_name_somebody_wrote_is_left_exactly_alone(written: str) -> None:
    """The risk runs both ways: tidying a real name is also a bug.

    All of these are real values from stored lessons. Anything with a space
    in it is somebody's prose, including one with hyphens in it.
    """
    assert readable_concept_name(written) == written


@pytest.mark.parametrize(
    "key,expected",
    [
        ("pHScale", "pH scale"),
        ("mRNATranscription", "mRNA transcription"),
    ],
)
def test_a_lowercase_prefix_keeps_its_meaning(key: str, expected: str) -> None:
    """pH split into "P h" reads as a stray letter rather than a quantity."""
    assert readable_concept_name(key) == expected


@pytest.mark.parametrize("value", [None, 42, [], {}, ""])
def test_a_missing_name_comes_back_empty_rather_than_invented(value) -> None:
    """The caller can see whether anything else names the idea; this cannot.

    An answer with no concept is counted nowhere, rather than lumped under a
    made-up heading.
    """
    assert readable_concept_name(value) == ""


def test_the_result_screen_humanises_rather_than_trusting_the_snapshot() -> None:
    """All three symptoms come off one list, so one call covers them.

    masteredConcepts, the concepts worth another look, and the sentence are
    all derived from the outcomes list, which is where the call goes.
    """
    from nevo.api import product_learning

    source = product_learning.__loader__.get_source(product_learning.__name__)
    outcomes = source[source.index("async def _check_in_outcome") :]
    outcomes = outcomes[: outcomes.index("def _result_note")]
    assert "readable_concept_name(snapshot.get(" in outcomes
    assert 'str(snapshot.get("conceptName")' not in outcomes


def test_the_writer_stops_storing_keys_in_new_lessons() -> None:
    from nevo.content_parsing import service

    source = service.__loader__.get_source(service.__name__)
    assert "readable_concept_name(checkpoint.get(" in source
