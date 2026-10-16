"""Vertex's keys: a Sonar channel's volume (shown, stepped) and mute, the next
output or mic, a toggle between two mics or two outputs; the replay buffer
and saving a clip; and bringing Vertex to the front."""

from __future__ import annotations

import threading
from typing import ClassVar

from PIL import Image
from src.backend.DeckManagement.InputIdentifier import Input

from .. import vertex_client as vc
from .base import CHANNELS, KeyAction
from .theme import icon_path, tile_colors
from .tile import render

NOT_RUNNING = "Vertex off"
SONAR_OFF = "Sonar off"
VOLUME_STEP = 5


class VertexAction(KeyAction):
    """A key following the running Vertex, through its control socket."""

    app = "vertex"

    @property
    def vertex(self):
        return self.client

    def send(self, command: str, **args) -> None:
        """Send `command`; the key shows an error briefly if it fails."""
        self.vertex.request(command, self.done, **args)


class _ChannelKey(VertexAction):
    """A key for one Sonar channel, picked in its settings."""

    default_channel = "game"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    def _channel(self) -> str:
        return self.setting("channel", self.default_channel)

    def _title(self) -> str:
        channel_id = self._channel()
        return "Mic" if channel_id == "mic" else dict(CHANNELS)[channel_id]

    def _level(self, state) -> str:
        """The channel's volume, "Muted", or why there is none."""
        entry = vc.channel(state, self._channel())
        if state is None:
            return NOT_RUNNING
        if not vc.sonar(state).get("active"):
            return SONAR_OFF
        if entry is None:
            return ""
        return "Muted" if entry["muted"] else f"{entry['volume']}%"

    def get_config_rows(self):
        return [self.choice_row("Channel", "channel", CHANNELS, self.default_channel)]


LOOKS = (("tile", "Vertex tile"), ("labels", "Labels"))


class SonarInformation(_ChannelKey):
    """Shows a Sonar channel's volume, or that it is muted: as a tile drawn
    like the Vertex icons, in the colors of a Vertex theme, or as labels."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tile: tuple | None = None       # what the drawn tile shows

    def forget(self):
        super().forget()
        self._tile = None

    def _reading(self, state) -> tuple[str, str, str]:
        """The tile's label, its value, and the value's color."""
        entry = vc.channel(state, self._channel())
        if state is None:
            return "VERTEX", "OFF", "text"
        if not vc.sonar(state).get("active"):
            return "SONAR", "OFF", "text"
        if entry is None:
            return self._title().upper(), "–", "text"
        if entry["muted"]:
            return self._title().upper(), "MUTED", "red"
        return self._title().upper(), f"{entry['volume']}%", "value"

    def show(self, state):
        if self.setting("look", "tile") != "tile":
            if self._tile is not None:
                self.set_media()
                self._tile = None
            self.show_labels(self._title(), "", self._level(state))
            return
        label, value, tone = self._reading(state)
        tile = (label, value, tile_colors(*self.theme), tone)
        self.show_labels()
        if tile != self._tile:
            self.set_media(image=render(*tile))
            self._tile = tile

    def get_config_rows(self):
        return [*super().get_config_rows(),
                self.choice_row("Look", "look", LOOKS, "tile",
                                "The tile takes the colors of the plugin's theme")]


class SonarVolume(_ChannelKey):
    """Turns a Sonar channel up or down by a set step. On a dial, turning
    sets it by that step either way and pressing mutes."""

    FACES = (("volume", "Icon"),)

    def default_icon(self, face):
        return "Volume_Up_B" if self._direction() == "up" else "Volume_Down_B"

    def _step(self) -> int:
        return int(self.setting("step", VOLUME_STEP))

    def _direction(self) -> str:
        return self.setting("direction", "up")

    def show(self, state):
        up = self._direction() == "up"
        level = self._level(state)
        off = level in (NOT_RUNNING, SONAR_OFF)
        self.show_face("volume", self.default_icon("volume"),
                       (self._title(), f"{'+' if up else '-'}{self._step()}%", level),
                       level if off else "", dim=off)

    def _turn(self, action: str) -> None:
        self.send("volume", channel=self._channel(), action=action, step=self._step())

    def on_key_down(self):
        self._turn(self._direction())

    def event_callback(self, event, data=None):
        if event == Input.Dial.Events.TURN_CW:
            self._turn("up")
        elif event == Input.Dial.Events.TURN_CCW:
            self._turn("down")
        elif event == Input.Dial.Events.DOWN:
            self.send("mute", channel=self._channel())
        else:
            super().event_callback(event, data)

    def get_config_rows(self):
        return [*super().get_config_rows(),
                self.choice_row("When pressed", "direction",
                                (("up", "Turn up"), ("down", "Turn down")), "up"),
                self.number_row("Step (%)", "step", 1, 100, VOLUME_STEP),
                *self.image_rows()]


class SonarToggleChannelMute(_ChannelKey):
    """Mutes or unmutes a Sonar channel, and shows which it is."""

    default_channel = "mic"
    FACES = (("unmuted", "When on"), ("muted", "When muted"))

    def default_icon(self, face):
        return self._icon(face == "muted")

    def _icon(self, muted: bool) -> str:
        if self._channel() == "mic":
            return "Microphone_Muted" if muted else "Microphone_Unmuted"
        return "Speaker_Deafened" if muted else "Speaker_Undeafened"

    def show(self, state):
        entry = vc.channel(state, self._channel())
        if state is None or entry is None or not vc.sonar(state).get("active"):
            level = self._level(state)
            if icon_path(*self.theme, self._icon(False)):
                self.show_face("unmuted", self._icon(False), (self._title(), level), level,
                               dim=True)
            else:
                self.show_labels(self._title(), level)
            return
        muted = entry["muted"]
        self.show_face("muted" if muted else "unmuted", self._icon(muted),
                       (self._title(), "Muted" if muted else "On"))

    def on_key_down(self):
        self.send("mute", channel=self._channel())

    def get_config_rows(self):
        return [*super().get_config_rows(), *self.image_rows()]


class _NextDevice(VertexAction):
    """Switches to the next device in the device manager's priority list, for
    now (as `vertex device next` does), and shows the one in use."""

    title = ""
    channel = None
    icon = ""
    FACES = (("device", "Icon"),)

    def default_icon(self, face):
        return self.icon

    def _device(self, state) -> str:
        raise NotImplementedError

    def show(self, state):
        if state is None:
            name = NOT_RUNNING
        elif not vc.sonar(state).get("active"):
            name = SONAR_OFF
        else:
            name = self._device(state) or "None"
        self.show_face("device", self.icon, (self.title, "", name), name,
                       dim=name in (NOT_RUNNING, SONAR_OFF))

    def on_key_down(self):
        args = {"channel": self.channel} if self.channel else {}
        self.send("device", action="next", **args)


class SonarNextOutput(_NextDevice):
    title = "Output"
    icon = "Speaker_Undeafened"

    def _device(self, state):
        return vc.device_name(vc.sonar(state).get("output"))


class SonarNextMic(_NextDevice):
    title = "Mic"
    channel = "mic"
    icon = "Microphone"

    def _device(self, state):
        return vc.device_name(vc.sonar(state).get("mic"))


class _Toggle(VertexAction):
    """Switches between two devices picked in the key's settings, for now (as
    picking one on the Sonar page does), and shows which is in use: the
    first, the second, or neither (another device, or none)."""

    title = ""
    kind = ""          # the `devices` list: "mics" or "outputs"
    channel = None
    none = ""
    ICONS: ClassVar[dict[str, str]] = {}     # the theme's icon for each face

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    def _current(self, state) -> dict | None:
        raise NotImplementedError

    def _picks(self) -> tuple[str, str]:
        return self.setting("first", ""), self.setting("second", "")

    def _in_use(self) -> str:
        state = self.vertex.state
        if state is None or not vc.sonar(state).get("active"):
            return ""
        return (self._current(state) or {}).get("name", "")

    def show(self, state):
        first, second = self._picks()
        if state is None or not vc.sonar(state).get("active"):
            why = NOT_RUNNING if state is None else SONAR_OFF
            self._show(f"{self.face_name}-none", (self.title, why), why, dim=True)
            return
        current = self._current(state)
        name = (current or {}).get("name", "")
        if name and name in (first, second):
            number = 1 if name == first else 2
            self._show(f"{self.face_name}-{number}",
                       (f"{self.title} {number}", "", vc.device_name(current)),
                       vc.device_name(current))
        else:
            self._show(f"{self.face_name}-none",
                       (self.title, self.none, vc.device_name(current)), vc.device_name(current))

    def _show(self, face: str, labels: tuple[str, ...], bottom: str, dim: bool = False) -> None:
        self.show_face(face, self.default_icon(face), labels, bottom, dim)

    def default_icon(self, face):
        return self.ICONS.get(face, "")

    @property
    def face_name(self) -> str:
        return self.title.lower()

    def on_key_down(self):
        first, second = self._picks()
        current = self._in_use()
        order = (second, first) if current == first else (first, second)
        targets = [target for target in order if target and target != current]
        args = {"channel": self.channel} if self.channel else {}

        def switch():
            # The other pick; if it isn't plugged in, the first one that is.
            for target in targets:
                try:
                    if self.vertex.send("device", action="set", name=target, **args).get("ok"):
                        return
                except vc.NotRunning:
                    break
            try:
                self.show_error(duration=1)
            except Exception:
                pass
        threading.Thread(target=switch, daemon=True, name="vertex-toggle").start()

    def _choices(self) -> tuple[list[tuple[str, str]], str]:
        """The devices to pick from, as Sonar lists them now, and a note when
        Vertex couldn't be asked."""
        note = ""
        try:
            reply = self.vertex.send("devices", timeout=2)
        except vc.NotRunning:
            reply, note = {}, "Vertex isn't running, so only the devices picked so far are listed."
        choices = [("", "None")]
        for device in (reply.get("data") or {}).get(self.kind) or []:
            label = device["description"]
            if not device["connected"]:
                label += " (not plugged in)"
            choices.append((device["name"], label))
        for picked in self._picks():
            if picked and picked not in [value for value, _label in choices]:
                choices.append((picked, picked))
        return choices, note

    def get_config_rows(self):
        choices, note = self._choices()
        return [self.choice_row(f"{self.title} 1", "first", choices, "", note),
                self.choice_row(f"{self.title} 2", "second", choices, ""),
                *self.image_rows()]


class SonarToggleMic(_Toggle):
    title = "Mic"
    kind = "mics"
    channel = "mic"
    none = "No mic"
    FACES = (("mic-1", "Mic 1"), ("mic-2", "Mic 2"), ("mic-none", "No mic"))
    ICONS: ClassVar = {"mic-1": "Microphone", "mic-2": "Headset", "mic-none": "No_Microphone"}

    def _current(self, state):
        return vc.sonar(state).get("mic")


class SonarToggleOutput(_Toggle):
    title = "Output"
    kind = "outputs"
    none = "No output"
    FACES = (("output-1", "Output 1"), ("output-2", "Output 2"), ("output-none", "No output"))
    ICONS: ClassVar = {"output-1": "Speaker_Undeafened", "output-2": "Volume_Up_C",
             "output-none": "Speaker_Deafened"}

    def _current(self, state):
        return vc.sonar(state).get("output")


REPLAY_PHASES = {"running": "On", "stopped": "Off", "starting": "Starting",
                 "restarting": "Starting", "failed": "Failed"}


class ReplayToggle(VertexAction):
    """Starts or stops the replay buffer, and shows whether it runs."""

    FACES = (("replay-on", "When on"), ("replay-off", "When off"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    def show(self, state):
        if state is None:
            self.show_face("replay-off", "Clip_Save_B", ("Replay", NOT_RUNNING), NOT_RUNNING,
                           dim=True)
            return
        phase = ((state.get("replay") or {}).get("state")) or "stopped"
        text = REPLAY_PHASES.get(phase, phase.capitalize())
        on = phase == "running"
        # Over the icon, which shows on and off, only the phases between.
        self.show_face("replay-on" if on else "replay-off", "Clip_Save_B", ("Replay", text),
                       "" if phase in ("running", "stopped") else text, dim=not on)

    def default_icon(self, face):
        return "Clip_Save_B"

    def on_key_down(self):
        self.send("replay", action="toggle")

SAVE_LENGTHS = ((0, "Replay length"), (10, "10 seconds"), (30, "30 seconds"),
                (60, "1 minute"), (300, "5 minutes"), (600, "10 minutes"), (1800, "30 minutes"))


FLASH = (40, 160, 90, 255)      # green, while a clip has just landed
FLASH_SECONDS = 1.5


def _length(seconds: int) -> str:
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min"


def _flashed(path: str) -> Image.Image:
    """The icon at `path` washed with the flash's green."""
    with Image.open(path) as image:
        image = image.convert("RGB")
    return Image.blend(image, Image.new("RGB", image.size, FLASH[:3]), 0.45)


class ReplaySaveClip(VertexAction):
    """Saves the replay buffer to a clip: all of it, or the last few seconds."""

    FACES = (("clip", "Icon"),)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self._icon = ""            # the theme's icon, if it is on the key

    def show(self, state):
        replay = (state or {}).get("replay") or {}
        if state is None:
            text = NOT_RUNNING
        elif not replay.get("running"):
            text = "Replay off"
        else:
            text = _length(self.setting("seconds", 0) or replay.get("seconds") or 0)
        self._icon = icon_path(*self.theme, self.icon_name("clip", "Clip_Save_A"))
        self.face("clip", "Clip_Save_A", dim=not replay.get("running"))
        self.set_bottom_label(text)

    def on_key_down(self):
        seconds = self.setting("seconds", 0)
        self.send("save-clip", **({"seconds": seconds} if seconds else {}))

    def on_notice(self, notice):
        """The key lights up green when a clip lands, however it was saved,
        and shows an error when saving failed."""
        if notice.get("kind") == "clip_saved":
            if self._face and self._face[0] == self._icon:    # the icon covers the key
                self.set_media(image=_flashed(self._icon))
                self._face = None
            else:
                self.set_background_color(list(FLASH))
            threading.Timer(FLASH_SECONDS, self._unflash).start()
        elif notice.get("kind") == "clip_not_saved":
            self.show_error(duration=2)

    def _unflash(self):
        try:
            self.set_background_color([0, 0, 0, 0])
            self._redraw(self.vertex.state)
        except Exception:      # the key went away meanwhile
            pass

    def get_config_rows(self):
        return [self.choice_row("Length", "seconds", SAVE_LENGTHS, 0), *self.image_rows()]

    def default_icon(self, face):
        return "Clip_Save_A"


class ShowVertex(VertexAction):
    """Brings the Vertex window to the front, and shows Vertex's logo."""

    FACES = (("logo", "Icon"),)

    def default_icon(self, face):
        return "Vertex_Logo"

    def show(self, state):
        # The logo from the white set while the plugin has no theme.
        self.face("logo", "Vertex_Logo", fallback="white")

    def on_key_down(self):
        self.send("show")
