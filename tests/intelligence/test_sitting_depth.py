from datetime import UTC, datetime
from types import SimpleNamespace

from nevo.ai_gateway.safety import POLICY_VERSION
from nevo.intelligence.delivery_preferences import (
    SegmentChoiceWrite,
    delivery_for_read,
    lesson_choices,
    save_choice,
    segment_choice,
)


def segment(key, approved=True):
    variant = {
        "reviewStatus": "approved",
        "reviewedBy": "teacher",
        "reviewedAt": "now",
        "safetyPolicyVersion": POLICY_VERSION,
    }
    return SimpleNamespace(id=key, depth_variants={"simplified": variant} if approved else {})


def test_depth_and_slower_follow_sitting_but_format_does_not():
    sitting = SimpleNamespace(delivery_state={})
    first, second = segment("one"), segment("two")
    save_choice(
        sitting, first, SegmentChoiceWrite(depth="simplified", slower=True, modality="audio")
    )
    reloaded = SimpleNamespace(delivery_state=dict(sitting.delivery_state))
    assert segment_choice(reloaded, second)["depth"] == "simplified"
    assert segment_choice(reloaded, second)["slower"] is True
    assert "modality" not in segment_choice(reloaded, second)
    save_choice(reloaded, second, SegmentChoiceWrite(modality="visual"))
    assert segment_choice(reloaded, first)["modality"] == "audio"
    assert segment_choice(reloaded, first)["depth"] == "simplified"
    save_choice(reloaded, second, SegmentChoiceWrite(depth="original", slower=False))
    assert segment_choice(reloaded, first)["depth"] == "original"
    assert segment_choice(reloaded, first)["slower"] is False


def test_latest_legacy_choice_is_read_without_copying_to_each_section():
    sitting = SimpleNamespace(
        delivery_state={
            "segmentChoices": {
                "one": {"depth": "simplified", "slower": True, "updatedAt": "2026-10-21T10:00:00Z"},
                "two": {
                    "depth": "expanded",
                    "modality": "audio",
                    "updatedAt": "2026-10-21T11:00:00Z",
                },
            }
        }
    )
    assert lesson_choices(sitting)["depth"] == "expanded"
    assert lesson_choices(sitting)["slower"] is True
    save_choice(sitting, segment("two"), SegmentChoiceWrite(slower=False))
    assert sitting.delivery_state["lessonPreferences"]["depth"] == "expanded"
    assert "depth" not in sitting.delivery_state["segmentChoices"]["one"]


def test_unapproved_depth_is_not_served_but_preference_is_remembered():
    sitting = SimpleNamespace(delivery_state={})
    save_choice(sitting, segment("one"), SegmentChoiceWrite(depth="simplified"))
    assert segment_choice(sitting, segment("two", approved=False))["depth"] == "original"
    assert lesson_choices(sitting)["depth"] == "simplified"
    assert segment_choice(sitting, segment("three"))["depth"] == "simplified"


def test_ended_and_new_sittings_do_not_inherit_choices():
    sitting = SimpleNamespace(delivery_state={})
    save_choice(sitting, segment("one"), SegmentChoiceWrite(depth="simplified", slower=True))
    sitting.ended_at = datetime.now(UTC)
    assert segment_choice(sitting, segment("one")) == {}
    assert delivery_for_read(sitting)["lessonPreferences"] == {}
    assert delivery_for_read(sitting)["segmentChoices"] == {}
    assert lesson_choices(SimpleNamespace(delivery_state={})) == {}
