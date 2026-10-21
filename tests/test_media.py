"""The media keys: the client against a fake `gdbus` that answers as the
session bus would with MPRIS players on it, and the keys with
StreamController stubbed out."""

import os
import stat
import threading
import types
from pathlib import Path

import pytest
from conftest import Events, wait

SPOTIFY = "org.mpris.MediaPlayer2.spotify"
FIREFOX = "org.mpris.MediaPlayer2.firefox.instance_1_74"


def _props(status="Playing", title="Song", artist="Band", can_next=True):
    can = "true" if can_next else "false"
    return (f"({{'CanGoNext': <{can}>, 'CanGoPrevious': <true>, 'Metadata': <{{"
            f"'mpris:trackid': <objectpath '/com/spotify/track/1'>, 'xesam:title': "
            f"<{title!r}>, 'xesam:artist': <['{artist}']>}}>, 'PlaybackStatus': "
            f"<'{status}'>, 'Volume': <1.0>}},)")


class FakeBus:
    """`gdbus` on PATH: lists the players written in `players`, answers
    GetAll with each one's properties, and logs every method called."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.players: dict[str, str] = {}
        script = folder / "gdbus"
        script.write_text(f"""#!/bin/sh
dir="{folder}"
dest=""; method=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dest) dest="$2"; shift ;;
    --method) method="$2"; shift ;;
  esac
  shift
done
case "$method" in
  org.freedesktop.DBus.ListNames)
    printf "(['org.freedesktop.DBus', ':1.2'"
    for f in "$dir"/players/*; do [ -e "$f" ] && printf ", '%s'" "$(basename "$f")"; done
    printf '],)\\n' ;;
  org.freedesktop.DBus.Properties.GetAll)
    cat "$dir/players/$dest" 2>/dev/null || exit 1 ;;
  *)
    echo "$dest $method" >> "$dir/calls"
    echo "()" ;;
esac
""")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        (folder / "players").mkdir()

    def set(self, bus: str, props: str | None) -> None:
        path = self.folder / "players" / bus
        if props is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(props + "\n")

    def calls(self) -> list[str]:
        path = self.folder / "calls"
        return path.read_text().split("\n")[:-1] if path.exists() else []


@pytest.fixture
def bus(tmp_path, monkeypatch):
    fake = FakeBus(tmp_path)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return fake


@pytest.fixture
def media(plugin, bus):
    client = plugin.media_client.Media(host=None, poll=0.05)
    client.start()
    yield client
    client.stop()


# --- The client ---------------------------------------------------------------------

def test_parse_reads_the_players_properties(plugin):
    players = plugin.media_client.parse(
        [f"PLAYER {SPOTIFY}", _props(title="It's \"here\"", artist="The Band"),
         f"PLAYER {FIREFOX}", _props("Paused", can_next=False),
         "PLAYER org.mpris.MediaPlayer2.gone", ""]
    )
    assert players == [
        {"bus": SPOTIFY, "app": "spotify", "label": "Spotify", "status": "Playing",
         "title": "It's \"here\"", "artist": "The Band", "can_next": True,
         "can_previous": True},
        {"bus": FIREFOX, "app": "firefox", "label": "Firefox", "status": "Paused",
         "title": "Song", "artist": "Band", "can_next": False, "can_previous": True}]


def test_follows_the_players(plugin, bus, media):
    assert wait(lambda: media.state == {"players": []})
    bus.set(SPOTIFY, _props())
    assert wait(lambda: [p["app"] for p in media.players()] == ["spotify"])
    bus.set(FIREFOX, _props("Paused", title="Video"))
    assert wait(lambda: len(media.players()) == 2)
    bus.set(SPOTIFY, None)
    assert wait(lambda: [p["app"] for p in media.players()] == ["firefox"])


def test_no_gdbus_means_no_media(plugin, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))          # neither gdbus nor sh
    client = plugin.media_client.Media(host=None, poll=0.05)
    client._set_state({"players": []})
    client.start()
    try:
        assert wait(lambda: client.state is None and client.problem)
        assert client.problem.startswith("Couldn't run sh")
    finally:
        client.stop()


def test_says_why_gdbus_failed(plugin, tmp_path, monkeypatch):
    broken = tmp_path / "gdbus"
    broken.write_text("#!/bin/sh\necho 'Cannot autolaunch D-Bus without X11' >&2\nexit 1\n")
    broken.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    client = plugin.media_client.Media(host=None, poll=0.05)
    client.start()
    try:
        assert wait(lambda: client.problem)
        assert client.problem == ("gdbus couldn't list the players. "
                                  "Cannot autolaunch D-Bus without X11")
        assert "Cannot autolaunch" in plugin.main.media_status(None, client.problem)
    finally:
        client.stop()


def test_without_the_host_it_looks_in_the_sandbox(plugin, bus):
    # flatpak-spawn refused (or missing): the players are looked at, and
    # controlled, from where the plugin runs.
    client = plugin.media_client.Media(host=["/nonexistent/flatpak-spawn", "--host"],
                                       poll=0.05)
    bus.set(SPOTIFY, _props())
    client.start()
    try:
        assert wait(lambda: client.players())
        assert client.host == [] and client.problem == ""
        replies = []
        client.command("Pause", callback=replies.append)
        assert wait(lambda: replies) and replies[0]["ok"]
    finally:
        client.stop()


def test_the_host_runs_from_StreamControllers_folder(plugin, bus, flatpak_spawn):
    client = plugin.media_client.Media(host=flatpak_spawn, poll=0.05)
    bus.set(SPOTIFY, _props())
    client.start()
    try:
        assert wait(lambda: client.players())
        assert client.host == flatpak_spawn            # on the host, not the sandbox
        replies = []
        client.command("Pause", callback=replies.append)
        assert wait(lambda: replies) and replies[0]["ok"]
    finally:
        client.stop()


def test_the_player_a_key_controls(plugin):
    client = plugin.media_client.Media(host=None)
    client._set_state({"players": [
        {"bus": FIREFOX, "app": "firefox", "status": "Paused"},
        {"bus": SPOTIFY, "app": "spotify", "status": "Playing"}]})
    assert client.player()["app"] == "spotify"              # the one playing
    assert client.player("firefox")["bus"] == FIREFOX       # the one picked
    assert client.player("vlc") is None
    client._set_state({"players": [
        {"bus": FIREFOX, "app": "firefox", "status": "Paused"},
        {"bus": SPOTIFY, "app": "spotify", "status": "Paused"}]})
    assert client.player()["app"] == "spotify"              # the one that played last


def test_commands_go_to_the_player(plugin, bus, media):
    bus.set(SPOTIFY, _props())
    assert wait(lambda: media.players())
    replies = []
    media.command("Next", callback=replies.append)
    assert wait(lambda: replies)
    assert replies[0]["ok"]
    assert bus.calls() == [f"{SPOTIFY} org.mpris.MediaPlayer2.Player.Next"]


def test_play_pause_shows_at_once(plugin):
    client = plugin.media_client.Media(host=["env"])
    client._call = lambda bus, method: {"ok": True, "message": ""}
    client._set_state({"players": [{"bus": SPOTIFY, "app": "spotify", "status": "Playing"}]})
    client.command("PlayPause")
    assert wait(lambda: client.players()[0]["status"] == "Paused")


def test_a_command_without_a_player_fails(plugin):
    client = plugin.media_client.Media(host=None)
    client._set_state({"players": []})
    replies = []
    client.command("PlayPause", callback=replies.append)
    assert wait(lambda: replies) and not replies[0]["ok"]


# --- The keys -----------------------------------------------------------------------

def _key(plugin, cls, client, theme=("white", "A"), **settings):
    base = types.SimpleNamespace(media=client, theme=theme, PATH="")
    key = getattr(plugin.media_keys, cls)(plugin_base=base, settings=settings)
    key.on_ready()
    return key


def _shown(key):
    return Path(key.media[-1]).name if key.media and isinstance(key.media[-1], str) else None


def _players(*players):
    return {"players": [{"bus": f"org.mpris.MediaPlayer2.{app}", "app": app,
                         "label": app.title(), "status": status, "title": f"{app} song",
                         "artist": "Band", "can_next": True, "can_previous": app != "mpv"}
                        for app, status in players]}


def test_play_pause_key_shows_what_a_press_does(plugin):
    client = plugin.media_client.Media(host=None)
    client._set_state(_players(("spotify", "Playing")))
    key = _key(plugin, "MediaPlayPause", client)
    assert _shown(key) == "Media_Pause.png"
    assert key.labels == {"top": "", "center": "", "bottom": "spotify song"}
    client._set_state(_players(("spotify", "Paused")))
    assert _shown(key) == "Media_Play.png"


def test_play_pause_key_without_a_theme_shows_labels(plugin):
    client = plugin.media_client.Media(host=None)
    client._set_state(_players(("spotify", "Paused")))
    key = _key(plugin, "MediaPlayPause", client, theme=("", "A"), show_artist=True)
    assert key.labels == {"top": "Media", "center": "Paused", "bottom": "Band – spotify song"}
    assert key.media == []


def test_keys_fade_without_a_player(plugin):
    client = plugin.media_client.Media(host=None)
    client._set_state({"players": []})
    key = _key(plugin, "MediaNext", client)
    assert _shown(key) is None and key.media[-1].size == (144, 144)       # faded
    assert key.labels["bottom"] == "No player"
    key.on_key_down()
    assert key.errors == 1
    client._set_state(None)
    assert key.labels["bottom"] == "No media"


def test_next_and_previous_keys(plugin):
    client = plugin.media_client.Media(host=None)
    calls = []
    client.command = lambda method, app="", callback=None: calls.append((method, app))
    client._set_state(_players(("mpv", "Playing"), ("spotify", "Paused")))
    following = _key(plugin, "MediaNext", client, show_song=False)
    assert _shown(following) == "Media_Next.png" and following.labels["bottom"] == ""
    following.on_key_down()
    back = _key(plugin, "MediaPrevious", client)
    assert back.labels["bottom"] == "Can't go back"                 # mpv says it can't
    pinned = _key(plugin, "MediaPrevious", client, player="spotify")
    pinned.on_key_down()
    assert calls == [("Next", ""), ("Previous", "spotify")]


def test_play_pause_key_on_a_dial_and_set_to_pause(plugin):
    client = plugin.media_client.Media(host=None)
    calls = []
    client.command = lambda method, app="", callback=None: calls.append(method)
    client._set_state(_players(("spotify", "Playing")))
    key = _key(plugin, "MediaPlayPause", client)
    for event in (Events.TURN_CW, Events.TURN_CCW, Events.DOWN):
        key.event_callback(event)
    pause = _key(plugin, "MediaPlayPause", client, press="Pause")
    pause.on_key_down()
    client._set_state(_players(("spotify", "Paused")))
    assert _shown(pause) == "Media_Pause.png"                        # always pauses
    assert calls == ["Next", "Previous", "PlayPause", "Pause"]


def test_media_keys_list_the_running_players(plugin):
    client = plugin.media_client.Media(host=None)
    client._set_state(_players(("spotify", "Playing"), ("firefox", "Paused")))
    key = _key(plugin, "MediaNext", client, player="vlc")
    assert key._players() == [("", "The one playing"), ("spotify", "Spotify"),
                              ("firefox", "Firefox"), ("vlc", "vlc (not running)")]


def test_media_status(plugin):
    status = plugin.main.media_status
    assert status(None).startswith("Can't reach")
    assert status({"players": []}) == "No media player is running."
    assert status(_players(("spotify", "Playing"))) == "Found Spotify (playing)."


def test_a_watcher_round_is_one_state(plugin, bus, media):
    # Each round of the watcher turns into one state, not one per player.
    bus.set(SPOTIFY, _props())
    bus.set(FIREFOX, _props("Paused"))
    seen = []
    media.add_listener(listener := lambda event, data: seen.append(data))
    assert wait(lambda: len(media.players()) == 2)
    threading.Event().wait(0.2)
    assert all(state is None or len(state["players"]) in (0, 2) for state in seen)
    del listener
