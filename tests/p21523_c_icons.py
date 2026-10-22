#!/usr/bin/env python3
"""2.152.3 (#2667) app icon on the dark macOS 26 tile: the antenna is no longer black, the eyes are painted violet.
Static file checks, no browser, no container. usage: python3 tests/p21523_c_icons.py [ignored]
KALMIDO_SRC_ROOT=<dir> checks another checkout (default: repo)"""
import json
import os
import re
import sys

from PIL import Image

ROOT = os.environ.get("KALMIDO_SRC_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ST = os.path.join(ROOT, "static")
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what)


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def dark(col):
    r, g, b = (int(col[i:i + 2], 16) for i in (1, 3, 5))
    return (r * 299 + g * 587 + b * 114) / 1000 < 90


ANT = re.compile(r'<path d="M58 6V15"[^>]*stroke="(#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3})"')
for n in ("icon.svg", "favicon.svg"):
    s = read("static", n)
    m = ANT.search(s)
    check(m and not dark(m.group(1) if len(m.group(1)) == 7 else "#" + "".join(c * 2 for c in m.group(1)[1:])),
          f"{n}: the antenna is light, not black")
    check(s.count('stroke="#6d4bd8"') == 2, f"{n}: both eyes are painted in the accent #6d4bd8")
    check("18171D" not in s, f"{n}: no black left")
for n in ("static/js/icons.js", "static/index.html"):
    s = read(*n.split("/"))
    check(not re.search(r'M58 6V15" stroke="#18171D"', s), f"{n}: no black antenna in the small logo")

man = json.loads(read("static", "manifest.json"))
for i in man["icons"]:
    p = os.path.join(ROOT, i["src"].lstrip("/"))
    check(os.path.exists(p), f"manifest: {i['src']} exists")
    if os.path.exists(p):
        im = Image.open(p)
        check(f"{im.width}x{im.height}" == i["sizes"], f"manifest: {i['src']} is {i['sizes']}")
        # antenna on the grid: x 57, y 10..24 (scale .9; .84 maskable): some pixel of that strip is light
        rgb = im.convert("RGBA")
        z = im.width
        strip = [rgb.getpixel((x, y)) for x in range(int(z * 0.55), int(z * 0.59)) for y in range(int(z * 0.15), int(z * 0.27))]
        check(any(q[3] > 200 and sum(q[:3]) > 700 for q in strip), f"{i['src']}: a light antenna sits above the head")
for n, z in (("apple-touch-icon.png", 180), ("favicon-32.png", 32), ("favicon-16.png", 16), ("apple-touch-icon-1024.png", 1024)):
    check(os.path.exists(os.path.join(ST, n)) and Image.open(os.path.join(ST, n)).size == (z, z), f"{n}: {z} px")
print(f"p21523_c_icons: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
