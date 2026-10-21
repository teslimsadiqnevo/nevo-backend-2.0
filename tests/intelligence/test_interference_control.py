from nevo.intelligence.baseline import build_baseline_profile, reduce_trials
from nevo.intelligence.interference import reduce_interference


def trials(n=12, congruent_correct=True):
    return [
        {
            "dimension": "interference_control",
            "condition": condition,
            "correct": congruent_correct if condition == "congruent" else index < 8,
            "responseTimeMs": 700 if condition == "congruent" else 1100,
        }
        for condition in ("congruent", "incongruent")
        for index in range(n)
    ]


def test_contrast_uses_own_congruent_baseline_and_both_costs():
    result = reduce_interference(trials())
    assert result["status"] == "established"
    assert 0.33 < result["accuracyCost"] < 0.34
    assert 0.57 < result["relativeLatencyCost"] < 0.58
    features = reduce_trials(trials())
    profile, config = build_baseline_profile(session_id="test", features=features)
    assert profile["measurements"]["interference_control"] == result
    assert config["support"]["shorterTextBlocks"]
    assert config["support"]["simplifiedLayout"]


def test_insufficient_and_failed_instructions_never_derive_value():
    for rows in (trials(3), trials(congruent_correct=False)):
        result = reduce_interference(rows)
        assert result["status"] == "unestablished"
        assert "accuracyCost" not in result and "relativeLatencyCost" not in result


def test_anticipations_are_discarded_and_slow_tail_is_capped():
    rows = trials()
    rows.extend(
        [
            {"condition": "congruent", "correct": True, "responseTimeMs": 50},
            {"condition": "incongruent", "correct": True, "responseTimeMs": 600000},
        ]
    )
    result = reduce_interference(rows)
    assert result["discardedTrials"] == 1
    assert result["status"] == "established"
