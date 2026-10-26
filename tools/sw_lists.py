#!/usr/bin/env python3
"""The precache lists of the service worker (static/sw.js: SHELL, LAZY, LAZY_CSS) written from their sources (2.320, #1368).

SHELL = the fixed start files (kept as they stand in sw.js: '/', manifest, app.css, i18n.js, icons, fonts, ...) + every
static/js/<module>.js that static/index.html loads with a <script> tag, in that order; LAZY = the modules of LD_MODS in
static/js/lazyload.js; LAZY_CSS = the stylesheets of LD_CSS there (tools/check_layout.py checks exactly this). Every package
that adds a module appended to these three lines by hand, so two packages built side by side always conflicted in sw.js.

  python3 tools/sw_lists.py                 rewrite the three lists in static/sw.js from index.html + lazyload.js
  python3 tools/sw_lists.py --check         exit 1 when sw.js differs from what the sources say
  python3 tools/sw_lists.py %O %A %B        git merge driver for static/sw.js (.gitattributes `merge=swlists`): git's own
                                            three-way merge; conflicts ONLY in the three list lines are solved by rebuilding
                                            the lists from index.html + lazyload.js as the merge / rebase / cherry-pick will
                                            have them (three-way merged from the git objects; any other conflict, or a source
                                            file in conflict itself, stays a conflict)
Register once per clone (worktrees share it):
    git config merge.swlists.name "Kalmido sw.js precache lists"
    git config merge.swlists.driver "python3 tools/sw_lists.py %O %A %B"
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST_RE = {n: re.compile(r"^const " + n + r" = \[(.*?)\];", re.S | re.M) for n in ("SHELL", "LAZY", "LAZY_CSS")}
WRAP = 150


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def sources():
    """(script tags of index.html, LD_MODS modules, LD_CSS stylesheets) as URLs."""
    tags = re.findall(r'<script src="(/static/js/[\w-]+\.js)"(?: defer)?></script>', read("static", "index.html"))
    ll = read("static", "js", "lazyload.js")
    m = re.search(r"const LD_MODS = \{(.*?)\n\};", ll, re.S)
    mods = [f"/static/js/{f}.js" for f in re.findall(r"'([\w-]+)'", re.sub(r"^\s*\w+:", "", m.group(1), flags=re.M))] if m else []
    c = re.search(r"const LD_CSS = \{(.*?)\};", ll, re.S)
    css = [f"/static/css/{f}.css" for f in re.findall(r"'([\w-]+)'", re.sub(r"^\s*\w+:", "", c.group(1), flags=re.M))] if c else []
    return tags, mods, css


def fmt(name, urls):
    """const NAME = [...]; wrapped like the hand-written lines (one line of ~150 chars, continuation indented)."""
    out, line = [], f"const {name} = ["
    for i, u in enumerate(urls):
        item = f"'{u}'" + ("," if i + 1 < len(urls) else "")
        if len(line) + len(item) + 1 > WRAP and line.strip() not in (f"const {name} = [",):
            out.append(line.rstrip())
            line = "  " + item
        else:
            line += ("" if line.endswith("[") else " ") + item
    out.append(line + "];")
    return "\n".join(out)


def rebuild(sw_text, src=None):
    """-> (new sw.js text, changed?) with the three lists rewritten from the sources; the fixed SHELL entries are kept."""
    tags, mods, css = src or sources()
    m = LIST_RE["SHELL"].search(sw_text)
    if not m:
        raise SystemExit("static/sw.js: const SHELL = [...] not found")
    fixed = [u for u in re.findall(r"'(/[^']*)'", m.group(1)) if not u.startswith("/static/js/")]
    new = sw_text
    for name, urls in (("SHELL", fixed + tags), ("LAZY", mods), ("LAZY_CSS", css)):
        mm = LIST_RE[name].search(new)
        if not mm:
            raise SystemExit(f"static/sw.js: const {name} = [...] not found")
        new = new[:mm.start()] + fmt(name, urls) + new[mm.end():]
    return new, new != sw_text


def entries(text, name):
    m = LIST_RE[name].search(text)
    return re.findall(r"'(/[^']*)'", m.group(1)) if m else None


def merge_driver(base_p, ours_p, theirs_p):
    """The three lists are merged as ENTRY lists (one entry per line, git merge-file --union: additions of both sides are
    kept, ours first), the rest of the file by git's normal three-way merge. tools/check_layout.py still checks the lists
    against index.html + lazyload.js afterwards (lint / CI): a wrong order = run tools/sw_lists.py."""
    import tempfile
    texts = [open(p, encoding="utf-8").read() for p in (base_p, ours_p, theirs_p)]
    merged = {}
    with tempfile.TemporaryDirectory() as td:
        for name in LIST_RE:
            ents = [entries(t, name) for t in texts]
            if any(e is None for e in ents):  # a side without the list: git's own merge of the whole file
                return subprocess.run(["git", "merge-file", "-L", "ours", "-L", "base", "-L", "theirs", ours_p, base_p, theirs_p]).returncode
            fs = []
            for i, e in enumerate(ents):
                f = os.path.join(td, f"{name}.{i}")
                with open(f, "w", encoding="utf-8") as fh:
                    fh.write("".join(x + "\n" for x in e))
                fs.append(f)
            p = subprocess.run(["git", "merge-file", "--union", "-p", fs[1], fs[0], fs[2]], capture_output=True, text=True)
            merged[name] = list(dict.fromkeys(x for x in p.stdout.splitlines() if x))
        holders = [t for t in texts]
        for name in LIST_RE:
            holders = [LIST_RE[name].sub(f"const {name} = [__SWLISTS_{name}__];", t, count=1) for t in holders]
        fs = []
        for i, t in enumerate(holders):
            f = os.path.join(td, f"rest.{i}")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(t)
            fs.append(f)
        p = subprocess.run(["git", "merge-file", "-L", "ours", "-L", "base", "-L", "theirs", "-p", fs[1], fs[0], fs[2]], capture_output=True, text=True)
        rest = p.stdout
    for name, urls in merged.items():
        rest = rest.replace(f"const {name} = [__SWLISTS_{name}__];", fmt(name, urls))
    with open(ours_p, "w", encoding="utf-8") as f:
        f.write(rest)
    if p.returncode > 0:
        return 1  # a conflict outside the lists stays a conflict (markers in the file)
    print("sw_lists: precache lists merged entry by entry (check: tools/check_layout.py)", file=sys.stderr)
    return 0


def main(argv):
    sw = os.path.join(ROOT, "static", "sw.js")
    if len(argv) == 4 and all(os.path.exists(a) for a in argv[1:4]):  # merge driver: %O %A %B
        return merge_driver(*argv[1:4])
    text = read("static", "sw.js")
    new, changed = rebuild(text)
    lists = lambda t: [re.findall(r"'(/[^']*)'", LIST_RE[n].search(t).group(1)) for n in ("SHELL", "LAZY", "LAZY_CSS")]
    changed = lists(new) != lists(text)  # the wrapping of the lines does not count
    if "--check" in argv:
        if changed:
            print("static/sw.js: the lists SHELL / LAZY / LAZY_CSS differ from index.html + lazyload.js - run python3 tools/sw_lists.py")
            return 1
        print("sw.js lists current")
        return 0
    if changed:
        with open(sw, "w", encoding="utf-8") as f:
            f.write(new)
        print("static/sw.js: lists rewritten")
    else:
        print("static/sw.js: lists unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
