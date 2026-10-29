#!/usr/bin/env python3
# kalmido-suite: after=p2450_b_lint nodata
"""2.419.0 (#3495): one type and spacing scale in static/app.css and static/css/*.css, checked without a container.
 - font-size and the size in font: only the tokens --fs-xxs ... --fs-xl (10 11 12 13 14 16 18 20 px); free stay display
   figures of 22 px and more, inherit / calc / clamp / max, pt in print rules and em for inline code, reference cards,
   the ::after mark and the wiki reading styles (they scale with the text around them)
 - no token with a fallback that names another size (var(--fs-s,.8125rem) said 13 px, the token is 12 px)
 - line-height: 1.2 ... 1.55 only as var(--lh) / var(--lh-tight)
 - margin / padding / gap in rem only on the 1 px grid (.3rem / .35rem / .4rem / .6rem rounded onto the scale)
 - icons: an svg sized by hand between 9 and 20 px uses var(--ic-xs|--ic-s|--ic|--ic-l) (svg.i / svg.i.s / svg.i.l)
usage: p2419_scale_test.py"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from kt import FAILS, OKS, check  # tests/kt.py

FILES = [os.path.join(ROOT, "static", "app.css")] + sorted(glob.glob(os.path.join(ROOT, "static", "css", "*.css")))
RULE = re.compile(r"([^{}]*)\{([^{}]*)\}")
EM_OK = ("code", ".tref", ".rfcard", "::after", ".wkst-")
MICRO_OK = (".tthav .avatar",)  # initials in a 20 px dot: 8 px, below the scale on purpose
LOGO = re.compile(r"svg\.(logo|kword|bot)|#boot|#fab|\.empty|\.alogo")


def rem(v):
    m = re.fullmatch(r"(\d*\.?\d+)rem", v.strip())
    return float(m.group(1)) if m else None


def size_ok(sel, v, media):
    v = v.strip()
    if v.startswith("var(--fs-") and "," not in v or v in ("inherit", "var(--fld-fs)", "var(--row-fs)", "var(--meta-fs)"):
        return True
    if v.startswith(("calc(", "clamp(", "max(")):
        return True
    if v.endswith("pt") and "print" in media:
        return True
    if v.endswith("em") and not v.endswith("rem"):
        return any(s in sel for s in EM_OK)
    r = rem(v)
    if r is not None and (r >= 1.375 or any(s in sel for s in MICRO_OK)):
        return True
    return False


bad_fs, bad_fb, bad_lh, bad_sp, bad_ic, n = [], [], [], [], [], 0
for f in FILES:
    name = os.path.relpath(f, ROOT)
    text = open(f, encoding="utf-8").read()
    for m in RULE.finditer(text):
        sel, body = m.group(1), m.group(2)
        before = text[:m.start()]
        media = before[before.rfind("@media"):] if "@media" in before[-4000:] else ""
        media = media if media.count("{") > media.count("}") else ""
        line = before.count("\n") + 1
        short = sel.strip().splitlines()[-1].strip()[-60:] if sel.strip() else "?"
        where = f"{name}:{line} {short}"
        if re.search(r"(^|\})\s*:root\s*$", sel) or re.search(r":root(\[[^\]]*\])*\s*$", sel.strip()):
            continue
        n += 1
        for v in re.findall(r"(?<![-\w])font-size:\s*([^;!]+?)\s*(?=;|!|$)", body):
            if not size_ok(sel, v, media):
                bad_fs.append(f"{where}: font-size:{v}")
        for v in re.findall(r"(?<![-\w])font:\s*([^;]+)", body):
            s = re.search(r"(?<![\w.(-])(\d*\.?\d+(?:rem|em|px))(?:/([\d.]+))?", v)
            if s and not size_ok(sel, s.group(1), media):
                bad_fs.append(f"{where}: font:{v}")
            if s and s.group(2) and 1.195 <= float(s.group(2)) <= 1.555:
                bad_lh.append(f"{where}: font:{v}")
            t = re.search(r"var\(--fs-[a-z]+\)/([\d.]+)(?![\w.])", v)
            if t and 1.195 <= float(t.group(1)) <= 1.555:
                bad_lh.append(f"{where}: font:{v}")
        for v in re.findall(r"var\(--fs-[a-z]+,[^)]*\)", body):
            bad_fb.append(f"{where}: {v}")
        for v in re.findall(r"(?<![-\w])line-height:\s*(\d*\.?\d+)\s*(?=;|!|$)", body):
            if 1.195 <= float(v) <= 1.555:
                bad_lh.append(f"{where}: line-height:{v}")
        for prop, v in re.findall(r"(?<![-\w])((?:margin|padding|gap|row-gap|column-gap)(?:-[a-z-]+)?):\s*([^;]+)", body):
            for x in re.findall(r"(?<![\w.])-?(\d*\.?\d+)rem", v):
                if abs(float(x) * 16 - round(float(x) * 16)) > 1e-6:
                    bad_sp.append(f"{where}: {prop}:{v.strip()}")
        if "svg" in sel and not LOGO.search(sel):
            for prop in ("width", "height"):
                w = re.search(r"(?<![-\w])" + prop + r":\s*(\d*\.?\d+)rem", body)
                if w and .5625 <= float(w.group(1)) <= 1.25:
                    bad_ic.append(f"{where}: {prop}:{w.group(1)}rem")

check(n > 2000, f"the rules were read ({n})")
check(not bad_fs, f"font sizes on the tokens --fs-xxs ... --fs-xl ({len(bad_fs)} off: {bad_fs[:8]})")
check(not bad_fb, f"no token with another size as fallback ({bad_fb[:8]})")
check(not bad_lh, f"line heights 1.2 ... 1.55 as var(--lh) / var(--lh-tight) ({len(bad_lh)} off: {bad_lh[:8]})")
check(not bad_sp, f"margin / padding / gap on the 1 px grid ({len(bad_sp)} off: {bad_sp[:8]})")
check(not bad_ic, f"icons only in the svg.i sizes ({len(bad_ic)} off: {bad_ic[:8]})")

app = open(FILES[0], encoding="utf-8").read()
root = re.search(r":root\{([^}]*)\}", app).group(1)
want = {"--fs-xxs": ".625rem", "--fs-xs": ".6875rem", "--fs-s": ".75rem", "--fs-m": ".8125rem", "--fs-b": ".875rem",
        "--fs-l": "1rem", "--fs-h": "1.125rem", "--fs-xl": "1.25rem", "--lh": "1.45", "--lh-tight": "1.25",
        "--ic-xs": ".625rem", "--ic-s": ".8125rem", "--ic": "1rem", "--ic-l": "1.25rem"}
for k, v in want.items():
    check(re.search(re.escape(k) + r":" + re.escape(v) + r";", root) is not None, f":root defines {k}:{v}")
check(re.search(r"svg\.i\{width:var\(--ic\);height:var\(--ic\)", app) and re.search(r"svg\.i\.s\{width:var\(--ic-s\);height:var\(--ic-s\)", app)
      and re.search(r"svg\.i\.l\{width:var\(--ic-l\);height:var\(--ic-l\)\}", app), "svg.i / .s / .l take the icon tokens")
check(re.search(r"body\{font:var\(--fs-b\)/var\(--lh\) var\(--sans\)\}", app) is not None, "body text: --fs-b / --lh")

print(f"p2419_scale: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
