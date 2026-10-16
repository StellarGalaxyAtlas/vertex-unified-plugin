"""The media keys: play or pause, the next song and the previous one, in
whatever plays on the desktop (Spotify, a browser, mpv, ...), or in the
player picked in the key's settings."""

from __future__ import annotations

from src.backend.DeckManagement.InputIdentifier import Input

from .base import KeyAction

UNAVAILABLE = "No media"         # the players can't be looked at
NO_PLAYER = "No player"
ANY = ""                         # the player setting: whichever plays


class MediaAction(KeyAction):
    """A key for one media player: the one picked in its settings, or else
    the one playing (else the one that played last)."""

    app = "media"
    method = ""                  # what a press calls on the player
    title = ""
    icon = ""
    FACES = (("media", "Icon"),)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    def _app(self) -> str:
        return self.setting("player", ANY)

    def _player(self, state) -> dict | None:
        return None if state is None else self.client.player(self._app())

    def why_not(self, state) -> str:
        """Why the key can't do its job now, or "" when it can."""
        if state is None:
            return UNAVAILABLE
        return "" if self._player(state) else NO_PLAYER

    def song(self, player: dict | None) -> str:
        """What the key shows of the song, if its settings ask for it."""
        if not player or not self.setting("show_song", True):
            return ""
        title, artist = player.get("title", ""), player.get("artist", "")
        return f"{artist} – {title}" if title and artist and \
            self.setting("show_artist", False) else title

    def default_icon(self, face):
        return self.icon

    def show(self, state):
        why = self.why_not(state)
        player = self._player(state)
        self.show_face("media", self.default_icon("media"),
                       (self.title, "", why or self.song(player)), why or self.song(player),
                       dim=bool(why))

    def press(self, method: str = "") -> None:
        if self.why_not(self.client.state):
            self.show_error(duration=1)
            return
        self.client.command(method or self.method, self._app(), self.done)

    def on_key_down(self):
        self.press()

    def event_callback(self, event, data=None):
        """On a dial: turn for the next or previous song, press as a key."""
        if event == Input.Dial.Events.TURN_CW:
            self.press("Next")
        elif event == Input.Dial.Events.TURN_CCW:
            self.press("Previous")
        elif event == Input.Dial.Events.DOWN:
            self.press()
        else:
            super().event_callback(event, data)

    # --- Settings -------------------------------------------------------------------

    def _players(self) -> list[tuple[str, str]]:
        """The players to pick from: those running now, and the one picked."""
        choices = [(ANY, "The one playing")]
        for player in self.client.players():
            if player["app"] not in [value for value, _label in choices]:
                choices.append((player["app"], player["label"]))
        picked = self._app()
        if picked and picked not in [value for value, _label in choices]:
            choices.append((picked, f"{picked} (not running)"))
        return choices

    def get_config_rows(self):
        return [self.choice_row("Player", "player", self._players(), ANY,
                                "Players that are running are listed"),
                self.switch_row("Show the song", "show_song", True),
                self.switch_row("With the artist", "show_artist", False),
                *self.image_rows()]


PRESS = (("PlayPause", "Play or pause"), ("Play", "Play"), ("Pause", "Pause"))


class MediaPlayPause(MediaAction):
    """Plays or pauses, and shows which a press does: the pause sign while
    it plays, the play sign while it doesn't."""

    title = "Media"
    FACES = (("playing", "While playing"), ("paused", "While paused"))

    def default_icon(self, face):
        press = self.setting("press", "PlayPause")
        if press != "PlayPause":
            return "Media_Play" if press == "Play" else "Media_Pause"
        return "Media_Pause" if face == "playing" else "Media_Play"

    @property
    def method(self):
        return self.setting("press", "PlayPause")

    def show(self, state):
        why = self.why_not(state)
        player = self._player(state)
        on = bool(player) and player["status"] == "Playing"
        face = "playing" if on else "paused"
        self.show_face(face, self.default_icon(face),
                       (self.title, "Playing" if on else "Paused" if player else "",
                        why or self.song(player)),
                       why or self.song(player), dim=bool(why))

    def get_config_rows(self):
        rows = super().get_config_rows()
        return [rows[0], self.choice_row("When pressed", "press", PRESS, "PlayPause"),
                *rows[1:]]


class MediaNext(MediaAction):
    title = "Next"
    method = "Next"
    icon = "Media_Next"

    def why_not(self, state):
        why = super().why_not(state)
        player = self._player(state)
        return why or ("" if player.get("can_next", True) else "Can't skip")


class MediaPrevious(MediaAction):
    title = "Previous"
    method = "Previous"
    icon = "Media_Previous"

    def why_not(self, state):
        why = super().why_not(state)
        player = self._player(state)
        return why or ("" if player.get("can_previous", True) else "Can't go back")
