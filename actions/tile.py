"""Information tiles drawn in the style of the Vertex icons: a small label
over a big value, in Chakra Petch Bold, whose cut-off corners match the
icons' (see assets/icons/source)."""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from .theme import TileColors

SIZE = 144
MARGIN = 10                         # the text keeps this far from the key's sides
FONT = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                    "assets", "fonts", "ChakraPetch-Bold.ttf")
LABEL_SIZE = 30
VALUE_SIZES = range(48, 17, -2)     # the biggest that fits the key's width
GAP = 10


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def render(label: str, value: str, colors: TileColors, tone: str = "value") -> Image.Image:
    """The key: `label` over `value`, both centered, the value in the color
    `tone` names ("value", "text" or "red")."""
    image = Image.new("RGB", (SIZE, SIZE), colors.ground)
    draw = ImageDraw.Draw(image)
    width = SIZE - 2 * MARGIN

    label_font = _font(LABEL_SIZE)
    while label and draw.textlength(label, font=label_font) > width and label_font.size > 14:
        label_font = _font(label_font.size - 2)
    for size in VALUE_SIZES:
        value_font = _font(size)
        if draw.textlength(value, font=value_font) <= width:
            break

    # Cap heights, so the two lines sit centered however their letters hang.
    label_height = label_font.getbbox("H")[3] - label_font.getbbox("H")[1] if label else 0
    value_height = value_font.getbbox("H")[3] - value_font.getbbox("H")[1]
    top = (SIZE - label_height - (GAP if label else 0) - value_height) / 2
    if label:
        draw.text((SIZE / 2, top + label_height), label, font=label_font,
                  fill=colors.label, anchor="ms")
        top += label_height + GAP
    draw.text((SIZE / 2, top + value_height), value, font=value_font,
              fill=getattr(colors, tone, colors.value), anchor="ms")
    return image
