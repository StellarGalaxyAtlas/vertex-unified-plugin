"""What the plugin does across its apps: one theme for every key, and icon
variants picked per key."""

import types
from pathlib import Path

import pytest


def _icon(media):
    return "/".join(Path(media).parts[-2:]) if isinstance(media, str) else media


def test_every_app_has_its_keys(registered):
    suffixes = [holder.action_id_suffix for holder in registered.holders]
    assert len(suffixes) == len(set(suffixes)) == 18
    assert {"MediaPlayPause", "MediaNext", "MediaPrevious"} <= set(suffixes)
    assert registered.registered["plugin_name"] == "vertex-unified-plugin"


def test_one_theme_redraws_every_apps_keys(plugin, registered):
    registered.media._set_state({"players": []})
    keys = [plugin.vertex_keys.ShowVertex(registered, {}),
            plugin.discord_keys.ToggleMute(registered, {}),
            plugin.media_keys.MediaNext(registered, {})]
    for key in keys:
        key.on_ready()
    registered.set_theme("spooky", "D")
    assert registered.get_settings() == {"theme": "spooky", "version": "D"}
    assert [_icon(key.media[-1]) if isinstance(key.media[-1], str) else "faded"
            for key in keys] == ["D_Pumpkin_Into_Purple/Vertex_Logo.png", "faded", "faded"]
    registered.media._set_state({"players": [
        {"bus": "org.mpris.MediaPlayer2.mpv", "app": "mpv", "label": "mpv",
         "status": "Playing", "title": "", "artist": "", "can_next": True,
         "can_previous": True}]})
    assert _icon(keys[2].media[-1]) == "D_Pumpkin_Into_Purple/Media_Next.png"


def test_the_theme_is_kept(plugin, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    for client in (plugin.vertex_client.Vertex, plugin.discord_client.Discord,
                   plugin.media_client.Media):
        monkeypatch.setattr(client, "start", lambda self: None)
    monkeypatch.setattr(plugin.main.VertexPlugin, "get_settings",
                        lambda self: {"theme": "navy", "version": "C"})
    assert plugin.main.VertexPlugin().theme == ("navy", "C")


# --- Variants -------------------------------------------------------------------------

def test_icons_with_variants(plugin):
    theme = plugin.theme
    assert theme.VARIANTS == {"Clip_Save": ("A", "B"), "Volume_Down": ("A", "B", "C"),
                              "Volume_Up": ("A", "B", "C")}
    assert "Volume_Up" in theme.ICON_BASES and "Volume_Up_A" not in theme.ICON_BASES
    assert "Media_Play_Pause" in theme.ICON_BASES and "Camera_Off" in theme.ICON_BASES
    assert theme.split_variant("Volume_Up_C") == ("Volume_Up", "C")
    assert theme.split_variant("Camera_Off") == ("Camera_Off", "")
    assert theme.with_variant("Volume_Up_B", "C") == "Volume_Up_C"
    assert theme.with_variant("Volume_Up_B", "") == "Volume_Up_B"
    assert theme.with_variant("Volume_Up", "") == "Volume_Up_A"
    assert theme.with_variant("Clip_Save_B", "C") == "Clip_Save_B"     # it has no C
    assert theme.with_variant("Camera", "B") == "Camera"


def _vertex_key(plugin, cls, theme=("spooky", "C"), **settings):
    client = types.SimpleNamespace(state=None, add_listener=lambda _l: None,
                                   remove_listener=lambda _l: None)
    key = cls(types.SimpleNamespace(vertex=client, theme=theme, PATH=""), settings)
    key.on_ready()
    return key


def test_a_picked_variant_changes_the_default_icon(plugin):
    key = _vertex_key(plugin, plugin.vertex_keys.SonarVolume, variants={"volume": "C"})
    key.plugin_base.vertex.state = {"sonar": {"active": True, "channels": {}}}
    key.redraw()
    assert _icon(key.media[-1]).endswith("/Volume_Up_C.png")
    key.save(direction="down")                         # the variant goes along
    assert _icon(key.media[-1]).endswith("/Volume_Down_C.png")
    assert key.face_summary("volume") == "Volume Down, variant C (default)"


def test_a_picked_icon_takes_its_variant(plugin):
    key = _vertex_key(plugin, plugin.vertex_keys.ShowVertex, icons={"logo": "Volume_Up"},
                      variants={"logo": "B"})
    assert _icon(key.media[-1]).endswith("/Volume_Up_B.png")
    assert key.face_summary("logo") == "Volume Up, variant B"
    key.set_variant("logo", "")
    assert _icon(key.media[-1]).endswith("/Volume_Up_A.png")
    key.set_icon("logo", "")
    assert _icon(key.media[-1]).endswith("/Vertex_Logo.png")
    assert key.face_summary("logo") == "Vertex Logo (default)"


def test_icons_picked_before_variants_still_show(plugin):
    # Keys set up before variants were picked on their own kept the full name.
    key = _vertex_key(plugin, plugin.vertex_keys.ShowVertex, icons={"logo": "Clip_Save_B"})
    assert _icon(key.media[-1]).endswith("/Clip_Save_B.png")


@pytest.mark.parametrize("name", ["white", "abyss", "polar"])
def test_version_names_and_previews(plugin, name):
    theme = plugin.theme
    choices = theme.version_choices(name)
    assert [value for value, _label in choices] == ["A", "B", "C", "D", "E"]
    if name == "polar":
        assert choices[1] == ("B", "B: Ink Violet Highlights")
    for version, _label in choices:
        assert Path(theme.preview_path(name, version)).is_file()
    assert theme.preview_path("", "A") == ""
