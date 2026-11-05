#!/usr/bin/env python3
# kalmido-suite: nodata
"""tools/pins.py --osv checks mermaid, katex and the DOMPurify inside mermaid.min.js (#4169); pip is removed from both images.
Offline: the OSV answer is faked. Python standard library only."""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pins  # noqa: E402

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


names = dict(pins.osv_targets())
check(set(names) == {"pdfjs-dist", "mermaid", "katex", "dompurify"}, f"targets: {names}")
check(all(re.match(r"\d+\.\d+\.\d+$", v) for v in names.values()), f"a version is missing: {names}")

fake = {"dompurify": [{"id": "GHSA-new-new-new", "summary": "new hole"}, {"id": "X-1", "aliases": ["GHSA-listed"], "summary": "old"}]}
q = lambda n, v: fake.get(n, [])  # noqa: E731
out = pins.osv_check(q, [("dompurify", "3.4.12"), ("katex", "0.19.1")], {"GHSA-listed": "reason"})
check(len(out) == 1 and "GHSA-new-new-new" in out[0], f"only the unlisted hole must fail (alias match lets the listed one pass): {out}")
check(pins.osv_check(q, [("mermaid", "")], {}) != [], "a missing version must be a problem")

ign = pins.osv_ignored()
check(ign and all(isinstance(v, str) and len(v) > 20 for v in ign.values()), "every ignored hole needs a reason")
with open(os.path.join(ROOT, "tools/pins_osv_ignore.json"), encoding="utf-8") as f:
    check("_comment" in json.load(f) and "_comment" not in ign, "_comment is no ignored id")

for rel in ("Dockerfile", "embed/Dockerfile"):
    text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    last_install = max(m.start() for m in re.finditer(r"pip install", text))
    rm = text.rfind("python -m pip uninstall -y pip")
    check(rm > last_install, f"{rel}: pip must be removed after the last pip install")
    # the final stage of Dockerfile starts at its last FROM; the removal must sit in that stage
    check(rm > text.rfind("\nFROM "), f"{rel}: the removal is not in the final stage")

if fails:
    print("\n".join("FAIL: " + f for f in fails))
    sys.exit(1)
print("p2554_d_pins_test ok")
