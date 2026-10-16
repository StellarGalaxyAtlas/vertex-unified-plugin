"""Renders the sharp icon set in several colour approaches, as SVGs, PNGs and sheets.

Each glyph part is drawn with one of four colour slots: fg (the body), hi (the
highlight: the moving part, a badge, a lens), bg (the key) and red (a strike
line, always red). An approach fills the slots from a Vertex theme.
"""
import os
import sys

import cairosvg
from PIL import Image, ImageDraw, ImageFont

from sharp_icons import ICONS

OUT = sys.argv[1]
KEY, GLYPH = 144, 96

GRAD = ('<linearGradient id="g" gradientUnits="userSpaceOnUse" x1="3" y1="3" x2="21" y2="21">'
        '<stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient>')

# From src/vertex/ui/theme.py: page ground, text, accent, the fill text sits on,
# what sits on that fill, second colour, recording red; then names for the labels.
SCHEMES = {
    "plum": ("Plum", "#150a1f", "#f8f0ff", "#ff3ea5", "#d42481", "#ffffff", "#7d8bff", "#ff4d6a",
             "White", "Magenta", "Periwinkle"),
    "spooky": ("Spooky", "#09070b", "#f6eee6", "#ff7a1a", "#ff7a1a", "#1a0a00", "#a259ff", "#ff4757",
               "Bone", "Pumpkin", "Purple"),
    "abyss": ("Abyss", "#02050c", "#e4f3ff", "#1fe5ff", "#1fe5ff", "#00161c", "#ff4fd8", "#ff4766",
              "Ice", "Cyan", "Magenta"),
    "aurora": ("Aurora", "#0f0b24", "#f3f0ff", "#52e0f0", "#52e0f0", "#0f0b24", "#a68bff", "#ff5470",
               "White", "Cyan", "Violet"),
    "midnight": ("Midnight blue", "#0a1020", "#ecf1f9", "#f6b03e", "#f6b03e", "#0a1020", "#3dd6f0", "#ff5d62",
                 "White", "Amber", "Cyan"),
    "coral": ("Coral", "#0d1117", "#eef2f7", "#ff8a66", "#ff8a66", "#1a0f0b", "#8c9eff", "#f04a5a",
              "White", "Coral", "Periwinkle"),
    "polar": ("Polar", "#d5d9e8", "#1a1730", "#7c3aed", "#7c3aed", "#ffffff", "#0d9488", "#d92d3f",
              "Ink", "Violet", "Teal"),
    "glacier": ("Glacier", "#d1dce7", "#0f1e2b", "#0a6cb4", "#0a6cb4", "#ffffff", "#14a3b8", "#d92d3f",
                "Ink", "Glacier blue", "Teal"),
    "navy": ("Navy", "#0b0e14", "#eef0f3", "#4a62ec", "#4a62ec", "#ffffff", "#9aabff", "#ff5c6c",
             "White", "Blue", "Periwinkle"),
}


def variants(ground, text, accent, fill, on_fill, second, red, n_text, n_acc, n_sec):
    base = dict(bg=ground, red=red, gap=None)
    return {
        "a-mono": (f"A · {n_acc}", {**base, "fg": accent, "hi": accent}, ""),
        "b-text-highlights": (f"B · {n_text}, {n_acc.lower()} highlights", {**base, "fg": text, "hi": accent}, ""),
        "c-second-highlights": (f"C · {n_sec}, {n_acc.lower()} highlights",
                                {**base, "fg": second, "hi": accent}, ""),
        "d-gradient": (f"D · {n_acc} into {n_sec.lower()}", {**base, "fg": "url(#g)", "hi": "url(#g)"},
                       GRAD.format(a=accent, b=second)),
        "e-key": (f"E · {n_acc} key", dict(bg=fill, fg=on_fill, hi=on_fill, red=red, gap=on_fill), ""),
    }


WHITE = dict(fg="#ffffff", hi="#ffffff", bg="#000000", red="#ff4757", gap=None)


def svg(parts, c, defs):
    scale, off = GLYPH / 24, (KEY - GLYPH) / 2
    c = {**c, "gap": c["gap"] or c["bg"]}
    body = "\n    ".join(p.format(**c) for p in parts)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {KEY} {KEY}" width="{KEY}" height="{KEY}">\n'
            + (f'  <defs>{defs}</defs>\n' if defs else "")
            + f'  <rect width="{KEY}" height="{KEY}" fill="{c["bg"]}"/>\n'
            f'  <g transform="translate({off} {off}) scale({scale})" fill="none" stroke="{c["fg"]}" '
            f'stroke-width="2" stroke-linecap="square" stroke-linejoin="miter">\n    {body}\n  </g>\n</svg>\n')


def rounded(path, size, radius):
    key = Image.open(path).convert("RGB")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=255)
    return key, mask


def render(base, title, c, defs):
    for sub in ("svg", "png/144", "png/72"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    for icon, (_l, parts) in ICONS.items():
        text = svg(parts, c, defs)
        open(os.path.join(base, "svg", icon + ".svg"), "w").write(text)
        for size in (144, 72):
            cairosvg.svg2png(bytestring=text.encode(), output_width=size, output_height=size,
                             write_to=os.path.join(base, "png", str(size), icon + ".png"))
    # A full sheet for this approach.
    names, cols, pad, lh = list(ICONS), 6, 28, 34
    rows = -(-len(names) // cols)
    img = Image.new("RGB", (cols * KEY + (cols + 1) * pad, 70 + rows * (KEY + lh + pad)), "#1b1b20")
    d = ImageDraw.Draw(img)
    d.text((pad, 24), title, font=TITLE, fill="#f2f2f5")
    for i, icon in enumerate(names):
        r, col = divmod(i, cols)
        x, y = pad + col * (KEY + pad), 70 + r * (KEY + lh + pad)
        k, m = rounded(os.path.join(base, "png", "144", icon + ".png"), KEY, 18)
        img.paste(k, (x, y), m)
        t = ICONS[icon][0]
        d.text((x + (KEY - d.textlength(t, font=FONT)) / 2, y + KEY + 8), t, font=FONT, fill="#c9c9d2")
    img.save(os.path.join(base, "preview.png"))


def overview(base, scheme_name, vs):
    """Every variant of one theme as a row of keys, to compare them."""
    names = list(ICONS)
    size, gap, pad, row_h = 72, 10, 28, 72 + 44
    w = pad * 2 + len(names) * (size + gap) - gap
    img = Image.new("RGB", (w, 70 + len(vs) * row_h + 8), "#1b1b20")
    d = ImageDraw.Draw(img)
    d.text((pad, 24), f"{scheme_name}: five ways to use its colors", font=TITLE, fill="#f2f2f5")
    for r, (v, (label, _c, _d)) in enumerate(vs.items()):
        y = 70 + r * row_h
        d.text((pad, y), label, font=FONT, fill="#c9c9d2")
        for i, icon in enumerate(names):
            k, m = rounded(os.path.join(base, v, "png", "72", icon + ".png"), size, 10)
            img.paste(k, (pad + i * (size + gap), y + 26), m)
    img.save(os.path.join(base, "overview.png"))


TITLE = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-SemiBold.otf", 26)
FONT = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Medium.otf", 15)
render(os.path.join(OUT, "white"), "White on black", WHITE, "")
for key, (scheme_name, *colours) in SCHEMES.items():
    vs = variants(*colours)
    for v, (label, c, defs) in vs.items():
        render(os.path.join(OUT, "themes", key, v), f"{scheme_name}, {label}", c, defs)
    overview(os.path.join(OUT, "themes", key), scheme_name, vs)
