"""Display bands for the engine's class pulse scores (0 to 100)."""

PULSE_BANDS = (
    ("support", 0.0, 50.0, "May benefit from support"),
    ("mixed", 50.0, 75.0, "Mixed"),
    ("steady", 75.0, 100.0, "Steady"),
)
PULSE_NO_DATA_LABEL = "Still gathering a picture"


def pulse_label(score: float | None) -> str:
    if score is None:
        return PULSE_NO_DATA_LABEL
    for _, minimum, maximum, label in PULSE_BANDS:
        if minimum <= score < maximum:
            return label
    return PULSE_BANDS[-1][3] if score >= 100 else PULSE_BANDS[0][3]
