"""Copies the rendered sets into one folder per theme and variant, with readable file names."""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(__file__))
from make_themed_defs import SCHEMES, variants  # noqa: E402

SRC, OUT = sys.argv[1], sys.argv[2]
FILES = {
    "media-play": "Media_Play", "media-pause": "Media_Pause", "media-play-pause": "Media_Play_Pause",
    "media-previous": "Media_Previous", "media-next": "Media_Next",
    "volume-up": "Volume_Up_A", "volume-down": "Volume_Down_A",
    "volume-up-b": "Volume_Up_B", "volume-down-b": "Volume_Down_B",
    "volume-up-c": "Volume_Up_C", "volume-down-c": "Volume_Down_C",
    "clip-save": "Clip_Save_A", "clip-save-b": "Clip_Save_B",
    "mic-elgato-wave": "Microphone", "headset-steelseries-arctis": "Headset",
    "mic-none": "No_Microphone",
    "webcam": "Camera", "webcam-off": "Camera_Off",
    "screenshare": "Screenshare", "screenshare-off": "Screenshare_Off",
    "mic-unmuted": "Microphone_Unmuted", "mic-muted": "Microphone_Muted",
    "headphones-undeafened": "Speaker_Undeafened", "headphones-deafened": "Speaker_Deafened",
    "vertex-logo": "Vertex_Logo",
}


def folder(text):
    words = re.split(r"[\s·,]+", text.strip())
    return "_".join(w[:1].upper() + w[1:] for w in words if w)


def copy(src, dst):
    os.makedirs(dst, exist_ok=True)
    for key, name in FILES.items():
        shutil.copy(os.path.join(src, "png", "144", key + ".png"), os.path.join(dst, name + ".png"))
        shutil.copy(os.path.join(src, "svg", key + ".svg"), os.path.join(dst, name + ".svg"))


copy(os.path.join(SRC, "white"), os.path.join(OUT, "White"))
# Contact sheets: one per theme with every variant, and one per variant with every icon.
PREVIEWS = os.path.join(OUT, "_previews")
os.makedirs(PREVIEWS, exist_ok=True)
shutil.copy(os.path.join(SRC, "white", "preview.png"), os.path.join(PREVIEWS, "White.png"))
for key, (scheme_name, *colours) in SCHEMES.items():
    os.makedirs(os.path.join(PREVIEWS, folder(scheme_name)), exist_ok=True)
    for v, (label, _c, _d) in variants(*colours).items():
        copy(os.path.join(SRC, "themes", key, v), os.path.join(OUT, folder(scheme_name), folder(label)))
        shutil.copy(os.path.join(SRC, "themes", key, v, "preview.png"),
                    os.path.join(PREVIEWS, folder(scheme_name), folder(label) + ".png"))
    shutil.copy(os.path.join(SRC, "themes", key, "overview.png"),
                os.path.join(OUT, "_previews", folder(scheme_name) + ".png"))
