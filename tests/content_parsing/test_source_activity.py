from nevo.api.lesson_contracts import InteractiveActivityVariant
from nevo.api.response_models import OfflinePackageModalityVariants
from nevo.content_parsing.activity import source_activity_observations
from nevo.content_parsing.service import _interactive_variant


def test_activity_without_outcome_keeps_its_real_steps():
    activity = _interactive_variant(
        {"steps": [{"instruction": "Observe a leaf."}, {"text": "Draw the veins."}]},
        "Observe a leaf. Draw the veins.",
    )
    assert activity is not None
    assert len(activity["steps"]) == 2
    assert "outcome" not in activity
    assert "inProgress" not in activity


def test_source_experiment_is_recovered_without_inventing_or_losing_safety():
    source = (
        "We can test a leaf for starch. Take a leaf from a plant in sunlight. "
        "Boil it in water, then place it in warm alcohol. Rinse it in warm water. "
        "Add iodine solution. If starch is present, it turns blue-black. "
        "Safety: heat alcohol in a water bath, never over a flame."
    )
    activity = _interactive_variant(None, source, title="Testing a Leaf for Starch")
    assert activity is not None
    instructions = [step["instruction"] for step in activity["steps"]]
    assert instructions[0].startswith("Safety:")
    assert "If starch is present, it turns blue-black." not in instructions
    assert activity["outcome"] == "If starch is present, it turns blue-black."
    assert activity["introduction"] == "We can test a leaf for starch."
    assert activity["title"] == "Testing a Leaf for Starch"
    assert len(instructions) == 4
    assert instructions[0].endswith("Take a leaf from a plant in sunlight.")


def test_explanation_and_question_are_not_fabricated_into_activities():
    assert _interactive_variant(None, "Plants use sunlight to make food.") is None
    assert _interactive_variant({"prompt": "What do plants need?"}, "Plants need water.") is None


def test_source_safety_is_never_truncated():
    assert _interactive_variant(None, "Take a leaf. Add iodine. Safety: " + "a" * 501) is None


def test_authored_observation_lines_are_preserved_and_invented_lines_are_dropped():
    source = "While you wait, bubbles collect on the leaf. At the end, compare both leaves."
    activity = _interactive_variant(
        {
            "steps": ["Place a leaf in each cup."],
            "inProgress": "While you wait, bubbles collect on the leaf.",
            "outcome": "At the end, compare both leaves.",
        },
        source,
    )
    checked = source_activity_observations(activity, source)
    assert checked["inProgress"] == "While you wait, bubbles collect on the leaf."
    assert checked["outcome"] == "At the end, compare both leaves."
    fabricated = source_activity_observations(
        {**activity, "inProgress": "The leaf will turn purple.", "outcome": "It will explode."},
        source,
    )
    assert "inProgress" not in fabricated and "outcome" not in fabricated


def test_missing_blank_and_legacy_default_lines_are_omitted_online_and_offline():
    base = {"type": "activity", "steps": [{"id": "one", "instruction": "Observe the leaf."}]}
    for extra in (
        {},
        {"inProgress": None, "outcome": None},
        {"inProgress": " ", "outcome": "You have completed the activity."},
    ):
        activity = {**base, **extra}
        serialized = InteractiveActivityVariant.model_validate(activity).model_dump(by_alias=True)
        assert "inProgress" not in serialized and "outcome" not in serialized
        offline = OfflinePackageModalityVariants(interactive=activity).model_dump(by_alias=True)
        assert "inProgress" not in offline["interactive"]
        assert "outcome" not in offline["interactive"]


def test_source_steps_survive_without_an_authored_final_observation():
    activity = _interactive_variant(None, "Take a leaf. Draw the veins.")
    assert len(activity["steps"]) == 2
    assert "outcome" not in activity and "inProgress" not in activity
