#!/usr/bin/env python3
"""2.757.0 (#5295): every module and script has a line in docs/GLOSSAR.md.

Rule: each kalmido/**/*.py file (except __init__.py and the one-per-task migration fragments in
kalmido/core/migrations.d/) and each static/js/*.js file must appear in docs/GLOSSAR.md as `path` (in backticks, the
path from the repository root). Exit 1 with the list of the missing ones; entries for files that no longer exist are
reported too, so the page does not rot. Static: reads files only, imports nothing of the app.

  python3 tools/check_glossar.py [-v] [--root DIR]     (DIR: repository root, default: the one of this file)
  python3 tools/check_glossar.py --fix                 #4314 (Karte 17345): writes the missing lines itself (the text from
                                                       the file's own header comment, sorted in) and takes out the lines of
                                                       gone files -- the line is derived from the code, nobody types it
"""
import os
import re
import sys


def modules(root):
    out = []
    for base, dirs, files in os.walk(os.path.join(root, "kalmido")):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "migrations.d")]
        for f in files:
            if f.endswith(".py") and f != "__init__.py":
                out.append(os.path.relpath(os.path.join(base, f), root).replace(os.sep, "/"))
    jsdir = os.path.join(root, "static", "js")
    if os.path.isdir(jsdir):
        out += ["static/js/" + f for f in os.listdir(jsdir) if f.endswith(".js")]
    return sorted(out)


def check(root):
    """(missing, stale): files without a glossary line, glossary lines of files that are gone."""
    with open(os.path.join(root, "docs", "GLOSSAR.md"), encoding="utf-8") as fh:
        text = fh.read()
    listed = set(re.findall(r"^- `((?:kalmido|static/js)/[^`]+\.(?:py|js))`", text, re.M))
    have = set(modules(root))
    return sorted(have - listed), sorted(listed - have)


def header_line(root, rel):
    """#4314: the one-line text of a module / script from its own header comment (the first sentence, at most 140 characters);
    the docstring of a .py file, the first comment of a .js file (without the "Kalmido web client:" lead)."""
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            src = fh.read(4000)
    except OSError:
        return "(no header comment)"
    if rel.endswith(".py"):
        m = re.match(r'\s*(?:#[^\n]*\n\s*)*(?:[rRbBuU]{0,2})("""|\'\'\')(.*?)(?:\1|$)', src, re.S)
    else:
        m = re.match(r"\s*(?:'use strict';\s*)?(/\*)(.*?)(?:\*/|$)", src, re.S) or re.match(r"\s*(//)([^\n]*)", src)
    txt = " ".join((m.group(2) if m else "").split())
    txt = re.sub(r"^(?:\d+\.\d+(?:\.\d+)?\s*[A-Z]?\s*)?(?:\(#\d+[^)]*\):?\s*)?", "", txt)
    txt = re.sub(r"^Kalmido web client:\s*", "", txt)
    txt = re.split(r"(?<=[a-z0-9)])\.\s", txt + " ", maxsplit=1)[0].strip().rstrip(".")
    return (txt[:137] + "...") if len(txt) > 140 else (txt or "(no header comment)")


def fix(root):
    """#4314: missing lines in (sorted between the existing ones of the same kind), lines of gone files out. -> (added, removed)"""
    fn = os.path.join(root, "docs", "GLOSSAR.md")
    with open(fn, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    missing, stale = check(root)
    rx = re.compile(r"^- `((?:kalmido|static/js)/[^`]+\.(?:py|js))`")
    lines = [ln for ln in lines if not (rx.match(ln) and rx.match(ln).group(1) in stale)]
    for rel in missing:
        new = f"- `{rel}` - {header_line(root, rel)}"
        same = [i for i, ln in enumerate(lines) if rx.match(ln) and rx.match(ln).group(1).startswith(rel.split("/")[0] + "/")
                and (rel.startswith("static/") == rx.match(ln).group(1).startswith("static/"))]
        before = [i for i in same if rx.match(lines[i]).group(1) < rel]
        at = (before[-1] + 1) if before else (same[0] if same else len(lines))
        lines.insert(at, new)
    with open(fn + ".new", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    os.replace(fn + ".new", fn)
    return missing, stale


def main(argv):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]
    if "--fix" in argv:
        added, removed = fix(root)
        for f in added:
            print("added to docs/GLOSSAR.md: " + f)
        for f in removed:
            print("removed from docs/GLOSSAR.md: " + f)
    missing, stale = check(root)
    for f in missing:
        print("missing in docs/GLOSSAR.md: " + f)
    for f in stale:
        print("in docs/GLOSSAR.md but no such file: " + f)
    if missing or stale:
        print("%d missing, %d stale: python3 tools/check_glossar.py --fix writes the lines (text from the file's header comment)"
              % (len(missing), len(stale)))
        return 1
    if "-v" in argv:
        print("glossary complete: %d files" % len(modules(root)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
