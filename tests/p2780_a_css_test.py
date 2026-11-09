#!/usr/bin/env python3
# kalmido-suite: after=perf_budget nodata
"""2.780.0 part A (#5388): no --accent-ink text on the pale --accent-soft ground. Static, no container:
 - tools/check_appcss.py: the tree is clean; a rule with background:var(--accent-soft) and color:var(--accent-ink) = exit 1
   (also written background-color / split over lines / in an inline style of a script); the full accent with its ink stays fine
 - the tag pills and chips (tagsel.css .tsp.tsp-in .tsfx .tflb, app.css .rt9dup .sptm, playbook.css .pbcur) have a text colour
   that reads on the tinted ground (>= 4.5:1) in light and dark, with the default accent and with workspace accents
usage: python3 tests/p2780_a_css_test.py"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402


def rd(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def lint(root=ROOT):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_appcss.py"), "--root", root], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


rc, out = lint()
check(rc == 0, "the tree passes check_appcss: " + out)

with tempfile.TemporaryDirectory() as tmp:
    root = os.path.join(tmp, "tree")
    shutil.copytree(os.path.join(ROOT, "static"), os.path.join(root, "static"),
                    ignore=shutil.ignore_patterns("fonts", "*.png", "*.svg", "*.woff2", "i18n", "vendor"))
    css = os.path.join(root, "static", "css", "p2780-probe.css")

    def probe(text):
        with open(css, "w", encoding="utf-8") as f:
            f.write(text)
        return lint(root)

    rc, out = probe(".x{background:var(--accent-soft);color:var(--accent-ink)}\n")
    check(rc == 1 and "--accent-soft" in out and "p2780-probe.css" in out, "ink on soft: exit 1, the message names the file: " + out)
    rc, out = probe(".x{\n  background-color: var(--accent-soft);\n  color: var(--accent-ink);\n}\n")
    check(rc == 1, "background-color and a rule over several lines: exit 1: " + out)
    rc, out = probe(".x{background:var(--accent);color:var(--accent-ink)}\n.y{background:var(--accent-soft);color:var(--text)}\n.z{background:var(--accent-soft);border-color:var(--accent-ink)}\n")
    check(rc == 0, "full accent with ink, soft with text, a border in ink: stays fine: " + out)
    os.remove(css)
    js = os.path.join(root, "static", "js", "p2780-probe.js")
    with open(js, "w", encoding="utf-8") as f:
        f.write("el.style.cssText = 'background:var(--accent-soft);color:var(--accent-ink)';\n")
    rc, out = lint(root)
    check(rc == 1 and "p2780-probe.js" in out, "an inline style in a script: exit 1: " + out)


# ---- contrast of the fixed places
def lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(rgb):
    r, g, b = (lin(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def hx(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(acc, bg):  # --accent-soft = color-mix(in srgb, accent 9%, bg)
    return tuple(round(0.09 * a + 0.91 * b) for a, b in zip(acc, bg))


app = rd("static", "app.css")
dark = {k: re.search(rf"--{k}:(#[0-9a-fA-F]{{6}})", app).group(1) for k in ("bg", "text", "acc-d", "acc-l")}
lt = re.search(r':root\[data-theme="light"\]\{([^}]*)\}', app).group(1)
light = {k: re.search(rf"--{k}:(#[0-9a-fA-F]{{6}})", lt).group(1) for k in ("bg", "text")}
# default accent, and accents a workspace may bring (wscolor.js fits them to 4.5:1 for their ink: pale in dark, deep in light)
SAMPLES = {"dark": [dark["acc-d"], "#ffd54f", "#9ccc65", "#ff8a80", "#ffffff"], "light": [dark["acc-l"], "#0d47a1", "#1b5e20", "#8e24aa", "#000000"]}
THEME = {"dark": dark, "light": light}

PLACES = [("static/css/tagsel.css", r"\.tsp\.tsp-in"), ("static/css/tagsel.css", r"\.tsfx"),
          ("static/css/tagsel.css", r'\.tflb li\[aria-selected="true"\]'), ("static/app.css", r"\.rt9dup,\.rt9dupb"),
          ("static/app.css", r"\.meta \.sptm"), ("static/css/tagsel.css", r'\.tflb li\.tfnew\[aria-selected="true"\]'),
          ("static/css/playbook.css", r"\.pbcur")]
for f, sel in PLACES:
    m = re.search(r"(?m)^" + sel + r"\{([^}]*)\}", rd(*f.split("/")))
    check(bool(m), f"{f}: rule {sel} found")
    if not m:
        continue
    body = m.group(1)
    col = re.search(r"(?<![-\w])color:var\(--(text|accent|accent-ink)\)", body).group(1)
    check(col != "accent-ink", f"{sel}: the text is not --accent-ink ({col})")
    soft = "accent-soft" in body or sel.startswith(r"\.tflb")
    for theme in ("dark", "light"):
        t = THEME[theme]
        for acc in SAMPLES[theme]:
            bg = mix(hx(acc), hx(t["bg"])) if soft else hx(t["bg"])
            fg = hx(t["text"]) if col == "text" else hx(acc)
            r = ratio(fg, bg)
            check(col == "accent" and acc != SAMPLES[theme][0] or r >= 4.5, f"{sel} {theme} accent {acc}: contrast {r:.1f}:1 >= 4.5")

print(f"{OKS[0]} ok, {'FAILED ' + str(len(FAILS)) if FAILS else 'all ok'}")
sys.exit(1 if FAILS else 0)
