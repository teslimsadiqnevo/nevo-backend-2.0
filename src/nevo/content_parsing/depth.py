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
from dataclasses import dataclass
from uuid import UUID

from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.errors import AiGatewayError
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

#: The simplified version has to actually be shorter, and the expanded one
#: longer, or the call did not do what it was asked and the variant is noise
#: on a screen. Ten per cent, so ordinary variation is not treated as failure.
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

    @property
    def empty(self) -> bool:
        return self.simplified is None and self.expanded is None

    def payload(self, *, model: str | None) -> dict[str, object]:
        """The stored shape, keyed by the engine's own action names."""

        variants: dict[str, object] = {}
        if self.simplified is not None:
            variants[SIMPLIFIED] = {"body": self.simplified}
        if self.expanded is not None:
            variants[EXPANDED] = {"body": self.expanded}
        if model:
            variants["model"] = model
        return variants


def numbers_in(text: str) -> set[str]:
    """Every figure in a piece of text, normalised so 1,500 matches 1500."""

    return {match.group().replace(",", "") for match in NUMBER.finditer(text)}


def invented_numbers(variant: str, source: str) -> set[str]:
    """Figures the rewrite has that the teacher's material does not."""

    return numbers_in(variant) - numbers_in(source)


def accept(variant: str | None, *, source: str, shorter: bool) -> str | None:
    """Keep the rewrite, or None with the reason logged.

    Refusing is always safe: the segment still has the body the teacher
    uploaded, and the client falls back to it.
    """

    if not variant:
        return None
    text = variant.strip()
    if not text or text == source.strip():
        return None
    stray = invented_numbers(text, source)
    if stray:
        # The failure this whole check exists for. A child reading a simpler
        # version of a worked example must not be reading a different sum.
        logger.warning("Depth variant invented figures %s; dropped", sorted(stray))
        return None
    if shorter and len(text) > len(source) * LENGTH_MARGIN:
        return None
    if not shorter and len(text) * LENGTH_MARGIN < len(source):
        return None
    return text


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
    ) -> tuple[DepthVariants, str | None]:
        """Both versions of one segment, and the model that wrote them."""

        try:
            result = await self._ai_gateway.generate(
                AiGenerationRequest(
                    requester_user_id=requested_by_user_id,
                    # Parse-time work, so it queues with the parse rather
                    # than jumping into the adaptation lane, which exists for
                    # calls made while a child is waiting.
                    service=AiService.LESSON_GENERATION,
                    prompt_name=PROMPT_NAME,
                    variables={"title": title or "", "body": body},
                    max_output_tokens=DEPTH_OUTPUT_TOKENS,
                )
            )
        except AiGatewayError as error:
            raise DepthVariantError(str(error)) from error

        if result.fallback_used:
            # The deterministic fallback rewrites nothing; it would store the
            # same text under two names and tell a child it was simpler.
            raise DepthVariantError("The provider was unavailable")
        payload = _json_payload(result.text)
        return (
            DepthVariants(
                simplified=accept(
                    _text(payload.get(SIMPLIFIED)),
                    source=body,
                    shorter=True,
                ),
                expanded=accept(
                    _text(payload.get(EXPANDED)),
                    source=body,
                    shorter=False,
                ),
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
