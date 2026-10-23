# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Bundled display faces for packshots and studio captions.

Each face is integrity-checked against `fonts/display.json`. Text containing a
character a face lacks falls back to the bundled Noto Sans as a whole string,
so a line never mixes glyphs from two fonts or shows replacement boxes.
"""

import hashlib
import json
import threading
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_ROOT = Path(__file__).with_name("fonts")
LOCK = threading.Lock()


@lru_cache(maxsize=1)
def manifest() -> dict:
    data = json.loads((FONT_ROOT / "display.json").read_text())
    for name, entry in data.items():
        digest = hashlib.sha256((FONT_ROOT / entry["file"]).read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(f"The bundled {name} font failed its integrity check.")
    return data


def covers(name: str, text: str) -> bool:
    ranges = manifest()[name]["ranges"]
    return all(
        character.isspace() or any(a <= ord(character) <= b for a, b in ranges)
        for character in text
    )


@lru_cache(maxsize=48)
def _face(name: str, size: int, weight: int | None):
    entry = manifest()[name]
    value = ImageFont.truetype(str(FONT_ROOT / entry["file"]), size)
    if entry["axes"] and weight is not None:
        value.set_variation_by_axes([weight])
    return value


def face(name: str, text: str, size: int, weight: int | None = None):
    """The named face, or Noto Sans at a matching weight if any glyph is missing."""
    if covers(name, text):
        return _face(name, size, weight)
    from .finishing import font

    return font(size, weight or 600)


def text_layer(
    text: str,
    typeface,
    fill,
    *,
    tracking: float = 0.0,
    shadow: int = 0,
    shadow_alpha: int = 150,
) -> Image.Image:
    """One line of text as RGBA, with optional letter spacing and soft shadow.

    `tracking` is in ems. Tracked text is drawn glyph by glyph, which drops
    kerning; use it for short display lines and uppercase labels.
    """
    size = typeface.size
    spacing = round(size * tracking)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    if spacing:
        widths = [probe.textlength(character, font=typeface) for character in text]
        width = round(sum(widths) + spacing * max(0, len(text) - 1))
    else:
        widths, width = [], round(probe.textlength(text, font=typeface))
    ascent, descent = typeface.getmetrics()
    pad = shadow * 2 + 2
    layer = Image.new("RGBA", (width + 2 * pad, ascent + descent + 2 * pad))
    glyphs = Image.new("L", layer.size)
    draw = ImageDraw.Draw(glyphs)
    if spacing:
        x = pad
        for character, advance in zip(text, widths, strict=True):
            draw.text((x, pad), character, font=typeface, fill=255)
            x += advance + spacing
    else:
        draw.text((pad, pad), text, font=typeface, fill=255)
    if shadow:
        soft = glyphs.filter(ImageFilter.GaussianBlur(shadow)).point(
            lambda value: value * shadow_alpha // 255
        )
        dark = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        dark.putalpha(soft)
        layer.alpha_composite(dark, (0, max(1, shadow // 3)))
    ink = Image.new("RGBA", layer.size, fill if len(fill) == 4 else (*fill, 255))
    ink.putalpha(glyphs)
    layer.alpha_composite(ink)
    return layer


def wrap(text: str, typeface, width: int, tracking: float = 0.0) -> list[str]:
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    def measure(value: str) -> float:
        return probe.textlength(value, font=typeface) + typeface.size * tracking * max(
            0, len(value) - 1
        )

    lines, line = [], ""
    words = text.split()
    for word in words:
        candidate = f"{line} {word}" if line else word
        if not line or measure(candidate) <= width:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) in (2, 3) and len(words) <= 24:
        # Balance two- and three-line breaks instead of leaving a lone word.
        count = len(lines)
        cuts = (
            [(i,) for i in range(1, len(words))]
            if count == 2
            else [
                (i, j)
                for i in range(1, len(words) - 1)
                for j in range(i + 1, len(words))
            ]
        )
        splits = [
            tuple(
                " ".join(words[a:b])
                for a, b in zip((0, *cut), (*cut, len(words)), strict=True)
            )
            for cut in cuts
        ]
        fitting = [split for split in splits if max(map(measure, split)) <= width]
        if fitting:
            # Most even line widths (lowest spread), then the narrowest block.
            lines = list(
                min(
                    fitting,
                    key=lambda split: (
                        max(map(measure, split)) - min(map(measure, split)),
                        max(map(measure, split)),
                    ),
                )
            )
    return lines


def trim(layer: Image.Image) -> Image.Image:
    """Crop to visible pixels vertically; fonts with tall line metrics
    otherwise leave large gaps between stacked lines."""
    # Ignore faint shadow pixels so the gap is measured between letters.
    box = layer.getchannel("A").point(lambda value: 255 if value > 160 else 0).getbbox()
    return layer.crop((0, box[1], layer.width, box[3])) if box else layer


def stack(layers: list[Image.Image], gap: int) -> Image.Image:
    """Center layers vertically with a fixed gap between visible glyphs."""
    layers = [trim(layer) for layer in layers]
    width = max(layer.width for layer in layers)
    height = sum(layer.height for layer in layers) + gap * (len(layers) - 1)
    result = Image.new("RGBA", (width, height))
    y = 0
    for layer in layers:
        result.alpha_composite(layer, ((width - layer.width) // 2, y))
        y += layer.height + gap
    return result
