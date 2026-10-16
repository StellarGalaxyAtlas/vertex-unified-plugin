"""The themes, their icons and the drawn information tile. Needs only Pillow."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from actions import theme, tile

# Every icon a key asks for.
KEY_ICONS = ["Volume_Up_B", "Volume_Down_B", "Microphone_Muted", "Microphone_Unmuted",
             "Speaker_Deafened", "Speaker_Undeafened", "Microphone", "Headset", "No_Microphone",
             "Volume_Up_C", "Clip_Save_A", "Clip_Save_B", "Vertex_Logo", "Camera", "Camera_Off",
             "Screenshare", "Screenshare_Off", "Media_Play", "Media_Pause", "Media_Next",
             "Media_Previous"]


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


@pytest.mark.parametrize("name", list(theme.THEMES))
@pytest.mark.parametrize("version", [v for v, _label in theme.VERSIONS])
def test_every_theme_and_version_has_the_keys_icons(name, version):
    for icon in KEY_ICONS:
        path = theme.icon_path(name, version, icon)
        assert path, (name, version, icon)
        with Image.open(path) as image:
            assert image.size == (144, 144)
    assert f"/{version}_" in theme.icon_path(name, version, "Headset") or name == "white"


def test_no_theme_no_icon():
    assert theme.icon_path(theme.OFF, "A", "Headset") == ""
    assert theme.icon_path("spooky", "A", "Not_An_Icon") == ""


@pytest.mark.parametrize("name", list(theme.THEMES))
@pytest.mark.parametrize("version", [v for v, _label in theme.VERSIONS])
def test_the_tile_draws_its_colors(name, version):
    colors = theme.tile_colors(name, version)
    drawn = {c for _n, c in tile.render("GAME", "55%", colors).getcolors(1 << 16)}
    assert {_rgb(colors.ground), _rgb(colors.label), _rgb(colors.value)} <= drawn
    muted = {c for _n, c in tile.render("MIC", "MUTED", colors, "red").getcolors(1 << 16)}
    assert _rgb(colors.red) in muted


def test_the_tile_matches_the_icons_key():
    # Version E's icons fill the key with the main color; so does the tile.
    spooky = theme.THEMES["spooky"]
    assert theme.tile_colors("spooky", "E").ground == spooky.fill
    assert theme.tile_colors("spooky", "C").ground == spooky.ground
    assert theme.tile_colors(theme.OFF, "A") == theme.tile_colors("white", "C")


@pytest.mark.parametrize("value", ["100%", "MUTED", "OFF", "–"])
def test_text_stays_inside_the_key(value):
    image = tile.render("MEDIA", value, theme.tile_colors("spooky", "C"))
    assert image.size == (tile.SIZE, tile.SIZE)
    ground = Image.new("RGB", image.size, image.getpixel((0, 0)))
    left, top, right, bottom = ImageChops.difference(image, ground).getbbox()
    edge = tile.MARGIN - 2
    assert left >= edge and right <= tile.SIZE - edge
    assert top >= edge and bottom <= tile.SIZE - edge
