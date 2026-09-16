"""What actually gets downloaded to a child's phone.

The provider hands back a PNG of about 1.4 MB. Four of those is nearly six
megabytes for one lesson, which is a real cost on a Nigerian phone paying by
the megabyte and slow enough to be felt. These are posters with small text in
them, so the resolution is the teaching and cannot be reduced - but PNG is the
wrong container for flat colour.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from nevo.visuals.service import PREVIEW_MAX_WIDTH, _encode


def _poster(width: int = 1536, height: int = 1024) -> bytes:
    """Flat colour with hard edges, which is what these images are."""

    image = Image.new("RGB", (width, height), "white")
    for index in range(0, width, 64):
        block = Image.new("RGB", (48, height // 3), (12, 42, 110) if index % 128 else (220, 40, 40))
        image.paste(block, (index, height // 4))
    raw = io.BytesIO()
    image.save(raw, format="PNG")
    return raw.getvalue()


def test_the_display_image_keeps_every_pixel_of_the_original() -> None:
    # Shrinking it would cost a child the diagram: the text inside is the
    # content, not decoration around it.
    png = _poster()
    display, _, width, height = _encode(png)

    assert (width, height) == (1536, 1024)
    with Image.open(io.BytesIO(display)) as rendered:
        assert rendered.size == (1536, 1024)
        assert rendered.format == "WEBP"


def test_the_same_picture_encodes_to_the_same_bytes() -> None:
    """The storage key is a digest of the prompt, so a re-parse must not
    upload a different file under a path that is already there."""

    png = _poster()

    assert _encode(png)[0] == _encode(png)[0]


def test_the_preview_is_small_enough_to_paint_first() -> None:
    png = _poster()
    display, preview, _, _ = _encode(png)

    with Image.open(io.BytesIO(preview)) as rendered:
        assert rendered.width <= PREVIEW_MAX_WIDTH
        assert rendered.format == "WEBP"
    assert len(preview) < len(display)


def test_a_picture_smaller_than_the_preview_is_not_enlarged() -> None:
    # Scaling up would cost bytes and add nothing.
    png = _poster(width=320, height=240)
    _, preview, width, _ = _encode(png)

    assert width == 320
    with Image.open(io.BytesIO(preview)) as rendered:
        assert rendered.width == 320


@pytest.mark.parametrize("mode", ["RGBA", "P", "L"])
def test_whatever_the_provider_sends_is_handled(mode: str) -> None:
    # A transparent or paletted PNG must not throw: WebP is written from RGB.
    raw = io.BytesIO()
    Image.new(mode, (800, 600), 255 if mode == "L" else None).save(raw, format="PNG")

    display, preview, width, height = _encode(raw.getvalue())

    assert display and preview
    assert (width, height) == (800, 600)
