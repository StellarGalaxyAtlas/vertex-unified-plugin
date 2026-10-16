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
