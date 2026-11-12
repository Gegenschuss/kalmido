#!/usr/bin/env python3
"""2.1077.0 (#5459, rest of #5270): who hears of something is decided in ONE place, kalmido/core/objnotify.py obj_notify.

obj_notify cuts every recipient with the object's rights first, then runs the settings check notif_ok and writes the News
entry through news_put (both in kalmido/collab/news.py). A new direct call of notif_ok( or news_put( somewhere else would
build its own set of people and skip the rights step -- the fault #5046 was. This lint counts those calls per file outside
the two homes (kalmido/core/objnotify.py, kalmido/collab/news.py). The ones there are today (the push ways of comments,
public lists, the portal, the request mails, dependencies, approvals, review ...) stand per file in
tools/notify_calls_baseline.json, and that file only shrinks (as tools/check_live_filter.py): a file with MORE than its
number is red (use obj_notify), a file with fewer is a notice to lower the number (--strict: red), a baseline line of a
file that is gone is a notice too (--strict: red). --update lowers the numbers to what is there now and takes out the lines
of files without any - it never raises a number or adds a file (a new one stays red).

Read: kalmido/**/*.py, parsed with ast: a call whose function is the name notif_ok / news_put or an attribute of that name
(news.notif_ok(...)) counts; the definition, an import, a mention in a docstring or a comment do not. A file that does not
parse is red (the lint cannot vouch for it).

usage: python3 tools/check_notify_calls.py [-v] [--strict] [--update] [--seed] [--root DIR]      exit 1 on a finding
Standard library only.
"""
import ast
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join("tools", "notify_calls_baseline.json")
NAMES = ("notif_ok", "news_put")
HOME = ("kalmido/core/objnotify.py", "kalmido/collab/news.py")
HELP = "send through obj_notify() of kalmido/core/objnotify.py (rights first, then notif_ok / news_put)"


def count_text(text):
    """Number of calls of notif_ok / news_put in the Python source text; None if it does not parse."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name in NAMES:
                n += 1
    return n


def counts(root=ROOT):
    """({path relative to root: number of direct calls}, [paths that do not parse]) of the server code (files without one
    left out, the two homes not read)."""
    out, bad = {}, []
    for p in sorted(glob.glob(os.path.join(root, "kalmido", "**", "*.py"), recursive=True)):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        if rel in HOME:
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            n = count_text(f.read())
        if n is None:
            bad.append(rel)
        elif n:
            out[rel] = n
    return out, bad


def load(root=ROOT):
    p = os.path.join(root, BASELINE)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return {k: int(v) for k, v in (data.get("files") or {}).items()}


def save(root, base):
    with open(os.path.join(root, BASELINE), "w", encoding="utf-8") as f:
        json.dump({"about": "tools/check_notify_calls.py (#5459): direct notif_ok( / news_put( calls outside obj_notify per file; only shrinks",
                   "total": sum(base.values()), "files": dict(sorted(base.items()))}, f, indent=1, ensure_ascii=False)
        f.write("\n")


def findings(now, base, strict=False, bad=()):
    """(red, notices) as lines for the counts now against the baseline base."""
    red, note = [], []
    for path in bad:
        red.append(f"check_notify_calls: {path} does not parse - the lint cannot count its calls")
    for path, n in sorted(now.items()):
        allowed = base.get(path, 0)
        if n > allowed:
            red.append(f"check_notify_calls: {path} has {n} direct notif_ok / news_put call(s), the baseline {allowed} - {HELP}")
        elif n < allowed:
            note.append(f"check_notify_calls: {path} has {n} (baseline {allowed}) - lower it: python3 tools/check_notify_calls.py --update")
    for path in sorted(set(base) - set(now)):
        note.append(f"check_notify_calls: {path} has none any more (baseline {base[path]}) - python3 tools/check_notify_calls.py --update")
    if strict:
        red, note = red + note, []
    return red, note


def update(now, base):
    """The baseline lowered to now: never higher than before, never a file it did not hold."""
    return {k: min(v, now[k]) for k, v in base.items() if now.get(k)}


def main(argv):
    root = argv[argv.index("--root") + 1] if "--root" in argv else ROOT
    now, bad = counts(root)
    base = load(root)
    if "--seed" in argv and not os.path.exists(os.path.join(root, BASELINE)):  # the very first baseline only
        save(root, now)
        base = dict(now)
        print(f"check_notify_calls: baseline written, {sum(now.values())} call(s) in {len(now)} file(s)")
    if "--update" in argv:
        new = update(now, base)
        save(root, new)
        print(f"check_notify_calls: baseline {sum(base.values())} -> {sum(new.values())} in {len(new)} file(s)")
        base = new
    red, note = findings(now, base, "--strict" in argv, bad)
    for x in note + red:
        print(x)
    if "-v" in argv or red:
        print(f"check_notify_calls: {sum(now.values())} direct call(s) in {len(now)} file(s), baseline "
              f"{sum(base.values())}, {len(red)} finding(s)")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
