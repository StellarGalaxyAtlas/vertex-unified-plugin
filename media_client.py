"""Follows and controls the media players on the desktop, through MPRIS.

Every player that shows its media in the desktop's media controls (Spotify,
Firefox, Chromium, mpv, VLC, ...) is on the session bus as
`org.mpris.MediaPlayer2.<name>`, with the same Play, Pause, PlayPause, Next
and Previous methods and a PlaybackStatus. The client asks the bus through
`gdbus`, which comes with GLib on every desktop:

- one watcher, a small shell loop, prints every player's state once a
  second for as long as the plugin runs;
- each key press runs one `gdbus call`.

Standard library only: this runs in StreamController's Python. Inside
StreamController's Flatpak both go through `flatpak-spawn --host`, since the
sandbox can't see the players on the bus.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import threading
import weakref
from collections.abc import Callable

PREFIX = "org.mpris.MediaPlayer2."
OBJECT = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
POLL = 1.0           # seconds between looks at the players
RETRY = 5.0          # seconds before the watcher starts again after it stopped
TIMEOUT = 5.0
COMMANDS = ("PlayPause", "Play", "Pause", "Next", "Previous")

# Run with `sh -c WATCH sh <seconds>`: prints "PLAYER <bus name>", then the
# player's properties on one line, for every player, then "END"; and again.
WATCH = r"""
while :; do
  names=$(gdbus call --session --dest org.freedesktop.DBus \
          --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.ListNames) || exit 3
  for name in $(printf '%s\n' "$names" | grep -o "org\.mpris\.MediaPlayer2\.[A-Za-z0-9_.-]*"); do
    echo "PLAYER $name"
    gdbus call --session --dest "$name" --object-path /org/mpris/MediaPlayer2 \
      --method org.freedesktop.DBus.Properties.GetAll org.mpris.MediaPlayer2.Player \
      2>/dev/null | tr '\n' ' '
    echo
  done
  echo END
  sleep "$1"
done
"""

# A GVariant string, as gdbus prints it: in single quotes, or in double
# quotes when it holds a single quote.
_STRING = r"""('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""


def in_flatpak() -> bool:
    return os.path.exists("/.flatpak-info")


def _string(text: str) -> str:
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text[1:-1]
    return value if isinstance(value, str) else ""


def _value(props: str, key: str, kind: str) -> str:
    """The text of `key`'s value in gdbus's print of a properties dict: a
    string, the first of a list of strings, or a word (true, false)."""
    pattern = {"string": _STRING, "list": r"\[" + _STRING, "word": r"(\w+)"}[kind]
    found = re.search(r"'" + re.escape(key) + r"': <" + pattern, props)
    if not found:
        return ""
    return found.group(1) if kind == "word" else _string(found.group(1))


def app_of(bus_name: str) -> str:
    """The player's app in its bus name: "firefox" for
    org.mpris.MediaPlayer2.firefox.instance_1_74, which a restart renames."""
    return bus_name[len(PREFIX):].split(".")[0] if bus_name.startswith(PREFIX) else bus_name


def app_label(app: str) -> str:
    return {"vlc": "VLC", "mpv": "mpv"}.get(app, app[:1].upper() + app[1:])


def parse(lines: list[str]) -> list[dict]:
    """The players in one round of the watcher's lines."""
    players = []
    for index, line in enumerate(lines):
        if not line.startswith("PLAYER "):
            continue
        name = line[len("PLAYER "):].strip()
        props = lines[index + 1] if index + 1 < len(lines) else ""
        status = _value(props, "PlaybackStatus", "string")
        if not status:                # gone meanwhile, or no player interface
            continue
        players.append({
            "bus": name, "app": app_of(name), "label": app_label(app_of(name)),
            "status": status,
            "title": _value(props, "xesam:title", "string"),
            "artist": _value(props, "xesam:artist", "list"),
            "can_next": _value(props, "CanGoNext", "word") != "false",
            "can_previous": _value(props, "CanGoPrevious", "word") != "false",
        })
    return players


def playing(state: dict | None) -> bool:
    return any(p["status"] == "Playing" for p in (state or {}).get("players") or [])


Listener = Callable[[str, dict | None], None]


class Media:
    """The desktop's media players, as the plugin's actions see them.

    `state` is {"players": [...]} (see `parse`), or None while the players
    can't be looked at (no `gdbus`, no session bus). Listeners are called on
    a background thread with ("state", state-or-None) whenever it changes,
    and held weakly, as the other clients do.
    """

    def __init__(self, host: list[str] | bool | None = True, poll: float = POLL):
        # True: pick by whether we are in the Flatpak; a list: the prefix
        # that runs a command on the host; None: run here.
        if host is True:
            host = ["flatpak-spawn", "--host"] if in_flatpak() else None
        # Where the watcher and commands run: on the host, then, if that fails
        # (StreamController's Flatpak may not be let to use flatpak-spawn),
        # in the sandbox, which sees the players if it was let talk to them.
        self._hosts = [list(host), []] if host else [[]]
        self.host = self._hosts[0]
        self.poll = poll
        self.state: dict | None = None
        self.problem = ""             # why the players can't be looked at, if they can't
        self.last_playing = ""        # the app that played last
        self._listeners: list[weakref.ref] = []
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._watcher: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    # --- Picking a player ---------------------------------------------------------------

    def players(self) -> list[dict]:
        return list((self.state or {}).get("players") or [])

    def player(self, app: str = "") -> dict | None:
        """The player a key controls: the one of `app`; with no app picked,
        the one playing, else the one that played last, else the first."""
        players = self.players()
        if app:
            ours = [p for p in players if p["app"] == app]
            return next((p for p in ours if p["status"] == "Playing"), ours[0] if ours else None)
        for wanted in (lambda p: p["status"] == "Playing",
                       lambda p: p["app"] == self.last_playing,
                       lambda p: True):
            found = next((p for p in players if wanted(p)), None)
            if found:
                return found
        return None

    # --- Commands -------------------------------------------------------------------------

    def command(self, method: str, app: str = "",
                callback: Callable[[dict], None] | None = None) -> None:
        """Call `method` (one of COMMANDS) on the player of `app` (see
        `player`), on a thread of its own so a key press never waits. The
        callback gets {"ok": ..., "message": ...}."""
        player = self.player(app)

        def run():
            if player is None:
                reply = {"ok": False, "message": "No media player is running."}
            else:
                reply = self._call(player["bus"], method)
                if reply["ok"]:
                    self._guess(player["bus"], method)
            if callback is not None:
                callback(reply)
        threading.Thread(target=run, daemon=True, name=f"media-{method}").start()

    def _call(self, bus: str, method: str) -> dict:
        if method not in COMMANDS:
            return {"ok": False, "message": f"Unknown command {method}."}
        try:
            done = subprocess.run(
                [*self.host, "gdbus", "call", "--session", "--dest", bus, "--object-path",
                 OBJECT, "--method", f"{PLAYER}.{method}"],
                capture_output=True, text=True, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": done.returncode == 0,
                "message": (done.stderr or done.stdout).strip()}

    def _guess(self, bus: str, method: str) -> None:
        """Show what a play or pause did at once, before the watcher sees it."""
        status = {"Play": "Playing", "Pause": "Paused"}.get(method)
        players = []
        for player in self.players():
            if player["bus"] == bus and method in ("Play", "Pause", "PlayPause"):
                flipped = "Paused" if player["status"] == "Playing" else "Playing"
                player = {**player, "status": status or flipped}
            players.append(player)
        self._set_state({"players": players})

    # --- Following changes ----------------------------------------------------------------

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
        self._emit("state", self.state)

    def _set_state(self, state: dict | None) -> None:
        for player in (state or {}).get("players") or []:
            if player["status"] == "Playing":
                self.last_playing = player["app"]
                break
        if state != self.state:
            self.state = state
            self._emit("state", state)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._follow, daemon=True,
                                            name="media-follow")
            self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        watcher = self._watcher
        if watcher is not None and watcher.poll() is None:
            watcher.terminate()        # flatpak-spawn passes it on to the shell

    def _watch_ended(self, host: list[str], code: int | None, errors: str) -> str:
        """Why the watcher stopped, from its exit status and what it wrote."""
        last = errors.strip().splitlines()[-1] if errors.strip() else ""
        where = " on the host" if host else ""
        if code == 127 or "No such file" in last or "not found" in last:
            problem = f"gdbus wasn't found{where}."
        elif code == 3:
            problem = f"gdbus couldn't list the players{where}."
        else:
            problem = f"Looking at the players{where} stopped ({code})."
        return f"{problem} {last}".strip() if last and last not in problem else problem

    def _watch(self, host: list[str]) -> str:
        """Follow the players with a watcher run with `host`, for as long as it
        runs; returns why it stopped, or "" when the plugin stops."""
        try:
            watcher = subprocess.Popen([*host, "sh", "-c", WATCH, "sh", str(self.poll)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True)
        except OSError as exc:
            return f"Couldn't run {(host or ['sh'])[0]}: {exc.strerror}."
        self._watcher = watcher
        lines: list[str] = []
        try:
            for line in watcher.stdout:
                line = line.rstrip("\n")
                if line == "END":
                    self.host = host           # commands go the same way
                    self.problem = ""
                    self._set_state({"players": parse(lines)})
                    lines = []
                else:
                    lines.append(line)
        except (OSError, ValueError):
            pass
        finally:
            if watcher.poll() is None:
                watcher.terminate()
            code = watcher.wait()
            try:
                errors = watcher.stderr.read()
            except (OSError, ValueError):
                errors = ""
            self._watcher = None
        return "" if self._stopping.is_set() else self._watch_ended(host, code, errors)

    def _follow(self) -> None:
        while not self._stopping.is_set():
            problems = []
            for host in self._hosts:
                problem = self._watch(host)
                if not problem or self._stopping.is_set():
                    break
                problems.append(problem)
            if problems:
                self.problem = " ".join(problems)
                if self.state is None:
                    self._emit("state", None)    # the same state, but maybe another problem
                else:
                    self._set_state(None)
            self._stopping.wait(RETRY)
