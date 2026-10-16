# Development

## How it works

`main.py` registers the keys and starts one client per app, each following
its app's state for every key and calling them back when it changes:

| App | Client | Keys |
| --- | --- | --- |
| Vertex | `vertex_client.py` | `actions/vertex_keys.py` |
| Discord | `discord_client.py` | `actions/discord_keys.py` |
| Media players | `media_client.py` | `actions/media_keys.py` |

Every key derives from `KeyAction` in `actions/base.py`, which draws it with
the icons in `assets/icons` in the plugin's one theme (`actions/theme.py`),
and gives it its icon settings: an icon, its variant and a picture of the
user's own for each face. Each kind of key names its client in `app`.
The clients use only the standard library, since they run in
StreamController's Python. The information tile (`actions/tile.py`) draws
with Pillow, which StreamController ships.

### Vertex

The client talks to Vertex's control socket at
`$XDG_RUNTIME_DIR/vertex/control.sock`, one JSON line per request and reply.
It keeps one `subscribe` connection open for all keys. Key presses send
commands such as `volume`, `mute`, `device`, `replay`, `save-clip` and
`show` (see Vertex's `src/vertex/control.py`). Inside the Flatpak without
the `xdg-run/vertex` permission, it reaches the socket through a small relay
run with `flatpak-spawn --host`.

### Discord

The client connects to Discord's socket, `discord-ipc-<n>` in
`$XDG_RUNTIME_DIR` (or the folder of Discord's Flatpak or Snap). Every
message is an opcode and a length, as two little-endian 32-bit numbers,
then that much JSON. After the handshake Discord sends READY and the client
logs in:

1. `AUTHENTICATE` with the saved access token;
2. if that fails, a new token from the saved refresh token, through
   `https://discord.com/api/oauth2/token`;
3. if that fails too, `AUTHORIZE` (Discord's popup), with the camera and
   screen share scopes, or without them if Discord refuses them, then the
   code is swapped for tokens. The popup opens on its own once; after a
   "no", only the settings' **Authorize** button opens it again.

Then it subscribes to `VOICE_SETTINGS_UPDATE`, `VOICE_CHANNEL_SELECT`,
`VIDEO_STATE_UPDATE` and `SCREENSHARE_STATE_UPDATE`, and reads the voice
settings and the channel the user is in. Keys send `SET_VOICE_SETTINGS`,
`TOGGLE_VIDEO`, `TOGGLE_SCREENSHARE` and `SELECT_VOICE_CHANNEL`; the key
settings list channels with `GET_GUILDS` and `GET_CHANNELS`. The commands
are described in the community's
[RPC docs](https://docs.discord.food/topics/rpc).

Discord allows only a couple of new connections a minute, so one
connection carries the state and every command, matched to replies by
nonce.

Inside the Flatpak, when the socket isn't in sight, the client runs a small
relay with `flatpak-spawn --host python3 -c` that finds the socket on the
host and copies bytes both ways. `discord_client.py` uses only the standard
library, since it runs in StreamController's Python.

### Media players

Players are on the session bus as `org.mpris.MediaPlayer2.<name>`. The
client runs one watcher, a shell loop that lists them with `gdbus` and
prints each one's `org.mpris.MediaPlayer2.Player` properties once a second;
the client reads PlaybackStatus, the title and artist, and CanGoNext and
CanGoPrevious from gdbus's print. A key press runs one `gdbus call` of
PlayPause, Play, Pause, Next or Previous. Inside the Flatpak both go through
`flatpak-spawn --host`.

## Action ids

Keep the action ids in `main.py` as they are, even where a key's name
changed: StreamController stores keys by these ids. The plugin keeps the
Vertex plugin's id and its keys' ids, so keys set up with it carry over.

## Tests

The tests run each client against its app: Vertex's real socket server
(so Vertex has to be installed in the same Python, or those tests are
skipped), a fake Discord on a socket, and a fake `gdbus`; and the keys with
StreamController stubbed out (`tests/conftest.py`):

```fish
python3 -m venv .venv
source .venv/bin/activate.fish
pip install pytest ruff pillow
pip install -e ../vertex
python -m pytest
ruff check .
```

## Releasing

Raise the version in `manifest.json` and `VERSION` in `main.py`.
