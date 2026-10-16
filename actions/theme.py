"""Vertex's color themes, as the plugin's settings pick one for every key
(Vertex's, Discord's and the media keys alike): the icons in `assets/icons`
for a theme and version, and the colors the information tile is drawn in.

Some icons come in variants, drawn differently but meaning the same, such as
Volume_Up_A, Volume_Up_B and Volume_Up_C. A key's settings pick the icon by
its name (Volume Up) and then, where there is more than one, the variant."""

from __future__ import annotations

import glob
import os
from typing import NamedTuple

ICONS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")


class Theme(NamedTuple):
    name: str
    folder: str          # under assets/icons
    ground: str          # the key
    text: str
    main: str
    second: str
    red: str
    fill: str            # version E's key
    on_fill: str         # what sits on it


# From Vertex's src/vertex/ui/theme.py, as in assets/icons/source.
THEMES = {
    "white": Theme("White", "White", "#000000", "#ffffff", "#ffffff", "#b4b4be", "#ff4757",
                   "#000000", "#ffffff"),
    "abyss": Theme("Abyss", "Abyss", "#02050c", "#e4f3ff", "#1fe5ff", "#ff4fd8", "#ff4766",
                   "#1fe5ff", "#00161c"),
    "aurora": Theme("Aurora", "Aurora", "#0f0b24", "#f3f0ff", "#52e0f0", "#a68bff", "#ff5470",
                    "#52e0f0", "#0f0b24"),
    "coral": Theme("Coral", "Coral", "#0d1117", "#eef2f7", "#ff8a66", "#8c9eff", "#f04a5a",
                   "#ff8a66", "#1a0f0b"),
    "glacier": Theme("Glacier", "Glacier", "#d1dce7", "#0f1e2b", "#0a6cb4", "#14a3b8", "#d92d3f",
                     "#0a6cb4", "#ffffff"),
    "midnight": Theme("Midnight Blue", "Midnight_Blue", "#0a1020", "#ecf1f9", "#f6b03e",
                      "#3dd6f0", "#ff5d62", "#f6b03e", "#0a1020"),
    "navy": Theme("Navy", "Navy", "#0b0e14", "#eef0f3", "#4a62ec", "#9aabff", "#ff5c6c",
                  "#4a62ec", "#ffffff"),
    "plum": Theme("Plum", "Plum", "#150a1f", "#f8f0ff", "#ff3ea5", "#7d8bff", "#ff4d6a",
                  "#d42481", "#ffffff"),
    "polar": Theme("Polar", "Polar", "#d5d9e8", "#1a1730", "#7c3aed", "#0d9488", "#d92d3f",
                   "#7c3aed", "#ffffff"),
    "spooky": Theme("Spooky", "Spooky", "#09070b", "#f6eee6", "#ff7a1a", "#a259ff", "#ff4757",
                    "#ff7a1a", "#1a0a00"),
}
OFF = ""
THEME_CHOICES = ((OFF, "None"), *((key, theme.name) for key, theme in THEMES.items()))
VERSIONS = (("A", "A: the main color"),
            ("B", "B: the text color, main-color highlights"),
            ("C", "C: the second color, main-color highlights"),
            ("D", "D: the main color into the second"),
            ("E", "E: a key filled with the main color"))
DEFAULT_VERSION = "A"
DEFAULT_THEME = "white"     # the keys show icons until another theme is picked


# Every icon in the sets, by file name, as the key settings offer them.
ICON_NAMES = tuple(sorted(name[:-4] for name in os.listdir(os.path.join(ICONS, "White"))
                          if name.endswith(".png")))


def _split(icon: str) -> tuple[str, str]:
    """`icon` as its name and its variant's letter, by the file name alone."""
    base, _, letter = icon.rpartition("_")
    return (base, letter) if base and len(letter) == 1 and letter.isupper() else (icon, "")


# The icons by name, and the variants of those that have more than one:
# {"Volume_Up": ("A", "B", "C"), ...}.
VARIANTS: dict[str, tuple[str, ...]] = {}
for _icon in ICON_NAMES:
    _base, _letter = _split(_icon)
    if _letter:
        VARIANTS[_base] = (*VARIANTS.get(_base, ()), _letter)
ICON_BASES = tuple(sorted({_split(icon)[0] if _split(icon)[0] in VARIANTS else icon
                           for icon in ICON_NAMES}))


def split_variant(icon: str) -> tuple[str, str]:
    """`icon` as (name, variant): ("Volume_Up", "B") for Volume_Up_B, and
    (icon, "") for an icon without variants."""
    base, letter = _split(icon)
    return (base, letter) if base in VARIANTS else (icon, "")


def with_variant(icon: str, variant: str) -> str:
    """The file name of `icon` (a name, or a name with a variant) in
    `variant`, where it has that variant; a name alone gets its first."""
    base, own = split_variant(icon)
    letters = VARIANTS.get(base)
    if not letters:
        return icon
    return f"{base}_{variant if variant in letters else own or letters[0]}"


def icon_label(icon: str) -> str:
    return icon.replace("_", " ")


def version_choices(theme: str) -> tuple[tuple[str, str], ...]:
    """The versions as the theme names them in its folders, such as
    ("B", "B: White Cyan Highlights"); without such names, the general ones."""
    folder = os.path.join(ICONS, THEMES[theme].folder) if theme in THEMES else ""
    named = {}
    if folder and theme != "white":
        for path in sorted(glob.glob(os.path.join(folder, "?_*"))):
            letter, _, name = os.path.basename(path).partition("_")
            named[letter] = f"{letter}: {icon_label(name)}"
    return tuple((value, named.get(value, label)) for value, label in VERSIONS)


def preview_path(theme: str, version: str) -> str:
    """The sheet with every icon of the theme and version, or "" without one."""
    if theme not in THEMES:
        return ""
    previews = os.path.join(ICONS, "_previews")
    if theme == "white":
        path = os.path.join(previews, "White.png")
    else:
        found = sorted(glob.glob(os.path.join(previews, THEMES[theme].folder, f"{version}_*.png")))
        path = found[0] if found else ""
    return path if path and os.path.isfile(path) else ""


def icon_path(theme: str, version: str, icon: str) -> str:
    """The PNG of `icon` in the theme and version, or "" without one. The
    white set has no versions."""
    if theme not in THEMES or not icon:
        return ""
    folder = os.path.join(ICONS, THEMES[theme].folder)
    if theme != "white":
        versions = sorted(glob.glob(os.path.join(folder, f"{version}_*")))
        if not versions:
            return ""
        folder = versions[0]
    path = os.path.join(folder, f"{icon}.png")
    return path if os.path.isfile(path) else ""


class TileColors(NamedTuple):
    ground: str
    label: str
    value: str           # a volume
    text: str            # a state that isn't one: Vertex or Sonar off
    red: str             # muted


def tile_colors(theme: str, version: str) -> TileColors:
    """The information tile's colors, matching the icons of the same theme
    and version; with no theme, the white set's."""
    t = THEMES.get(theme, THEMES["white"])
    if theme == "white" or theme not in THEMES:
        return TileColors(t.ground, t.second, t.main, t.text, t.red)
    if version == "E":
        return TileColors(t.fill, t.on_fill, t.on_fill, t.on_fill, t.on_fill)
    label = {"A": t.main, "B": t.text}.get(version, t.second)
    return TileColors(t.ground, label, t.main, t.text, t.red)
