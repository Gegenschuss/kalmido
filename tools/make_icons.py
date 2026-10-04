#!/usr/bin/env python3
"""2.18.0 (#394): the Kalmido icon set, direction B "Auf einem Bein" (on one leg).

One source of truth for every icon file: the heron stands on one leg in the water, the violet sun sits half on the
water line (clipped), light lines on the dark plate. This script writes the SVGs and renders all PNGs from them with
rsvg-convert + ImageMagick (metadata and time chunks stripped), so the same drawing gives byte-identical files:

  static/icon.svg               app icon, 100 x 100 grid, rounded plate (also the "Kalmido" list-icon preset)
  static/icon-192.png / -512    manifest icons, purpose "any" (rounded plate, transparent corners)
  static/icon-maskable-512.png  manifest icon, purpose "maskable": plate full-bleed, heron inside the inner 80 % circle
  static/apple-touch-icon.png   180 px, square and opaque (iOS rounds the corners itself)
  static/favicon.svg            browser tab: SIMPLIFIED drawing (no leg / knee, thick lines) that still reads at 16 px
  static/favicon-16.png / -32   PNG fallbacks (16 = simplified, 32 = the full drawing)
  static/badge-96.png           push badge: one colour (white) on transparent, grey + alpha PNG, no sun / water
  static/shortcuts/*-96/-192    long-press shortcut icons: the app's line icon in the icon's colours
  --site DIR                    also the website assets: icon.svg, icon-192/512.png, apple-touch-icon.png,
                                favicon.svg, favicon-32.png, kalmido-logo.svg / kalmido-logo-light.svg (icon + word mark)

The word mark is Geist SemiBold (600, the sidebar weight, letter spacing -0.02em) converted to outlines once (fontTools
instancer + SVGPathPen from static/fonts/Geist-Variable.woff2), so the lockup does not depend on installed fonts.

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
PLATE, LINE, SUN = "#161a21", "#e9e6f2", "#8b6cf0"   # the plate, the heron's lines, the sun
INK = "#17151f"                                       # word mark on light backgrounds

# Geist 600, "Kalmido", 1000 units per em, baseline y = 0 (y grows downwards), advance -20 units per letter
WORD_W = 3775
WORD = (
    "M80 0V-710H210V-385.8L488.2 -710H642.4L376 -398.4L659.4 0H509.6L290 -309.2L210 -218.2V0Z M876.6 12Q793.4 12 "
    "742.3 -26.4Q691.2 -64.8 691.2 -133.6Q691.2 -203.2 734.2 -242Q777.2 -280.8 864.6 -298L1042.2 -332.6Q1042.2 "
    "-389.6 1016.1 -418.2Q990 -446.8 939.4 -446.8Q892.8 -446.8 866.2 -425.5Q839.6 -404.2 830.4 -363.8L700.2 "
    "-370.4Q715.6 -454.6 777.7 -500.3Q839.8 -546 939.4 -546Q1053.4 -546 1111.8 -488.7Q1170.2 -431.4 1170.2 "
    "-324.4V-129.8Q1170.2 -108.6 1177.5 -100.9Q1184.8 -93.2 1199.8 -93.2H1216.8V0Q1210.8 1.8 1197.4 3.1Q1184 4.4 "
    "1170.4 4.4Q1137.2 4.4 1111.3 -6.5Q1085.4 -17.4 1071 -43.5Q1056.6 -69.6 1056.6 -115.6L1068.2 -108Q1059.6 "
    "-72.8 1033.4 -45.5Q1007.2 -18.2 967 -3.1Q926.8 12 876.6 12ZM903 -81.2Q945.6 -81.2 976.7 -97.9Q1007.8 -114.6 "
    "1025 -144.9Q1042.2 -175.2 1042.2 -215.6V-245.6L903.8 -217.6Q861.4 -209.2 842.5 -191.5Q823.6 -173.8 823.6 "
    "-145.6Q823.6 -115 844.3 -98.1Q865 -81.2 903 -81.2Z M1410.4 0Q1351.6 0 1317 -30Q1282.4 -60 1282.4 "
    "-126.4V-710H1410.4V-139.4Q1410.4 -118.6 1420.7 -108.9Q1431 -99.2 1450.2 -99.2H1489.4V0Z M1559.4 "
    "0V-534H1675.2L1679.4 -403.2L1666.6 -408.8Q1676.4 -452 1698.9 -482.5Q1721.4 -513 1753.8 -529.5Q1786.2 -546 "
    "1825 -546Q1892.8 -546 1934.9 -507.4Q1977 -468.8 1988.4 -402L1970.8 -401.8Q1979.6 -448.6 2001.7 -480.5Q2023.8 "
    "-512.4 2057.2 -529.2Q2090.6 -546 2132.6 -546Q2188.4 -546 2228.2 -522.7Q2268 -499.4 2289.4 -454.2Q2310.8 -409 "
    "2310.8 -343.4V0H2182.8V-309.8Q2182.8 -375.8 2160.6 -408.9Q2138.4 -442 2091.8 -442Q2061.2 -442 2039.3 "
    "-426Q2017.4 -410 2005.6 -379.7Q1993.8 -349.4 1993.8 -306.2V0H1875.4V-306.2Q1875.4 -371.6 1855.2 -406.8Q1835 "
    "-442 1786 -442Q1755.4 -442 1733.5 -426Q1711.6 -410 1699.5 -379.4Q1687.4 -348.8 1687.4 -306.2V0Z M2431.4 "
    "0V-534H2559.4V0ZM2429 -605.4V-718.6H2561.8V-605.4Z M2870.4 12Q2802.2 12 2752.5 -22.2Q2702.8 -56.4 2676 "
    "-119Q2649.2 -181.6 2649.2 -267Q2649.2 -352.4 2676.2 -415Q2703.2 -477.6 2753.1 -511.8Q2803 -546 2870.4 "
    "-546Q2926.2 -546 2968.6 -522.9Q3011 -499.8 3032.6 -458.4V-710H3160.6V0H3039.4L3036.4 -79.2Q3014.4 -36.2 "
    "2970.4 -12.1Q2926.4 12 2870.4 12ZM2909 -91.6Q2948.8 -91.6 2976.3 -112Q3003.8 -132.4 3018.2 -171.7Q3032.6 "
    "-211 3032.6 -267Q3032.6 -324.2 3018.2 -363.2Q3003.8 -402.2 2976.3 -422.3Q2948.8 -442.4 2909 -442.4Q2850.6 "
    "-442.4 2816.1 -395.5Q2781.6 -348.6 2781.6 -267Q2781.6 -186.8 2816.3 -139.2Q2851 -91.6 2909 -91.6Z M3512.8 "
    "12Q3433.8 12 3374.6 -22.4Q3315.4 -56.8 3282.8 -119.7Q3250.2 -182.6 3250.2 -267Q3250.2 -352 3282.8 "
    "-414.4Q3315.4 -476.8 3374.6 -511.4Q3433.8 -546 3512.8 -546Q3591.8 -546 3650.7 -511.4Q3709.6 -476.8 3742.2 "
    "-414.4Q3774.8 -352 3774.8 -267Q3774.8 -182.6 3742.2 -119.7Q3709.6 -56.8 3650.7 -22.4Q3591.8 12 3512.8 "
    "12ZM3512.8 -91.6Q3574.6 -91.6 3608.5 -137.9Q3642.4 -184.2 3642.4 -267Q3642.4 -349.4 3608.5 -395.9Q3574.6 "
    "-442.4 3512.8 -442.4Q3451 -442.4 3416.8 -395.9Q3382.6 -349.4 3382.6 -267Q3382.6 -184.2 3416.8 -137.9Q3451 "
    "-91.6 3512.8 -91.6Z")


def heron(fg=LINE, sun=SUN, cid="w"):
    """Direction B on the 100 x 100 grid (paths exactly as in the chosen design)."""
    return (f'<clipPath id="{cid}"><rect width="100" height="74"/></clipPath>'
            f'<circle cx="76" cy="74" r="11" fill="{sun}" clip-path="url(#{cid})"/>'
            f'<path d="M18 74H86" stroke="{fg}" stroke-width="3" stroke-linecap="round" opacity=".55"/>'
            f'<g fill="none" stroke="{fg}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M24 50C34 42 52 43 62 51C55 58 40 60 30 55"/>'
            '<path d="M54 48C51 39 49 32 51 25C53 20 58 19 61 22"/>'
            '<path d="M61 22L77 26"/>'
            '<path d="M44 58V84"/>'
            '<path d="M44 68L37 64L41 60" stroke-width="4"/></g>')


def heron_small(fg=LINE, sun=SUN, cid="w"):
    """16 px favicon: plate + body / neck / beak + sun on the horizon, thick lines, no leg, knee or water line; drawn
    a little larger so it fills the tab icon."""
    return (f'<g transform="translate(50 50) scale(1.14) translate(-53 -47)">'
            f'<clipPath id="{cid}"><rect width="100" height="74"/></clipPath>'
            f'<circle cx="76" cy="74" r="13" fill="{sun}" clip-path="url(#{cid})"/>'
            f'<g fill="none" stroke="{fg}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M24 50C34 42 52 43 62 51C55 58 40 60 30 55"/>'
            '<path d="M54 48C51 39 49 32 51 25C53 20 58 19 61 22L77 26"/></g></g>')


def badge(fg="#ffffff"):
    """Push badge: the silhouette only (body, neck + beak, leg), thick lines, one colour."""
    return (f'<g fill="none" stroke="{fg}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M24 50C34 42 52 43 62 51C55 58 40 60 30 55"/>'
            '<path d="M54 48C51 39 49 32 51 25C53 20 58 19 61 22L77 26"/>'
            '<path d="M44 58V86"/></g>')


def svg(inner, w=100, h=100, label=None):
    a11y = f' role="img" aria-label="{label}"' if label else ' aria-hidden="true"'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}"{a11y}>{inner}</svg>\n'


ROUND = f'<rect width="100" height="100" rx="22" fill="{PLATE}"/>'
SQUARE = f'<rect width="100" height="100" fill="{PLATE}"/>'
ICON = svg(ROUND + heron(), label="Kalmido")
# maskable: the safe zone is the circle of radius 40 around the centre; scaled to .84 around the drawing's centre
# (52, 52) the farthest point (the right end of the water line) stays at a radius of about 35
MASKABLE = svg(SQUARE + f'<g transform="translate(50 50) scale(.84) translate(-52 -52)">{heron()}</g>')
APPLE = svg(SQUARE + heron())
FAVICON = svg(ROUND + heron_small(), label="Kalmido")
BADGE = svg(badge())

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
    return svg(ROUND + '<g transform="translate(28 28) scale(2.2)">'
               f'<path d="{d}" fill="none" stroke="{LINE}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
               + "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{SUN}"/>' for x, y, r in dots) + '</g>')


def lockup(text_fill):
    """Icon + word mark for the website (100 high): cap height 46 = font size 64.8, baseline at 73, gap 20 + side bearing."""
    s = 0.0648
    w = round(100 + 20 + WORD_W * s + 4)  # 4 units of air after the "o"
    return svg(ROUND + heron() + f'<path transform="translate(120 73) scale({s})" fill="{text_fill}" d="{"".join(WORD)}"/>',
               w, 100, label="Kalmido")


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
    png(ICON, 192, os.path.join(static, "icon-192.png"))
    png(ICON, 512, os.path.join(static, "icon-512.png"))
    png(MASKABLE, 512, os.path.join(static, "icon-maskable-512.png"), OPAQUE)
    png(APPLE, 180, os.path.join(static, "apple-touch-icon.png"), OPAQUE)
    png(FAVICON, 16, os.path.join(static, "favicon-16.png"))
    png(ICON, 32, os.path.join(static, "favicon-32.png"))
    png(BADGE, 96, os.path.join(static, "badge-96.png"), ONECOLOUR)
    for k in SHORTCUTS:
        for z in (96, 192):
            png(shortcut(k), z, os.path.join(static, "shortcuts", f"{k}-{z}.png"))
    if site:
        a = os.path.join(site, "assets")
        text(os.path.join(a, "icon.svg"), ICON)
        text(os.path.join(a, "favicon.svg"), FAVICON)
        text(os.path.join(a, "kalmido-logo.svg"), lockup(LINE))
        text(os.path.join(a, "kalmido-logo-light.svg"), lockup(INK))
        png(ICON, 192, os.path.join(a, "icon-192.png"))
        png(ICON, 512, os.path.join(a, "icon-512.png"))
        png(APPLE, 180, os.path.join(a, "apple-touch-icon.png"), OPAQUE)
        png(ICON, 32, os.path.join(a, "favicon-32.png"))
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
