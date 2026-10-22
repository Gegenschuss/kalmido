#!/usr/bin/env python3
"""2.19.0: the profile picture presets (static/avatars/*.svg) on a dark, coloured disc ("Leitstand" look), each with one
prop in a light accent colour. 2.170.0 B (#2674): the bot figure of the app icon (static/icon.svg, render.js botFig)
instead of the heron: light body, eyes in the disc colour, the antenna in the accent; props large and plain so the
figure still reads at 24-32 px. Deterministic: run it again and the files are byte-identical (--check compares instead
of writing).
2.170.0 (#2675): user pictures and agent pictures are two sets now. The old names (coffee.svg ... stored as "p:<name>")
draw a person in the same style (head with hair instead of the antenna, same eyes, a shirt in the accent), so saved
profile pictures become a person without a data change; the bots are a-<name>.svg, offered for agents (an agent with an
old "p:<name>" shows its a-<name> bot, accounts/pictures.py).

2.170.0 (#2675): no props any more on either set; the pictures differ only by colour (disc, hair /
skin, shirt), the hair of the person, the antenna of the bot and the face (e.g. sleepy = half-closed eyes). The names stay
(they are stored as "p:<name>") and are just keys now.

usage: python3 tools/make_avatars.py [--check]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "avatars")
INK = "#ece9f4"
# the figure on the 100 grid of the app icon, placed on the 96 grid of a picture
FIG = '<g transform="translate(48 50) scale(.95) translate(-50 -42)">{body}</g>'
BODY = '<path d="M50 22C74 22 78 26 78 50S74 78 50 78 22 74 22 50 26 22 50 22Z" fill="{ink}"/>'


def _st(d, w=6.5):
    return f'<path d="{d}" fill="none" stroke="{{bg}}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>'


# faces, drawn in the disc colour (like the eyes of the app icon); "plain" is the bot's line + dot or the person's two lines
FACES = {
    "bot": _st("M41 44V56") + _st("M59 50V50.1", 8.5),
    "person": _st("M41 46V54M59 46V54"),
    "happy": _st("M35.5 52q5.5-6 11 0M53.5 52q5.5-6 11 0", 4.6),
    "sleepy": '<path d="M35 48h12a6 6 0 0 1-12 0zM53 48h12a6 6 0 0 1-12 0z" fill="{bg}"/>',
    "wink": _st("M41 44V56") + _st("M53.5 50q5.5 4.5 11 0", 4.6),
    "glance": _st("M37 45V55M55 45V55"),
    "wide": '<circle cx="41" cy="50" r="5" fill="{bg}"/><circle cx="59" cy="50" r="5" fill="{bg}"/>',
    "cool": _st("M36 50h10M54 50h10", 6),
}


def _ant(d, w=7):
    return f'<path d="{d}" fill="none" stroke="{{acc}}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>'


LAMP = "#f2c46d"
ANTENNAS = {
    "straight": _ant("M58 6V15"),
    "ball": _ant("M58 10V15") + '<circle cx="58" cy="6" r="4.8" fill="{acc}"/>',
    "ring": _ant("M58 11V15", 5) + '<circle cx="58" cy="6" r="4" fill="none" stroke="{acc}" stroke-width="3"/>',
    "bent": _ant("M50 15V11Q50 5 58 5", 5.5),
    "droop": _ant("M58 16C58 9 54 5.5 47 6.5", 5.5),
    "zigzag": _ant("M55 16L61 12L55 8L61 4", 4.2),
    "fork": _ant("M50 16V10L44 4M50 10L56 4", 4.5),
    "twin": _ant("M42 9V15M58 9V15", 5) + f'<circle cx="42" cy="7" r="4.6" fill="{LAMP}"/><circle cx="58" cy="7" r="4.6" fill="{LAMP}"/>',
    "lamp": _ant("M50 16V13", 5) + f'<circle cx="50" cy="8" r="5.2" fill="{LAMP}"/>',
    "curl": _ant("M50 16V10a4.5 4.5 0 1 1 6 4", 4.2),
    "tall": _ant("M50 2V15", 5.5),
}


def _hair(d):
    return f'<path d="{d}" fill="{{hair}}"/>'


H_SHORT = _hair("M20 48C18 24 30 15 50 15S82 24 80 48C76 38 70 33 62 32C54 29 40 29 34 33C28 36 23 41 20 48Z")
H_LONG_B = _hair("M17 48C15 22 30 14 50 14S85 22 83 48V82Q83 88 77 88H23Q17 88 17 82Z")
H_LONG_F = _hair("M21 46C21 26 32 18 50 18S79 26 79 46C72 36 60 31 46 33C36 34 27 39 21 46Z")
# hair style: (behind the head, on top of the head)
HAIR = {
    "short": ("", H_SHORT),
    "curly": ("", _hair("M22 42C22 26 32 20 50 20S78 26 78 42C70 34 30 34 22 42Z")
              + "".join(f'<circle cx="{x}" cy="{y}" r="8.5" fill="{{hair}}"/>' for x, y in ((24, 40), (28, 28), (38, 20), (50, 17), (62, 20), (72, 28), (76, 40)))),
    "bun": ('<circle cx="50" cy="10" r="9" fill="{hair}"/>', H_SHORT),
    "long": (H_LONG_B, H_LONG_F),
    "swept": ("", _hair("M20 50C16 26 30 15 50 15C68 15 82 24 80 40C74 34 64 30 52 34C42 38 30 40 20 50Z")),
    "ponytail": (_hair("M74 30Q96 36 88 68Q84 52 72 46Z"), H_SHORT),
    "afro": ('<circle cx="50" cy="38" r="33" fill="{hair}"/>', ""),
    "buzz": ("", _hair("M24 40C25 25 36 19 50 19S75 25 76 40C66 33 34 33 24 40Z")),
    "bob": (_hair("M17 46C15 22 30 14 50 14S85 22 83 46V64Q83 70 77 70H23Q17 70 17 64Z"), H_LONG_F),
    "sidepart": ("", _hair("M80 50C84 26 70 15 50 15C32 15 18 24 20 40C26 34 36 30 48 34C58 38 70 40 80 50Z")),
}
SHIRT = '<path d="M12 116C12 90 28 82 50 82S88 90 88 116Z" fill="{acc}"/><rect x="42" y="68" width="16" height="18" rx="4" fill="{skin}"/>'
# key: (disc, accent = antenna / shirt, face, bot antenna, person hair, skin, hair colour)
PRESETS = {
    "coffee": ("#4a3426", "#f2c46d", "happy", "ball", "short", "#f1c7a5", "#6b3f22"),
    "headphones": ("#233a5e", "#a78bfa", None, "ring", "curly", "#8d5a3b", "#1f1714"),
    "camera": ("#3b2a5c", "#7dd3fc", "glance", "bent", "bun", "#e0ac85", "#a6402a"),
    "sleepy": ("#1f2a3a", "#a78bfa", "sleepy", "droop", "long", "#f5d6bd", "#d9a65b"),
    "laptop": ("#1f3d3a", "#7dd3fc", None, "zigzag", "swept", "#c68a5e", "#241a15"),
    "plant": ("#24402a", "#86efac", "wink", "fork", "ponytail", "#f1c7a5", "#8a5a33"),
    "robot": ("#2e3440", "#f472b6", "wide", "twin", "afro", "#5c3a27", "#1b1411"),
    "shades": ("#5a2e2a", "#fca5a5", "cool", "lamp", "buzz", "#e8b48f", "#c9c3b8"),
    "party": ("#4b2350", "#f472b6", "happy", "curl", "bob", "#a86b45", "#2b1d16"),
    "glasses": ("#3d3a24", "#f2c46d", None, "tall", "sidepart", "#f5d6bd", "#9aa0a8"),
}


def _wrap(label, bg, fig):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" role="img" aria-label="{label}">'
            f'<defs><clipPath id="c"><circle cx="48" cy="48" r="48"/></clipPath></defs><g clip-path="url(#c)">'
            f'<rect width="96" height="96" fill="{bg}"/>{FIG.replace("{body}", fig)}</g></svg>\n')


def svg(key):
    """"a-<name>" = the bot, "<name>" = the person."""
    bot = key.startswith("a-")
    bg, acc, face, ant, hair, skin, hcol = PRESETS[key[2:] if bot else key]
    eyes = FACES[face or ("bot" if bot else "person")]
    if bot:
        fig = ANTENNAS[ant] + BODY + eyes
        return _wrap("Bot profile picture", bg, fig.replace("{ink}", INK).replace("{acc}", acc).replace("{bg}", bg))
    back, top = HAIR[hair]
    fig = SHIRT + back + BODY.replace("{ink}", "{skin}") + eyes + top
    return _wrap("Profile picture", bg, fig.replace("{skin}", skin).replace("{hair}", hcol).replace("{acc}", acc).replace("{bg}", bg))


KEYS = list(PRESETS) + ["a-" + k for k in PRESETS]


def main():
    check = "--check" in sys.argv
    bad = []
    for k in KEYS:
        p = os.path.join(OUT, k + ".svg")
        s = svg(k)
        if check:
            try:
                with open(p, encoding="utf-8") as f:
                    if f.read() != s:
                        bad.append(k)
            except OSError:
                bad.append(k)
        else:
            with open(p, "w", encoding="utf-8") as f:
                f.write(s)
    if bad:
        sys.exit("make_avatars: differs: " + ", ".join(bad))
    print("make_avatars:", "checked" if check else "wrote", len(KEYS))


if __name__ == "__main__":
    main()
