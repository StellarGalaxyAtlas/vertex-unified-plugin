# Vertex Media for StreamController

Stream Deck keys for [Vertex](https://github.com/StellarGalaxyAtlas/vertex),
[Discord](https://discord.com) and your media player, in
[StreamController](https://github.com/StreamController/StreamController) on
Linux.

- Every key shows its app's current state, whatever changed it.
- All keys share one Vertex color theme.

The Discord part is based on
[DiscordSC](https://github.com/oparada1988/DiscordSC).

## Keys

**Vertex**

| Key | What it does |
| --- | --- |
| Sonar Information | Shows a channel's volume, or "Muted" |
| Sonar Volume | Turns a channel up or down. On a dial: turn to change, press to mute |
| Sonar Toggle Channel Mute | Mutes or unmutes a channel |
| Sonar Next Microphone | Switches to the next mic |
| Sonar Next Output Device | Switches to the next output |
| Sonar Toggle Microphone | Switches between two mics you pick |
| Sonar Toggle Output Device | Switches between two outputs you pick |
| Replay Buffer Toggle | Starts or stops the replay buffer |
| Replay Save Clip | Saves a clip, and flashes green when it's saved |
| Show Vertex | Brings Vertex to the front |

**Discord**

| Key | What it does |
| --- | --- |
| Discord Toggle Mute | Mutes or unmutes your mic |
| Discord Toggle Deafen | Deafens or undeafens you |
| Discord Toggle Camera | Turns your camera on or off (in a call) |
| Discord Toggle Screen Share | Starts or stops sharing (in a call). Discord asks what to share |
| Discord Voice Channel | Joins a voice channel. Press again to leave, unless set to stay |

**Media**

| Key | What it does |
| --- | --- |
| Media Play/Pause | Plays or pauses. Can be set to only play or only pause. On a dial: turn to skip, press to play or pause |
| Media Next | Next song |
| Media Previous | Previous song |

Each key's settings pick its channel, step, devices, clip length, voice
channel or player.

- **Media keys** work with any player in your desktop's media controls
  (Spotify, Firefox, Chromium, mpv, VLC and most others). They follow the
  player that's playing, or one you pick, and can show the song and artist.
  They need `gdbus`, which every Linux desktop has.
- **Camera and screen share** use Discord commands that aren't officially
  documented. If Discord doesn't allow them for your app, only these two keys
  stop working.

## Settings

In StreamController, open the plugin's page, then **Settings**:

- **Look**: the theme and version for all keys. Pick None to show text
  labels instead of icons.
- **Vertex**, **Discord**, **Media**: whether the plugin reaches each app.
  Discord also has **Set up** and **Authorize**.

Each key can also use another icon per state, a variant (A, B or C for some
icons), or a picture of your own. Leave the key's own image in
StreamController empty, or it covers these.

## Icons

25 icons, in white and in each of Vertex's nine color schemes. Each scheme
comes in five versions:

- **A**: main color
- **B**: text color, main-color highlights
- **C**: second color, main-color highlights
- **D**: main color fading into the second
- **E**: key filled with the main color

![Navy icons](assets/icons/_previews/Navy.png)

All themes: [Abyss](assets/icons/_previews/Abyss.png) ·
[Aurora](assets/icons/_previews/Aurora.png) ·
[Coral](assets/icons/_previews/Coral.png) ·
[Glacier](assets/icons/_previews/Glacier.png) ·
[Midnight Blue](assets/icons/_previews/Midnight_Blue.png) ·
[Navy](assets/icons/_previews/Navy.png) ·
[Plum](assets/icons/_previews/Plum.png) ·
[Polar](assets/icons/_previews/Polar.png) ·
[Spooky](assets/icons/_previews/Spooky.png) ·
[White](assets/icons/_previews/White.png).
Each theme's folder in `assets/icons/_previews` has one sheet per version.

The information tile uses [Chakra Petch](https://fonts.google.com/specimen/Chakra+Petch)
Bold (SIL Open Font License, in `assets/fonts`).

## Install

> [!WARNING]
> **These installation instructions were written by AI and have not been
> verified.** Check each step before you run it.

You need StreamController 1.5.0 beta or later, plus Vertex and the Discord
desktop app for their keys.

If you have the old Vertex or Vertex Discord plugin, remove it first. Vertex
keys and the theme carry over; Discord keys have to be added again.

```fish
git clone https://github.com/StellarGalaxyAtlas/vertex-unified-plugin.git ~/vertex-media
mkdir -p ~/.var/app/com.core447.StreamController/data/plugins
ln -s ~/vertex-media ~/.var/app/com.core447.StreamController/data/plugins/com_stellargalaxyatlas_Vertex
```

Restart StreamController. The keys are under "vertex-unified-plugin".

**Update:** `git -C ~/vertex-media pull`, then restart StreamController.

### Your Discord app

Discord only lets apps you made control it, so you need one of your own:

1. In the [Discord Developer Portal](https://discord.com/developers/applications),
   create a **New Application**.
2. Under **OAuth2**, add `http://localhost:9000` to **Redirects** and save.
3. Copy the **Client ID**. Reset and copy the **Client Secret**.
4. In the plugin's settings, open **Set up** under Discord, paste both, and
   press the check mark on each.
5. Press **Authorize** in the popup Discord shows.

Discord may ask twice the first time. The plugin stays logged in after that.

**`invalid_scope`?** Discord only lets the app's maker and its **App
Testers** use it. Log in to Discord with the account that made the app, or
add your account under **App Testers** and accept the invite.

### Flatpak StreamController

Give it access to Vertex's folder, in Flatseal (**Filesystem**, add
`xdg-run/vertex`) or with:

```fish
flatpak override --user --filesystem=xdg-run/vertex com.core447.StreamController
```

Without it the Vertex keys still work, just slower.

If the settings say Discord or the media players can't be reached, run:

```fish
flatpak override --user --filesystem=xdg-run/discord-ipc-0 --talk-name=org.mpris.MediaPlayer2.\* com.core447.StreamController
```

For the Flatpak Discord, use `xdg-run/app/com.discordapp.Discord` instead of
`xdg-run/discord-ipc-0`.

## Development

See [development.md](development.md).

## License

MIT, see [LICENSE](LICENSE).
