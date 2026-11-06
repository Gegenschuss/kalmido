#!/usr/bin/env python3
# kalmido-suite: after=launcher_ps1 nodata
"""2.609.0 (#4512) the state files of the suites live in the test data folder, "myself" is looked up: static, no container.
 - tests/kt.py state_file() is under DATA (KALMIDO_TEST_DATA / the data folder argument), not in tests/; boot.js has the
   same folder (TEST_DATA, stateFile, readState)
 - no suite writes or reads ids.json / cal_ids.json / news_ids.json next to the test files any more (two runs in one work
   tree overwrote each other's)
 - no suite calls the fixed /api/users/1 for the logged-in user (kt.me_id / boot.js meId instead)"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kt  # noqa: E402
from kt import check, done  # noqa: E402

check(kt.state_file("ids.json") == os.path.join(kt.DATA, "ids.json"), f"kt.state_file is in the data folder: {kt.state_file('ids.json')}")
check(os.path.dirname(os.path.abspath(kt.state_file("ids.json"))) != HERE, "kt.state_file is not tests/ itself")
with open(os.path.join(HERE, "boot.js"), encoding="utf-8") as f:
    boot = f.read()
check("exports.TEST_DATA = process.env.KALMIDO_TEST_DATA || require('path').join(__dirname, '.data');" in boot,
      "boot.js: TEST_DATA = KALMIDO_TEST_DATA, else tests/.data (as kt.DATA)")
check(re.search(r"exports\.stateFile = name => require\('path'\)\.join\(exports\.TEST_DATA, name\)", boot), "boot.js: stateFile under TEST_DATA")
check("exports.meId = async cookie =>" in boot and "'api/me'" in boot, "boot.js: meId looks up /api/me")

NEXT_TO = re.compile(r"""require\(['"]\./[a-z_]*ids\.json|__dirname\s*,\s*['"][a-z_]*ids\.json|"""
                     r"""(?:__file__\)\)|\bN|\bHERE)\s*,\s*["'][a-z_]*ids\.json""")
FIXED_ME = re.compile(r"""["'`]/api/users/""" + "1" + r"""(?![0-9])""")
me = os.path.basename(__file__)
next_to, fixed = [], []
for name in sorted(os.listdir(HERE)):
    if not name.endswith((".py", ".js")) or name == me:
        continue
    with open(os.path.join(HERE, name), encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            if NEXT_TO.search(line):
                next_to.append(f"{name}:{n}")
            if FIXED_ME.search(line):
                fixed.append(f"{name}:{n}")
check(not next_to, f"no state file next to the test files (kt.state_file / boot.js readState): {next_to}")
check(not fixed, f"no fixed /api/users/1 for myself (kt.me_id / boot.js meId): {fixed}")

sys.exit(done("p2609_d_testdata"))
