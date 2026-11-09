#!/usr/bin/env python3
"""2.548.0 (#4511): CSS hygiene as a WARNING (exit code always 0).

  * class selectors in static/app.css and static/css/*.css that appear nowhere else in static/js, static/*.html or
    kalmido/ (Python templates and strings) = dead-class candidates. Nothing is deleted, only reported.
  * @media widths outside the convention: phone = max-width 599px (pairs with min-width 600px), tablet = max-width 767px
    (pairs with min-width 768px). Deliberate special widths are listed in SPECIAL_WIDTHS.

A class built from pieces at run time (`'k-' + type`) is not found as a whole: its prefix goes into DYNAMIC_PREFIXES.

usage: python3 tools/check_css_classes.py [-v] [--root DIR]
"""
import glob
import os
import re
import sys

CONVENTION = {"599px", "767px"}
# very small devices, short screens, wide desktops: deliberate, not to be merged into phone/tablet
SPECIAL_WIDTHS = {"560px", "480px", "479px", "420px", "400px", "399px", "360px", "320px", "30rem", "23rem",
                  "359px", "1100px", "1180px", "1139px", "1199px", "1000px", "900px", "899px", "720px", "700px", "699px",
                  "760px", "64rem", "56.25rem", "48rem"}
DYNAMIC_PREFIXES = ("c-", "k-", "pri", "col-", "is-", "has-", "lang-", "ic-", "tone-", "st-", "t-")

CLASS_RE = re.compile(r"\.(-?[A-Za-z_][\w-]*)")
MEDIA_RE = re.compile(r"@media([^{]*)\{")
WIDTH_RE = re.compile(r"(max|min)-width:\s*([\d.]+(?:px|rem))")


def strip_css(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"url\([^)]*\)|\"[^\"]*\"|'[^']*'", "", s)
    return s


def selectors(css):
    """class names used in selector position (text before a `{`), not inside declarations."""
    out = set()
    for m in re.finditer(r"([^{}]+)\{", css):
        pre = m.group(1)
        if pre.lstrip().startswith("@"):
            continue
        for c in CLASS_RE.finditer(re.sub(r"\d+\.\d+", "", pre)):
            out.add(c.group(1))
    return out


def main():
    root = "."
    if "--root" in sys.argv:
        root = sys.argv[sys.argv.index("--root") + 1]
    verbose = "-v" in sys.argv
    css_files = [os.path.join(root, "static/app.css")] + sorted(glob.glob(os.path.join(root, "static/css/*.css")))
    classes, widths = {}, []
    for f in css_files:
        if not os.path.exists(f):
            continue
        raw = open(f, encoding="utf-8").read()
        s = strip_css(raw)
        for c in selectors(s):
            classes.setdefault(c, f)
        for m in MEDIA_RE.finditer(s):
            for kind, w in WIDTH_RE.findall(m.group(1)):
                if kind == "max" and w not in CONVENTION and w not in SPECIAL_WIDTHS:
                    widths.append((os.path.relpath(f, root), m.group(1).strip(), w))
    src = []
    for pat in ("static/js/**/*.js", "static/*.js", "static/*.html", "static/**/*.html", "kalmido/**/*.py", "kalmido/**/*.html"):
        src += glob.glob(os.path.join(root, pat), recursive=True)
    blob = "\n".join(open(p, encoding="utf-8", errors="replace").read() for p in sorted(set(src)))
    tokens = set(re.findall(r"[A-Za-z_][\w-]*", blob))
    dead = sorted(c for c, f in classes.items() if c not in tokens and not c.startswith(DYNAMIC_PREFIXES))
    for c in dead:
        if verbose:
            print("WARNING: class without a use: .%s (%s)" % (c, os.path.relpath(classes[c], root)))
    for f, q, w in widths:
        print("WARNING: %s: @media %s - %s is neither phone (599px) nor tablet (767px) nor a listed special width" % (f, q, w))
    print("check_css_classes: %d classes without a use (candidates, -v lists them), %d widths outside the convention (warnings only)"
          % (len(dead), len(widths)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
