#!/usr/bin/env python3
"""2.136.0 (#2193): the Kalmido icon set, the bot figure (replaces the heron of 2.18.0, #394).

One source of truth for every icon file: a soft rounded body with two eyes (a line and a dot) and an antenna; the app
icon is white on the violet plate (#6d4bd8, the app accent) with a dark antenna. The paths come 1:1 from the final design
files (kalmido-bot.zip, 18.10.2026). This script writes the SVGs and renders all PNGs from them with
rsvg-convert + ImageMagick (metadata and time chunks stripped), so the same drawing gives byte-identical files:

  static/icon.svg               app icon, 100 x 100 grid, rounded violet plate (also the "Kalmido" list-icon preset)
  static/icon-light.svg         light variant (light plate, dark figure, violet antenna)
  static/logo-white.svg         the figure alone in white on transparent (eyes cut out), violet antenna
  static/icon-192.png / -512    manifest icons, purpose "any" (rounded plate, transparent corners)
  static/icon-maskable-512.png  manifest icon, purpose "maskable": plate full-bleed, figure inside the inner 80 % circle
  static/apple-touch-icon.png   180 px, square and opaque (iOS rounds the corners itself; design file icon-ios-180)
  static/favicon.svg            browser tab: the figure a little larger with thicker eyes, reads at 16 px
  static/favicon-16.png / -32   PNG fallbacks (both from the favicon drawing)
  static/badge-96.png           push badge (Android): the silhouette in one colour (white) on transparent, eyes cut out
  static/shortcuts/*-96/-192    long-press shortcut icons: the app's line icon in the icon's colours
  --site DIR                    also the website assets: icon.svg, icon-192/512.png, apple-touch-icon.png,
                                favicon.svg, favicon-32.png, kalmido-logo.svg / kalmido-logo-light.svg (icon + word mark)

The word mark is the outlined path of the design file (wortmarke-*.svg), so the lockup does not depend on fonts.

usage: python3 tools/make_icons.py [--site ~/kalmido-site] [--check]
       --check: render into a temp dir and compare with the files on disk (exit 1 when anything differs)
"""
import argparse
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLATE, WHITE, INK = "#6d4bd8", "#FFFFFF", "#18171D"   # violet plate, the figure, the antenna on the plate
LIGHT_PLATE, LIGHT_BODY = "#F1F0F5", "#2B2A31"         # light variant
ANT_DARK = "#a78bfa"                                   # antenna on dark plates (lockups), the accent of the dark theme
WORD_INK, WORD_LIGHT = "#18171D", "#EEEDF3"            # word mark on light / on dark backgrounds

# the figure on the 100 x 100 grid (design file): body, eyes (a line and a dot), antenna
BODY = "M50 22C74 22 78 26 78 50S74 78 50 78 22 74 22 50 26 22 50 22Z"
EYES = ("M41 44V56", "M59 50V50.1")
ANTENNA = "M58 6V15"
CAP = 'stroke-linecap="round" stroke-linejoin="round"'

# word mark "Kalmido" (design file wortmarke-*.svg), baseline y = 0, viewBox -1 -78 371.8 81
WORD = (
    "M7.3 -70H19.2V-40.4H23L48.9 -70H63.7L33.7 -35.5L64.2 0H48.8L22.9 -30.5H19.2V0H7.3ZM99 0 98 -6.1Q95.6 -2.9 92.3"
    " -1.2Q89 0.5 83.5 0.5Q78.3 0.5 74.5 -1.25Q70.7 -3 68.65 -6.15Q66.6 -9.3 66.6 -13.5Q66.6 -19.8 71.25 -24.05Q75."
    "9 -28.3 84.9 -29.3L98 -30.7V-34.6Q98 -37 95.9 -38.95Q93.8 -40.9 89.2 -40.9Q85.2 -40.9 82.25 -38.95Q79.3 -37 78"
    ".3 -33.1L68.5 -36.7Q70.4 -43.3 76.05 -47Q81.7 -50.7 89.8 -50.7Q99.6 -50.7 104.5 -45.8Q109.4 -40.9 109.4 -33.3V"
    "0ZM98 -22 86 -20.5Q82.2 -20 80.3 -18.35Q78.4 -16.7 78.4 -14.2Q78.4 -11.9 80.25 -10.25Q82.1 -8.6 85.3 -8.6Q89.4"
    " -8.6 92.25 -10.1Q95.1 -11.6 96.55 -14.4Q98 -17.2 98 -21.3ZM120.9 -72H132.2V0H120.9ZM144.4 -50H154.6L155.4 -45"
    ".3Q157.9 -47.8 161.3 -49.25Q164.7 -50.7 168.7 -50.7Q173.7 -50.7 177.7 -48.65Q181.7 -46.6 184.2 -42.7Q186.8 -46"
    ".6 191.3 -48.65Q195.8 -50.7 201 -50.7Q206.9 -50.7 211.25 -48.25Q215.6 -45.8 218 -41.05Q220.4 -36.3 220.4 -29.2"
    "V0H209V-27.7Q209 -34 206.35 -37.2Q203.7 -40.4 198.6 -40.4Q193.4 -40.4 190.5 -37.15Q187.6 -33.9 187.6 -27.5V0H1"
    "76.3V-27.7Q176.3 -34 173.85 -37.2Q171.4 -40.4 166.3 -40.4Q161.1 -40.4 158.4 -37.15Q155.7 -33.9 155.7 -27.6V0H1"
    "44.4ZM233.5 -50H244.8V0H233.5ZM239.2 -57.6Q236.1 -57.6 234 -59.7Q231.9 -61.8 231.9 -64.7Q231.9 -67.8 234 -69.9"
    "Q236.1 -72 239.2 -72Q242.2 -72 244.3 -69.9Q246.4 -67.8 246.4 -64.7Q246.4 -61.8 244.3 -59.7Q242.2 -57.6 239.2 -"
    "57.6ZM295.5 -42.6 294.2 -42.3V-72H305.5V0H295.3L294.5 -6.2Q291.9 -3.3 287.9 -1.3Q283.9 0.7 278.4 0.7Q271.7 0.7"
    " 266.65 -2.5Q261.6 -5.7 258.8 -11.5Q256 -17.3 256 -25Q256 -32.7 258.8 -38.5Q261.6 -44.3 266.65 -47.5Q271.7 -50"
    ".7 278.4 -50.7Q284.3 -50.7 288.7 -48.35Q293.1 -46 295.5 -42.6ZM268.1 -25Q268.1 -18.1 271.7 -13.8Q275.3 -9.5 28"
    "1.1 -9.5Q284.6 -9.5 287.55 -11.3Q290.5 -13.1 292.35 -16.55Q294.2 -20 294.2 -25Q294.2 -30 292.35 -33.45Q290.5 -"
    "36.9 287.55 -38.7Q284.6 -40.5 281.1 -40.5Q275.3 -40.5 271.7 -36.2Q268.1 -31.9 268.1 -25ZM340.1 0.7Q332.9 0.7 3"
    "27.2 -2.45Q321.5 -5.6 318.3 -11.35Q315.1 -17.1 315.1 -24.9Q315.1 -32.8 318.4 -38.6Q321.7 -44.4 327.5 -47.55Q33"
    "3.3 -50.7 340.4 -50.7Q347.6 -50.7 353.35 -47.55Q359.1 -44.4 362.5 -38.65Q365.9 -32.9 365.9 -25.1Q365.9 -17.2 3"
    "62.45 -11.4Q359 -5.6 353.15 -2.45Q347.3 0.7 340.1 0.7ZM340 -9.4Q343.5 -9.4 346.65 -11.1Q349.8 -12.8 351.8 -16."
    "25Q353.8 -19.7 353.8 -25.1Q353.8 -30.3 351.9 -33.75Q350 -37.2 346.9 -38.9Q343.8 -40.6 340.2 -40.6Q336.7 -40.6 "
    "333.75 -38.9Q330.8 -37.2 329 -33.75Q327.2 -30.3 327.2 -24.9Q327.2 -19.7 328.95 -16.25Q330.7 -12.8 333.6 -11.1Q"
    "336.5 -9.4 340 -9.4Z")


def bot(body=WHITE, eye=PLATE, ant=INK, scale=0.9, bold=0.0, cid=None):
    """The figure, centred like in the design files. bold thickens eyes and antenna (favicon). cid: eyes cut out of the
    body through a mask instead of painted (logo on transparent, push badge)."""
    eyes = (f'<path d="{EYES[0]}" fill="none" stroke="{{c}}" stroke-width="{6.5 + bold:g}" {CAP}/>'
            f'<path d="{EYES[1]}" fill="none" stroke="{{c}}" stroke-width="{8.5 + bold:g}" {CAP}/>')
    if cid:
        head = (f'<mask id="{cid}"><rect x="-50" y="-50" width="200" height="200" fill="#fff"/>{eyes.format(c="#000")}</mask>'
                f'<path d="{BODY}" fill="{body}" mask="url(#{cid})"/>')
    else:
        head = f'<path d="{BODY}" fill="{body}"/>' + eyes.format(c=eye)
    return (f'<g transform="translate(50 50) scale({scale:g}) translate(-50 -40)">{head}'
            f'<path d="{ANTENNA}" stroke="{ant}" stroke-width="{7 + bold:g}" stroke-linecap="round"/></g>')


def svg(inner, w=100, h=100, label=None):
    a11y = f' role="img" aria-label="{label}"' if label else ' aria-hidden="true"'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:g} {h:g}" width="{w:g}" height="{h:g}"{a11y}>{inner}</svg>\n'


def plate(fill=PLATE, rx=22.5):
    return f'<rect width="100" height="100"{f" rx={chr(34)}{rx:g}{chr(34)}" if rx else ""} fill="{fill}"/>'


ICON = svg(plate() + bot(), label="Kalmido")
ICON_LIGHT = svg(plate(LIGHT_PLATE) + bot(LIGHT_BODY, LIGHT_PLATE, PLATE), label="Kalmido")
LOGO_WHITE = svg(bot(WHITE, ant=ANT_DARK, cid="e"), label="Kalmido")
# maskable: the safe zone is the circle of radius 40 around the centre; the design file scales the figure to .84
MASKABLE = svg(plate(rx=0) + bot(scale=0.84))
APPLE = svg(plate(rx=0) + bot())
FAVICON = svg(plate() + bot(scale=1.08, bold=1), label="Kalmido")
# push badge: Android shows only the alpha channel, so one colour, eyes cut out, a little larger with thick strokes
BADGE = svg(bot(WHITE, ant=WHITE, scale=1.05, bold=1.5, cid="b"))

# shortcut icons: the app's "Punkt" line icons (20 x 20 grid, see P in static/app.js) in the icon's colours
SHORTCUTS = {
    "new": ("M10 4V16M4 10H16", []),
    "capture": ("M11 3L5.5 11H10.5L9 17", [(15.5, 6, 2)]),
    "today": ("M13.5 10A3.5 3.5 0 1 1 6.5 10A3.5 3.5 0 0 1 13.5 10M10 2.5V4.3M10 15.7V17.5M2.5 10H4.3M15.7 10H17.5"
              "M4.7 4.7L5.9 5.9M14.1 14.1L15.3 15.3M4.7 15.3L5.9 14.1M14.1 5.9L15.3 4.7", [(10, 10, 1.5)]),
    "news": ("M5 14V9A5 5 0 0 1 15 9V14M3 14H17", [(10, 17.5, 2)]),
    "search": ("M14 9A5 5 0 1 1 4 9A5 5 0 0 1 14 9M13 13L17 17", [(9, 9, 2)]),
}


def shortcut(key):
    d, dots = SHORTCUTS[key]
    return svg(plate() + '<g transform="translate(28 28) scale(2.2)">'
               f'<path d="{d}" fill="none" stroke="{WHITE}" stroke-width="1.6" {CAP}/>'
               + "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{INK}"/>' for x, y, r in dots) + '</g>')


def lockup(text_fill):
    """Icon + word mark for the website, like the design file lockup-waagerecht-*: the dark plate with the light
    antenna, the word mark in the text colour of the background (WORD_INK on light, WORD_LIGHT on dark)."""
    return svg(f'<g transform="scale(1.12)">{plate(INK)}{bot(WHITE, INK, ANT_DARK)}</g>'
               f'<path transform="translate(146 91)" fill="{text_fill}" d="{"".join(WORD)}"/>', 517.8, 112, label="Kalmido")


STRIP = ["-strip", "-define", "png:exclude-chunks=date,time"]


def render(src_svg, size, out, tmp, extra=()):
    """SVG text -> PNG of size x size: rsvg-convert renders, ImageMagick normalises (no metadata, fixed colour type)."""
    sp, rp = os.path.join(tmp, "in.svg"), os.path.join(tmp, "raw.png")
    with open(sp, "w", encoding="utf-8") as f:
        f.write(src_svg)
    subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), sp, "-o", rp], check=True)
    subprocess.run(["magick", rp, *extra, *STRIP, out], check=True)
    # the same pass kalmido-export.sh runs over static/*.png: after it the file is a fixed point, so the export copies
    # the bytes unchanged and `--check` also holds in the public repo
    subprocess.run(["magick", "mogrify", *STRIP, out], check=True)


OPAQUE = ["-background", PLATE, "-alpha", "remove", "-alpha", "off", "-define", "png:color-type=2"]
# white silhouette on transparent as grey + alpha (colour type 4): every visible pixel pure white, only alpha varies
ONECOLOUR = ["-channel", "RGB", "-evaluate", "set", "100%", "+channel", "-colorspace", "Gray", "-define", "png:color-type=4"]
RGBA = []   # ImageMagick picks the smallest lossless PNG type (palette where it fits)


def build(static, site, tmp):
    """Writes everything below static/ (and site/assets when given). Returns the written paths."""
    out = []

    def text(path, body):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        out.append(path)

    def png(src, size, path, extra=RGBA):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        render(src, size, path, tmp, extra)
        out.append(path)

    text(os.path.join(static, "icon.svg"), ICON)
    text(os.path.join(static, "favicon.svg"), FAVICON)
    text(os.path.join(static, "icon-light.svg"), ICON_LIGHT)
    text(os.path.join(static, "logo-white.svg"), LOGO_WHITE)
    png(ICON, 192, os.path.join(static, "icon-192.png"))
    png(ICON, 512, os.path.join(static, "icon-512.png"))
    png(MASKABLE, 512, os.path.join(static, "icon-maskable-512.png"), OPAQUE)
    png(APPLE, 180, os.path.join(static, "apple-touch-icon.png"), OPAQUE)
    png(FAVICON, 16, os.path.join(static, "favicon-16.png"))
    png(FAVICON, 32, os.path.join(static, "favicon-32.png"))
    png(BADGE, 96, os.path.join(static, "badge-96.png"), ONECOLOUR)
    for k in SHORTCUTS:
        for z in (96, 192):
            png(shortcut(k), z, os.path.join(static, "shortcuts", f"{k}-{z}.png"))
    if site:
        a = os.path.join(site, "assets")
        text(os.path.join(a, "icon.svg"), ICON)
        text(os.path.join(a, "favicon.svg"), FAVICON)
        text(os.path.join(a, "kalmido-logo.svg"), lockup(WORD_LIGHT))
        text(os.path.join(a, "kalmido-logo-light.svg"), lockup(WORD_INK))
        png(ICON, 192, os.path.join(a, "icon-192.png"))
        png(ICON, 512, os.path.join(a, "icon-512.png"))
        png(APPLE, 180, os.path.join(a, "apple-touch-icon.png"), OPAQUE)
        png(FAVICON, 32, os.path.join(a, "favicon-32.png"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", help="website checkout (writes <site>/assets/...)")
    ap.add_argument("--check", action="store_true", help="compare a fresh render with the files on disk")
    a = ap.parse_args()
    for tool in ("rsvg-convert", "magick"):
        if not shutil.which(tool):
            sys.exit(f"{tool} is missing")
    static = os.path.join(ROOT, "static")
    site = os.path.expanduser(a.site) if a.site else None
    with tempfile.TemporaryDirectory() as tmp:
        if not a.check:
            for p in build(static, site, tmp):
                print(os.path.relpath(p, ROOT) if p.startswith(ROOT) else p)
            return 0
        fresh = os.path.join(tmp, "fresh")
        ref = build(os.path.join(fresh, "static"), os.path.join(fresh, "site") if site else None, tmp)
        bad = []
        for p in ref:
            rel = os.path.relpath(p, fresh)
            disk = os.path.join(static, rel[len("static/"):]) if rel.startswith("static/") else os.path.join(site, rel[len("site/"):])
            if not os.path.exists(disk) or not filecmp.cmp(p, disk, shallow=False):
                bad.append(disk)
        for b in bad:
            print("differs:", b)
        print(f"{len(ref) - len(bad)}/{len(ref)} identical")
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
