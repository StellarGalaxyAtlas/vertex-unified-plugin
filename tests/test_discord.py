"""Discord's keys: the client against a fake Discord speaking the RPC
protocol on a socket, and the keys with StreamController stubbed out."""

import json
import socket
import struct
import threading
import types
from pathlib import Path

import pytest
from conftest import PLUGIN
from conftest import wait as _wait

# --- A Discord that answers ---------------------------------------------------------

def _send(conn, op, payload):
    data = json.dumps(payload).encode()
    conn.sendall(struct.pack("<II", op, len(data)) + data)


def _read(conn, size):
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


class FakeDiscord:
    """Discord's RPC server, as far as the plugin uses it."""

    TOKEN = "good-token"

    def __init__(self, path):
        self.path = path
        self.received = []
        self.handshakes = []
        self.voice = {"mute": False, "deaf": False}
        self.channel = None
        self.video = False
        self.refuse = set()            # commands answered with an error
        self.refuse_scopes = set()     # scopes AUTHORIZE won't take
        self.decline = False           # the user says no to the popup
        self.refuse_redirect = False   # AUTHORIZE takes no redirect_uri
        self.silent = 0                # handshakes left unanswered, as by a Discord starting
        self.conns = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.conns.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        while True:
            header = _read(conn, 8)
            if header is None:
                return
            op, length = struct.unpack("<II", header)
            payload = json.loads(_read(conn, length))
            if op == 0:
                self.handshakes.append(payload)
                if self.silent:
                    self.silent -= 1
                    continue
                _send(conn, 1, {"cmd": "DISPATCH", "evt": "READY", "data": {"v": 1}})
                continue
            self.received.append((payload["cmd"], payload.get("args"), payload.get("evt")))
            reply = {"cmd": payload["cmd"], "nonce": payload["nonce"]}
            try:
                reply["data"] = self._answer(conn, payload)
            except ValueError as exc:
                reply.update(evt="ERROR", data={"code": 4000, "message": str(exc)})
            _send(conn, 1, reply)

    def _answer(self, conn, payload):
        cmd, args = payload["cmd"], payload.get("args") or {}
        if cmd in self.refuse:
            raise ValueError("Refused")
        if cmd == "AUTHORIZE":
            if self.refuse_redirect and "redirect_uri" in args:
                raise ValueError("OAuth2 Error: Redirect URI cannot be used in the RPC "
                                 "OAuth2 Authorization flow")
            bad = set(args["scopes"]) & self.refuse_scopes
            if bad:
                raise ValueError("OAuth2 Error: invalid_scope: The requested scope is "
                                 "invalid, unknown, or malformed.")
            if self.decline:
                raise ValueError("OAuth2 Error: access_denied")
            return {"code": "the-code"}
        if cmd == "AUTHENTICATE":
            if args["access_token"] != self.TOKEN:
                raise ValueError("Invalid access token")
            return {"scopes": ["rpc", "rpc.voice.read"], "user": {"id": "1"}}
        if cmd == "SUBSCRIBE":
            return {"evt": payload["evt"]}
        if cmd == "GET_VOICE_SETTINGS":
            return dict(self.voice)
        if cmd == "SET_VOICE_SETTINGS":
            self.voice.update({k: v for k, v in args.items() if k in ("mute", "deaf")})
            self.dispatch("VOICE_SETTINGS_UPDATE", dict(self.voice), conn)
            return dict(self.voice)
        if cmd == "GET_SELECTED_VOICE_CHANNEL":
            return self.channel
        if cmd == "SELECT_VOICE_CHANNEL":
            channel_id = args.get("channel_id")
            self.channel = {"id": channel_id, "name": f"Room {channel_id}",
                            "guild_id": "g1"} if channel_id else None
            self.dispatch("VOICE_CHANNEL_SELECT",
                          {"channel_id": channel_id, "guild_id": "g1"}, conn)
            return self.channel
        if cmd == "TOGGLE_VIDEO":
            if not self.channel:
                raise ValueError("Not in a voice channel")
            self.video = not self.video
            self.dispatch("VIDEO_STATE_UPDATE", {"active": self.video}, conn)
            return None
        if cmd == "TOGGLE_SCREENSHARE":
            return None
        if cmd == "GET_GUILDS":
            return {"guilds": [{"id": "g1", "name": "Home"}]}
        if cmd == "GET_CHANNELS":
            return {"channels": [{"id": "c1", "name": "General", "type": 2},
                                 {"id": "t1", "name": "chat", "type": 0}]}
        raise ValueError(f"Unknown {cmd}")

    def dispatch(self, evt, data, conn=None):
        for target in [conn] if conn else self.conns:
            try:
                _send(target, 1, {"cmd": "DISPATCH", "evt": evt, "data": data})
            except OSError:
                pass

    def close(self):
        self.server.close()
        for conn in self.conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()


@pytest.fixture
def discord(tmp_path):
    fake = FakeDiscord(str(tmp_path / "discord-ipc-0"))
    yield fake
    fake.close()


def _client(plugin, discord, monkeypatch, **kwargs):
    monkeypatch.setattr(plugin.discord_client, "RETRY", 0.1)
    saved = []
    kwargs.setdefault("client_id", "123")
    kwargs.setdefault("client_secret", "secret")
    client = plugin.discord_client.Discord(socket_path=discord.path, relay=None,
                                   save_tokens=lambda *tokens: saved.append(tokens),
                                   **kwargs)
    client.saved = saved
    return client


def _token_server(monkeypatch, plugin, client, token="good-token"):
    """Discord's web API, for swapping a code or refresh token for tokens."""
    forms = []

    class Response:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def urlopen(request, timeout=None):
        forms.append(dict(item.split("=", 1) for item in request.data.decode().split("&")))
        return Response(json.dumps({"access_token": token,
                                    "refresh_token": "new-refresh"}).encode())
    monkeypatch.setattr(plugin.discord_client.urllib.request, "urlopen", urlopen)
    return forms


# --- The client ---------------------------------------------------------------------

def test_saved_token_logs_in_and_follows_state(plugin, discord, monkeypatch):
    client = _client(plugin, discord, monkeypatch, access_token="good-token")
    discord.voice["mute"] = True
    client.start()
    try:
        assert _wait(lambda: plugin.discord_client.ready(client.state) and client.state["mute"])
        assert discord.handshakes == [{"v": 1, "client_id": "123"}]
        assert not any(cmd == "AUTHORIZE" for cmd, *_ in discord.received)
        subscribed = {evt for cmd, _args, evt in discord.received if cmd == "SUBSCRIBE"}
        assert subscribed == set(plugin.discord_client.EVENTS)
        discord.dispatch("VOICE_SETTINGS_UPDATE", {"mute": False, "deaf": True})
        assert _wait(lambda: client.state["deaf"] and not client.state["mute"])
        discord.dispatch("VIDEO_STATE_UPDATE", {"active": True})
        assert _wait(lambda: client.state["video"])
        discord.dispatch("SCREENSHARE_STATE_UPDATE", {"active": True, "pid": 7})
        assert _wait(lambda: client.state["screenshare"])
    finally:
        client.stop()


def test_first_login_asks_with_camera_scopes(plugin, discord, monkeypatch):
    client = _client(plugin, discord, monkeypatch)
    forms = _token_server(monkeypatch, plugin, client)
    client.start()
    try:
        assert _wait(lambda: plugin.discord_client.ready(client.state))
        scopes = [args["scopes"] for cmd, args, _ in discord.received if cmd == "AUTHORIZE"]
        assert scopes == [list(plugin.discord_client.SCOPES + plugin.discord_client.VIDEO_SCOPES)]
        assert forms[0]["grant_type"] == "authorization_code"
        assert forms[0]["code"] == "the-code"
        assert client.saved == [("good-token", "new-refresh")]
    finally:
        client.stop()


def test_login_goes_on_without_camera_scopes(plugin, discord, monkeypatch):
    discord.refuse_scopes = {"rpc.video.write"}
    refused = []
    client = _client(plugin, discord, monkeypatch, video_refused=lambda: refused.append(1))
    _token_server(monkeypatch, plugin, client)
    client.start()
    try:
        assert _wait(lambda: plugin.discord_client.ready(client.state))
        asked = [args for cmd, args, _ in discord.received if cmd == "AUTHORIZE"]
        assert [args["scopes"] for args in asked] == \
            [list(plugin.discord_client.SCOPES + plugin.discord_client.VIDEO_SCOPES),
             list(plugin.discord_client.SCOPES)]
        assert asked[0]["redirect_uri"] == plugin.discord_client.REDIRECT
        assert refused == [1] and client.ask_video is False
        client.authorize()                 # the next login asks once, without them
        assert _wait(lambda: len([c for c, *_ in discord.received if c == "AUTHORIZE"]) == 3)
        assert _wait(lambda: plugin.discord_client.ready(client.state))
        last = [args for cmd, args, _ in discord.received if cmd == "AUTHORIZE"][-1]
        assert last["scopes"] == list(plugin.discord_client.SCOPES)
    finally:
        client.stop()


def test_an_account_discord_wont_let_in_is_told_about_app_testers(plugin, discord,
                                                                  monkeypatch):
    discord.refuse_scopes = {"rpc"}            # not the app's developer or a tester
    client = _client(plugin, discord, monkeypatch)
    _token_server(monkeypatch, plugin, client)
    client.start()
    try:
        assert _wait(lambda: (client.state or {}).get("status") == plugin.discord_client.DECLINED)
        assert "App Testers" in client.problem
        assert client.ask_video is True        # nothing learned about the camera
    finally:
        client.stop()


def test_declined_asks_once_until_authorize(plugin, discord, monkeypatch):
    discord.decline = True
    client = _client(plugin, discord, monkeypatch)
    _token_server(monkeypatch, plugin, client)
    client.start()
    try:
        assert _wait(lambda: (client.state or {}).get("status") == plugin.discord_client.DECLINED)
        discord.decline = False
        client.reconnect()             # a reconnect alone doesn't open the popup again
        assert _wait(lambda: (client.state or {}).get("status") == plugin.discord_client.AUTHORIZE)
        assert sum(cmd == "AUTHORIZE" for cmd, *_ in discord.received) == 1
        client.authorize()
        assert _wait(lambda: plugin.discord_client.ready(client.state))
    finally:
        client.stop()


def test_expired_token_is_refreshed(plugin, discord, monkeypatch):
    client = _client(plugin, discord, monkeypatch, access_token="old", refresh_token="r")
    forms = _token_server(monkeypatch, plugin, client)
    client.start()
    try:
        assert _wait(lambda: plugin.discord_client.ready(client.state))
        assert forms[0]["grant_type"] == "refresh_token"
        assert not any(cmd == "AUTHORIZE" for cmd, *_ in discord.received)
    finally:
        client.stop()


def test_no_app_and_not_running(plugin, discord, tmp_path, monkeypatch):
    client = _client(plugin, discord, monkeypatch, client_id="")
    client.start()
    try:
        assert _wait(lambda: (client.state or {}).get("status") == plugin.discord_client.NO_APP)
    finally:
        client.stop()
    gone = plugin.discord_client.Discord("123", socket_path=str(tmp_path / "missing"), relay=None)
    with pytest.raises(plugin.discord_client.NotRunning):
        gone.send("GET_VOICE_SETTINGS")
    replies = []
    gone.request("GET_VOICE_SETTINGS", callback=replies.append)
    assert _wait(lambda: replies)
    assert replies[0]["ok"] is False and replies[0]["error"] == "not_running"


def test_discord_quitting(plugin, discord, monkeypatch):
    client = _client(plugin, discord, monkeypatch, access_token="good-token")
    client.start()
    try:
        assert _wait(lambda: plugin.discord_client.ready(client.state))
        discord.close()
        assert _wait(lambda: client.state is None)
    finally:
        client.stop()


def test_find_socket(plugin, tmp_path, monkeypatch):
    monkeypatch.delenv("DISCORD_IPC_PATH", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "none"))
    assert plugin.discord_client.find_socket() == ""
    flatpak = tmp_path / "app" / "com.discordapp.Discord"
    flatpak.mkdir(parents=True)
    (flatpak / "discord-ipc-0").touch()
    assert plugin.discord_client.find_socket() == str(flatpak / "discord-ipc-0")
    (tmp_path / "discord-ipc-0").touch()
    assert plugin.discord_client.find_socket() == str(tmp_path / "discord-ipc-0")


# --- The keys -----------------------------------------------------------------------

@pytest.fixture
def live(plugin, discord, monkeypatch):
    """A plugin connected and logged in to the fake Discord."""
    client = _client(plugin, discord, monkeypatch, access_token="good-token")
    client.start()
    assert _wait(lambda: plugin.discord_client.ready(client.state))
    base = types.SimpleNamespace(discord=client, theme=("white", "A"), PATH=str(PLUGIN))
    yield base
    client.stop()


def _key(plugin, cls, base, **settings):
    key = getattr(plugin.discord_keys, cls)(plugin_base=base, settings=settings)
    key.on_ready()
    return key


def _shown(key):
    return Path(key.media[-1]).name if key.media and isinstance(key.media[-1], str) else None


def test_mute_key_toggles_and_shows(plugin, live, discord):
    key = _key(plugin, "ToggleMute", live)
    assert _shown(key) == "Microphone_Unmuted.png"
    key.on_key_down()
    assert _wait(lambda: discord.voice["mute"])
    assert _wait(lambda: _shown(key) == "Microphone_Muted.png")
    key.on_key_down()
    assert _wait(lambda: not discord.voice["mute"])


def test_deafen_key(plugin, live, discord):
    key = _key(plugin, "ToggleDeafen", live)
    key.on_key_down()
    assert _wait(lambda: discord.voice["deaf"])
    assert _wait(lambda: _shown(key) == "Speaker_Deafened.png")


def test_camera_key_needs_a_call(plugin, live, discord):
    key = _key(plugin, "ToggleCamera", live)
    assert key.labels["bottom"] == "No call"
    key.on_key_down()
    assert key.errors == 1
    live.discord.join("c1")
    assert _wait(lambda: plugin.discord_client.in_call(live.discord.state))
    assert _wait(lambda: key.labels["bottom"] == "")
    key.on_key_down()
    assert _wait(lambda: _shown(key) == "Camera_Off.png")      # on: the next press turns it off
    assert ("TOGGLE_VIDEO", {}, None) in discord.received


def test_screenshare_key_without_events_flips_itself(plugin, live, discord):
    live.discord._live.discard("SCREENSHARE_STATE_UPDATE")
    live.discord.join("c1")
    assert _wait(lambda: plugin.discord_client.in_call(live.discord.state))
    key = _key(plugin, "ToggleScreenshare", live)
    assert _shown(key) == "Screenshare.png"
    key.on_key_down()
    assert _wait(lambda: _shown(key) == "Screenshare_Off.png")


def test_voice_channel_key_joins_and_leaves(plugin, live, discord):
    key = _key(plugin, "VoiceChannel", live, channel_id="c1", channel_name="General")
    assert key.labels["bottom"] == "General"
    key.on_key_down()
    assert _wait(lambda: (live.discord.state["channel"] or {}).get("id") == "c1")
    assert _wait(lambda: (live.discord.state["channel"] or {}).get("name") == "Room c1")
    key.on_key_down()
    assert _wait(lambda: live.discord.state["channel"] is None)
    stay = _key(plugin, "VoiceChannel", live, channel_id="c1", when_in="stay")
    stay.on_key_down()
    assert _wait(lambda: live.discord.state["channel"] is not None)
    count = len(discord.received)
    stay.on_key_down()
    threading.Event().wait(0.2)
    assert len(discord.received) == count


def test_voice_channel_lists_voice_channels(plugin, live):
    assert live.discord.guilds() == [{"id": "g1", "name": "Home"}]
    assert [c["id"] for c in live.discord.voice_channels("g1")] == ["c1"]


def test_keys_while_discord_is_off(plugin, tmp_path):
    client = plugin.discord_client.Discord("123", socket_path=str(tmp_path / "missing"), relay=None)
    base = types.SimpleNamespace(discord=client, theme=("white", "A"), PATH=str(PLUGIN))
    key = _key(plugin, "ToggleMute", base)
    assert key.labels["bottom"] == "Discord off"
    key.on_key_down()
    assert key.errors == 1


def test_theme_picks_the_icon_set(plugin, live):
    live.theme = ("navy", "C")
    key = _key(plugin, "ToggleDeafen", live)
    assert "Navy/C_Periwinkle_Blue_Highlights/Speaker_Undeafened.png" in key.media[-1]
    live.theme = ("", "A")                  # None: labels only
    key = _key(plugin, "ToggleDeafen", live)
    assert key.media == [] and key.labels["center"] == "On"


def test_every_theme_has_every_icon(plugin):
    theme = plugin.theme
    for name in theme.THEMES:
        for version, _label in theme.VERSIONS:
            for icon in theme.ICON_NAMES:
                assert theme.icon_path(name, version, icon), (name, version, icon)


def test_plugin_registers_keys_and_saves_settings(registered):
    main = registered
    names = {holder.action_id_suffix: holder.action_name for holder in main.holders}
    assert names.items() >= {
        "DiscordMute": "Discord Toggle Mute", "DiscordDeafen": "Discord Toggle Deafen",
        "DiscordCamera": "Discord Toggle Camera",
        "DiscordScreenshare": "Discord Toggle Screen Share",
        "DiscordVoiceChannel": "Discord Voice Channel"}.items()
    assert main.theme == ("white", "A")
    main.set_theme("plum", "E")
    assert main.get_settings()["theme"] == "plum"
    main.save_tokens("a", "r")
    assert main.get_settings()["access_token"] == "a"


def test_relay_when_the_sandbox_cannot_see_the_socket(plugin, discord, tmp_path, monkeypatch):
    # The fake's socket is $XDG_RUNTIME_DIR/discord-ipc-0, which the relay finds
    # on the "host"; the plugin itself is made not to see it.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(plugin.discord_client, "find_socket", lambda: "")
    monkeypatch.setattr(plugin.discord_client, "RETRY", 0.1)
    client = plugin.discord_client.Discord("123", access_token="good-token", relay=["env"])
    client.start()
    try:
        assert _wait(lambda: plugin.discord_client.ready(client.state))
        client.toggle_mute()
        assert _wait(lambda: discord.voice["mute"])
    finally:
        client.stop()


# A relay that can't start, as flatpak-spawn says when the host won't run it.
FAILING_RELAY = ["sh", "-c", "echo 'Portal call failed: no such method' >&2; exit 1", "sh"]

def test_says_why_the_relay_failed(plugin, monkeypatch):
    monkeypatch.setattr(plugin.discord_client, "find_socket", lambda: "")
    monkeypatch.setattr(plugin.discord_client, "RETRY", 0.1)
    client = plugin.discord_client.Discord("123", relay=FAILING_RELAY)
    client.start()
    try:
        assert _wait(lambda: "failed" in client.problem)
        assert client.problem == ("The relay to the host failed (1): "
                                  "Portal call failed: no such method")
    finally:
        client.stop()


def test_a_dead_socket_in_sight_falls_back_to_the_relay(plugin, discord, tmp_path,
                                                        monkeypatch):
    # A socket the sandbox sees but can't connect to (left over, or another
    # sandbox's): the relay finds the live one on the host.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    dead = tmp_path / "dead" / "discord-ipc-0"
    dead.parent.mkdir()
    dead.write_text("")
    monkeypatch.setattr(plugin.discord_client, "RETRY", 0.1)
    client = plugin.discord_client.Discord("123", access_token="good-token",
                                           socket_path=str(dead), relay=["env"])
    client.start()
    try:
        assert _wait(lambda: plugin.discord_client.ready(client.state))
    finally:
        client.stop()


def test_a_discord_that_never_says_ready_is_tried_again(plugin, discord, monkeypatch):
    monkeypatch.setattr(plugin.discord_client, "READY_TIMEOUT", 0.3)
    discord.silent = 1
    client = _client(plugin, discord, monkeypatch, access_token="good-token")
    problems = []
    client.add_listener(listener := lambda event, data: problems.append(client.problem))
    client.start()
    try:
        assert _wait(lambda: plugin.discord_client.ready(client.state))
        assert len(discord.handshakes) == 2
        assert any("didn't answer within 0.3 seconds" in problem for problem in problems)
        assert client.problem == ""
    finally:
        client.stop()
    del listener


def test_a_relay_that_hangs_is_dropped(plugin, monkeypatch):
    monkeypatch.setattr(plugin.discord_client, "READY_TIMEOUT", 0.3)
    monkeypatch.setattr(plugin.discord_client, "find_socket", lambda: "")
    monkeypatch.setattr(plugin.discord_client, "RETRY", 0.1)
    client = plugin.discord_client.Discord("123", relay=["sh", "-c", "exec sleep 60", "sh"])
    client.start()
    try:
        assert _wait(lambda: "didn't answer" in client.problem)
    finally:
        client.stop()


def test_authorizes_without_the_redirect_when_discord_refuses_it(plugin, discord,
                                                                 monkeypatch):
    discord.refuse_redirect = True
    client = _client(plugin, discord, monkeypatch)
    forms = _token_server(monkeypatch, plugin, client)
    client.start()
    try:
        assert _wait(lambda: plugin.discord_client.ready(client.state))
        authorized = [args for cmd, args, _ in discord.received if cmd == "AUTHORIZE"]
        assert "redirect_uri" in authorized[0] and "redirect_uri" not in authorized[-1]
        assert forms[0]["code"] == "the-code" and "redirect_uri" not in forms[0]
        assert client.saved == [("good-token", "new-refresh")]
    finally:
        client.stop()


def test_a_failed_token_swap_says_why(plugin, discord, monkeypatch):
    import io
    import urllib.error

    def urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {},
                                     io.BytesIO(b'{"error": "invalid_client"}'))
    monkeypatch.setattr(plugin.discord_client.urllib.request, "urlopen", urlopen)
    client = _client(plugin, discord, monkeypatch)
    client.start()
    try:
        assert _wait(lambda: (client.state or {}).get("status") == plugin.discord_client.DECLINED)
        assert client.problem == "Discord didn't give a token (401): invalid_client"
        assert "invalid_client" in plugin.main.status_text(client.state, client.problem)
    finally:
        client.stop()
