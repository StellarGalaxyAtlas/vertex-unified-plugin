"""Talks to the running Discord over its local RPC socket.

Discord listens on `discord-ipc-<n>` in the runtime folder (or the folder of
its Flatpak or Snap). Each message is framed as two little-endian 32-bit
numbers, the opcode and the length, then that many bytes of JSON. The
client sends a handshake with the app's client id, Discord answers READY,
and after that the plugin logs in (AUTHORIZE once, then AUTHENTICATE with a
saved token) and sends commands matched to replies by their nonce.

Discord allows only a couple of new connections a minute, so the plugin
keeps one open for everything: the state every key shows and every command
a key sends.

Standard library only: this runs in StreamController's Python.
StreamController's Flatpak can't see the socket unless it was given it
(`xdg-run/discord-ipc-0`, in Flatseal or with `flatpak override`). Without
it, the connection goes through a small relay that `flatpak-spawn --host`
runs on the host.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import weakref
from collections.abc import Callable

TIMEOUT = 5.0
AUTHORIZE_TIMEOUT = 120.0     # the user answers Discord's popup
RETRY = 3.0                   # seconds between attempts to reach a Discord that isn't running
REDIRECT = "http://localhost:9000"
TOKEN_URL = "https://discord.com/api/oauth2/token"
USER_AGENT = ("DiscordBot (https://github.com/StellarGalaxyAtlas/"
              "vertex-private, 0.3)")

HANDSHAKE, FRAME, CLOSE, PING, PONG = 0, 1, 2, 3, 4

# What the keys need: voice settings and channels.
SCOPES = ("rpc", "rpc.voice.read", "rpc.voice.write")
# The camera and screen share. Discord doesn't document these, and may not
# grant them to every app; without them the login goes on with SCOPES.
VIDEO_SCOPES = ("rpc.video.read", "rpc.video.write",
                "rpc.screenshare.read", "rpc.screenshare.write")

EVENTS = ("VOICE_SETTINGS_UPDATE", "VOICE_CHANNEL_SELECT",
          "VIDEO_STATE_UPDATE", "SCREENSHARE_STATE_UPDATE")

# The states before the keys work, as `state["status"]`.
NO_APP = "no_app"             # no client id in the plugin's settings
LOGGING_IN = "logging_in"
AUTHORIZE = "authorize"       # waiting for the user to allow the app in Discord
DECLINED = "declined"         # the user said no, or the login failed
READY = "ready"


def _folders() -> list[str]:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    folders = []
    for base in (runtime, f"/run/user/{os.getuid()}"):
        folders += [base, *(os.path.join(base, sub) for sub in (
            "app/com.discordapp.Discord", "app/com.discordapp.DiscordCanary",
            "app/com.discordapp.DiscordPTB", "app/dev.vencord.Vesktop",
            "snap.discord", "snap.discord-canary", "snap.discord-ptb", ".flatpak"))]
    folders.append(os.environ.get("TMPDIR") or "/tmp")
    return list(dict.fromkeys(folders))


def find_socket() -> str:
    """Discord's socket, or "" without one in sight."""
    override = os.environ.get("DISCORD_IPC_PATH")
    if override and os.path.exists(override):
        return override
    for number in range(10):
        for folder in _folders():
            path = os.path.join(folder, f"discord-ipc-{number}")
            if os.path.exists(path):
                return path
    return ""


# Run on the host by `flatpak-spawn --host python3 -c RELAY`: finds Discord's
# socket as `find_socket` does, connects, and copies bytes both ways.
RELAY = r"""
import os, socket, sys, threading
run = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
subs = ["", "app/com.discordapp.Discord", "app/com.discordapp.DiscordCanary",
        "app/com.discordapp.DiscordPTB", "app/dev.vencord.Vesktop", "snap.discord",
        "snap.discord-canary", "snap.discord-ptb", ".flatpak"]
folders = [os.path.join(run, s) for s in subs] + [os.environ.get("TMPDIR") or "/tmp"]
paths = [os.path.join(f, "discord-ipc-%d" % n) for n in range(10) for f in folders]
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
for path in paths:
    if os.path.exists(path):
        try:
            client.connect(path)
            break
        except OSError:
            pass
else:
    sys.exit(3)
def pump():
    while True:
        data = os.read(0, 65536)
        if not data:
            break
        client.sendall(data)
    client.shutdown(socket.SHUT_WR)
threading.Thread(target=pump, daemon=True).start()
while True:
    data = client.recv(65536)
    if not data:
        break
    os.write(1, data)
"""


def in_flatpak() -> bool:
    return os.path.exists("/.flatpak-info")


class NotRunning(RuntimeError):
    def __init__(self, message: str = "Discord is not running."):
        super().__init__(message)


class _Pipe:
    """The connection to Discord: its socket, or the relay's stdin and stdout."""

    def __init__(self, path: str, relay: list[str] | None):
        self._sock = self._proc = None
        if relay is None:
            if not path:
                raise NotRunning()
            try:
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._sock.connect(path)
            except OSError as exc:
                self.close()
                raise NotRunning() from exc
        else:
            try:
                self._proc = subprocess.Popen(relay, stdin=subprocess.PIPE,
                                              stdout=subprocess.PIPE,
                                              stderr=subprocess.DEVNULL)
            except OSError as exc:
                raise NotRunning() from exc

    def write(self, data: bytes) -> None:
        if self._sock is not None:
            self._sock.sendall(data)
        else:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()

    def read(self, size: int) -> bytes:
        """Exactly `size` bytes, or b"" once the connection is gone."""
        data = b""
        while len(data) < size:
            try:
                chunk = (self._sock.recv(size - len(data)) if self._sock is not None
                         else self._proc.stdout.read(size - len(data)))
            except (OSError, ValueError):
                return b""
            if not chunk:
                return b""
            data += chunk
        return data

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()       # flatpak-spawn passes it on to the relay
            try:
                self._proc.wait(2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()


def frame(op: int, payload: dict) -> bytes:
    data = json.dumps(payload).encode()
    return struct.pack("<II", op, len(data)) + data


Listener = Callable[[str, dict | None], None]
SaveTokens = Callable[[str, str], None]


class Discord:
    """The running Discord, as the plugin's actions see it.

    `state` is None while Discord can't be reached, else a dict: "status"
    (NO_APP, LOGGING_IN, AUTHORIZE, DECLINED or READY), "mute", "deaf",
    "video" and "screenshare" (booleans), "channel" (the voice channel the
    user is in, as {"id", "name", "guild_id"}, or None), and "scopes" (what
    the login granted). Listeners are called on a background thread with
    ("state", state-or-None) whenever it changes, and are held weakly, so an
    action StreamController has thrown away stops getting calls.
    """

    def __init__(self, client_id: str = "", client_secret: str = "",
                 redirect_uri: str = REDIRECT, access_token: str = "",
                 refresh_token: str = "", save_tokens: SaveTokens | None = None,
                 ask_video: bool = True, video_refused: Callable[[], None] | None = None,
                 socket_path: str | None = None, relay: list[str] | bool | None = True):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri or REDIRECT
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.save_tokens = save_tokens
        # Whether to ask for the camera and screen share scopes; once Discord
        # refused them while taking the rest, `video_refused` is told so the
        # next login asks once instead of twice.
        self.ask_video = ask_video
        self.video_refused = video_refused
        self.socket_path = socket_path      # None: look for it each time
        # True: pick by whether we are in the Flatpak; a list: the relay's
        # command prefix; None: always the socket.
        if relay is True:
            relay = ["flatpak-spawn", "--host"] if in_flatpak() else None
        self.relay = None if relay is None else [*relay, "python3", "-c", RELAY]
        self.token_url = TOKEN_URL
        self.state: dict | None = None
        self._listeners: list[weakref.ref] = []
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._pending: dict[str, list] = {}          # nonce: [event, reply]
        self._pipe: _Pipe | None = None
        self._live: set[str] = set()                 # the events Discord sends us
        self._ask = True          # may the login open Discord's popup on its own
        # Why the last connection or login went wrong, for the settings' status.
        self.problem = ""
        self._stopping = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # --- Settings -----------------------------------------------------------------

    def configure(self, client_id: str, client_secret: str, redirect_uri: str,
                  connect: bool = True) -> None:
        """New app details: log in again with them (without `connect`, at the
        next connection)."""
        changed = (client_id, client_secret, redirect_uri or REDIRECT) != \
            (self.client_id, self.client_secret, self.redirect_uri)
        if not changed:
            return
        if client_id != self.client_id:
            self.access_token = self.refresh_token = ""
        self.client_id, self.client_secret = client_id, client_secret
        self.redirect_uri = redirect_uri or REDIRECT
        self._ask = True
        if connect:
            self.reconnect()

    def authorize(self) -> None:
        """Ask the user again, in Discord, to allow the app (the settings' button)."""
        self._ask = True
        self.access_token = self.refresh_token = ""
        self._problem("")
        self.reconnect()

    def _problem(self, problem: str) -> None:
        if problem != self.problem:
            self.problem = problem
            self._emit("state", self.state)

    def reconnect(self) -> None:
        pipe = self._pipe
        if pipe is not None:
            pipe.close()
        self._wake.set()

    # --- Requests -----------------------------------------------------------------

    def send(self, command: str, args: dict | None = None, evt: str | None = None,
             timeout: float = TIMEOUT) -> dict:
        """Send one command and return Discord's reply: a dict with "ok", and
        "data" or "message". Raises NotRunning."""
        pipe = self._pipe
        if pipe is None:
            raise NotRunning()
        nonce = str(uuid.uuid4())
        payload = {"cmd": command, "args": args or {}, "nonce": nonce}
        if evt:
            payload["evt"] = evt
        waiting = [threading.Event(), None]
        self._pending[nonce] = waiting
        try:
            try:
                with self._write_lock:
                    pipe.write(frame(FRAME, payload))
            except (OSError, ValueError) as exc:
                raise NotRunning() from exc
            if not waiting[0].wait(timeout):
                return {"ok": False, "message": f"Discord didn't answer {command}."}
        finally:
            self._pending.pop(nonce, None)
        reply = waiting[1]
        if reply is None:
            raise NotRunning()
        if reply.get("evt") == "ERROR":
            data = reply.get("data") or {}
            return {"ok": False, "code": data.get("code"),
                    "message": data.get("message") or "Discord refused it."}
        return {"ok": True, "data": reply.get("data")}

    def request(self, command: str, args: dict | None = None,
                callback: Callable[[dict], None] | None = None) -> None:
        """`send` on a thread of its own, so a key press never waits on
        Discord. The callback gets the reply."""
        def run():
            try:
                reply = self.send(command, args)
            except NotRunning as exc:
                reply = {"ok": False, "error": "not_running", "message": str(exc)}
            if callback is not None:
                callback(reply)
        threading.Thread(target=run, daemon=True, name=f"discord-{command}").start()

    # --- What the keys do ---------------------------------------------------------

    def toggle_mute(self, callback=None) -> None:
        self.request("SET_VOICE_SETTINGS", {"mute": not (self.state or {}).get("mute")},
                     callback)

    def toggle_deafen(self, callback=None) -> None:
        self.request("SET_VOICE_SETTINGS", {"deaf": not (self.state or {}).get("deaf")},
                     callback)

    def toggle_video(self, callback=None) -> None:
        self._toggle("TOGGLE_VIDEO", "video", "VIDEO_STATE_UPDATE", callback)

    def toggle_screenshare(self, callback=None) -> None:
        """Starts or stops sharing. Discord asks what to share, as its own
        button does."""
        self._toggle("TOGGLE_SCREENSHARE", "screenshare", "SCREENSHARE_STATE_UPDATE",
                     callback)

    def _toggle(self, command: str, key: str, event: str, callback) -> None:
        def done(reply):
            # Without the event, Discord won't tell us; take its word that it toggled.
            if reply.get("ok") and event not in self._live and self.state:
                self._update(**{key: not self.state.get(key)})
            if callback is not None:
                callback(reply)
        self.request(command, {}, done)

    def join(self, channel_id: str | None, callback=None) -> None:
        """Joins the voice channel (moving from another), or leaves with None."""
        self.request("SELECT_VOICE_CHANNEL", {"channel_id": channel_id, "force": True},
                     callback)

    def guilds(self) -> list[dict]:
        """The user's servers, as {"id", "name"}. Raises NotRunning."""
        reply = self.send("GET_GUILDS")
        return list((reply.get("data") or {}).get("guilds") or []) if reply["ok"] else []

    def voice_channels(self, guild_id: str) -> list[dict]:
        """The server's voice and stage channels. Raises NotRunning."""
        reply = self.send("GET_CHANNELS", {"guild_id": guild_id})
        channels = (reply.get("data") or {}).get("channels") or [] if reply["ok"] else []
        return [channel for channel in channels if channel.get("type") in (2, 13)]

    # --- Following changes --------------------------------------------------------

    def add_listener(self, listener: Listener) -> None:
        ref = weakref.WeakMethod(listener) if hasattr(listener, "__self__") else \
            weakref.ref(listener)
        with self._lock:
            self._listeners.append(ref)

    def remove_listener(self, listener: Listener) -> None:
        with self._lock:
            self._listeners = [ref for ref in self._listeners
                               if ref() is not None and ref() != listener]

    def _emit(self, event: str, data: dict | None) -> None:
        with self._lock:
            self._listeners = [ref for ref in self._listeners if ref() is not None]
            listeners = [ref() for ref in self._listeners]
        for listener in listeners:
            if listener is None:
                continue
            try:
                listener(event, data)
            except Exception:     # one broken key must not stop the others
                pass

    def redraw(self) -> None:
        """Hand every listener the state again, as after a change."""
        self._emit("state", self.state)

    def _set_state(self, state: dict | None) -> None:
        with self._state_lock:
            if state != self.state:
                self.state = state
                self._emit("state", state)

    def _update(self, **changes) -> None:
        with self._state_lock:      # the reader and the login both change it
            if self.state is not None:
                self._set_state({**self.state, **changes})

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._follow, daemon=True,
                                            name="discord-follow")
            self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self.reconnect()

    def _relay_now(self) -> tuple[str, list[str] | None]:
        """Where to connect: the socket when it is in sight, else the relay."""
        path = self.socket_path or find_socket()
        return (path, None) if path or self.relay is None else ("", self.relay)

    def _follow(self) -> None:
        while not self._stopping.is_set():
            self._wake.clear()
            if not self.client_id:
                self._set_state({**_blank(), "status": NO_APP})
                self._wake.wait(RETRY)
                continue
            path, relay = self._relay_now()
            try:
                self._pipe = _Pipe(path, relay)
            except NotRunning:
                self._pipe = None
                self._problem("Discord's socket wasn't found." if relay is None else
                              "flatpak-spawn couldn't run the relay to Discord.")
            if self._pipe is not None:
                try:
                    self._run(self._pipe)
                except OSError:          # the relay found no Discord, or Discord left
                    if relay is not None and self.state is None:
                        self._problem("The relay found no Discord on the host.")
                finally:
                    self._pipe.close()
                    self._pipe = None
                    for waiting in list(self._pending.values()):
                        waiting[0].set()           # no reply: NotRunning
                    self._live.clear()
            self._set_state(None)
            self._wake.wait(RETRY)

    def _run(self, pipe: _Pipe) -> None:
        with self._write_lock:
            pipe.write(frame(HANDSHAKE, {"v": 1, "client_id": self.client_id}))
        while True:
            header = pipe.read(8)
            if not header:
                return
            op, length = struct.unpack("<II", header)
            body = pipe.read(length)
            if length and not body:
                return
            try:
                payload = json.loads(body.decode()) if body else {}
            except ValueError:
                continue
            if op == PING:
                with self._write_lock:
                    pipe.write(frame(PONG, payload))
            elif op == CLOSE:          # such as a client id Discord doesn't know
                self._problem(f"Discord closed the connection: {payload.get('message') or ''}"
                              .rstrip(": "))
                return
            elif op == FRAME:
                self._handle(payload)

    def _handle(self, payload: dict) -> None:
        nonce, evt, data = payload.get("nonce"), payload.get("evt"), payload.get("data")
        if nonce and nonce in self._pending:
            waiting = self._pending[nonce]
            waiting[1] = payload
            waiting[0].set()
            return
        if payload.get("cmd") != "DISPATCH":
            return
        data = data or {}
        if evt == "READY":
            self._set_state({**_blank(), "status": LOGGING_IN})
            threading.Thread(target=self._log_in, daemon=True, name="discord-login").start()
        elif evt == "VOICE_SETTINGS_UPDATE":
            self._update(mute=bool(data.get("mute")), deaf=bool(data.get("deaf")))
        elif evt == "VOICE_CHANNEL_SELECT":
            channel_id = data.get("channel_id")
            if not channel_id:
                self._update(channel=None, video=False, screenshare=False)
            else:
                self._update(channel={"id": channel_id, "name": "",
                                      "guild_id": data.get("guild_id")})
                threading.Thread(target=self._fetch_channel, daemon=True,
                                 name="discord-channel").start()
        elif evt == "VIDEO_STATE_UPDATE":
            self._update(video=bool(data.get("active")))
        elif evt == "SCREENSHARE_STATE_UPDATE":
            self._update(screenshare=bool(data.get("active")))

    # --- Logging in ---------------------------------------------------------------

    def _log_in(self) -> None:
        try:
            scopes = self._authenticate()
            if scopes is None:
                return
            self._problem("")
            self._update(status=READY, scopes=scopes)
            for event in EVENTS:
                if self.send("SUBSCRIBE", evt=event)["ok"]:
                    self._live.add(event)
            settings = self.send("GET_VOICE_SETTINGS")
            if settings["ok"]:
                data = settings.get("data") or {}
                self._update(mute=bool(data.get("mute")), deaf=bool(data.get("deaf")))
            self._fetch_channel()
        except NotRunning:
            pass

    def _authenticate(self) -> list[str] | None:
        """Logs in with the saved token, a refreshed one, or (asking the
        user) a new one. The scopes granted, or None without a login."""
        if self.access_token:
            reply = self.send("AUTHENTICATE", {"access_token": self.access_token})
            if reply["ok"]:
                return list((reply.get("data") or {}).get("scopes") or [])
            if self.refresh_token and self._exchange(grant_type="refresh_token",
                                                     refresh_token=self.refresh_token):
                reply = self.send("AUTHENTICATE", {"access_token": self.access_token})
                if reply["ok"]:
                    return list((reply.get("data") or {}).get("scopes") or [])
        if not self._ask:
            self._update(status=AUTHORIZE)
            return None
        self._ask = False          # one popup per press of Authorize, not one per retry
        self._update(status=AUTHORIZE)
        code = self._code()
        if not code or not self._exchange(grant_type="authorization_code", code=code,
                                          redirect_uri=self.redirect_uri):
            self._update(status=DECLINED)
            return None
        reply = self.send("AUTHENTICATE", {"access_token": self.access_token})
        if not reply["ok"]:
            self._problem(f"Discord refused the new login: {reply.get('message')}")
            self._update(status=DECLINED)
            return None
        return list((reply.get("data") or {}).get("scopes") or [])

    def _code(self) -> str:
        """Opens Discord's popup asking to allow the app: with the camera and
        screen share if Discord takes those scopes, else without."""
        tries = (SCOPES + VIDEO_SCOPES, SCOPES) if self.ask_video else (SCOPES,)
        for number, scopes in enumerate(tries):
            reply = self.send("AUTHORIZE", {"client_id": self.client_id,
                                            "scopes": list(scopes),
                                            "redirect_uri": self.redirect_uri},
                              timeout=AUTHORIZE_TIMEOUT)
            if reply["ok"]:
                if number:              # only without the camera and screen share
                    self.ask_video = False
                    if self.video_refused is not None:
                        self.video_refused()
                return (reply.get("data") or {}).get("code") or ""
            message = reply.get("message") or ""
            if "invalid_scope" in message and scopes == SCOPES:
                # Discord takes RPC scopes only from the app's own developers
                # and its App Testers.
                self._problem(f"Discord's authorization: {message} Discord gives these only "
                              "to the account that made the app and to its App Testers.")
            else:
                self._problem(f"Discord's authorization: {message}")
            if "scope" not in message.lower():
                return ""          # the user said no
        return ""

    def _exchange(self, **form) -> bool:
        """Swaps a code or a refresh token for tokens, with Discord's web API."""
        body = urllib.parse.urlencode({"client_id": self.client_id,
                                       "client_secret": self.client_secret, **form}).encode()
        request = urllib.request.Request(
            self.token_url, data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                tokens = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode())
                detail = detail.get("error_description") or detail.get("error") or detail
            except (OSError, ValueError, AttributeError):
                detail = exc.reason
            self._problem(f"Discord didn't give a token ({exc.code}): {detail}")
            return False
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self._problem(f"Couldn't reach discord.com for a token: {exc}")
            return False
        if not tokens.get("access_token"):
            self._problem("Discord didn't give a token.")
            return False
        self.access_token = tokens["access_token"]
        self.refresh_token = tokens.get("refresh_token") or self.refresh_token
        if self.save_tokens is not None:
            try:
                self.save_tokens(self.access_token, self.refresh_token)
            except Exception:
                pass
        return True

    def _fetch_channel(self) -> None:
        """The voice channel the user is in, with its name."""
        try:
            reply = self.send("GET_SELECTED_VOICE_CHANNEL")
        except NotRunning:
            return
        if not reply["ok"]:
            return
        channel = reply.get("data")
        if not channel or not channel.get("id"):
            self._update(channel=None, video=False, screenshare=False)
            return
        self._update(channel={"id": channel["id"], "name": channel.get("name") or "",
                              "guild_id": channel.get("guild_id")})


def _blank() -> dict:
    return {"status": LOGGING_IN, "mute": False, "deaf": False, "video": False,
            "screenshare": False, "channel": None, "scopes": []}


# --- Reading the state --------------------------------------------------------------

def ready(state: dict | None) -> bool:
    return bool(state) and state.get("status") == READY


def in_call(state: dict | None) -> bool:
    return ready(state) and bool(state.get("channel"))
