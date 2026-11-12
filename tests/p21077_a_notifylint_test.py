#!/usr/bin/env python3
# kalmido-suite: after=p2501_a_nosham nodata
"""2.1077.0 (#5459): tools/check_notify_calls.py. Static, no container.
 - a new direct notif_ok( / news_put( call (bare name or attribute) outside core/objnotify.py and collab/news.py is red
 - the two homes, the definition, an import, a docstring or a comment that names them do not count
 - the same number as the baseline: quiet; fewer, or a file without any left: a notice (--strict: red)
 - --update lowers the numbers and takes out empty files, it never raises one or adds a file (the baseline only shrinks)
 - a file that does not parse is red
 - the repository: no finding, and no file of it above its baseline
usage: p21077_a_notifylint_test.py"""
import os
import shutil
import sys
import tempfile

from kt import FAILS, OKS, check

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import check_notify_calls as nc  # noqa: E402


def tree(files, base=None):
    tmp = tempfile.mkdtemp(prefix="p21077a-")
    for rel, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(tmp, rel)), exist_ok=True)
        with open(os.path.join(tmp, rel), "w", encoding="utf-8") as f:
            f.write(text)
    os.makedirs(os.path.join(tmp, "tools"), exist_ok=True)
    if base is not None:
        nc.save(tmp, base)
    return tmp


FILES = {
    "kalmido/meet/push.py": ('from ..collab.news import notif_ok, news_put\nfrom ..collab import news\n'
                             'def f(c, u, s):\n    """calls notif_ok(c, u, s) the old way"""\n    # news_put(c, u, "x") in a comment\n'
                             '    if notif_ok(c, u, s, "assign", "push"):\n        news.news_put(c, u, "assign")\n'),
    "kalmido/meet/clean.py": 'from ..core.objnotify import obj_notify\ndef g(c):\n    obj_notify(c, "task", 1, [2], row="assign")\n',
    "kalmido/core/objnotify.py": 'def obj_notify(c):\n    news_put(c, 1, "x")\n    notif_ok(c, 1, {}, "x", "push")\n',
    "kalmido/collab/news.py": 'def notif_ok(*a):\n    return True\ndef news_put(*a):\n    return notif_ok(*a)\n',
}
tmp = tree(FILES, {"kalmido/meet/push.py": 1})
now, bad = nc.counts(tmp)
check(now == {"kalmido/meet/push.py": 2} and not bad, f"counted: two calls in push.py (name + attribute), none in the homes, docstring, comment, import {now} {bad}")
red, note = nc.findings(now, nc.load(tmp))
check(len(red) == 1 and "kalmido/meet/push.py has 2" in red[0] and "baseline 1" in red[0] and "obj_notify" in red[0], f"one more than the baseline: red {red}")
check(nc.main(["x", "--root", tmp]) == 1, "the script: exit 1")
red, note = nc.findings(now, {"kalmido/meet/push.py": 2})
check(not red and not note, f"the same number: quiet {red} {note}")
red, note = nc.findings(now, {"kalmido/meet/push.py": 3, "kalmido/meet/old.py": 1})
check(not red and len(note) == 2 and any("lower it" in x for x in note) and any("old.py has none" in x for x in note), f"fewer / a file gone: notices {note}")
red, _ = nc.findings(now, {"kalmido/meet/push.py": 3, "kalmido/meet/old.py": 1}, strict=True)
check(len(red) == 2, f"--strict: the notices are red {red}")
check(nc.findings({"kalmido/new/x.py": 1}, {})[0], "a new file with one: red (not in the baseline = 0)")
shutil.rmtree(tmp, ignore_errors=True)

tmp = tree({"kalmido/meet/broken.py": "def f(:\n    notif_ok(\n"}, {})
_, bad = nc.counts(tmp)
check(bad == ["kalmido/meet/broken.py"] and nc.main(["x", "--root", tmp]) == 1, f"a file that does not parse: red {bad}")
shutil.rmtree(tmp, ignore_errors=True)

# ---- --seed writes the first baseline only, --update only shrinks
tmp = tree(FILES)
check(nc.main(["x", "--seed", "--root", tmp]) == 0 and nc.load(tmp) == {"kalmido/meet/push.py": 2}, f"--seed: the first baseline {nc.load(tmp)}")
nc.save(tmp, {"kalmido/meet/push.py": 1})
check(nc.main(["x", "--seed", "--root", tmp]) == 1 and nc.load(tmp) == {"kalmido/meet/push.py": 1}, "--seed does not raise a baseline that is there")
shutil.rmtree(tmp, ignore_errors=True)
up = nc.update({"a.py": 1, "b.py": 5, "new.py": 2}, {"a.py": 3, "b.py": 4, "gone.py": 2})
check(up == {"a.py": 1, "b.py": 4}, f"--update: lowered, never raised, no new file, empty ones out {up}")
tmp = tree(FILES, {"kalmido/meet/push.py": 5, "kalmido/meet/old.py": 1})
check(nc.main(["x", "--update", "--root", tmp]) == 0 and nc.load(tmp) == {"kalmido/meet/push.py": 2}, f"the script --update writes it {nc.load(tmp)}")
shutil.rmtree(tmp, ignore_errors=True)

# ---- the repository
now, bad = nc.counts()
base = nc.load()
red, note = nc.findings(now, base, bad=bad)
check(not red, f"the repository: {red[:5]}")
check(base and sum(base.values()) >= sum(now.values()), f"the repository's baseline holds every file ({sum(base.values())} / {sum(now.values())})")
check(not any(p in base for p in nc.HOME), "the homes stand in no baseline line")

print(f"p21077_a_notifylint: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
