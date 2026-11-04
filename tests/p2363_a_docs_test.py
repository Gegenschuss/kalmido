#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.363.0 (#3102): the move and backup guide stays with the code: every folder of a backup archive
(kalmido/admin/backup.py BK_FLAT, BK_PER_ID) is named in docs/SELF-HOSTING.md, every setting of the move checklist exists in
kalmido/core/env.py, and the old "stage 1" paragraph does not come back.
usage: p2363_a_docs_test.py"""
import os
import re
import sys

from kt import FAILS, OKS, check

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*p):
    with open(os.path.join(R, *p), encoding="utf-8") as f:
        return f.read()


doc = read("docs", "SELF-HOSTING.md")
code = read("kalmido", "admin", "backup.py")
m = re.search(r"<!-- backup-folders -->(.*?)<!-- /backup-folders -->", doc, re.S)
check(bool(m), "the folder list is marked in docs/SELF-HOSTING.md")
box = m.group(1) if m else ""
names = []
for var in ("BK_FLAT", "BK_PER_ID"):
    g = re.search(rf"^{var} = \((.*?)\)$", code, re.M)
    check(bool(g), f"{var} found in backup.py")
    names += re.findall(r'"(\w+)"', g.group(1)) if g else []
check(len(names) >= 11, f"the folders were read {names}")
for n in names:
    check(f"`{n}/`" in box, f"backup folder {n}/ is named in the guide")
# 2.510.0 (#4286): the test kalmido/admin/backup.py promises: the folders the code writes to below ATT_DIR (three ways of naming
# one) are exactly the archive's. A new folder that is not in BK_FLAT / BK_PER_ID would be left out of every backup
WRITES = (r'os\.path\.join\(\s*ATT_DIR,\s*"([a-z_.]+)"', r'os\.path\.join\(\s*"([a-z_]+)",\s*(?:str\(|f"|[a-z_]*id\b)', r'^[A-Z_]+\s*=\s*"([a-z_]+)"\s*#\s*below ATT_DIR')
written = set()
for root, _, fns in os.walk(os.path.join(R, "kalmido")):
    for fn in fns:
        if fn.endswith(".py") and fn != "backup.py":
            with open(os.path.join(root, fn), encoding="utf-8") as f:
                text = f.read()
            for rx in WRITES:
                written |= set(re.findall(rx, text, re.M))
written -= {".wikitmp", "chat"}  # .wikitmp: the export ZIP while it is written, skipped on purpose; chat: its own rule in BK_MEMBER_RE
check(written == set(names), f"the folders the code writes to are the folders of the archive: only written {sorted(written - set(names))}, only listed {sorted(set(names) - written)}")
check("chat/" in code, "the agent chat files have their rule in BK_MEMBER_RE")
env = read("kalmido", "core", "env.py")
sec = doc[doc.index("## Moving to a new server"):doc.index("<!-- backup-folders -->")]
want = set(re.findall(r"`((?:KALMIDO|TASKS)_[A-Z0-9_]+)`", sec))
check(len(want) >= 8, f"the checklist names its settings {sorted(want)}")
for v in sorted(want):
    check(f'"{v}"' in env, f"{v} of the checklist exists")
check("stage 1" not in doc, "the stale stage 1 paragraph stays out")
print(f"p2363_a_docs: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
