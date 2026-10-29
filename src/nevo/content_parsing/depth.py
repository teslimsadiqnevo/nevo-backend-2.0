"""The two versions of a segment that the adaptation engine already asks for.

The engine decides a child needs the explanation made simpler, or has earned
a longer one, and returns ``action="simplify"`` or ``action="expand"``. Until
now nothing stood behind those words: the decision layer was built and the
content layer was not, so a plan to simplify arrived at a client that had
only the one body of text the teacher uploaded.

These are that missing layer. They are written once, when the lesson is
parsed, for the same reasons the pictures and the narration are:

* a child waiting mid-lesson for a model to write is a child waiting, and the
  adaptation is supposed to be the thing that keeps them going;
* a teacher approves what a child sees, and cannot approve text that does not
  exist until the moment it is shown;
* the cost is then known before the lesson is assigned rather than unbounded
  per child per reread. Measured on real lessons it is about $0.0225 a lesson,
  roughly one per cent of what a lesson already costs to parse.

What comes back is checked before it is kept. A simpler version that quietly
introduces a figure the teacher never wrote is worse than no simpler version,
so any number that is not in the source is grounds for dropping the variant.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from uuid import UUID

from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.errors import AiGatewayError
from nevo.ai_gateway.safety import POLICY_VERSION
from nevo.ai_gateway.service import AiGatewayService
from nevo.domain.ai_gateway.vocabulary import AiService

logger = logging.getLogger(__name__)

PROMPT_NAME = "lesson_depth.default"

#: The engine's two actions, and the keys they map to in the stored variant.
#: Named after the action rather than a reading level, because the engine
#: decides from behaviour in a session and never from a judgement about the
#: child.
SIMPLIFIED = "simplified"
EXPANDED = "expanded"

#: Enough for both versions of one segment. A segment is a few paragraphs;
#: the expanded one is longer, not a new lesson.
DEPTH_OUTPUT_TOKENS = 2_048

#: A segment shorter than this has nothing to simplify - a one-line
#: definition rewritten "more simply" is a one-line definition. Skipping them
#: is most of the saving in the measured cost.
MIN_SOURCE_CHARS = 200

#: Expansion needs meaningful extra explanation. Simplification must be shorter,
#: but a percentage cutoff must not reject otherwise faithful, plainer prose.
LENGTH_MARGIN = 0.9

#: A number in the variant that is not in the source is an invented fact. This
#: is the one check that matters: everything else here is tidiness.
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")

#: How many segments are rewritten at once. The gateway serialises by priority
#: anyway; this stops one long lesson from filling the queue.
DEPTH_CONCURRENCY = 4


class DepthVariantError(RuntimeError):
    """The rewrite could not be produced, or could not be trusted."""


@dataclass(frozen=True, slots=True)
class DepthVariants:
    """Both rewrites of one segment, either of which may be missing."""

    simplified: str | None
    expanded: str | None
    rejection_reasons: dict[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return self.simplified is None and self.expanded is None

    def payload(self, *, model: str | None, source_body: str = "") -> dict[str, object]:
        """The stored shape, keyed by the engine's own action names."""

        variants: dict[str, object] = {}
        if self.simplified is not None:
            variants[SIMPLIFIED] = {
                "body": self.simplified,
                "reviewStatus": "pending",
                "safetyPolicyVersion": POLICY_VERSION,
                "sourceClaims": source_claims(source_body),
            }
        if self.expanded is not None:
            variants[EXPANDED] = {
                "body": self.expanded,
                "reviewStatus": "pending",
                "safetyPolicyVersion": POLICY_VERSION,
                "sourceClaims": source_claims(source_body),
            }
        if model:
            variants["model"] = model
        return variants


def numbers_in(text: str) -> set[str]:
    """Every figure in a piece of text, normalised so 1,500 matches 1500."""

    return {match.group().replace(",", "") for match in NUMBER.finditer(text)}


def invented_numbers(variant: str, source: str) -> set[str]:
    """Figures the rewrite has that the teacher's material does not."""

    return numbers_in(variant) - numbers_in(source)


def source_claims(source):
    from nevo.content_parsing.chunks import sentence_units

    return [piece.strip() for piece in sentence_units(source) if piece.strip()]


def missing_claim_anchors(source, variant):
    """Conservative screening, not a claim of automatic semantic equivalence."""
    stop = set(
        (
            "a an the is are was were be been to of in on at and or it this that these those "
            "for from as by with into its their them they we you your can will has have had "
            "which what how"
        ).split()
    )
    words = set(re.findall(r"[a-z]+", variant.casefold()))
    missing = []
    for claim in source_claims(source):
        anchors = set(re.findall(r"[a-z]+", claim.casefold())) - stop
        if len(anchors) >= 3 and len(anchors & words) / len(anchors) < 0.5:
            missing.append(claim)
    return missing


def rejection_reason(variant: str | None, *, source: str, shorter: bool) -> str | None:
    if not variant:
        return "missing_rewrite"
    text = variant.strip()
    if not text or text == source.strip():
        return "unchanged_source"
    if missing_claim_anchors(source, text):
        return "source_claim_anchors_missing"
    stray = invented_numbers(text, source)
    if stray:
        # The failure this whole check exists for. A child reading a simpler
        # version of a worked example must not be reading a different sum.
        return "invented_figures"
    if numbers_in(source) - numbers_in(text):
        return "source_figures_missing"
    equations = re.findall(r"\$[^$\n]+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]", source)
    equations.extend(
        line.strip()
        for line in source.splitlines()
        if re.search(r"\S\s*(?:=|<=|>=)\s*\S", line)
        and len(line.strip()) <= 160
        and not re.search(r"\b[A-Za-z]{3,}\b", line)
    )
    compact = re.sub(r"\s+", "", text)
    if any(re.sub(r"\s+", "", equation) not in compact for equation in equations):
        return "source_equation_missing"
    if shorter and len(text) >= len(source.strip()):
        return "not_shorter"
    if not shorter and len(text) * LENGTH_MARGIN < len(source):
        return "not_expanded"
    return None


def missing_key_terms(variant: str, key_terms: list[str]) -> list[str]:
    text = " ".join(variant.casefold().split())
    return [term for term in key_terms if " ".join(term.casefold().split()) not in text]


def accept(variant: str | None, *, source: str, shorter: bool) -> str | None:
    """Reject missing content or invented facts, not a cosmetic percentage miss."""
    reason = rejection_reason(variant, source=source, shorter=shorter)
    if reason:
        logger.info("Depth variant rejected: %s", reason)
        return None
    return variant.strip()


class DepthVariantService:
    """Writes the simpler and the longer version of a segment."""

    def __init__(self, *, ai_gateway: AiGatewayService) -> None:
        self._ai_gateway = ai_gateway

    @property
    def configured(self) -> bool:
        # Probed rather than asserted: the parsing service builds one of these
        # for every gateway it is given, including stand-ins that do not carry
        # the flag, and an attribute error here would fail the whole parse.
        return bool(getattr(self._ai_gateway, "configured", False))

    def worth_rewriting(self, body: str) -> bool:
        return len(body.strip()) >= MIN_SOURCE_CHARS

    async def generate(
        self,
        *,
        title: str | None,
        body: str,
        requested_by_user_id: UUID,
        key_terms: list[str] | None = None,
    ) -> tuple[DepthVariants, str | None]:
        """Both versions of one segment, and the model that wrote them."""

        if len(body) > 10_000:
            from nevo.content_parsing.chunks import reading_chunks

            parts = []
            held = []
            size = 0
            for chunk in reading_chunks("depth-source", body):
                text = str(chunk["text"])
                if held and size + len(text) > 6000:
                    parts.append("\n\n".join(held))
                    held, size = [], 0
                held.append(text)
                size += len(text)
            if held:
                parts.append("\n\n".join(held))
            if len(parts) > 50:
                raise DepthVariantError("Source exceeds the bounded depth-rewrite budget")
            results = [
                await self.generate(
                    title=title, body=part, requested_by_user_id=requested_by_user_id,
                    key_terms=[term for term in (key_terms or []) if term.casefold() in part.casefold()],
                )
                for part in parts
            ]
            simplified = [result.simplified for result, _ in results]
            expanded = [result.expanded for result, _ in results]
            simplified_text = "\n\n".join(simplified) if all(simplified) else None
            expanded_text = "\n\n".join(expanded) if all(expanded) else None
            return (
                DepthVariants(
                    simplified=accept(simplified_text, source=body, shorter=True)
                    if simplified_text and not missing_key_terms(simplified_text, key_terms or [])
                    else None,
                    expanded=accept(expanded_text, source=body, shorter=False)
                    if expanded_text and not missing_key_terms(expanded_text, key_terms or [])
                    else None,
                ),
                results[-1][1],
            )

        token_budget = max(DEPTH_OUTPUT_TOKENS, min(8192, len(body) * 2))
        accepted = {SIMPLIFIED: None, EXPANDED: None}
        rejected = {}
        repair_details = {}
        for attempt in range(2):
            try:
                result = await self._ai_gateway.generate(
                    AiGenerationRequest(
                        requester_user_id=requested_by_user_id,
                        # Parse-time work, so it queues with the parse rather
                        # than jumping into the adaptation lane, which exists for
                        # calls made while a child is waiting.
                        service=AiService.LESSON_GENERATION,
                        prompt_name=PROMPT_NAME,
                        variables={
                            "title": title or "",
                            "body": (
                                "Rewrite instructions (not lesson content): preserve every source "
                                "claim, technical term, example, figure, equation "
                                "and safety warning. "
                                "Use shorter, plainer sentences without omitting content. "
                                f"The source alone contains {len(body.strip())} characters. "
                                f"Keep simplified below {len(body.strip())} characters; "
                                "do not count these instructions as source content. "
                                "Keep questions as questions, with the same item numbering. "
                                "Preserve every procedural step and its safety warning. "
                                "Never reverse a scientific relationship, movement direction, "
                                "concentration comparison, cause, negation or inequality. "
                                "Explain only relationships supported by the source. "
                                + (
                                    "Correct these rejected outputs: "
                                    + json.dumps(repair_details)
                                    + ". "
                                    if rejected
                                    else ""
                                )
                                + "\n\nSOURCE SEGMENT:\n"
                                + body
                                + ("\n\nREQUIRED KEY TERMS (preserve verbatim): "
                                   + json.dumps(key_terms) if key_terms else "")
                            ),
                        },
                        max_output_tokens=token_budget,
                        timeout_seconds=90,
                        json_output=True,
                    )
                )
            except AiGatewayError as error:
                raise DepthVariantError(str(error)) from error
            if result.fallback_used:
                # The deterministic fallback rewrites nothing; it would store the
                # same text under two names and tell a child it was simpler.
                raise DepthVariantError("The provider was unavailable")
            try:
                if result.stop_reason == "max_tokens":
                    raise DepthVariantError("The rewrite reached its output token limit")
                payload = _json_payload(result.text)
            except DepthVariantError:
                if attempt == 1:
                    if any(accepted.values()):
                        for kind in (SIMPLIFIED, EXPANDED):
                            if accepted[kind] is None:
                                rejected[kind] = "invalid_retry_output"
                        break
                    raise
                token_budget = min(16384, token_budget * 2)
                continue
            for kind in (SIMPLIFIED, EXPANDED):
                if accepted[kind] is not None:
                    continue
                candidate = _text(payload.get(kind))
                reason = rejection_reason(candidate, source=body, shorter=kind == SIMPLIFIED)
                if not reason and missing_key_terms(candidate or "", key_terms or []):
                    reason = "key_terms_missing"
                if reason:
                    rejected[kind] = reason
                    repair_details[kind] = {
                        "reason": reason,
                        "sourceClaimsToRetain": missing_claim_anchors(body, candidate or ""),
                        "sourceFiguresToRetain": sorted(numbers_in(body)),
                        "keyTermsToRetain": missing_key_terms(candidate or "", key_terms or []),
                    }
                else:
                    accepted[kind] = candidate.strip()
                    rejected.pop(kind, None)
                    repair_details.pop(kind, None)
            if all(accepted.values()):
                break
        return (
            DepthVariants(
                simplified=accepted[SIMPLIFIED],
                expanded=accepted[EXPANDED],
                rejection_reasons=rejected,
            ),
            result.model,
        )


def _text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _text(value.get("body"))
    return None


def _json_payload(content: str) -> dict[str, object]:
    """The object in the answer, whether or not it came fenced."""

    text = content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text.removeprefix("json").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise DepthVariantError("The rewrite was not valid JSON") from error
    if not isinstance(payload, dict):
        raise DepthVariantError("The rewrite was not an object")
    return payload
