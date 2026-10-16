from dataclasses import replace

from pydantic import TypeAdapter

from nevo.api.lesson_contracts import (
    AudioVariant,
    CalculationVariant,
    DepthVariants,
    InteractiveVariant,
    TextVariant,
    VisualVariant,
    checkpoint_payloads,
)
from nevo.content_parsing.entities import ParsedLessonSegment

DELIVERY_CONTRACTS = {
    "text_variant": TextVariant,
    "visual_variant": VisualVariant,
    "audio_variant": AudioVariant,
    "interactive_variant": InteractiveVariant,
    "calculation_variant": CalculationVariant,
    "depth_variants": DepthVariants,
}


def validated_delivery(segment: ParsedLessonSegment) -> ParsedLessonSegment:
    """Validate the actual public renderer contracts before any database write."""
    variants = {}
    for name, contract in DELIVERY_CONTRACTS.items():
        payload = getattr(segment, name)
        if payload is not None:
            variants[name] = (
                TypeAdapter(contract)
                .validate_python(payload)
                .model_dump(by_alias=True, mode="json")
            )
    return replace(
        segment,
        **variants,
        comprehension_checkpoints=tuple(
            checkpoint_payloads(
                list(segment.comprehension_checkpoints), segment_key=segment.segment_key
            )
        ),
    )
