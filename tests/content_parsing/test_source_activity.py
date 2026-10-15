from nevo.content_parsing.service import _interactive_variant


def test_activity_without_outcome_keeps_its_real_steps():
    activity = _interactive_variant(
        {"steps": [{"instruction": "Observe a leaf."}, {"text": "Draw the veins."}]},
        "Observe a leaf. Draw the veins.",
    )
    assert activity is not None
    assert len(activity["steps"]) == 2
    assert activity["outcome"] == "You have completed the activity."


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
