"""Declarative thresholds for engagement anomaly detection (SCRUM-62).

This module is deliberately inert. It defines *when* detection would fire and
*what a teacher would read*, so the foundation exists without a retrofit, but
it evaluates nothing. There is no function here that inspects a learner. The
detection engine is post-launch work; it will consume these rules rather than
restate them.

Two principles hold the design together:

1. Breadth over depth. A learner who genuinely struggles with one content type
   slows down on that content type. A learner steering the system toward
   easier material slows down across all of them at once. Every rule below
   therefore requires ``EngagementAnomalyScope.ALL_CONTENT_TYPES`` and a
   minimum spread of distinct content types.
2. The learner is never accused. The stored level is internal. What a teacher
   sees is a suggestion about material difficulty, phrased so it is useful
   whether or not the underlying guess is right.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from nevo.domain.learner_profiles.vocabulary import (
    EngagementAnomalyScope,
    EngagementAnomalyType,
    GamingSuspicionLevel,
)


@dataclass(frozen=True, slots=True)
class GamingThresholdRule:
    """One documented condition under which detection would fire.

    ``key`` is persisted on a recorded anomaly so a stored row always names
    the rule that produced it, and rules can be revised without orphaning
    history.
    """

    key: str
    anomaly_type: EngagementAnomalyType
    scope: EngagementAnomalyScope
    # Observed value must reach this multiple of the learner's own baseline.
    # Baselines are per-learner: the comparison is never against a cohort.
    minimum_deviation_ratio: float
    # Guards against a single bad afternoon being read as intent.
    minimum_observations: int
    minimum_distinct_content_types: int
    # How long the deviation must hold before it counts as a pattern.
    sustained_over_sessions: int
    suspicion_level: GamingSuspicionLevel
    rationale: str


RESPONSE_TIME_DOUBLED_EVERYWHERE = GamingThresholdRule(
    key="response_time_doubled_everywhere",
    anomaly_type=EngagementAnomalyType.RESPONSE_TIME_SLOWDOWN,
    scope=EngagementAnomalyScope.ALL_CONTENT_TYPES,
    minimum_deviation_ratio=2.0,
    minimum_observations=8,
    minimum_distinct_content_types=3,
    sustained_over_sessions=2,
    suspicion_level=GamingSuspicionLevel.MODERATE,
    rationale=(
        "Response time at least doubled against the learner's own baseline "
        "across every content type at once. Genuine difficulty concentrates "
        "in a content type rather than spreading evenly."
    ),
)

RESPONSE_TIME_TRIPLED_EVERYWHERE = GamingThresholdRule(
    key="response_time_tripled_everywhere",
    anomaly_type=EngagementAnomalyType.RESPONSE_TIME_SLOWDOWN,
    scope=EngagementAnomalyScope.ALL_CONTENT_TYPES,
    minimum_deviation_ratio=3.0,
    minimum_observations=8,
    minimum_distinct_content_types=3,
    sustained_over_sessions=3,
    suspicion_level=GamingSuspicionLevel.HIGH,
    rationale=(
        "A sustained, uniform tripling of response time across all content "
        "types, held over three sessions."
    ),
)

ERRORS_SPIKE_AGAINST_MASTERY = GamingThresholdRule(
    key="errors_spike_against_mastery",
    anomaly_type=EngagementAnomalyType.ERROR_RATE_SPIKE,
    scope=EngagementAnomalyScope.ALL_CONTENT_TYPES,
    minimum_deviation_ratio=2.5,
    minimum_observations=10,
    minimum_distinct_content_types=3,
    sustained_over_sessions=2,
    suspicion_level=GamingSuspicionLevel.LOW,
    rationale=(
        "Errors rose sharply on material the learner had already answered "
        "correctly. Kept at LOW on its own because genuine regression, "
        "tiredness, and disengagement all produce the same shape."
    ),
)

ABANDONED_ATTEMPTS_SPIKE = GamingThresholdRule(
    key="abandoned_attempts_spike",
    anomaly_type=EngagementAnomalyType.ABANDONED_ATTEMPT_SPIKE,
    scope=EngagementAnomalyScope.ALL_CONTENT_TYPES,
    minimum_deviation_ratio=2.0,
    minimum_observations=6,
    minimum_distinct_content_types=3,
    sustained_over_sessions=2,
    suspicion_level=GamingSuspicionLevel.LOW,
    rationale=(
        "Attempts abandoned before completion rose uniformly. Weak on its "
        "own: disengagement and frustration look identical from here."
    ),
)

GAMING_THRESHOLD_RULES: tuple[GamingThresholdRule, ...] = (
    RESPONSE_TIME_DOUBLED_EVERYWHERE,
    RESPONSE_TIME_TRIPLED_EVERYWHERE,
    ERRORS_SPIKE_AGAINST_MASTERY,
    ABANDONED_ATTEMPTS_SPIKE,
)

GAMING_THRESHOLD_RULES_BY_KEY: Mapping[str, GamingThresholdRule] = (
    MappingProxyType({rule.key: rule for rule in GAMING_THRESHOLD_RULES})
)

# A learner must never be told the system is watching for this, and a teacher
# must never be handed an accusation. The notification proposes a change to
# the material, which is the useful action whether the learner was steering
# the system or genuinely finding the work too easy.
TEACHER_NOTIFICATION_TEMPLATES: Mapping[GamingSuspicionLevel, str] = (
    MappingProxyType(
        {
            GamingSuspicionLevel.LOW: (
                "{student_name}'s recent work looks different from their "
                "usual pattern. Worth a look when you have a moment."
            ),
            GamingSuspicionLevel.MODERATE: (
                "{student_name} may be finding this content too easy. "
                "Consider assigning more challenging material."
            ),
            GamingSuspicionLevel.HIGH: (
                "{student_name} may be ready to move on from this material. "
                "Consider stepping the difficulty up, or having a quick chat "
                "about how they are finding it."
            ),
        }
    )
)

# Nothing surfaces at NONE, and NONE has no template by design.
SURFACEABLE_SUSPICION_LEVELS: frozenset[GamingSuspicionLevel] = frozenset(
    TEACHER_NOTIFICATION_TEMPLATES
)
