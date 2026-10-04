#!/usr/bin/env python3
"""2.19.0: the profile picture presets (static/avatars/*.svg): the heron of the app icon as a line drawing on a dark,
coloured disc ("Leitstand" look), each with one prop in a light accent colour. Deterministic: run it again and the files
are byte-identical (--check compares instead of writing).

usage: python3 tools/make_avatars.py [--check]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "avatars")
INK = "#ece9f4"
# the heron of the app icon (100 grid: body, neck + head, beak), placed on the 96 grid of a picture
HERON = ('<g transform="translate(48 50) scale(1.25) translate(-50.5 -39.5)" fill="none" stroke="{ink}" stroke-width="3.6" '
         'stroke-linecap="round" stroke-linejoin="round"><path d="M24 50C34 42 52 43 62 51C55 58 40 60 30 55"/>'
         '<path d="M54 48C51 39 49 32 51 25C53 20 58 19 61 22"/><path d="M61 22L77 26"/></g>')
EYE = '<circle cx="56" cy="30.4" r="2.1" fill="{ink}"/>'
# key: (label, background, accent, extra drawing, own eye or None = the dot)
PRESETS = {
    "coffee": ("Profile picture with coffee", "#4a3426", "#f2c46d",
               '<rect x="62" y="66" width="15" height="15" rx="3" fill="{acc}"/><path d="M77 70h2.5a3.5 3.5 0 0 1 0 7H77" fill="none" stroke="{acc}" stroke-width="2.4"/>'
               '<path d="M66 62q-2.2-3 0-6M71.5 62q-2.2-3 0-6" fill="none" stroke="{ink}" stroke-width="1.8" stroke-linecap="round" opacity=".8"/>', None),
    "headphones": ("Profile picture with headphones", "#233a5e", "#a78bfa",
                   '<path d="M45 33C44 17 67 15 66 31" fill="none" stroke="{acc}" stroke-width="3.2" stroke-linecap="round"/>'
                   '<rect x="41.5" y="28" width="7" height="11" rx="3" fill="{acc}"/>', None),
    "camera": ("Profile picture with a camera", "#3b2a5c", "#7dd3fc",
               '<rect x="13" y="25" width="24" height="16" rx="3" fill="{acc}"/><rect x="17" y="21.5" width="7" height="4" rx="1" fill="{acc}"/>'
               '<circle cx="25" cy="33" r="5" fill="{bg}"/><circle cx="25" cy="33" r="2.2" fill="{acc}"/>', None),
    "sleepy": ("Sleepy profile picture", "#1f2a3a", "#a78bfa",
               '<path d="M65 13h8l-8 8h8M77 22h5l-5 5h5" fill="none" stroke="{acc}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
               '<path d="M24 14a8 8 0 1 0 8 11a6.5 6.5 0 0 1-8-11z" fill="{acc}"/>',
               '<path d="M53.4 30.2q2.6 2.2 5.2 0" fill="none" stroke="{ink}" stroke-width="1.8" stroke-linecap="round"/>'),
    "laptop": ("Profile picture with a laptop", "#1f3d3a", "#7dd3fc",
               '<path d="M60 63h22v14H60z" fill="{acc}"/><path d="M63 66h16v8H63z" fill="{bg}" opacity=".55"/>'
               '<path d="M56 79.5h30" stroke="{acc}" stroke-width="3" stroke-linecap="round"/>', None),
    "plant": ("Profile picture with a plant", "#24402a", "#86efac",
              '<path d="M66 72h15l-2 11h-11z" fill="#e08a5a"/><path d="M73.5 72V60M73.5 66c-5-1-7-5-6-8c4 0 6 3 6 8zM73.5 63c4-2 7-5 6-9c-4 1-6 4-6 9z" '
              'fill="{acc}" stroke="{acc}" stroke-width="1.6" stroke-linejoin="round"/>', None),
    "robot": ("Robot profile picture", "#2e3440", "#f472b6",
              '<path d="M54 22V12" stroke="{ink}" stroke-width="2.4" stroke-linecap="round"/><circle cx="54" cy="10" r="3.2" fill="{acc}"/>',
              '<rect x="53.6" y="28" width="4.8" height="4.8" fill="{acc}"/>'),
    "shades": ("Profile picture with sunglasses", "#5a2e2a", "#fca5a5",
               '<path d="M47.5 30.6h3" stroke="{ink}" stroke-width="1.8" stroke-linecap="round"/>'
               '<rect x="50" y="27" width="12.5" height="7.4" rx="3" fill="#0f1012" stroke="{ink}" stroke-width="1.6"/>'
               '<path d="M52.6 29.5h3" stroke="{acc}" stroke-width="1.4" stroke-linecap="round" opacity=".9"/>', ""),
    "party": ("Profile picture with a party hat", "#4b2350", "#f472b6",
              '<path d="M46 24L60 22L51 5z" fill="{acc}"/><path d="M48.5 17.5L55.5 16.5M47.5 21L58 19.8" stroke="{bg}" stroke-width="1.6" opacity=".55"/>'
              '<circle cx="51" cy="5" r="3" fill="#f2c46d"/><circle cx="22" cy="20" r="2" fill="#f2c46d"/><circle cx="76" cy="14" r="1.8" fill="#7dd3fc"/>'
              '<circle cx="80" cy="66" r="2" fill="{acc}"/><circle cx="18" cy="44" r="1.6" fill="#86efac"/>', None),
    "glasses": ("Profile picture with reading glasses", "#3d3a24", "#f2c46d",
                '<circle cx="56" cy="30.4" r="5.2" fill="none" stroke="{acc}" stroke-width="2"/><path d="M50.8 30h-4" stroke="{acc}" stroke-width="2" stroke-linecap="round"/>', None),
}


def svg(key):
    label, bg, acc, extra, eye = PRESETS[key]
    eye = EYE if eye is None else eye
    body = (f'<rect width="96" height="96" fill="{bg}"/>' + HERON + eye + extra).replace("{ink}", INK).replace("{acc}", acc).replace("{bg}", bg)
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
