#!/usr/bin/env python3
"""2.757.0 (#5295): every module and script has a line in docs/GLOSSAR.md.

Rule: each kalmido/**/*.py file (except __init__.py and the one-per-task migration fragments in
kalmido/core/migrations.d/) and each static/js/*.js file must appear in docs/GLOSSAR.md as `path` (in backticks, the
path from the repository root). Exit 1 with the list of the missing ones; entries for files that no longer exist are
reported too, so the page does not rot. Static: reads files only, imports nothing of the app.

  python3 tools/check_glossar.py [-v] [--root DIR]     (DIR: repository root, default: the one of this file)
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


def main(argv):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]
    missing, stale = check(root)
    for f in missing:
        print("missing in docs/GLOSSAR.md: " + f)
    for f in stale:
        print("in docs/GLOSSAR.md but no such file: " + f)
    if missing or stale:
        print("%d missing, %d stale: add (or remove) one line per file in docs/GLOSSAR.md" % (len(missing), len(stale)))
        return 1
    if "-v" in argv:
        print("glossary complete: %d files" % len(modules(root)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
