"""StreamController stubbed out, and the plugin imported as StreamController
imports it, for the tests of every app's keys."""

import importlib
import sys
import threading
import types
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
PACKAGE = "plugins.com_stellargalaxyatlas_Vertex"


def wait(condition, seconds=5.0):
    for _ in range(int(seconds / 0.02)):
        if condition():
            return True
        threading.Event().wait(0.02)
    return condition()


class Events:
    DOWN, UP, TURN_CW, TURN_CCW = "Down", "Up", "Turn CW", "Turn CCW"


class _Dial:
    Events = Events


class _ActionBase:
    def __init__(self, plugin_base=None, settings=None):
        self.plugin_base = plugin_base
        self.action_id = "test"
        self._settings = dict(settings or {})
        self.labels = {}
        self.errors = 0
        self.media = []

    def get_settings(self):
        return dict(self._settings)

    def set_settings(self, settings):
        self._settings = dict(settings)

    def set_top_label(self, text):
        self.labels["top"] = text

    def set_center_label(self, text):
        self.labels["center"] = text

    def set_bottom_label(self, text):
        self.labels["bottom"] = text

    def show_error(self, duration=-1):
        self.errors += 1

    def set_background_color(self, color):
        self.background = color

    def set_media(self, media_path=None, image=None, **_kwargs):
        self.media.append(image if image is not None else media_path)

    def event_callback(self, event, data=None):
        if event == Events.DOWN:
            self.on_key_down()

    def on_key_down(self):
        pass


class _PluginBase:
    PATH = str(PLUGIN)

    def __init__(self):
        self.holders = []

    def add_action_holder(self, holder):
        self.holders.append(holder)

    def register(self, **kwargs):
        self.registered = kwargs

    def get_settings(self):
        return dict(getattr(self, "_plugin_settings", {}))

    def set_settings(self, settings):
        self._plugin_settings = dict(settings)


def _stub_streamcontroller(monkeypatch):
    def module(name, **attrs):
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    gi = module("gi", require_version=lambda *_: None)
    gi.repository = module("gi.repository", Adw=types.SimpleNamespace(),
                           Gio=types.SimpleNamespace(), Gtk=types.SimpleNamespace(),
                           GLib=types.SimpleNamespace(idle_add=lambda f, *a: f(*a)))
    module("GtkHelper")
    module("GtkHelper.FileDialogRow", FileDialogRow=object,
           FileDialogFilter=lambda name, patterns: (name, patterns))
    module("loguru", logger=types.SimpleNamespace(debug=print, info=print, warning=print))
    module("src.backend.PluginManager.ActionBase", ActionBase=_ActionBase)
    module("src.backend.DeckManagement.InputIdentifier",
           Input=types.SimpleNamespace(Key="Key", Touchscreen="Touchscreen", Dial=_Dial))
    module("src.backend.PluginManager.ActionHolder",
           ActionHolder=lambda **kwargs: types.SimpleNamespace(**kwargs))
    module("src.backend.PluginManager.ActionInputSupport",
           ActionInputSupport=types.SimpleNamespace(SUPPORTED=2, UNSUPPORTED=0))
    module("src.backend.PluginManager.PluginBase", PluginBase=_PluginBase)
    plugins = module("plugins")
    plugins.__path__ = []
    package = module(PACKAGE)
    package.__path__ = [str(PLUGIN)]


@pytest.fixture
def plugin(monkeypatch):
    _stub_streamcontroller(monkeypatch)
    for name in [n for n in sys.modules if n.startswith(PACKAGE + ".")]:
        monkeypatch.delitem(sys.modules, name)
    names = ("actions.vertex_keys", "actions.discord_keys", "actions.media_keys",
             "actions.theme", "vertex_client", "discord_client", "media_client", "main")
    return types.SimpleNamespace(**{name.split(".")[-1]: importlib.import_module(
        f"{PACKAGE}.{name}") for name in names})


@pytest.fixture
def registered(plugin, tmp_path, monkeypatch):
    """The plugin as StreamController starts it, with no app to find."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    for client in (plugin.vertex_client.Vertex, plugin.discord_client.Discord,
                   plugin.media_client.Media):
        monkeypatch.setattr(client, "start", lambda self: None)
    return plugin.main.VertexPlugin()
