#!/usr/bin/env python3
"""The user's help (2.1072.0, #5820) names what is really on the screen and is translated from today's English text.

    python3 tools/check_userhelp.py [-v] [--src] [--docs DIR] [--js DIR] [--i18n DIR]
        exit 1 on a finding; --src prints every user's section with its key and the fingerprint (src=) a translation names

A user's section is a "## How to: ..." heading of docs/*.md with <!-- user-help: <area> --> right below it (api/helpdocs.py).
 1. its area is one of HELP_AREAS (api/helpdocs.py), its title plain text, no two with the same title in a file
 2. every **label** of its English text is a text of the interface: a string 'label' (or 'label|context') in static/js/*.js -
    a renamed or removed menu item, button or tab turns this red, so a click path cannot age unnoticed
 3. every language of the app (static/i18n/<lang>.json) has a block for it in docs/help/<lang>.md
    (<!-- help: <key> src=<fingerprint> --> + "## <title>" + text) made from the English text of today (src); no block for
    a key that is no user's section
 4. every **label** of a translation is the translation of one of the English section's labels in that language (or the
    English label while the language has none) - the help says "Integrationen" where the screen says "Integrationen"
 5. <!-- show: <target> -->: when docs/help-targets.json exists, a target it does not know is named (a warning, the list is
    kept by the "Show me" part, #5860)
The key and the fingerprint follow api/helpdocs.py (hlp_slug, hlp_src); tests/p21072_b_help_ui.js compares them with the server.
Standard library only (the CI lint job runs plain Python).
"""
import glob
import hashlib
import json
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
UH = re.compile(r"^<!--\s*user-help:\s*([a-z-]+)\s*-->\s*$")
SHOW = re.compile(r"^<!--\s*show:\s*([a-z0-9.-]+)\s*-->\s*$")
TRB = re.compile(r"^<!--\s*help:\s*(\S+)\s+src=([0-9a-f]+)\s*-->\s*$")
BOLD = re.compile(r"\*\*([^*\n]{1,80})\*\*")
# each kind of quote on its own: a 'text' inside a "${…}" of a template is found as well
JS_STR = (re.compile(r"'((?:[^'\\\n]|\\.){1,200})'"), re.compile(r'"((?:[^"\\\n]|\\.){1,200})"'))


def fold(s):
    s = unicodedata.normalize("NFKD", str(s).lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch)).replace("ß", "ss")


def slug(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", fold(s))).strip("-")[:80] or "section"


def is_marker(ln):
    return bool(UH.match(ln.strip()) or SHOW.match(ln.strip()))


def sections(path):
    """The user's sections of one docs file: [{key, area, show, title, text, line}]."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    fkey = slug(os.path.basename(path)[:-3])
    heads, fence = [], False
    for i, ln in enumerate(lines):
        if FENCE.match(ln):
            fence = not fence
            continue
        m = not fence and HEAD.match(ln)
        if m:
            heads.append((i, m.group(2).strip()))
    out = []
    for n, (i, title) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        area, show = None, ""
        for ln in lines[i + 1:min(end, i + 4)]:
            if UH.match(ln.strip()):
                area = UH.match(ln.strip()).group(1)
            elif SHOW.match(ln.strip()):
                show = SHOW.match(ln.strip()).group(1)
            elif ln.strip():
                break
        if not area:
            continue
        text = "\n".join(ln for ln in lines[i + 1:end] if not is_marker(ln)).strip("\n")
        out.append({"key": f"{fkey}#{slug(title)}", "area": area, "show": show, "title": title, "text": text, "line": i + 1,
                    "file": os.path.relpath(path, ROOT)})
    return out


def src(sec):
    t = sec["title"] + "\n" + sec["text"]
    return hashlib.sha256(re.sub(r"\s+", " ", t).strip().encode("utf-8")).hexdigest()[:10]


def tr_blocks(path):
    """docs/help/<lang>.md -> {key: {src, title, text, line}}."""
    out, cur = {}, None
    with open(path, encoding="utf-8") as f:
        for i, ln in enumerate(f.read().split("\n")):
            m = TRB.match(ln.strip())
            if m:
                cur = out[m.group(1)] = {"src": m.group(2), "title": "", "lines": [], "line": i + 1}
                continue
            if cur is None:
                continue
            h = HEAD.match(ln)
            if h and not cur["title"] and not "".join(cur["lines"]).strip():
                cur["title"] = h.group(2).strip()
                continue
            cur["lines"].append(ln)
    for v in out.values():
        v["text"] = "\n".join(v.pop("lines")).strip("\n")
    return out


def js_texts(js_dir):
    """Every string literal of static/js (a 'Text|context' also as 'Text')."""
    out = set()
    for p in glob.glob(os.path.join(js_dir, "*.js")):
        with open(p, encoding="utf-8") as f:
            src_js = f.read()
        for rx in JS_STR:
            for m in rx.finditer(src_js):
                s = m.group(1).replace("\\'", "'").replace('\\"', '"')
                out.add(s)
                if "|" in s:
                    out.add(s.split("|")[0])
    return out


def help_areas():
    with open(os.path.join(ROOT, "kalmido", "api", "helpdocs.py"), encoding="utf-8") as f:
        m = re.search(r"^HELP_AREAS = \(([^)]*)\)", f.read(), re.M)
    return set(re.findall(r'"([a-z-]+)"', m.group(1))) if m else set()


def check(docs_dir, js_dir, i18n_dir, verbose=False):
    """-> (problems, warnings, sections)"""
    bad, warn = [], []
    secs = []
    for p in sorted(glob.glob(os.path.join(docs_dir, "*.md"))):
        secs += sections(p)
    areas, texts = help_areas(), js_texts(js_dir)
    seen = {}
    for s in secs:
        where = f"{s['file']}:{s['line']}"
        if s["area"] not in areas:
            bad.append(f"{where}: area {s['area']!r} is not in HELP_AREAS (kalmido/api/helpdocs.py)")
        if not s["title"].startswith("How to: ") or re.search(r"[*_`\[\]]", s["title"]):
            bad.append(f"{where}: the title must be plain text starting with 'How to: ' ({s['title']!r})")
        if s["key"] in seen:
            bad.append(f"{where}: a second section with the key {s['key']} (also line {seen[s['key']]})")
        seen[s["key"]] = s["line"]
        bad += [f"{where}: a **label** is split over two lines - keep it on one line" for ln in s["text"].split("\n") if ln.count("**") % 2][:1]
        for lab in BOLD.findall(s["text"]):
            if lab not in texts:
                bad.append(f"{where}: **{lab}** is no text of the interface (static/js) - renamed or removed? Write today's label")
    langs = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(i18n_dir, "*.json")))
    by_key = {s["key"]: s for s in secs}
    for lg in langs:
        with open(os.path.join(i18n_dir, lg + ".json"), encoding="utf-8") as f:
            d = json.load(f)
        ctx = {}
        for k, v in d.items():
            if isinstance(v, str):
                ctx.setdefault(k.split("|")[0], set()).add(v)
        tp = os.path.join(docs_dir, "help", lg + ".md")
        blocks = tr_blocks(tp) if os.path.exists(tp) else {}
        rel = os.path.relpath(tp, ROOT)
        for k, b in blocks.items():
            if k not in by_key:
                bad.append(f"{rel}:{b['line']}: {k} is no user's section (any more) - remove the block")
        for s in secs:
            b = blocks.get(s["key"])
            if not b:
                bad.append(f"{rel}: no translation of {s['key']} ({s['file']}:{s['line']}) - add <!-- help: {s['key']} src={src(s)} -->")
                continue
            if b["src"] != src(s):
                bad.append(f"{rel}:{b['line']}: {s['key']} was translated from an older English text - update it and set src={src(s)}")
            if not b["title"] or not b["text"]:
                bad.append(f"{rel}:{b['line']}: {s['key']} needs a '## title' and a text")
            if any(ln.count("**") % 2 for ln in b["text"].split("\n")):
                bad.append(f"{rel}:{b['line']}: a **label** of {s['key']} is split over two lines - keep it on one line")
            ok = set()
            for lab in BOLD.findall(s["text"]):
                ok |= ctx.get(lab) or {lab}
            for lab in BOLD.findall(b["text"]):
                if lab not in ok:
                    bad.append(f"{rel}:{b['line']}: **{lab}** is not how the screen says one of the labels of the English text in {lg}")
    tg = os.path.join(docs_dir, "help-targets.json")
    if os.path.exists(tg):
        with open(tg, encoding="utf-8") as f:
            known = set(json.load(f))
        for s in secs:
            if s["show"] and s["show"] not in known:
                warn.append(f"{s['file']}:{s['line']}: show target {s['show']!r} is not in docs/help-targets.json")
    return bad, warn, secs


def main(argv):
    def opt(name, default):
        return argv[argv.index(name) + 1] if name in argv else default
    docs = opt("--docs", os.path.join(ROOT, "docs"))
    js = opt("--js", os.path.join(ROOT, "static", "js"))
    i18n = opt("--i18n", os.path.join(ROOT, "static", "i18n"))
    bad, warn, secs = check(docs, js, i18n)
    if "--src" in argv:
        for s in secs:
            print(f"{s['key']} src={src(s)}")
        return 0
    for w in bad:
        print(w)
    for w in warn:
        print("warning:", w)
    if "-v" in argv or bad:
        print(f"check_userhelp: {len(secs)} user's sections, {len(bad)} finding(s), {len(warn)} warning(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
