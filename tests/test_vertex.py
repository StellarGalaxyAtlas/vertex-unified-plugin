"""Vertex's keys: the client against Vertex's real control socket, and the
keys with StreamController stubbed out. Needs Vertex installed in the same
Python (see development.md); skipped without it."""

import json
import socket
import threading
import types
from pathlib import Path

import pytest
from conftest import Events as _Events
from conftest import wait as _wait

ipc = pytest.importorskip("vertex.ipc")


# --- A Vertex that answers ----------------------------------------------------------

def _state(volume=55, muted=False, mic="Headset mic", active=True, replay=True):
    def device(description):
        return {"name": description.lower().replace(" ", "_"), "description": description}
    return {"api": 1,
            "replay": {"state": "running" if replay else "stopped", "running": replay,
                       "seconds": 60},
            "sonar": {"enabled": active, "active": active, "linked": True,
                      "output": device("Headset") if active else None,
                      "mic": device(mic) if active else None,
                      "channels": {"game": {"name": "Game", "volume": volume, "muted": muted,
                                            "device": None}}}}


@pytest.fixture
def vertex(tmp_path):
    sock = tmp_path / "control.sock"
    subscribers = ipc.Subscribers()
    received = []
    box = {"state": _state()}

    def dispatch(command, args):
        received.append((command, args))
        if command == "state":
            return {"ok": True, "message": "", "data": box["state"]}
        if command == "devices":
            return {"ok": True, "message": "", "data": {"outputs": [], "mics": [
                {"name": "desk_mic", "description": "Desk mic", "connected": True,
                 "excluded": False},
                {"name": "old_mic", "description": "Old mic", "connected": False,
                 "excluded": False}]}}
        if command == "device" and args.get("name") == "gone":
            return {"ok": False, "error": "no_device", "message": "gone isn't plugged in."}
        return {"ok": command != "fail", "message": f"did {command}"}

    server = ipc.ControlServer(dispatch, sock, subscribers=subscribers)
    assert server.start()

    def publish(state):
        box["state"] = state
        subscribers.publish({"event": "state", "data": state})

    yield types.SimpleNamespace(sock=str(sock), server=server, received=received,
                                subscribers=subscribers, publish=publish)
    server.stop()


# --- The client ---------------------------------------------------------------------

@pytest.mark.parametrize("relay", [None, []])
def test_send_over_socket_and_relay(plugin, vertex, relay):
    client = plugin.vertex_client.Vertex(vertex.sock, relay=relay)
    client.prefer_socket = False
    assert client.send("save-clip", seconds=30) == {"ok": True, "message": "did save-clip"}
    assert vertex.received == [("save-clip", {"seconds": 30})]


@pytest.mark.parametrize("relay", [None, []])
def test_not_running(plugin, tmp_path, relay):
    client = plugin.vertex_client.Vertex(str(tmp_path / "missing.sock"), relay=relay)
    client.prefer_socket = False
    with pytest.raises(plugin.vertex_client.NotRunning):
        client.send("show")
    replies = []
    client.request("show", replies.append)
    assert _wait(lambda: replies)
    assert replies[0]["ok"] is False and replies[0]["error"] == "not_running"


@pytest.mark.parametrize("relay", [None, []])
def test_follow_state_changes_and_vertex_stopping(plugin, vertex, relay, monkeypatch):
    monkeypatch.setattr(plugin.vertex_client, "RETRY", 0.1)
    client = plugin.vertex_client.Vertex(vertex.sock, relay=relay)
    client.prefer_socket = False
    seen = []
    listener = lambda event, data: seen.append((event, data))  # noqa: E731
    client.add_listener(listener)
    client.start()
    try:
        assert _wait(lambda: client.state == _state())
        assert _wait(lambda: len(vertex.subscribers))
        vertex.publish(_state(volume=20))
        assert _wait(lambda: client.state == _state(volume=20))
        vertex.subscribers.publish({"event": "notice", "data": {"kind": "clip_saved"}})
        assert _wait(lambda: ("notice", {"kind": "clip_saved"}) in seen)
        vertex.server.stop()
        assert _wait(lambda: client.state is None)
        assert seen[-1] == ("state", None)
    finally:
        client.stop()


def test_a_vertex_that_stays_silent_is_tried_again(plugin, tmp_path, monkeypatch):
    # The first connection is taken but never answered, as by a Vertex (or
    # a relay) that hangs while the desktop starts; the next one answers.
    monkeypatch.setattr(plugin.vertex_client, "FIRST_REPLY", 0.3)
    monkeypatch.setattr(plugin.vertex_client, "RETRY", 0.1)
    path = str(tmp_path / "control.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen()
    conns = []

    def accept():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            conns.append(conn)
            if len(conns) > 1:
                conn.sendall(json.dumps({"ok": True, "data": _state()}).encode() + b"\n")
    threading.Thread(target=accept, daemon=True).start()
    client = plugin.vertex_client.Vertex(path, relay=None)
    problems = []
    client.add_listener(listener := lambda event, data: problems.append(client.problem))
    client.start()
    try:
        assert _wait(lambda: client.state == _state())
        assert any("didn't answer within 0.3 seconds" in problem for problem in problems)
        assert client.problem == ""
        assert plugin.main.vertex_status(None, "Why.") == "Vertex isn't running.\nWhy."
    finally:
        client.stop()
        server.close()
        for conn in conns:
            conn.close()
    del listener


def test_a_relay_that_hangs_is_dropped(plugin, tmp_path, monkeypatch):
    monkeypatch.setattr(plugin.vertex_client, "FIRST_REPLY", 0.3)
    monkeypatch.setattr(plugin.vertex_client, "RETRY", 0.1)
    client = plugin.vertex_client.Vertex(str(tmp_path / "missing" / "control.sock"),
                                         relay=["sh", "-c", "exec sleep 60", "sh"])
    client.start()
    try:
        assert _wait(lambda: "didn't answer" in client.problem)
        assert client.state is None
    finally:
        client.stop()


def test_socket_is_used_once_the_sandbox_can_see_it(plugin, vertex, tmp_path):
    client = plugin.vertex_client.Vertex(vertex.sock, relay=["/nonexistent/flatpak-spawn"])
    assert client.send("show")["ok"]                   # the folder is there: no relay
    hidden = plugin.vertex_client.Vertex(str(tmp_path / "hidden" / "control.sock"),
                                  relay=["/nonexistent/flatpak-spawn"])
    assert hidden._relay_now() == hidden.relay


def test_listeners_are_held_weakly(plugin):
    client = plugin.vertex_client.Vertex("unused", relay=None)

    class Key:
        calls = 0

        def heard(self, event, data):
            Key.calls += 1

    key = Key()
    client.add_listener(key.heard)
    client._set_state({"a": 1})
    del key
    client._set_state({"a": 2})
    assert Key.calls == 1


# --- The keys -----------------------------------------------------------------------

class _Plugin:
    def __init__(self, client, theme=("", "A")):
        self.vertex = client
        self.theme = theme


def _key(plugin, vertex, cls, theme=("", "A"), **settings):
    client = plugin.vertex_client.Vertex(vertex.sock, relay=None)
    key = cls(_Plugin(client, theme), settings)
    return key, client


def test_the_keys_names_and_ids(registered):
    names = {holder.action_id_suffix: holder.action_name for holder in registered.holders}
    # Ids stay as first published, so keys already set up keep working.
    assert names.items() >= {
        "Volume": "Sonar Information", "VolumeStep": "Sonar Volume",
        "Mute": "Sonar Toggle Channel Mute", "NextMic": "Sonar Next Microphone",
        "NextOutput": "Sonar Next Output Device", "MicToggle": "Sonar Toggle Microphone",
        "OutputToggle": "Sonar Toggle Output Device", "Replay": "Replay Buffer Toggle",
        "SaveClip": "Replay Save Clip", "Show": "Show Vertex"}.items()


def test_information_key_draws_a_tile(plugin, vertex):
    key, _client = _key(plugin, vertex, plugin.vertex_keys.SonarInformation, channel="game",
                        theme=("spooky", "C"))
    spooky = plugin.theme.tile_colors("spooky", "C")
    key.show(_state(volume=55))
    assert key.labels == {"top": "", "center": "", "bottom": ""}
    assert key._tile == ("GAME", "67%", spooky, "value")      # as the desktop shows it
    assert key.media[-1].size == (144, 144)
    key.show(_state(volume=55))                         # nothing changed: not redrawn
    assert len(key.media) == 1
    key.show(_state(muted=True))
    assert key._tile == ("GAME", "MUTED", spooky, "red")
    key.show(_state(active=False))
    assert key._tile[:2] == ("SONAR", "OFF")
    key.show(None)
    assert key._tile[:2] == ("VERTEX", "OFF")
    assert len(key.media) == 4
    key.on_key_down()                                   # only shows
    threading.Event().wait(0.2)
    assert vertex.received == []


def test_information_key_as_labels(plugin, vertex):
    key, _client = _key(plugin, vertex, plugin.vertex_keys.SonarInformation, channel="game",
                        look="labels")
    key.show(_state(volume=55))
    assert key.labels == {"top": "Game", "center": "", "bottom": "67%"}
    key.show(_state(muted=True))
    assert key.labels["bottom"] == "Muted"
    key.show(_state(active=False))
    assert key.labels["bottom"] == "Sonar off"
    key.show(None)
    assert key.labels["bottom"] == "Vertex off"
    assert key.media == []                              # the key's own image stays
    key.set_settings({"channel": "game"})               # to the tile and back
    key.show(_state())
    key.set_settings({"channel": "game", "look": "labels"})
    key.show(_state())
    assert key.media[-1] is None and key.labels["top"] == "Game"


def test_volume_key_steps_by_its_setting(plugin, vertex):
    down, _ = _key(plugin, vertex, plugin.vertex_keys.SonarVolume, channel="game",
                   direction="down", step=10)
    down.show(_state(volume=55))
    assert down.labels == {"top": "Game", "center": "-10%", "bottom": "67%"}
    down.on_key_down()
    assert _wait(lambda: vertex.received == [
        ("volume", {"channel": "game", "action": "down", "step": 10})])
    up, _ = _key(plugin, vertex, plugin.vertex_keys.SonarVolume)       # the defaults
    up.show(_state(volume=55))
    assert up.labels["center"] == "+5%"
    up.on_key_down()
    assert _wait(lambda: len(vertex.received) == 2)
    assert vertex.received[1] == ("volume", {"channel": "game", "action": "up", "step": 5})


def test_volumes_as_the_desktop_shows_them(plugin):
    vc = plugin.vertex_client
    # Vertex's 45% is the desktop's 59%; Vertex's 100% and 0% are its own.
    assert [vc.desktop_volume(level) for level in (0, 45, 55, 100)] == [0, 59, 67, 100]
    assert vc.level_for(59) == 45
    for level in range(0, 96):
        start = vc.desktop_volume(level)
        after = vc.desktop_volume(vc.level_after(level, "up", 5))
        assert 4 <= after - start <= 6 or after == 100
        assert vc.level_after(level, "up", 5) > level
    assert vc.level_after(100, "up", 5) == 100 and vc.level_after(0, "down", 5) == 0
    assert vc.level_after(45, "down", 5) == vc.level_for(54)


def test_volume_key_steps_the_desktop_volume(plugin, vertex):
    key, client = _key(plugin, vertex, plugin.vertex_keys.SonarVolume, channel="game")
    client._set_state(_state(volume=45))
    key.on_key_down()
    # The desktop shows 59%: the key asks Vertex for the level that makes it 64%.
    assert _wait(lambda: vertex.received[-1:] == [
        ("volume", {"channel": "game", "action": "set", "value": 51})])
    assert plugin.vertex_client.desktop_volume(51) == 64


def test_volume_key_on_a_dial(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.vertex_keys.SonarVolume, channel="chat", step=2)
    key.event_callback(_Events.TURN_CCW)
    assert _wait(lambda: vertex.received == [
        ("volume", {"channel": "chat", "action": "down", "step": 2})])
    key.event_callback(_Events.DOWN)
    assert _wait(lambda: vertex.received[-1] == ("mute", {"channel": "chat"}))


def test_next_device_keys(plugin, vertex):
    output, _ = _key(plugin, vertex, plugin.vertex_keys.SonarNextOutput)
    mic, _ = _key(plugin, vertex, plugin.vertex_keys.SonarNextMic)
    output.show(_state())
    mic.show(_state(mic="Desk mic"))
    assert output.labels == {"top": "Output", "center": "", "bottom": "Headset"}
    assert mic.labels == {"top": "Mic", "center": "", "bottom": "Desk mic"}
    output.on_key_down()
    mic.on_key_down()
    assert _wait(lambda: len(vertex.received) == 2)
    assert {("device", "channel" in args) for _c, args in vertex.received} == \
        {("device", True), ("device", False)}


def test_save_clip_key(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.vertex_keys.ReplaySaveClip, seconds=30)
    key.show(_state())
    assert key.labels["bottom"] == "30 s"
    key.show(_state(replay=False))
    assert key.labels["bottom"] == "Replay off"
    key.on_key_down()
    assert _wait(lambda: vertex.received == [("save-clip", {"seconds": 30})])


def test_failed_command_shows_an_error(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.vertex_keys.ShowVertex)
    key.send("fail")
    assert _wait(lambda: key.errors == 1)


def test_mic_toggle_faces(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.vertex_keys.SonarToggleMic, first="desk_mic",
                  second="headset_mic")
    key.show(_state(mic="Desk mic"))
    assert key.labels == {"top": "Mic 1", "center": "", "bottom": "Desk mic"}
    key.show(_state(mic="Headset mic"))
    assert key.labels == {"top": "Mic 2", "center": "", "bottom": "Headset mic"}
    key.show(_state(mic="Webcam"))                      # neither: the neutral face
    assert key.labels == {"top": "Mic", "center": "No mic", "bottom": "Webcam"}
    key.show(_state(active=False))
    assert key.labels["center"] == "Sonar off"
    key.show(None)
    assert key.labels["center"] == "Vertex off"


def _pressed(plugin, vertex, current, **picks):
    key, client = _key(plugin, vertex, plugin.vertex_keys.SonarToggleMic, **picks)
    client.state = _state(mic=current)
    key.on_key_down()
    return key


def test_mic_toggle_switches_to_the_other_pick(plugin, vertex):
    _pressed(plugin, vertex, "Desk mic", first="desk_mic", second="headset_mic")
    assert _wait(lambda: vertex.received == [
        ("device", {"action": "set", "name": "headset_mic", "channel": "mic"})])


def test_mic_toggle_from_neither_goes_to_the_first_plugged_in(plugin, vertex):
    key = _pressed(plugin, vertex, "Webcam", first="gone", second="desk_mic")
    assert _wait(lambda: [args["name"] for _c, args in vertex.received] == ["gone", "desk_mic"])
    threading.Event().wait(0.1)
    assert key.errors == 0


def test_mic_toggle_shows_an_error_when_the_other_is_unplugged(plugin, vertex):
    key = _pressed(plugin, vertex, "Desk mic", first="desk_mic", second="gone")
    assert _wait(lambda: key.errors == 1)


def test_mic_toggle_lists_sonars_mics(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.vertex_keys.SonarToggleMic, first="usb_mic")
    choices, note = key._choices()
    assert choices == [("", "None"), ("desk_mic", "Desk mic"),
                       ("old_mic", "Old mic (not plugged in)"), ("usb_mic", "usb_mic")]
    assert note == ""


def test_output_toggle(plugin, vertex):
    key, client = _key(plugin, vertex, plugin.vertex_keys.SonarToggleOutput, first="headset",
                       second="speakers")
    key.show(_state())
    assert key.labels == {"top": "Output 1", "center": "", "bottom": "Headset"}
    client.state = _state()
    key.on_key_down()
    assert _wait(lambda: vertex.received == [("device", {"action": "set",
                                                         "name": "speakers"})])


def test_mute_and_replay_keys(plugin, vertex):
    mute, _ = _key(plugin, vertex, plugin.vertex_keys.SonarToggleChannelMute, channel="game")
    mute.show(_state(muted=True))
    assert mute.labels == {"top": "Game", "center": "Muted", "bottom": ""}
    mute.show(_state())
    assert mute.labels["center"] == "On"
    replay, _ = _key(plugin, vertex, plugin.vertex_keys.ReplayToggle)
    replay.show(_state(replay=False))
    assert replay.labels["center"] == "Off"
    replay.show(_state())
    assert replay.labels["center"] == "On"
    mute.on_key_down()
    replay.on_key_down()
    assert _wait(lambda: len(vertex.received) == 2)
    assert ("replay", {"action": "toggle"}) in vertex.received
    assert ("mute", {"channel": "game"}) in vertex.received


def test_save_clip_key_flashes_when_a_clip_lands(plugin, vertex, monkeypatch):
    monkeypatch.setattr(plugin.vertex_keys, "FLASH_SECONDS", 0.05)
    key, _ = _key(plugin, vertex, plugin.vertex_keys.ReplaySaveClip)
    key.on_notice({"kind": "clip_saved"})
    assert key.background == list(plugin.vertex_keys.FLASH)
    assert _wait(lambda: key.background == [0, 0, 0, 0])
    key.on_notice({"kind": "clip_not_saved"})
    assert key.errors == 1


def test_toggle_shows_the_picture_picked_for_each_face(plugin, vertex, tmp_path):
    first, second = tmp_path / "desk.png", tmp_path / "headset.png"
    first.write_bytes(b"png")
    second.write_bytes(b"png")
    key, _ = _key(plugin, vertex, plugin.vertex_keys.SonarToggleMic, first="desk_mic",
                  second="headset_mic",
                  images={"mic-1": str(first), "mic-2": str(second)})
    key.show(_state(mic="Desk mic"))
    key.show(_state(mic="Desk mic"))                    # unchanged: not drawn again
    key.show(_state(mic="Headset mic"))
    key.show(_state(mic="Webcam"))                      # no picture for "No mic"
    assert key.media == [str(first), str(second), None]
    key.show(_state(mic="Webcam"))
    assert len(key.media) == 3


def test_keys_without_pictures_keep_their_image(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.vertex_keys.SonarToggleMic, first="desk_mic")
    key.show(_state(mic="Desk mic"))
    key.show(_state(mic="Webcam"))
    assert key.media == []


def test_picking_and_unpicking_a_picture(plugin, vertex, tmp_path):
    picture = tmp_path / "muted.png"
    picture.write_bytes(b"png")
    key, client = _key(plugin, vertex, plugin.vertex_keys.SonarToggleChannelMute, channel="game")
    client.state = _state()
    key.show(client.state)
    key.set_image("unmuted", str(picture))
    assert key.get_settings()["images"] == {"unmuted": str(picture)}
    key.set_image("unmuted", "")
    assert key.get_settings()["images"] == {}
    assert key.media == [str(picture), None]


# --- The plugin's theme -----------------------------------------------------------------

SPOOKY_C = ("spooky", "C")


def _icon(media):
    return "/".join(Path(media).parts[-2:]) if isinstance(media, str) else media


def test_themed_keys_show_the_themes_icons(plugin, vertex):
    mute, _ = _key(plugin, vertex, plugin.vertex_keys.SonarToggleChannelMute, theme=SPOOKY_C,
                   channel="game")
    mute.show(_state(muted=True))
    assert _icon(mute.media[-1]) == "C_Purple_Pumpkin_Highlights/Speaker_Deafened.png"
    assert mute.labels == {"top": "", "center": "", "bottom": ""}     # the icon says it
    mute.show(None)
    assert mute.media[-1].size == (144, 144)                          # faded
    assert mute.labels["bottom"] == "Vertex off"

    mic, _ = _key(plugin, vertex, plugin.vertex_keys.SonarNextMic, theme=SPOOKY_C)
    mic.show(_state(mic="Desk mic"))
    assert _icon(mic.media[-1]).endswith("/Microphone.png")
    assert mic.labels == {"top": "", "center": "", "bottom": "Desk mic"}

    toggle, _ = _key(plugin, vertex, plugin.vertex_keys.SonarToggleMic, theme=("white", "A"),
                     first="desk_mic")
    toggle.show(_state(mic="Webcam"))
    assert _icon(toggle.media[-1]) == "White/No_Microphone.png"
    assert toggle.labels["bottom"] == "Webcam"

    volume, _ = _key(plugin, vertex, plugin.vertex_keys.SonarVolume, theme=SPOOKY_C)
    volume.show(_state())
    assert _icon(volume.media[-1]).endswith("/Volume_Up_B.png")


def test_a_picked_picture_beats_the_theme(plugin, vertex, tmp_path):
    picture = tmp_path / "mine.png"
    picture.write_bytes(b"png")
    mute, _ = _key(plugin, vertex, plugin.vertex_keys.SonarToggleChannelMute, theme=SPOOKY_C,
                   channel="game", images={"unmuted": str(picture)})
    mute.show(_state())
    assert mute.media == [str(picture)]
    assert mute.labels["center"] == "On"                              # labels as before


def test_no_theme_leaves_the_keys_as_they_were(plugin, vertex):
    keys = plugin.vertex_keys
    for cls in (keys.SonarVolume, keys.SonarNextMic, keys.ReplayToggle, keys.ReplaySaveClip):
        key, _ = _key(plugin, vertex, cls)
        key.show(_state())
        assert key.media == []


def test_themed_save_clip_flashes_its_icon(plugin, vertex, monkeypatch):
    monkeypatch.setattr(plugin.vertex_keys, "FLASH_SECONDS", 0.05)
    key, client = _key(plugin, vertex, plugin.vertex_keys.ReplaySaveClip, theme=SPOOKY_C)
    client.state = _state()
    key.show(client.state)
    icon = key.media[-1]
    key.on_notice({"kind": "clip_saved"})
    assert not isinstance(key.media[-1], str)                         # washed green
    assert _wait(lambda: key.media[-1] == icon)


def test_the_plugins_theme_redraws_every_key(plugin, registered, vertex):
    assert registered.theme == ("white", "A") and registered.has_plugin_settings
    key = plugin.vertex_keys.SonarNextOutput(registered, {})
    key.on_ready()
    registered.vertex.state = _state()
    registered.set_theme("navy", "E")
    assert registered.get_settings() == {"theme": "navy", "version": "E"}
    assert _icon(key.media[-1]) == "E_Blue_Key/Speaker_Undeafened.png"


def test_a_picked_icon_follows_the_theme(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.vertex_keys.SonarToggleMic, theme=SPOOKY_C,
                  first="desk_mic", icons={"mic-1": "Camera"})
    key.show(_state(mic="Desk mic"))
    assert _icon(key.media[-1]) == "C_Purple_Pumpkin_Highlights/Camera.png"
    assert key.default_icon("mic-1") == "Microphone"

    plain, _ = _key(plugin, vertex, plugin.vertex_keys.SonarToggleMic, first="desk_mic",
                    icons={"mic-1": "Camera"})
    plain.show(_state(mic="Desk mic"))              # no theme: the white set
    assert _icon(plain.media[-1]) == "White/Camera.png"

    replay, _ = _key(plugin, vertex, plugin.vertex_keys.ReplayToggle, theme=SPOOKY_C,
                     icons={"replay-off": "Media_Pause"})
    replay.show(_state(replay=False))               # picked: not faded
    assert _icon(replay.media[-1]).endswith("/Media_Pause.png")


def test_show_vertex_shows_the_logo(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.vertex_keys.ShowVertex, theme=("abyss", "D"))
    key.show(None)
    assert _icon(key.media[-1]) == "D_Cyan_Into_Magenta/Vertex_Logo.png"
    plain, _ = _key(plugin, vertex, plugin.vertex_keys.ShowVertex)      # no theme: the white logo
    plain.show(None)
    assert _icon(plain.media[-1]) == "White/Vertex_Logo.png"


def test_keys_draw_again_when_streamcontroller_asks(plugin, vertex):
    # A page load wipes the key and calls on_ready (by on_update) again, with
    # nothing changed in Vertex: the key must still put its image back.
    tile, client = _key(plugin, vertex, plugin.vertex_keys.SonarInformation, channel="game")
    clip, _ = _key(plugin, vertex, plugin.vertex_keys.ReplaySaveClip, theme=SPOOKY_C)
    clip.plugin_base.vertex = client
    client.state = _state()
    for key in (tile, clip):
        key.on_ready()
        key.on_ready()
        assert len(key.media) == 2 and key.media[-1] is not None
    client.redraw()                                   # listening once, not twice
    assert len(tile.media) == 2
