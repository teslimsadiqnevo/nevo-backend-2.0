"""The gateway can send an image, and never keeps one.

ADR 0009 calls this the substantial part of the paper-work camera route: a
new capability rather than a new route. Until now the gateway could not send
an image at all - the safety guard reviewed pictures through its own direct
call, so anything needing a model to *read* a photograph had no route.

Everything here is about the half of ADR 0009 that is a rule rather than a
feature: the image is never written to disk, never put in the bucket, never
reaches a backup, is not kept on a failure either, and has no thumbnail or
cache of our own. Passing raw bytes keeps that true by construction - there
is no identifier for anything else to hold.

The route itself is deliberately not built. ADR 0009 requires a safety phase
for a photograph of a child's book, distinct from the phases that judge
pictures Nevo drew, and says that phase's policy is Lydia's to word. A route
that reads a child's photograph without the person check is the one thing
that must not ship.
"""

from __future__ import annotations

import base64
import inspect

import pytest

from nevo.ai_gateway import claude
from nevo.ai_gateway.entities import (
    ALLOWED_IMAGE_MEDIA_TYPES,
    MAX_IMAGE_BYTES,
    ProviderImage,
    ProviderRequest,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"pretend pixels"


def test_an_image_carries_bytes_rather_than_a_location() -> None:
    """A path or a key would be a thing that outlives the call."""
    fields = set(ProviderImage.__dataclass_fields__)
    assert fields == {"data", "media_type"}
    assert isinstance(ProviderImage(data=PNG).data, bytes)


def test_the_repr_never_contains_the_image() -> None:
    """A dataclass repr would put a base64 photograph of a child's exercise
    book into any log line, traceback or error report that formats it."""
    rendered = repr(ProviderImage(data=PNG))
    assert "pretend pixels" not in rendered
    assert base64.b64encode(PNG).decode() not in rendered
    assert "bytes=" in rendered


def test_an_oversized_image_is_refused_here_not_by_the_provider() -> None:
    """The caller can say something useful to the child; a provider 400
    cannot."""
    with pytest.raises(ValueError, match="over the"):
        ProviderImage(data=b"x" * (MAX_IMAGE_BYTES + 1))
    assert MAX_IMAGE_BYTES == 3_500_000, "matches the safety guard's own ceiling"


def test_an_empty_or_unsupported_image_is_refused() -> None:
    with pytest.raises(ValueError):
        ProviderImage(data=b"")
    with pytest.raises(ValueError, match="Unsupported"):
        ProviderImage(data=PNG, media_type="image/gif")
    assert "image/gif" not in ALLOWED_IMAGE_MEDIA_TYPES


def test_a_request_sends_no_images_by_default() -> None:
    assert ProviderRequest(
        system_instruction="s", user_content="u", max_output_tokens=16
    ).images == ()


def test_images_are_placed_before_the_text_that_asks_about_them() -> None:
    source = inspect.getsource(claude)
    image_at = source.index('"type": "image"')
    text_at = source.index('"text": request.user_content')
    assert image_at < text_at


def test_an_image_is_never_cached_on_the_providers_side() -> None:
    """A breakpoint on the text block caches the whole prefix, images
    included - so a photograph of a child's book would sit in the provider's
    cache for its lifetime. ADR 0009 says it is held for the read and then
    gone, so a request carrying an image sets no breakpoint at all."""
    source = inspect.getsource(claude)
    assert "if not request.images:" in source
    guard_at = source.index("if not request.images:")
    breakpoint_at = source.index('payload["messages"][0]["content"][-1]["cache_control"]')
    assert guard_at < breakpoint_at


def test_the_audit_row_has_nowhere_to_put_an_image() -> None:
    """The audit keeps token counts and a cost. It must not become the place
    a photograph of a child's book survives."""
    from nevo.db.models.ai_gateway import AiGatewayCall

    columns = {column.name for column in AiGatewayCall.__table__.c}
    assert not {"image", "images", "image_data", "attachment"} & columns
    from nevo.ai_gateway.entities import AiCallAudit

    assert "image" not in str(AiCallAudit.__dataclass_fields__.keys()).lower()


def test_the_camera_route_does_not_exist_yet() -> None:
    """Holds the line until Lydia has worded the safety phase.

    If this starts failing, either that phase exists and this test should be
    updated to match it, or a route that reads a child's photograph shipped
    without the person check ADR 0009 requires.
    """
    from nevo.api import paper_work

    source = inspect.getsource(paper_work)
    assert "image" not in source.lower(), "a camera route needs ADR 0009's safety phase first"
