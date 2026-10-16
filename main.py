"""Vertex Media for StreamController: Vertex's Sonar and Moments, the Discord
app's voice, camera and screen share, and the desktop's media players, on a
Stream Deck, all in the icons of one Vertex theme.

Each app has one client that follows its state for every key, so a change
made in the app's window, by a shortcut or by another key shows up on the
deck at once:

- Vertex through its control socket (`vertex_client`);
- Discord through its local RPC socket (`discord_client`);
- the media players through MPRIS on the session bus (`media_client`).
"""

from __future__ import annotations

from gi.repository import Adw, GLib, Gtk
from loguru import logger as log
from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.PluginManager.PluginBase import PluginBase

from . import discord_client as dc
from .actions.base import combo_row, set_choices
from .actions.discord_keys import (
    ToggleCamera,
    ToggleDeafen,
    ToggleMute,
    ToggleScreenshare,
    VoiceChannel,
)
from .actions.media_keys import MediaNext, MediaPlayPause, MediaPrevious
from .actions.theme import (
    DEFAULT_THEME,
    DEFAULT_VERSION,
    THEME_CHOICES,
    THEMES,
    preview_path,
    version_choices,
)
from .actions.vertex_keys import (
    ReplaySaveClip,
    ReplayToggle,
    ShowVertex,
    SonarInformation,
    SonarNextMic,
    SonarNextOutput,
    SonarToggleChannelMute,
    SonarToggleMic,
    SonarToggleOutput,
    SonarVolume,
)
from .media_client import Media
from .vertex_client import Vertex

VERSION = "0.3.0"

KEY_ONLY = {Input.Key: ActionInputSupport.SUPPORTED,
            Input.Dial: ActionInputSupport.UNSUPPORTED,
            Input.Touchscreen: ActionInputSupport.UNSUPPORTED}
KEY_OR_DIAL = {Input.Key: ActionInputSupport.SUPPORTED,
               Input.Dial: ActionInputSupport.SUPPORTED,
               Input.Touchscreen: ActionInputSupport.UNSUPPORTED}

# (key, id suffix, name, inputs). The ids of Vertex's keys stay as they were
# first published in the Vertex plugin, whose plugin id this one keeps, so
# keys already set up keep working: Volume is now Sonar Information, and Mute
# is Sonar Toggle Channel Mute. Discord's take a "Discord" in front, as the
# Vertex Discord plugin's own ids (Mute, ...) are taken here.
ACTIONS = (
    (SonarInformation, "Volume", "Sonar Information", KEY_OR_DIAL),
    (SonarVolume, "VolumeStep", "Sonar Volume", KEY_OR_DIAL),
    (SonarToggleChannelMute, "Mute", "Sonar Toggle Channel Mute", KEY_ONLY),
    (SonarNextMic, "NextMic", "Sonar Next Microphone", KEY_ONLY),
    (SonarNextOutput, "NextOutput", "Sonar Next Output Device", KEY_ONLY),
    (SonarToggleMic, "MicToggle", "Sonar Toggle Microphone", KEY_ONLY),
    (SonarToggleOutput, "OutputToggle", "Sonar Toggle Output Device", KEY_ONLY),
    (ReplayToggle, "Replay", "Replay Buffer Toggle", KEY_ONLY),
    (ReplaySaveClip, "SaveClip", "Replay Save Clip", KEY_ONLY),
    (ShowVertex, "Show", "Show Vertex", KEY_ONLY),
    (ToggleMute, "DiscordMute", "Discord Toggle Mute", KEY_ONLY),
    (ToggleDeafen, "DiscordDeafen", "Discord Toggle Deafen", KEY_ONLY),
    (ToggleCamera, "DiscordCamera", "Discord Toggle Camera", KEY_ONLY),
    (ToggleScreenshare, "DiscordScreenshare", "Discord Toggle Screen Share", KEY_ONLY),
    (VoiceChannel, "DiscordVoiceChannel", "Discord Voice Channel", KEY_ONLY),
    (MediaPlayPause, "MediaPlayPause", "Media Play/Pause", KEY_OR_DIAL),
    (MediaNext, "MediaNext", "Media Next", KEY_OR_DIAL),
    (MediaPrevious, "MediaPrevious", "Media Previous", KEY_OR_DIAL),
)

DISCORD_STATUS = {
    None: "Discord isn't running.",
    dc.NO_APP: "Not set up yet: open Set up below.",
    dc.LOGGING_IN: "Logging in…",
    dc.AUTHORIZE: "Allow the app in Discord's popup, or press Authorize.",
    dc.DECLINED: "Not allowed. Press Authorize to ask Discord again.",
    dc.READY: "Connected.",
}


def status_text(state: dict | None, problem: str = "") -> str:
    """Discord's status, in words."""
    text = DISCORD_STATUS.get(None if state is None else state.get("status"), "")
    return f"{text}\n{problem}" if problem and not dc.ready(state) else text


def vertex_status(state: dict | None) -> str:
    if state is None:
        return "Vertex isn't running."
    sonar = "on" if (state.get("sonar") or {}).get("active") else "off"
    return f"Connected. Sonar is {sonar}."


def media_status(state: dict | None, problem: str = "") -> str:
    if state is None:
        return "Can't reach the media players." + (f"\n{problem}" if problem else "")
    players = (state or {}).get("players") or []
    if not players:
        return "No media player is running."
    return "Found " + ", ".join(
        f"{p['label']} ({p['status'].lower()})" for p in players) + "."


class VertexPlugin(PluginBase):
    def __init__(self):
        super().__init__()
        settings = self.get_settings()
        # The one theme every key's icons and the information tile are drawn in.
        self.theme = (settings.get("theme", DEFAULT_THEME),
                      settings.get("version", DEFAULT_VERSION))
        self.has_plugin_settings = True
        self._rows: dict[str, Adw.ActionRow] = {}      # the status rows shown now
        self._logged = ""         # Discord's problem last written to the log

        self.vertex = Vertex()
        self.discord = dc.Discord(
            client_id=settings.get("client_id", ""),
            client_secret=settings.get("client_secret", ""),
            redirect_uri=settings.get("redirect_uri", dc.REDIRECT),
            access_token=settings.get("access_token", ""),
            refresh_token=settings.get("refresh_token", ""),
            save_tokens=self.save_tokens,
            ask_video=settings.get("ask_video", True),
            video_refused=lambda: self._save(ask_video=False))
        self.media = Media()
        for name in ("vertex", "discord", "media"):
            client = getattr(self, name)
            client.add_listener(getattr(self, f"_on_{name}"))
            client.start()

        for action, suffix, name, support in ACTIONS:
            self.add_action_holder(ActionHolder(plugin_base=self, action_base=action,
                                                action_id_suffix=suffix, action_name=name,
                                                action_support=support))

        self.register(plugin_name="vertex-unified-plugin",
                      github_repo="https://github.com/StellarGalaxyAtlas/vertex-private",
                      plugin_version=VERSION, app_version="1.5.0-beta.16")

    @property
    def clients(self):
        return (self.vertex, self.discord, self.media)

    # --- Settings ---------------------------------------------------------------------

    def save_tokens(self, access_token: str, refresh_token: str) -> None:
        self._save(access_token=access_token, refresh_token=refresh_token)

    def _save(self, **values) -> None:
        settings = self.get_settings()
        settings.update(values)
        self.set_settings(settings)

    def set_theme(self, theme: str, version: str) -> None:
        """Draw every key, of every app, in `theme` and `version`."""
        self._save(theme=theme, version=version)
        self.theme = (theme, version)
        for client in self.clients:
            client.redraw()

    def get_settings_area(self):
        # StreamController adds the area to an Adw.PreferencesPage, which takes
        # only a PreferencesGroup: the groups go inside one.
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        for group in (self._look_group(), self._vertex_group(), self._discord_group(),
                      self._media_group()):
            box.append(group)
        area = Adw.PreferencesGroup()
        area.add(box)
        return area

    def _look_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Look",
            description="One theme for every key: Vertex's, Discord's and the media keys. "
                        "Each key can still pick its own icon, variant or picture in its "
                        "settings.")
        preview = Gtk.Picture(can_shrink=True, height_request=220,
                              content_fit=Gtk.ContentFit.CONTAIN)
        version_row = combo_row("Version", version_choices(self.theme[0]), self.theme[1],
                                lambda version: picked(self.theme[0], version))

        def show(theme: str, version: str) -> None:
            path = preview_path(theme, version)
            preview.set_filename(path or None)
            preview.set_visible(bool(path))
            # The white set has one version, and None has no icons at all.
            version_row.set_sensitive(theme in THEMES and theme != "white")
            version_row.set_subtitle("" if theme in THEMES and theme != "white" else
                                     "This theme has only one" if theme == "white" else
                                     "Pick a theme first")

        def picked(theme: str, version: str) -> None:
            if theme != self.theme[0]:
                set_choices(version_row, version_choices(theme), version)
            self.set_theme(theme, version)
            show(theme, version)

        theme_row = combo_row("Theme", THEME_CHOICES, self.theme[0],
                              lambda theme: picked(theme, self.theme[1]),
                              "None shows labels instead of icons")
        group.add(theme_row)
        group.add(version_row)
        group.add(preview)
        show(*self.theme)
        return group

    def _status_row(self, name: str, text: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title="Status", subtitle=text)
        self._rows[name] = row
        return row

    def _vertex_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Vertex",
                                     description="The Sonar, replay and Show Vertex keys.")
        group.add(self._status_row("vertex", vertex_status(self.vertex.state)))
        return group

    def _media_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Media",
            description="The Media keys play, pause and skip in whatever plays on the "
                        "desktop. Each key can stick to one player in its settings.")
        group.add(self._status_row("media", media_status(self.media.state, self.media.problem)))
        return group

    def _discord_group(self) -> Adw.PreferencesGroup:
        settings = self.get_settings()
        group = Adw.PreferencesGroup(title="Discord",
                                     description="The Discord keys: mute, deafen, camera, "
                                                 "screen share and voice channels.")
        status = self._status_row("discord",
                                  status_text(self.discord.state, self.discord.problem))
        group.add(status)

        setup = Adw.ExpanderRow(
            title="Set up",
            subtitle="Discord lets only apps you made control it. Make one at "
                     "discord.com/developers/applications, add the redirect below under "
                     "OAuth2, and copy its Client ID and Client Secret here.")
        setup.set_expanded(not settings.get("client_id"))
        fields = {}
        for key, title, kind, default in (
            ("client_id", "Client ID", Adw.EntryRow, ""),
            ("client_secret", "Client Secret", Adw.PasswordEntryRow, ""),
            ("redirect_uri", "Redirect", Adw.EntryRow, dc.REDIRECT),
        ):
            row = kind(title=title)
            row.set_text(settings.get(key, default))
            row.set_show_apply_button(True)
            row.connect("apply", lambda _row: self._apply_app(fields))
            # Kept as typed even without the check mark; Authorize uses them too.
            row.connect("changed", lambda row, key=key: self._save(**{key: row.get_text().strip()}))
            fields[key] = row
            setup.add_row(row)
        group.add(setup)

        button = Gtk.Button(label="Authorize", valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda _button: self._authorize(fields))
        status.add_suffix(button)
        return group

    def _apply_app(self, fields: dict, connect: bool = True) -> None:
        values = {key: row.get_text().strip() for key, row in fields.items()}
        self._save(**values)
        self.discord.configure(values["client_id"], values["client_secret"],
                               values["redirect_uri"], connect)

    def _authorize(self, fields: dict) -> None:
        """Takes what is typed in the fields, applied or not, and asks Discord
        (for the camera and screen share again too)."""
        self._apply_app(fields, connect=False)
        self._save(ask_video=True)
        self.discord.ask_video = True
        if not self.discord.client_id:
            self._show_status("discord", "Enter the Client ID first, under Set up.")
            return
        self.discord.authorize()

    def _show_status(self, name: str, text: str) -> None:
        row = self._rows.get(name)
        if row is not None:
            GLib.idle_add(row.set_subtitle, text)

    def _on_vertex(self, event: str, state) -> None:
        if event == "state":
            self._show_status("vertex", vertex_status(state))

    def _on_media(self, event: str, state) -> None:
        if event == "state":
            self._show_status("media", media_status(state, self.media.problem))

    def _on_discord(self, event: str, state) -> None:
        if event != "state":
            return
        problem = self.discord.problem
        if problem and problem != self._logged:
            log.warning(f"Discord: {problem}")
        self._logged = problem
        self._show_status("discord", status_text(state, problem))

    def on_uninstall(self) -> None:
        for client in self.clients:
            client.stop()
        super().on_uninstall()
