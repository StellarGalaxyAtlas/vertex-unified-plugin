"""Discord's keys: mute, deafen, the camera and screen share, each toggled and
showing which it is; and joining (or leaving) a voice channel picked in the
key's settings."""

from __future__ import annotations

from .. import discord_client as dc
from .base import KeyAction, combo_row, set_choices

NOT_RUNNING = "Discord off"
STATUS = {dc.NO_APP: "Set up", dc.LOGGING_IN: "Logging in", dc.AUTHORIZE: "Authorize",
          dc.DECLINED: "Authorize"}
NO_CALL = "No call"


class DiscordAction(KeyAction):
    """A key following the Discord app, through its local RPC socket."""

    app = "discord"

    @property
    def discord(self):
        return self.client


def why_not(state: dict | None) -> str:
    """Why a key can't do its job now, or "" when it can."""
    if state is None:
        return NOT_RUNNING
    return STATUS.get(state.get("status"), "")


class _Toggle(DiscordAction):
    """A key that turns something on and off in Discord, and shows which it
    is: an icon for each, picked in the key's settings."""

    title = ""
    key = ""                      # in Discord's state
    on_icon = off_icon = ""
    on_text, off_text = "On", "Off"
    needs_call = False            # works only in a voice channel
    FACES = (("on", "When on"), ("off", "When off"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    def default_icon(self, face):
        return self.on_icon if face == "on" else self.off_icon

    def show(self, state):
        why = why_not(state) or (NO_CALL if self.needs_call and not dc.in_call(state) else "")
        if why:
            self.show_face("off", self.off_icon, (self.title, why), why, dim=True)
            return
        on = bool(state.get(self.key))
        self.show_face("on" if on else "off", self.default_icon("on" if on else "off"),
                       (self.title, self.on_text if on else self.off_text))

    def toggle(self) -> None:
        raise NotImplementedError

    def on_key_down(self):
        state = self.discord.state
        if why_not(state) or (self.needs_call and not dc.in_call(state)):
            self.show_error(duration=1)
            return
        self.toggle()

    def get_config_rows(self):
        return self.image_rows()


class ToggleMute(_Toggle):
    title = "Mic"
    key = "mute"
    on_icon, off_icon = "Microphone_Muted", "Microphone_Unmuted"
    on_text, off_text = "Muted", "On"
    FACES = (("on", "When muted"), ("off", "When on"))

    def toggle(self):
        self.discord.toggle_mute(self.done)


class ToggleDeafen(_Toggle):
    title = "Sound"
    key = "deaf"
    on_icon, off_icon = "Speaker_Deafened", "Speaker_Undeafened"
    on_text, off_text = "Deafened", "On"
    FACES = (("on", "When deafened"), ("off", "When on"))

    def toggle(self):
        self.discord.toggle_deafen(self.done)


class ToggleCamera(_Toggle):
    title = "Camera"
    key = "video"
    # The icon shows what a press does: the crossed camera while it's on.
    on_icon, off_icon = "Camera_Off", "Camera"
    needs_call = True

    def toggle(self):
        self.discord.toggle_video(self.done)


class ToggleScreenshare(_Toggle):
    """Starts sharing (Discord asks what to share, as its own button does),
    or stops it."""

    title = "Screen"
    key = "screenshare"
    on_icon, off_icon = "Screenshare_Off", "Screenshare"      # as the camera's
    on_text, off_text = "Sharing", "Off"
    needs_call = True

    def toggle(self):
        self.discord.toggle_screenshare(self.done)


WHEN_IN = (("leave", "Leave it"), ("stay", "Stay"))


class VoiceChannel(DiscordAction):
    """Joins a voice channel picked in the key's settings (moving from
    another one), and shows whether the user is in it. Pressed while in it,
    leaves it, unless set to stay."""

    FACES = (("in", "When in it"), ("out", "When not in it"))
    ICON = "Headset"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    def default_icon(self, face):
        return self.ICON

    def _picked(self) -> tuple[str, str]:
        return self.setting("channel_id", ""), self.setting("channel_name", "")

    def show(self, state):
        channel_id, name = self._picked()
        why = why_not(state) or ("" if channel_id else "Pick one")
        if why:
            self.show_face("out", self.ICON, ("Voice", name, why), why, dim=True)
            return
        here = ((state.get("channel") or {}).get("id")) == channel_id
        # The icon is the same either way; it fades while the user is elsewhere.
        self.show_face("in" if here else "out", self.ICON,
                       ("Voice", name, "Joined" if here else ""), name, dim=not here)

    def on_key_down(self):
        channel_id, _name = self._picked()
        state = self.discord.state
        if why_not(state) or not channel_id:
            self.show_error(duration=1)
            return
        here = ((state.get("channel") or {}).get("id")) == channel_id
        if here and self.setting("when_in", "leave") == "stay":
            return
        self.discord.join(None if here else channel_id, self.done)

    # --- Settings -------------------------------------------------------------------

    def _servers(self) -> tuple[list[tuple[str, str]], str]:
        """The user's servers, and a note when Discord couldn't be asked."""
        try:
            guilds = self.discord.guilds()
        except dc.NotRunning:
            return [], "Discord isn't running, so only the channel picked so far is listed."
        if not guilds and not dc.ready(self.discord.state):
            return [], "Log in to Discord in the plugin's settings to list the channels."
        return [(guild["id"], guild.get("name") or guild["id"]) for guild in guilds], ""

    def _channels(self, guild_id: str) -> list[tuple[str, str]]:
        if not guild_id:
            return []
        try:
            channels = self.discord.voice_channels(guild_id)
        except dc.NotRunning:
            return []
        return [(channel["id"], channel.get("name") or channel["id"]) for channel in channels]

    def get_config_rows(self):
        servers, note = self._servers()
        guild_id, guild_name = self.setting("guild_id", ""), self.setting("guild_name", "")
        if guild_id and guild_id not in [value for value, _label in servers]:
            servers.append((guild_id, guild_name or guild_id))
        servers.insert(0, ("", "None"))

        def fill(guild: str) -> None:
            channel_id, name = self._picked()
            choices = [("", "None"), *self._channels(guild)]
            if channel_id and self.setting("guild_id", "") == guild and \
                    channel_id not in [value for value, _label in choices]:
                choices.append((channel_id, name or channel_id))
            holder["choices"] = choices
            set_choices(channel_row, choices, channel_id)

        def server_picked(guild: str) -> None:
            self.save(guild_id=guild, guild_name=dict(servers).get(guild, ""))
            fill(guild)

        def channel_picked(channel_id: str) -> None:
            label = dict(holder["choices"]).get(channel_id, "")
            self.save(channel_id=channel_id, channel_name=label if channel_id else "")

        holder = {"choices": [("", "None")]}
        channel_row = combo_row("Channel", holder["choices"], "", channel_picked)
        server_row = combo_row("Server", servers, guild_id, server_picked, note)
        fill(guild_id)
        return [server_row, channel_row,
                self.choice_row("When pressed in it", "when_in", WHEN_IN, "leave"),
                *self.image_rows()]
