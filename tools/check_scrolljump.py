#!/usr/bin/env python3
"""2.924.0 (#5224): the view moves only when the person makes it move - a new jump in the web client needs a reason.

Product rule (08.11.2026): a redraw keeps the reading place (keepReading in static/js/render.js); a jump the person
asked for (a link, a search hit, "go to ...") is one calm jump. In static/js/**/*.js every

  scrollIntoView(...)                     scrollTo(...) / scrollBy(...) / scroll(...)
  .scrollTop = / += / -=                  .focus(...) without preventScroll, outside a dialog

needs the comment `// sprung-ok: <reason>` on its line (or alone on the line before; in a template `/* sprung-ok: … */`).
A focus() counts as "in a dialog" in static/js/dialogs.js or when the line or the eight lines before it name a modal /
dialog (modal(, .modal, dlg, dialog): a dialog lies over the page, its focus does not move the page.

#5227 (same product rule): a picture that loads must not grow from nothing and push the text below it. Every `<img` in a
template of static/js/**/*.js carries width= and height= (the browser reserves the box from their ratio) -- or it sits in a
fixed CSS box (a class with a set height / aspect-ratio), which the line says with `// sprung-ok: <reason>` (kind "img",
receiver = its first class or "?"). Lines that are comments do not count.

The calls that were there before the rule are the baseline (tools/scrolljump_baseline.json, "file|kind|receiver" -> count,
no line numbers, so moving code is no finding). It only ever shrinks: a NEW place is red (exit 1); --update writes the lower
counts (never adds; without a baseline file it writes the first one). Pattern of tools/check_lazy_calls.py (its reader that
blanks comments and strings) and tools/check_innerhtml.py (the baseline).

usage: python3 tools/check_scrolljump.py [-v] [--update] [--selftest]      exit 1 on a new place. Standard library only.
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_lazy_calls import blank  # noqa: E402  (comments and string texts blanked, offsets kept)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "tools", "scrolljump_baseline.json")
OK_RE = re.compile(r"sprung-ok:\s*\S")
DLG_RE = re.compile(r"modal\(|\.modal\b|dlg|dialog", re.I)
CALL = r"\s*(?:\?\.)?\s*\("  # f( and f?.(
PATS = [("scrollIntoView", re.compile(r"\.scrollIntoView" + CALL)),
        ("scrollTo", re.compile(r"\.scroll(?:To|By)?" + CALL)),
        ("scrollTop", re.compile(r"\.scrollTop\s*[-+]?=(?!=)")),
        ("focus", re.compile(r"\.focus" + CALL))]
OPEN, CLOSE = "([{", ")]}"
IMG_RE = re.compile(r"<img\b(?:=>|[^>])*>")  # an arrow function inside the tag's ${…} is no end
IMG_WH = re.compile(r"\swidth=.*\sheight=|\sheight=.*\swidth=", re.S)
IMG_CLS = re.compile(r"""\sclass=["']([\w-]*)""")


def receiver(b, raw, dot):
    """The expression before the dot (a.b, $('#x'), list[i]?.el), read backwards on the blanked text, returned from the
    raw text (strings back), spaces squeezed."""
    i, depth = dot, 0
    while i > 0:
        c = b[i - 1]
        if c in CLOSE:
            depth += 1
        elif c in OPEN:
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and not (c.isalnum() or c in "_$.?"):
            break
        i -= 1
    return re.sub(r"\s+", " ", raw[i:dot]).strip()[:80] or "?"


def args(b, op):
    """The text between the parentheses of a call whose '(' is at op (blanked text)."""
    depth, j = 0, op
    while j < len(b):
        if b[j] in OPEN:
            depth += 1
        elif b[j] in CLOSE:
            depth -= 1
            if depth == 0:
                return b[op + 1:j]
        j += 1
    return b[op + 1:]


def scan(src, rel=""):
    """-> [(line, kind, receiver)] of the unmarked places."""
    b, lines, out = blank(src), src.split("\n"), []
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln) + 1)

    def line_of(pos):
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo
    dialogs = os.path.basename(rel) == "dialogs.js"
    for kind, pat in PATS:
        for m in pat.finditer(b):
            k = line_of(m.start())
            if OK_RE.search(lines[k]) or (k and lines[k - 1].strip().startswith("//") and OK_RE.search(lines[k - 1])):
                continue
            if kind == "focus":
                if "preventScroll" in args(b, m.end() - 1):
                    continue
                if dialogs or any(DLG_RE.search(lines[j]) for j in range(max(0, k - 8), k + 1)):
                    continue
            out.append((k + 1, kind, receiver(b, src, m.start())))
    for m in IMG_RE.finditer(src):  # #5227: in the raw text (blank() empties the templates the tag lives in)
        k = line_of(m.start())
        if lines[k].lstrip().startswith(("//", "*", "/*")) or IMG_WH.search(m.group(0)):
            continue
        if OK_RE.search(lines[k]) or (k and lines[k - 1].strip().startswith("//") and OK_RE.search(lines[k - 1])):
            continue
        cl = IMG_CLS.search(m.group(0))
        out.append((k + 1, "img", (cl.group(1) if cl else "") or "?"))
    return sorted(out)


def collect():
    found = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "static", "js", "**", "*.js"), recursive=True)):
        rel = os.path.relpath(p, ROOT)
        for line, kind, rc in scan(open(p, encoding="utf-8").read(), rel):
            found.setdefault(f"{rel}|{kind}|{rc}", []).append(line)
    return found


def selftest():
    bad = ["el.scrollIntoView({block: 'nearest'});", "box.scrollTop = box.scrollHeight;", "$('#view').scrollTop += d;",
           "window.scrollTo(0, 0);", "e.scrollIntoView?.({block: 'start'});", "q?.focus?.();", "v.scrollBy({top: 9});", "inp.focus();", "x.focus({focusVisible: true});",
           "h = `<img class=\"wkimg\" src=\"${u}\" loading=\"lazy\">`;", "h = `<img src=\"${xs.map(x => x.u)[0]}\" alt=\"\">`;"]
    good = ["el.scrollIntoView(); // sprung-ok: the hit the person searched for", "inp.focus({preventScroll: true});",
            "const y = el.scrollTop;", "if (el.scrollTop == 0) go();", "// el.scrollTop = 0;", "s = 'x.scrollTop = 1';",
            "// sprung-ok: a link the person tapped\nrow.scrollIntoView();", "m = modal(h);\nm.querySelector('input').focus();",
            "h = `<img src=\"${u}\" width=\"${w}\" height=\"${h}\" alt=\"\">`;", "h = `<img class=\"av\" src=\"${u}\">`;  // sprung-ok: fixed 2rem box",
            "// a comment: <img src=x>"]
    f = 0
    for s in bad:
        if not scan(s):
            print("selftest: not reported:", s)
            f += 1
    for s in good:
        r = scan(s)
        if r:
            print("selftest: wrongly reported:", s, r)
            f += 1
    print("check_scrolljump selftest:", "FAILED %d" % f if f else "ok")
    return 1 if f else 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    found = collect()
    base = json.load(open(BASE, encoding="utf-8")) if os.path.exists(BASE) else {}
    cnt = {k: len(v) for k, v in found.items()}
    if "--update" in argv:
        new = {k: min(v, base.get(k, v)) for k, v in cnt.items() if (k in base or not base)}
        with open(BASE, "w", encoding="utf-8") as fh:
            json.dump(dict(sorted(new.items())), fh, indent=0, ensure_ascii=False)
            fh.write("\n")
        print("check_scrolljump: baseline written,", len(new), "entries,", sum(new.values()), "places")
        return 0
    out = []
    for k, n in sorted(cnt.items()):
        if n > base.get(k, 0):
            f, kind, rc = k.split("|", 2)
            lines = ", ".join(str(x) for x in found[k])
            if kind == "img":  # #5227
                out.append(f"{f}:{lines}: <img class=\"{rc}\"> without width= / height= grows when it loads and pushes the text - "
                           f"give it its size, or a fixed CSS box: `// sprung-ok: <reason>` ({n} > {base.get(k, 0)} in the baseline)")
                continue
            out.append(f"{f}:{lines}: {rc}.{kind} moves the view - keepReading / preventScroll, or a jump the person "
                       f"asked for: `// sprung-ok: <reason>` ({n} > {base.get(k, 0)} in the baseline)")
    stale = sorted(k for k, n in base.items() if cnt.get(k, 0) < n)
    for x in out:
        print(x)
    if "-v" in argv:
        for k in stale:
            print(f"tools/scrolljump_baseline.json: fewer than recorded (good), `--update` shrinks the baseline: {k}")
    print(f"check_scrolljump: {len(out)} new place(s), {sum(cnt.values())} known, {len(stale)} fewer than in the baseline")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
