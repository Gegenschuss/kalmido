#!/usr/bin/env python3
"""2.19.0: the profile picture presets (static/avatars/*.svg) on a dark, coloured disc ("Leitstand" look), each with one
prop in a light accent colour. 2.170.0 B (#2674): the bot figure of the app icon (static/icon.svg, render.js botFig)
instead of the heron: light body, eyes in the disc colour, the antenna in the accent; props large and plain so the
figure still reads at 24-32 px. Deterministic: run it again and the files are byte-identical (--check compares instead
of writing).

usage: python3 tools/make_avatars.py [--check]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "avatars")
INK = "#ece9f4"
DARK = "#0f1012"
# the bot figure on the 100 grid of the app icon, placed on the 96 grid of a picture (the disc is centre 50/40, r 50.5
# in the figure's grid); everything of a preset is drawn in that grid
FIG = '<g transform="translate(48 50) scale(.95) translate(-50 -42)">{body}</g>'
BODY = '<path d="M50 22C74 22 78 26 78 50S74 78 50 78 22 74 22 50 26 22 50 22Z" fill="{ink}"/>'
EYES = ('<path d="M41 44V56" stroke="{bg}" stroke-width="6.5" stroke-linecap="round"/>'
        '<path d="M59 50V50.1" stroke="{bg}" stroke-width="8.5" stroke-linecap="round"/>')
ANT = '<path d="M58 6V15" stroke="{acc}" stroke-width="7" stroke-linecap="round"/>'
# key: (label, background, accent, prop drawn below the body, prop drawn on top, own eyes or None, own antenna or None)
PRESETS = {
    "coffee": ("Profile picture with coffee", "#4a3426", "#f2c46d", "",
               '<rect x="63" y="62" width="17" height="17" rx="3.5" fill="{acc}" stroke="{bg}" stroke-width="3"/>'
               '<path d="M80.5 66h2a4.5 4.5 0 0 1 0 9h-2" fill="none" stroke="{acc}" stroke-width="3.4"/>'
               '<path d="M68 59q-2-2.5 0-5M75 59q-2-2.5 0-5" fill="none" stroke="{bg}" stroke-width="2.6" stroke-linecap="round"/>',
               None, None),
    "headphones": ("Profile picture with headphones", "#233a5e", "#a78bfa",
                   '<path d="M19 52C17 11 83 11 81 52" fill="none" stroke="{acc}" stroke-width="5" stroke-linecap="round"/>',
                   '<rect x="13" y="41" width="13" height="21" rx="5" fill="{acc}" stroke="{bg}" stroke-width="2.5"/>'
                   '<rect x="74" y="41" width="13" height="21" rx="5" fill="{acc}" stroke="{bg}" stroke-width="2.5"/>', None, None),
    "camera": ("Profile picture with a camera", "#3b2a5c", "#7dd3fc", "",
               '<rect x="11" y="27" width="9" height="5" rx="1.5" fill="{acc}"/>'
               '<rect x="7" y="30" width="28" height="19" rx="4" fill="{acc}" stroke="{bg}" stroke-width="2.5"/>'
               '<circle cx="21" cy="39.5" r="6.2" fill="{bg}"/><circle cx="21" cy="39.5" r="2.6" fill="{acc}"/>', None, None),
    "sleepy": ("Sleepy profile picture", "#1f2a3a", "#a78bfa",
               '<path d="M66 7h9l-9 9h9M77 19h6l-6 6h6" fill="none" stroke="{acc}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>'
               '<path d="M21 6a9.5 9.5 0 1 0 10 13a7.5 7.5 0 0 1-10-13z" fill="{acc}"/>', "",
               '<path d="M35.5 50q5.5 4.5 11 0M53.5 50q5.5 4.5 11 0" fill="none" stroke="{bg}" stroke-width="4.6" stroke-linecap="round"/>',
               '<path d="M58 16C58 9 54 5.5 47 6.5" fill="none" stroke="{acc}" stroke-width="5.5" stroke-linecap="round"/>'),
    "laptop": ("Profile picture with a laptop", "#1f3d3a", "#7dd3fc", "",
               '<rect x="54" y="55" width="29" height="20" rx="2.5" fill="{acc}" stroke="{bg}" stroke-width="2.5"/>'
               '<circle cx="68.5" cy="65" r="2.6" fill="{bg}" opacity=".6"/>'
               '<path d="M51 78.5h32" stroke="{acc}" stroke-width="4" stroke-linecap="round"/>', None, None),
    "plant": ("Profile picture with a plant", "#24402a", "#86efac", "",
              '<path d="M72 64V49M72 57c-6-1-8.5-6-7.5-10c5 0 7.5 4 7.5 10zM72 53c5-2 8.5-6 7.5-11c-5 1-7.5 5-7.5 11z" '
              'fill="{acc}" stroke="{acc}" stroke-width="2" stroke-linejoin="round"/>'
              '<path d="M63 63h18l-2.5 15h-13z" fill="#e08a5a" stroke="{bg}" stroke-width="2.5" stroke-linejoin="round"/>', None, None),
    # the bot is the base figure now: "robot" is the extra-robotic one, two antennas with lamps and bolts at the sides
    "robot": ("Robot profile picture", "#2e3440", "#f472b6",
              '<path d="M17 45v12M83 45v12" stroke="{acc}" stroke-width="6" stroke-linecap="round"/>', "", None,
              '<path d="M42 9V15M58 9V15" stroke="{acc}" stroke-width="5" stroke-linecap="round"/>'
              '<circle cx="42" cy="7" r="4.6" fill="#f2c46d"/><circle cx="58" cy="7" r="4.6" fill="#f2c46d"/>'),
    "shades": ("Profile picture with sunglasses", "#5a2e2a", "#fca5a5", "",
               '<path d="M24 47.5H33M67 47.5H76M47 48h6" stroke="{bg}" stroke-width="2.6" stroke-linecap="round"/>'
               '<rect x="31" y="42" width="17" height="13" rx="4.5" fill="' + DARK + '"/><rect x="52" y="42" width="17" height="13" rx="4.5" fill="' + DARK + '"/>'
               '<path d="M35 46h4.5M56 46h4.5" stroke="{acc}" stroke-width="2" stroke-linecap="round"/>', "", None),
    "party": ("Profile picture with a party hat", "#4b2350", "#f472b6", "",
              '<path d="M28 27L52 23L37 1z" fill="{acc}" stroke="{bg}" stroke-width="2.5" stroke-linejoin="round"/>'
              '<path d="M32 18L45 16" stroke="{bg}" stroke-width="2.4" opacity=".6"/>'
              '<circle cx="37" cy="1.5" r="4" fill="#f2c46d"/><circle cx="76" cy="8" r="2.6" fill="#7dd3fc"/>'
              '<circle cx="12" cy="40" r="2.6" fill="#86efac"/><circle cx="88" cy="40" r="2.6" fill="#f2c46d"/><circle cx="14" cy="64" r="2.2" fill="{acc}"/>',
              None, None),
    "glasses": ("Profile picture with reading glasses", "#3d3a24", "#f2c46d", "",
                '<circle cx="41" cy="50" r="8" fill="{acc}" fill-opacity=".35" stroke="{bg}" stroke-width="3"/>'
                '<circle cx="59" cy="50" r="8" fill="{acc}" fill-opacity=".35" stroke="{bg}" stroke-width="3"/>'
                '<path d="M33 49H23M67 49H77" stroke="{bg}" stroke-width="3" stroke-linecap="round"/>', None, None),
}

def svg(key):
    label, bg, acc, under, over, eyes, ant = PRESETS[key]
    eyes = EYES if eyes is None else eyes
    ant = ANT if ant is None else ant
    fig = under + ant + BODY + eyes + over
    body = (f'<rect width="96" height="96" fill="{bg}"/>' + FIG.replace("{body}", fig)).replace("{ink}", INK).replace("{acc}", acc).replace("{bg}", bg)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" role="img" aria-label="{label}">'
            f'<defs><clipPath id="c"><circle cx="48" cy="48" r="48"/></clipPath></defs><g clip-path="url(#c)">{body}</g></svg>\n')

def main():
    check = "--check" in sys.argv
    bad = []
    for k in PRESETS:
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
    print("make_avatars:", "checked" if check else "wrote", len(PRESETS))


if __name__ == "__main__":
    main()
