#!/usr/bin/env python3
# kalmido-suite: after=perf_budget nodata
"""2.624.0 part B (#3941): fewer merge conflicts in kalmido/__init__.py. Static, no container:
 - tools/check_layout.py: the tree is clean (the sorted block at the end of ORDER exists, sorted, only core.idem + startup after it)
 - on a copy of the tree: two new modules in the block, sorted = fine; unsorted = error; two on one line = error;
   a new module after the block = error; the marks gone = error
usage: python3 tests/p2624_b_order_test.py"""
import os
import shutil
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402


def lay(root):
    r = subprocess.run([sys.executable, os.path.join(root, "tools", "check_layout.py")], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


rc, out = lay(ROOT)
check(rc == 0, "the tree passes check_layout: " + out[-400:])

with tempfile.TemporaryDirectory() as tmp:
    root = os.path.join(tmp, "tree")
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "node_modules", "fonts", "*.png", "*.woff2", "i18n",
                                                              "vendor", "docs", "__pycache__", ".data*"))
    for n in ("aap2624", "zzp2624"):
        open(os.path.join(root, "kalmido", "tasks", n + ".py"), "w").close()
    ini = os.path.join(root, "kalmido", "__init__.py")
    src = open(ini, encoding="utf-8").read()
    end = "    # -- end of the sorted block"
    check(src.count(end) == 1, "the end mark stands once in ORDER")

    def put(text):
        with open(ini, "w", encoding="utf-8") as f:
            f.write(text)

    # 2.780.0: the two go to their sorted places in the block (appending them before the end mark broke once the block
    # held a module sorting after tasks.aap2624, e.g. tasks.tundo of 2.774.0)
    _bs = src.index("\n", src.index("# (it loads after every module above")) + 1
    _be = src.index(end)
    _rows = src[_bs:_be].splitlines(keepends=True) + ['    "tasks.aap2624",  # a\n', '    "tasks.zzp2624",\n']
    _rows.sort(key=lambda r: r.split('"')[1])
    put(src[:_bs] + "".join(_rows) + src[_be:])
    rc, out = lay(root)  # the copy leaves out folders such as kalmido/docs: other errors of the copy do not count here
    check(not any(x in out for x in ("sorted block", "one module per line", "after the sorted block")), "two new modules in the block, sorted: fine " + out[-400:])
    put(src.replace(end, '    "tasks.zzp2624",\n    "tasks.aap2624",\n' + end))
    rc, out = lay(root)
    check(rc == 1 and "sorted block is sorted by name" in out, "unsorted block: error " + out[-400:])
    put(src.replace(end, '    "tasks.aap2624", "tasks.zzp2624",\n' + end))
    rc, out = lay(root)
    check(rc == 1 and "one module per line" in out, "two modules on one line: error " + out[-400:])
    put(src.replace('    "startup",\n)', '    "tasks.aap2624",\n    "tasks.zzp2624",\n    "startup",\n)'))
    rc, out = lay(root)
    check(rc == 1 and "after the sorted block only" in out, "new modules after the block: error " + out[-400:])
    put(src.replace("# -- sorted block", "# sorted").replace('    "startup",\n)', '    "tasks.aap2624",\n    "tasks.zzp2624",\n    "startup",\n)'))
    rc, out = lay(root)
    check(rc == 1 and "marks of the sorted block" in out, "the marks gone: error " + out[-400:])

print(f"{OKS[0]} ok, {'FAILED ' + str(len(FAILS)) if FAILS else 'all ok'}")
sys.exit(1 if FAILS else 0)
