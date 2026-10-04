#!/usr/bin/env python3
"""2.18.0 (#394) the icon set "on one leg": file checks only, no container needed.
The manifest (purpose "any" and "maskable" as separate entries, sizes match the files), the PNGs (sizes, transparent
corners for "any", full-bleed + heron inside the safe circle for "maskable", an opaque Apple touch icon, the push badge
one colour on transparent as grey + alpha), the favicon links in index.html and on the public pages, the in-app logo,
the shortcut icons, no sloth left in public files, and the generator (tools/make_icons.py --check renders everything
again and compares byte for byte; skipped when rsvg-convert / ImageMagick are missing).

usage: python3 tests/p2180_icons_test.py [ignored]      KALMIDO_SRC_ROOT=<dir> checks another checkout (default: repo)"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from PIL import Image

ROOT = os.environ.get("KALMIDO_SRC_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ST = os.path.join(ROOT, "static")
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def read(*p):
    try:
        with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
            return f.read()
    except OSError:
        check(False, "/".join(p) + " exists")
        return ""


def pixels(im):
    """[(channel, ...)] per pixel (getdata() is deprecated in newer Pillow)."""
    n, b = len(im.getbands()), im.tobytes()
    return [tuple(b[i:i + n]) for i in range(0, len(b), n)]


def img(name):
    p = os.path.join(ST, name)
    if not os.path.exists(p):
        check(False, f"{name} exists")
        return None
    return Image.open(p)


# ---- manifest
man = json.loads(read("static", "manifest.json"))
icons = man.get("icons", [])
anyi = [i for i in icons if i.get("purpose") == "any"]
mask = [i for i in icons if i.get("purpose") == "maskable"]
check(all(" " not in i.get("purpose", "") for i in icons), "manifest: 'any' and 'maskable' are separate entries")
check({i["sizes"] for i in anyi} >= {"192x192", "512x512"}, "manifest: purpose any in 192 and 512")
check(len(mask) == 1 and mask[0]["sizes"] == "512x512" and mask[0]["src"] == "/static/icon-maskable-512.png",
      "manifest: one maskable 512 icon of its own file")
check(not any(i["src"] == "/static/icon-512.png" for i in mask), "manifest: the rounded icon is no longer used as maskable")
for i in icons:
    im = img(i["src"].replace("/static/", "", 1))
    if im:
        check(f"{im.width}x{im.height}" == i["sizes"] and i["type"] == "image/png", f"manifest: {i['src']} is {i['sizes']} PNG")

# ---- "any" icons: rounded plate (transparent corners), opaque centre in the plate colour
for n, z in (("icon-192.png", 192), ("icon-512.png", 512)):
    im = img(n)
    if im:
        im = im.convert("RGBA")
        check(im.size == (z, z), f"{n}: {z} px")
        check(im.getpixel((0, 0))[3] == 0 and im.getpixel((z - 1, z - 1))[3] == 0, f"{n}: transparent corners")
        check(im.getpixel((z // 10, z // 2))[:4] == (0x16, 0x1a, 0x21, 255), f"{n}: the dark plate")

# ---- maskable: full-bleed plate, everything outside the safe circle (radius 40 %) is plain plate
im = img("icon-maskable-512.png")
if im:
    im = im.convert("RGBA")
    px = im.load()
    plate = (0x16, 0x1a, 0x21, 255)
    check(px[0, 0] == plate and px[511, 511] == plate, "maskable: full-bleed, opaque corners")
    outside = [(x, y) for y in range(0, 512, 2) for x in range(0, 512, 2) if (x - 256) ** 2 + (y - 256) ** 2 > (0.4 * 512) ** 2]
    stray = [p for p in outside if px[p] != plate]
    check(not stray, f"maskable: the heron stays inside the safe circle ({len(stray)} pixels outside, e.g. {stray[:3]})")
    inside = sum(1 for y in range(0, 512, 4) for x in range(0, 512, 4) if px[x, y] != plate)
    check(inside > 300, f"maskable: the heron is there ({inside} sample pixels)")

# ---- Apple touch icon: 180, no transparency
im = img("apple-touch-icon.png")
if im:
    check(im.size == (180, 180), "apple-touch-icon: 180 px")
    check(im.mode == "RGB" or (im.mode == "RGBA" and im.getextrema()[3][0] == 255), f"apple-touch-icon: opaque ({im.mode})")

# ---- favicons
for n, z in (("favicon-16.png", 16), ("favicon-32.png", 32)):
    im = img(n)
    if im:
        check(im.size == (z, z), f"{n}: {z} px")
for n in ("favicon.svg", "icon.svg"):
    try:
        r = ET.fromstring(read("static", n))
        check(r.get("viewBox") == "0 0 100 100", f"{n}: valid SVG on the 100 grid")
    except (OSError, ET.ParseError) as e:
        check(False, f"{n}: valid SVG ({e})")
fav, ico = read("static", "favicon.svg"), read("static", "icon.svg")
check("M44 58V84" in ico and "M44 58V84" not in fav, "favicon.svg: the simplified drawing (no leg), icon.svg: the full one")
check("#8b6cf0" in ico and "#e9e6f2" in ico and "#2dd4bf" not in ico, "icon.svg: the new colours, not the old mint")

# ---- push badge: 96 x 96, grey + alpha, ONE colour (every visible pixel white), mostly transparent
im = img("badge-96.png")
if im:
    raw = open(os.path.join(ST, "badge-96.png"), "rb").read()
    check(im.size == (96, 96) and raw[25] == 4, "badge: 96 x 96 grey + alpha PNG (colour type 4)")
    la = im.convert("LA")
    vis = [(l, a) for l, a in pixels(la) if a > 0]
    check(vis and all(l == 255 for l, _ in vis), "badge: one colour (white) on transparent")
    check(0.05 < len(vis) / (96 * 96) < 0.5, f"badge: a silhouette, no plate ({len(vis)} visible pixels)")

# ---- shortcut icons
for k in ("new", "capture", "today", "news", "search"):
    for z in (96, 192):
        im = img(f"shortcuts/{k}-{z}.png")
        if im:
            rgba = im.convert("RGBA")
            check(im.size == (z, z), f"shortcut {k}-{z}: size")
            check(not any(abs(r - 0x2d) < 8 and abs(g - 0xd4) < 8 and abs(b - 0xbf) < 8 and a > 200 for r, g, b, a in pixels(rgba)),
                  f"shortcut {k}-{z}: no old mint")

# ---- links in the pages
html = read("static", "index.html")
check('<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">' in html, "index.html: SVG favicon")
check('href="/static/favicon-32.png" sizes="32x32"' in html and 'href="/static/favicon-16.png" sizes="16x16"' in html,
      "index.html: PNG favicons 32 + 16")
check('<link rel="apple-touch-icon" href="/static/apple-touch-icon.png" sizes="180x180">' in html, "index.html: Apple touch icon")
for m in re.findall(r'href="/static/([^"]+\.(?:png|svg))"', html):
    check(os.path.exists(os.path.join(ST, m)), f"index.html links an existing file: {m}")
app = read("app.py")
check('<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">' in app, "public pages (pub_html): SVG favicon")

# ---- in-app logo (sidebar, sign-in): the new mark, the sun in the accent (currentColor), no clipPath ids
js = read("static", "app.js")
m = re.search(r"const logoSvg = \(sz = 20\) => `(.*?)`;", js)
check(m and 'viewBox="0 0 100 100"' in m.group(1) and "M61 22L77 26" in m.group(1) and 'fill="currentColor"' in m.group(1)
      and " id=" not in m.group(1), "logoSvg: heron on the 100 grid, sun = currentColor, no ids")
check("M22 112 L78 168 L234 40" not in js, "app.js: the old check-mark logo is gone")
check("HERON_SWING_SVG" in js and 'class="cheron"' in js and "fetch('/static/quips.json')" in js,
      "celebration: the heron + quips.json")

# ---- no sloth in public files
WORDS = re.compile(r"sloth|faultier|paresseux|perezoso|bradipo|luiaard", re.I)
pub = ["app.py", "static/app.js", "static/app.css", "static/public.css", "static/index.html", "static/quips.json",
       "static/manifest.json"] + [os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ST, "i18n", "*.json"))
                                  + glob.glob(os.path.join(ST, "avatars", "*.svg"))]
for p in pub:
    hits = [l.strip()[:80] for l in read(p).splitlines() if WORDS.search(l)]
    check(not hits, f"no sloth in {p}: {hits[:2]}")
q = json.loads(read("static", "quips.json") or '{"en": [], "de": []}')
check(len(q["en"]) == len(q["de"]) == 50, "quips.json: 50 lines in en + de")

# ---- the generator: a fresh render is byte-identical to the files on disk
gen = os.path.join(ROOT, "tools", "make_icons.py")
if not os.path.exists(gen):
    check(False, "tools/make_icons.py exists")
elif not (shutil.which("rsvg-convert") and shutil.which("magick")):
    print("skip: generator check (rsvg-convert / magick missing)")
else:
    r = subprocess.run([sys.executable, gen, "--check"], capture_output=True, text=True, timeout=300)
    check(r.returncode == 0, "make_icons.py --check: identical bytes " + (r.stdout + r.stderr)[-300:])

print(f"p2180_icons: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
