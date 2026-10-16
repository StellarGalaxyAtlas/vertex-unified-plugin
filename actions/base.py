"""What every key has in common, Vertex's, Discord's and the media keys
alike: it follows its app's state and redraws when it changes, it sends
commands without making the deck wait, and it is drawn with the plugin's
icons in the plugin's one theme."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402
from GtkHelper.FileDialogRow import FileDialogFilter, FileDialogRow  # noqa: E402
from loguru import logger as log  # noqa: E402
from PIL import Image  # noqa: E402
from src.backend.PluginManager.ActionBase import ActionBase  # noqa: E402

from .theme import (  # noqa: E402
    DEFAULT_THEME,
    DEFAULT_VERSION,
    ICON_BASES,
    VARIANTS,
    icon_label,
    icon_path,
    split_variant,
    with_variant,
)

CHANNELS = (("game", "Game"), ("chat", "Chat"), ("media", "Media"), ("mic", "Microphone"))
IMAGES = FileDialogFilter("Images", ["*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.svg"])
DIM = 0.6           # how far a dimmed icon fades into its key


def combo_row(title: str, choices, current, changed, subtitle: str = "") -> Adw.ComboRow:
    """A drop-down row from (value, label) pairs; `changed` gets the value picked."""
    row = Adw.ComboRow(title=title)
    if subtitle:
        row.set_subtitle(subtitle)
    row.choice_values = []
    row.choice_quiet = False
    set_choices(row, choices, current)

    def selected(combo, _param):
        index = combo.get_selected()
        if not combo.choice_quiet and 0 <= index < len(combo.choice_values):
            changed(combo.choice_values[index])
    row.connect("notify::selected", selected)
    return row


def set_choices(row: Adw.ComboRow, choices, current) -> None:
    """Gives a drop-down row from `combo_row` new (value, label) pairs, with
    `current` picked, without calling its `changed`."""
    values = [value for value, _label in choices]
    row.choice_quiet = True
    try:
        row.choice_values = values
        row.set_model(Gtk.StringList.new([label for _v, label in choices]))
        row.set_selected(values.index(current) if current in values else 0)
    finally:
        row.choice_quiet = False


def dimmed(path: str) -> Image.Image:
    """The icon at `path`, faded into its key's color: the off state of a
    key whose icon has none of its own."""
    with Image.open(path) as image:
        image = image.convert("RGB")
    return Image.blend(image, Image.new("RGB", image.size, image.getpixel((0, 0))), DIM)


class KeyAction(ActionBase):
    """A key following one app: `app` names the plugin's client for it (the
    plugin's `vertex`, `discord` or `media`), which holds its state and calls
    the key back whenever that changes."""

    app = ""
    # The faces a key changes between, each with an icon (and a picture of
    # the user's own) the user can pick in the key's settings: (face, title).
    FACES: tuple[tuple[str, str], ...] = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = bool(self.FACES)
        # The picture shown, as (path, dimmed); "": none of ours; None: show it again.
        self._face: tuple[str, bool] | str | None = ""

    @property
    def client(self):
        return getattr(self.plugin_base, self.app)

    def on_ready(self) -> None:
        # Also called whenever StreamController wants the key drawn afresh
        # (on_update), such as when its page loads: whatever was drawn before
        # is gone, so draw everything again.
        self.client.remove_listener(self._on_event)
        self.client.add_listener(self._on_event)
        self.forget()
        self._redraw(self.client.state)

    def forget(self) -> None:
        """Forget what the key shows, so the next draw puts it up again."""
        if self._face:
            self._face = None

    def on_remove(self) -> None:
        self.client.remove_listener(self._on_event)

    def _on_event(self, event: str, data) -> None:
        if event == "state":
            self._redraw(data)
        elif event == "notice":
            self.on_notice(data or {})

    def _redraw(self, state) -> None:
        try:
            self.show(state)
        except Exception as exc:      # StreamController dropped the key mid-draw
            log.debug(f"{self.app}: couldn't redraw {self.action_id}: {exc}")

    def redraw(self) -> None:
        self._redraw(self.client.state)

    def show(self, state: dict | None) -> None:
        """Draw the key for `state` (None: the app isn't running)."""

    def on_notice(self, notice: dict) -> None:
        """A notification from the app."""

    def show_labels(self, top: str = "", center: str = "", bottom: str = "") -> None:
        """All three labels at once, so a face never keeps another's text."""
        self.set_top_label(top)
        self.set_center_label(center)
        self.set_bottom_label(bottom)

    def done(self, reply: dict) -> None:
        """What a command's reply calls: the key shows an error briefly if it
        failed."""
        if not reply.get("ok"):
            log.info(f"{self.app} {self.action_id}: {reply.get('message')}")
            try:
                self.show_error(duration=1)
            except Exception:
                pass

    # --- Icons ------------------------------------------------------------------------

    @property
    def theme(self) -> tuple[str, str]:
        """The theme and version picked in the plugin's settings."""
        return getattr(self.plugin_base, "theme", (DEFAULT_THEME, DEFAULT_VERSION))

    def icon_name(self, name: str, icon: str = "") -> str:
        """The icon the face `name` shows: the one picked for it in the key's
        settings, else `icon`, in the variant picked for it."""
        picked = self.icons().get(name, "") or icon
        return with_variant(picked, self.variants().get(name, "")) if picked else ""

    def face(self, name: str, icon: str = "", dim: bool = False, fallback: str = "") -> str:
        """Show the face `name`: the user's own picture for it, else the icon
        picked for it in the key's settings or else `icon`, in the plugin's
        theme (`icon` faded with `dim`), else the plugin's own `assets/<name>.png` if
        it has one. With none, a picture another face put up goes away; a key
        that never had one keeps the image it was given in StreamController.
        An icon picked while the plugin has no theme comes from the white set,
        as does `icon` with a `fallback` theme.

        Returns "icon" for one of the plugin's icons, "picture" for another,
        "" for none."""
        path, kind = self.images().get(name, ""), "picture"
        if not os.path.isfile(path):
            picked = bool(self.icons().get(name) or self.variants().get(name))
            chosen = self.icon_name(name, icon)
            path, kind = icon_path(*self.theme, chosen), "icon"
            if not path and (picked or fallback):
                path = icon_path(fallback or "white", DEFAULT_VERSION, chosen)
            dim = dim and not self.icons().get(name)   # an icon picked for the face shows as it is
        if not path:
            bundled = os.path.join(getattr(self.plugin_base, "PATH", ""), "assets", f"{name}.png")
            path, kind = (bundled, "picture") if os.path.isfile(bundled) else ("", "")
        shown = (path, dim and kind == "icon")
        if path and shown != self._face:
            self.set_media(image=dimmed(path)) if shown[1] else self.set_media(media_path=path)
        elif not path and self._face != "":       # ours, or the one just unpicked
            self.set_media()
        self._face = shown if path else ""
        return kind

    def show_face(self, name: str, icon: str, labels: tuple[str, ...], bottom: str = "",
                  dim: bool = False) -> None:
        """`face`, with `labels` over a picture; over the theme's icon only
        `bottom`, since the icon says the rest."""
        if self.face(name, icon, dim) == "icon":
            self.show_labels("", "", bottom)
        else:
            self.show_labels(*labels)

    def default_icon(self, face: str) -> str:
        """The icon a face shows when none is picked for it."""
        return ""

    def images(self) -> dict[str, str]:
        """The pictures picked in the key's settings, by face."""
        return self._faces_setting("images")

    def icons(self) -> dict[str, str]:
        """The plugin's icons picked in the key's settings, by face."""
        return self._faces_setting("icons")

    def variants(self) -> dict[str, str]:
        """The variants picked in the key's settings, by face."""
        return self._faces_setting("variants")

    def _faces_setting(self, key: str) -> dict[str, str]:
        faces = self.setting(key, {})
        return dict(faces) if isinstance(faces, dict) else {}

    def set_image(self, face: str, path: str) -> None:
        self._set_face_setting("images", face, path)

    def set_icon(self, face: str, icon: str) -> None:
        self._set_face_setting("icons", face, icon)

    def set_variant(self, face: str, variant: str) -> None:
        self._set_face_setting("variants", face, variant)

    def _set_face_setting(self, key: str, face: str, value: str) -> None:
        settings = self.get_settings()
        faces = settings.get(key)
        faces = dict(faces) if isinstance(faces, dict) else {}
        if value:
            faces[face] = value
        else:
            faces.pop(face, None)
        settings[key] = faces
        self.set_settings(settings)
        self._face = None
        self.redraw()

    # --- Settings ---------------------------------------------------------------------

    def setting(self, key: str, default):
        return self.get_settings().get(key, default)

    def save(self, **values) -> None:
        """Keep `values` in the key's settings, and draw it again."""
        settings = self.get_settings()
        settings.update(values)
        self.set_settings(settings)
        self.redraw()

    def choice_row(self, title: str, key: str, choices, default,
                   subtitle: str = "") -> Adw.ComboRow:
        """A drop-down row for the setting `key`, from (value, label) pairs."""
        values = [value for value, _label in choices]
        current = self.setting(key, default)
        return combo_row(title, choices, current if current in values else default,
                         lambda value: self.save(**{key: value}), subtitle)

    def number_row(self, title: str, key: str, low: int, high: int,
                   default: int) -> Adw.SpinRow:
        """A whole-number row for the setting `key`."""
        row = Adw.SpinRow.new_with_range(low, high, 1)
        row.set_title(title)
        row.set_value(self.setting(key, default))
        row.connect("notify::value", lambda spin, _param: self.save(**{key: int(spin.get_value())}))
        return row

    def switch_row(self, title: str, key: str, default: bool, subtitle: str = "") -> Adw.SwitchRow:
        """An on/off row for the setting `key`."""
        row = Adw.SwitchRow(title=title)
        if subtitle:
            row.set_subtitle(subtitle)
        row.set_active(bool(self.setting(key, default)))
        row.connect("notify::active",
                    lambda switch, _param: self.save(**{key: switch.get_active()}))
        return row

    def get_config_rows(self):
        return self.image_rows()

    def face_summary(self, face: str) -> str:
        """What a face shows, in words, for its row's subtitle."""
        picture = self.images().get(face, "")
        if picture:
            return f"Your picture: {os.path.basename(picture)}"
        icon = self.icon_name(face, self.default_icon(face))
        if not icon:
            return "No icon"
        base, variant = split_variant(icon)
        text = icon_label(base) + (f", variant {variant}" if variant else "")
        return text if self.icons().get(face) else f"{text} (default)"

    def image_rows(self) -> list[Adw.PreferencesRow]:
        """For each of the key's faces, a row that opens to pick its icon,
        drawn in the plugin's theme; the icon's variant, where it has more
        than one; and a picture of the user's own, which comes first."""
        return [self._face_row(face, title) for face, title in self.FACES]

    def _face_row(self, face: str, title: str) -> Adw.ExpanderRow:
        if len(self.FACES) > 1:
            title = f"Icon {title.lower()}" if title.startswith(("When", "While")) \
                else f"Icon for {title}"
        expander = Adw.ExpanderRow(title=title if len(self.FACES) > 1 else "Icon",
                                   subtitle=self.face_summary(face))

        def summarize():
            expander.set_subtitle(self.face_summary(face))

        def fill_variants():
            base, current = split_variant(self.icon_name(face, self.default_icon(face)))
            choices = [(letter, f"Variant {letter}") for letter in VARIANTS.get(base, ())]
            variant_row.set_visible(bool(choices))
            if choices:
                set_choices(variant_row, choices, current)

        def icon_picked(icon: str) -> None:
            self.set_icon(face, icon)
            fill_variants()
            summarize()

        def variant_picked(variant: str) -> None:
            self.set_variant(face, variant)
            summarize()

        default = self.default_icon(face)
        default_base, _ = split_variant(default)
        choices = [("", f"Default ({icon_label(default_base)})" if default else "None"),
                   *((base, icon_label(base)) for base in ICON_BASES)]
        picked_base, _ = split_variant(self.icons().get(face, ""))
        expander.add_row(combo_row("Icon", choices, picked_base, icon_picked))
        variant_row = combo_row("Variant", [], "", variant_picked,
                                "The same icon, drawn another way")
        expander.add_row(variant_row)
        fill_variants()
        expander.add_row(self._picture_row(face, summarize))
        return expander

    def _picture_row(self, face: str, summarize) -> Adw.PreferencesRow:
        def picked(path: str) -> None:
            self.set_image(face, path)
            summarize()

        row = FileDialogRow(title="Your own picture, instead", dialog_title="Your own picture",
                            filters=[IMAGES],
                            file_change_callback=lambda file: picked(file.get_path() or ""))
        current = self.images().get(face)
        if current:
            row.selected_file = Gio.File.new_for_path(current)
        row.update_label()
        clear = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER,
                           tooltip_text="No picture")

        def cleared(_button):
            picked("")
            row.selected_file = None
            row.update_label()
        clear.connect("clicked", cleared)
        row.add_suffix(clear)
        return row
