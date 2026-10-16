import math

SPEAKER = '<path d="M2.5 9 H6.5 L12 4.5 V19.5 L6.5 15 H2.5 Z" fill="{fg}" stroke="none"/>'
SPEAKER_B = '<path d="M1.5 9 H5.5 L11 4.5 V19.5 L5.5 15 H1.5 Z" fill="{fg}" stroke="none"/>'
WAVE_1 = '<path d="M13.6 9.6 L15.4 12 L13.6 14.4" stroke="{hi}"/>'
WAVES_B = WAVE_1 + '<path d="M16.2 7.8 L19.2 12 L16.2 16.2" stroke="{hi}"/>'
MIC_STAND = ('<path d="M6 10 V12.5 L9 16.5 H15 L18 12.5 V10"/>'
             '<path d="M12 16.5 V20.5 M8.5 20.5 H15.5"/>')
MIC = '<path d="M9 5 L10.5 3 H13.5 L15 5 V12 L13.5 14 H10.5 L9 12 Z"/>' + MIC_STAND
# The mute keys draw the capsule as the highlight.
MIC_HI = '<path d="M9 5 L10.5 3 H13.5 L15 5 V12 L13.5 14 H10.5 L9 12 Z" stroke="{hi}"/>' + MIC_STAND


def octagon(cx, cy, r, cut=0.35):
    c = r * cut
    pts = [(cx - r + c, cy - r), (cx + r - c, cy - r), (cx + r, cy - r + c), (cx + r, cy + r - c),
           (cx + r - c, cy + r), (cx - r + c, cy + r), (cx - r, cy + r - c), (cx - r, cy - r + c)]
    return "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"


SLASH = ('<path d="M3.5 3 L20.5 21" stroke="{gap}" stroke-width="5" stroke-linecap="butt"/>'
         '<path d="M3.5 3 L20.5 21" stroke="{red}" stroke-linecap="butt"/>')
WEBCAM = ('<path d="' + octagon(12, 10.5, 7.5) + '"/>'
          '<path d="' + octagon(12, 11, 3.2, 0.4) + '" stroke="{hi}"/>'
          '<rect x="11.3" y="4.9" width="1.4" height="1.4" fill="{hi}" stroke="none"/>'
          '<path d="M12 18 V20"/>'
          '<path d="M7.5 21.8 L9 19.8 H15 L16.5 21.8 Z" fill="{fg}" stroke="none"/>')
SCREEN = ('<path d="M4 3.5 H20 L21.5 5 V15 L20 16.5 H4 L2.5 15 V5 Z"/>'
          '<path d="M12 16.5 V19.5"/>'
          '<path d="M7.5 21.5 L9 19.5 H15 L16.5 21.5 Z" fill="{fg}" stroke="none"/>')

HEADPHONES = ('<path d="M4.5 13 V9 L8.5 4.5 H15.5 L19.5 9 V13" stroke="{hi}"/>'
              '<path d="M4.4 11.5 H6.6 L8.2 13.1 V18.9 L6.6 20.5 H4.4 L2.8 18.9 V13.1 Z" fill="{fg}" stroke="none"/>'
              '<path d="M17.4 11.5 H19.6 L21.2 13.1 V18.9 L19.6 20.5 H17.4 L15.8 18.9 V13.1 Z" fill="{fg}" '
              'stroke="none"/>')


def badge(cx, cy, r):
    """A square badge with its corners cut off."""
    c = r * 0.35
    pts = [(cx - r + c, cy - r), (cx + r - c, cy - r), (cx + r, cy - r + c), (cx + r, cy + r - c),
           (cx + r - c, cy + r), (cx - r + c, cy + r), (cx - r, cy + r - c), (cx - r, cy - r + c)]
    d = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
    return f'<path d="{d}" fill="{{hi}}" stroke="{{bg}}" stroke-width="1.6"/>'


def octagon_replay():
    # An octagon broken at the top left, ending in a sharp arrowhead.
    pts = []
    for k in range(8):
        a = math.radians(-112.5 + 45 * k)
        pts.append((12 + 9 * math.cos(a), 12 + 9 * math.sin(a)))
    d = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts)
    return [f'<path d="{d}"/>',
            '<path d="M6.3 1.7 L10.5 5.9 L5.7 6.5 Z" fill="{hi}" stroke="none"/>']


def vertex_logo():
    def node(x, y, r, fill="{fg}"):
        return f'<path d="{octagon(x, y, r, 0.4)}" fill="{fill}" stroke="none"/>'
    k, cx, cy = 1.0, 12, 12.2
    p = {name: (cx + (x - 12) * k, cy + (y - 12) * k) for name, (x, y) in {
        "top": (12, 5.3), "left": (6.2, 15.2), "right": (17.8, 15.2),
        "top-a": (7.1, 2.5), "top-b": (16.9, 2.5), "left-a": (1.4, 12.6), "left-b": (6.2, 20.8),
        "right-a": (22.6, 12.6), "right-b": (17.8, 20.8)}.items()}
    line = lambda a, b: f"M{p[a][0]:.2f} {p[a][1]:.2f} L{p[b][0]:.2f} {p[b][1]:.2f}"
    parts = [f'<path d="{line("top", "left")} {line("left", "right")} {line("right", "top")}" '
             'stroke-width="1.6" stroke-linejoin="miter"/>',
             f'<path d="{line("top", "top-a")} {line("top", "top-b")} {line("left", "left-a")} '
             f'{line("left", "left-b")} {line("right", "right-a")} {line("right", "right-b")}" '
             'stroke-width="1.8" stroke-linecap="butt"/>']
    parts += [node(*p[n], 1.55) for n in ("top-a", "top-b", "left-a", "left-b", "right-a", "right-b")]
    parts += [node(*p[n], 2.4) for n in ("top", "left", "right")]
    parts.append(node(cx, cy - 0.1, 1.8, "{hi}"))
    return parts


ICONS = {
    "media-play": ("Media play", [
        '<path d="M8.9 5.9 L18.4 12 L7.6 18.1 Z" fill="{hi}" stroke-width="1.6"/>']),
    "media-pause": ("Media pause", [
        '<path d="M6.6 5.3 H11.4 L10 18.7 H5.2 Z" fill="{hi}" stroke-width="1.6"/>',
        '<path d="M15 5.3 H19.8 L18.4 18.7 H13.6 Z" fill="{hi}" stroke-width="1.6"/>']),
    "media-play-pause": ("Media play/pause", [
        '<path d="M4.4 6 L12 12 L3.2 18 Z" fill="{hi}" stroke="none"/>',
        '<path d="M15 6 H17.8 L16.6 18 H13.8 Z" fill="{fg}" stroke="none"/>',
        '<path d="M19.8 6 H22.6 L21.4 18 H18.6 Z" fill="{fg}" stroke="none"/>']),
    "media-previous": ("Previous song", [
        '<path d="M3.5 6 H6 L5.2 18 H2.7 Z" fill="{fg}" stroke="none"/>',
        '<path d="M14 6 L6.8 12 L13.2 18 Z" fill="{hi}" stroke="none"/>',
        '<path d="M21.6 6 L14.4 12 L20.8 18 Z" fill="{hi}" stroke="none"/>']),
    "media-next": ("Next song", [
        '<path d="M3.4 6 L10.4 12 L2.6 18 Z" fill="{hi}" stroke="none"/>',
        '<path d="M11 6 L18 12 L10.2 18 Z" fill="{hi}" stroke="none"/>',
        '<path d="M19 6 H21.5 L20.7 18 H18.2 Z" fill="{fg}" stroke="none"/>']),
    "volume-up": ("Volume up", [SPEAKER, '<path d="M15 12 H21 M18 9 V15" stroke="{hi}" stroke-linecap="butt" stroke-width="2.4"/>']),
    "volume-down": ("Volume down", [SPEAKER, '<path d="M15 12 H21" stroke="{hi}" stroke-linecap="butt" stroke-width="2.4"/>']),
    "volume-up-b": ("Volume up (B)", [
        SPEAKER_B, WAVES_B, badge(19.4, 4.6, 3.9),
        '<path d="M17.4 4.6 H21.4 M19.4 2.6 V6.6" stroke="{bg}" stroke-width="1.7" stroke-linecap="butt"/>']),
    "volume-down-b": ("Volume down (B)", [
        SPEAKER_B, WAVES_B, badge(19.4, 4.6, 3.9),
        '<path d="M17.4 4.6 H21.4" stroke="{bg}" stroke-width="1.7" stroke-linecap="butt"/>']),
    "volume-up-c": ("Volume up (C)", [
        '<g transform="translate(1.7 0)">' + SPEAKER_B + WAVES_B + '</g>']),
    "volume-down-c": ("Volume down (C)", [
        '<g transform="translate(1.7 0)">' + SPEAKER_B + WAVE_1 + '</g>']),
    "clip-save": ("Clip save", [
        '<path d="M4.5 4 H18.5 V14 L16.5 16 H2.5 V6 Z"/>',
        '<path d="M9 7.2 L14 10 L8.2 12.8 Z" fill="{hi}" stroke="none"/>',
        badge(17.5, 16.5, 5),
        '<path d="M17.5 13.6 V18.8 M15.2 16.6 L17.5 18.9 L19.8 16.6" stroke="{bg}" stroke-width="1.7" '
        'stroke-linecap="butt"/>']),
    "clip-save-b": ("Clip save (B)", octagon_replay() + [
        '<path d="M10.4 8.2 L16.2 12 L9.4 15.8 Z" fill="{hi}" stroke="none"/>']),
    "mic-elgato-wave": ("Elgato Wave", [
        '<path d="M8 6.5 L10.5 3 H13.5 L16 6.5 V14 L14.8 15.3 H9.2 L8 14 Z" stroke="{hi}"/>',
        '<path d="M10.6 5.6 H13.4 M10.6 7.6 H13.4 M10.6 9.6 H13.4" stroke-width="1.2" stroke-linecap="butt"/>',
        '<path d="M12 10.9 L13.3 12.2 L12 13.5 L10.7 12.2 Z" fill="{hi}" stroke="none"/>',
        '<path d="M5 10 V16 L7 18 H17 L19 16 V10"/>',
        '<path d="M5 11 H8 M16 11 H19" stroke-width="1.6" stroke-linecap="butt"/>',
        '<path d="M12 18 V20"/>',
        '<path d="M7 21.8 L8.6 19.8 H15.4 L17 21.8 Z" fill="{fg}" stroke="none"/>']),
    "headset-steelseries-arctis": ("SteelSeries Arctis", [
        '<path d="M4.5 12 V8 L8.5 3.6 H15.5 L19.5 8 V12"/>',
        '<path d="M7.2 11.5 L9.6 8 H14.4 L16.8 11.5" stroke="{hi}" stroke-width="2.4"/>',
        '<path d="M4.4 10.5 H6.6 L8.2 12.1 V18.4 L6.6 20 H4.4 L2.8 18.4 V12.1 Z" fill="{fg}" stroke="none"/>',
        '<path d="M17.4 10.5 H19.6 L21.2 12.1 V18.4 L19.6 20 H17.4 L15.8 18.4 V12.1 Z" fill="{fg}" stroke="none"/>',
        '<path d="M5.5 19.5 L7.5 21.5 H10.5" stroke-width="1.6" stroke-linecap="butt"/>',
        '<path d="M10.3 20.5 H12.6 V22.5 H10.3 Z" fill="{hi}" stroke="none"/>']),
    "mic-none": ("No microphone", [
        # The mic with a cut-corner badge holding an X, like the other badges.
        '<g transform="translate(-2 0)">' + MIC + '</g>',
        badge(18, 17.5, 4.6),
        '<path d="M16.2 15.7 L19.8 19.3 M19.8 15.7 L16.2 19.3" stroke="{bg}" stroke-width="1.7" '
        'stroke-linecap="butt"/>']),
    "webcam": ("Camera", [WEBCAM]),
    "webcam-off": ("Camera off", [WEBCAM, SLASH]),
    "screenshare": ("Screenshare", [
        SCREEN, '<path d="M12 13.5 V7.5 M9 10.2 L12 7.2 L15 10.2" stroke="{hi}" stroke-linecap="butt"/>']),
    "screenshare-off": ("Screenshare off", [
        SCREEN, '<path d="M12 13.5 V7.5 M9 10.2 L12 7.2 L15 10.2" stroke="{hi}" stroke-linecap="butt"/>', SLASH]),
    "mic-unmuted": ("Mic unmuted", [MIC_HI]),
    "mic-muted": ("Mic muted", [MIC_HI, SLASH]),
    "headphones-undeafened": ("Undeafened", [HEADPHONES]),
    "headphones-deafened": ("Deafened", [HEADPHONES, SLASH]),
    # The Vertex logo: three nodes joined in a triangle, each with two
    # spokes, around a center node in the highlight color.
    "vertex-logo": ("Vertex", vertex_logo()),
}
