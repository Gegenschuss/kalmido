#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.928.0 (#5597): the git merge drivers for the lint baselines (tools/baseline_merge.py) and the developer docs every core
package extends (tools/doc_merge.py). On 11.11.2026 three packages were rebuilt, every check green, because the train's
move-up rebase stopped on docs/dev/kern.md (two paragraphs added at one place) or tools/live_filter_baseline.json (both
packages changed "total"). Throwaway git repos with the real .gitattributes lines and tools/git_setup.sh; no server.

- two packages lowering different counts of tools/live_filter_baseline.json rebase onto each other without a conflict,
  "total" is the sum of the merged counts, the layout stays the tool's own (check_live_filter.py --update writes it so)
- two packages adding a paragraph after the same line of docs/dev/kern.md rebase without a conflict, both paragraphs stay
- the same line rewritten differently on both sides stays a conflict (markers), nothing guessed
- a branch from before the drivers (no tools/*_merge.py in its tree) still merges with git's own line merge
- the selftests of both drivers; the real baselines come back byte for byte from a merge of three equal versions"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from kt import FAILS, OKS, check  # noqa: E402
import baseline_merge  # noqa: E402

KERN = "# Core\n\n## 4. Saving\n\nsave text\nc.commit()\n\n## 5. Routes\n\nroutes\n"


def lf(**files):
    """tools/live_filter_baseline.json as tools/check_live_filter.py save() writes it."""
    return json.dumps({"about": "x", "total": sum(files.values()), "files": dict(sorted(files.items()))}, indent=1,
                      ensure_ascii=False) + "\n"


def git(repo, *a, ok=True):
    p = subprocess.run(["git", "-C", repo, "-c", "user.name=T", "-c", "user.email=t@example.invalid", *a], capture_output=True, text=True)
    if ok and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)}: {p.stderr.strip()[-300:]}")
    return p


def put(repo, rel, text):
    os.makedirs(os.path.dirname(os.path.join(repo, rel)) or repo, exist_ok=True)
    with open(os.path.join(repo, rel), "w", encoding="utf-8") as f:
        f.write(text)


def rd(repo, rel):
    with open(os.path.join(repo, rel), encoding="utf-8") as f:
        return f.read()


def fresh_repo(with_drivers=True):
    r = tempfile.mkdtemp(prefix="merge2928-")
    git(r, "init", "-q", "-b", "main")
    os.makedirs(os.path.join(r, "tools"))
    for t in ("baseline_merge.py", "doc_merge.py", "git_setup.sh") if with_drivers else ("git_setup.sh",):
        shutil.copy(os.path.join(ROOT, "tools", t), os.path.join(r, "tools", t))
    ga = [ln for ln in rd(ROOT, ".gitattributes").splitlines() if "merge=baseline" in ln or "merge=docs" in ln]
    put(r, ".gitattributes", "\n".join(ga) + "\n")
    subprocess.run(["bash", os.path.join(r, "tools", "git_setup.sh")], capture_output=True, check=True)
    put(r, "tools/live_filter_baseline.json", lf(a=4, b=3, c=3))
    put(r, "docs/dev/kern.md", KERN)
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    return r


def branch(r, name, files):
    git(r, "checkout", "-q", "main")
    git(r, "checkout", "-qb", name)
    for rel, text in files.items():
        put(r, rel, text)
    git(r, "commit", "-qam", name)


ga = rd(ROOT, ".gitattributes")
check("tools/*_baseline.json merge=baseline" in ga and "docs/dev/kern.md merge=docs" in ga, ".gitattributes names both drivers")

# the 11.11.2026 case: p1 lowers a, p2 lowers b - both changed "total"; both add a paragraph after c.commit()
r = fresh_repo()
branch(r, "p1", {"tools/live_filter_baseline.json": lf(a=2, b=3, c=3), "docs/dev/kern.md": KERN.replace("c.commit()\n", "c.commit()\n\nP1 paragraph\n")})
branch(r, "p2", {"tools/live_filter_baseline.json": lf(a=4, b=1, c=3), "docs/dev/kern.md": KERN.replace("c.commit()\n", "c.commit()\n\nP2 paragraph\n")})
git(r, "checkout", "-q", "main")
git(r, "merge", "-q", "--ff-only", "p1")
p = git(r, "rebase", "main", "p2", ok=False)  # the train's move-up: rebase commit by commit
check(p.returncode == 0, f"the second package rebases onto the first without a conflict: {(p.stdout + p.stderr).strip()[-300:]}")
got = rd(r, "tools/live_filter_baseline.json")
check(got == lf(a=2, b=1, c=3), f"baseline: both lowerings, total = sum (6), the tool's layout\n{got}")
kern = rd(r, "docs/dev/kern.md")
check("P1 paragraph" in kern and "P2 paragraph" in kern and "<<<<<<<" not in kern and kern.count("c.commit()") == 1,
      f"kern.md: both paragraphs, no markers, nothing doubled\n{kern}")
git(r, "rebase", "--abort", ok=False)
shutil.rmtree(r, ignore_errors=True)

# a real content question stays a conflict: the same line rewritten differently on both sides
r = fresh_repo()
branch(r, "q1", {"docs/dev/kern.md": KERN.replace("save text", "save text A")})
branch(r, "q2", {"docs/dev/kern.md": KERN.replace("save text", "save text B")})
git(r, "checkout", "-q", "main")
git(r, "merge", "-q", "--ff-only", "q1")
p = git(r, "merge", "q2", ok=False)
check(p.returncode != 0 and "<<<<<<<" in rd(r, "docs/dev/kern.md"), "the same line rewritten differently stays a conflict with markers")
shutil.rmtree(r, ignore_errors=True)

# a tree without the drivers' scripts (a branch from before 2.928.0): git's own line merge, no error from the driver line
r = fresh_repo(with_drivers=False)
branch(r, "o1", {"docs/dev/kern.md": KERN.replace("routes", "routes changed")})
branch(r, "o2", {"docs/dev/kern.md": KERN.replace("save text", "save changed")})
git(r, "checkout", "-q", "main")
git(r, "merge", "-q", "--ff-only", "o1")
p = git(r, "merge", "-q", "o2", ok=False)
check(p.returncode == 0 and "routes changed" in rd(r, "docs/dev/kern.md") and "save changed" in rd(r, "docs/dev/kern.md"),
      f"without the scripts: git's line merge as before: {p.stderr.strip()[-200:]}")
shutil.rmtree(r, ignore_errors=True)

# selftests + the real baselines in their own layout
for t in ("baseline_merge.py", "doc_merge.py"):
    check(subprocess.run([sys.executable, os.path.join(ROOT, "tools", t), "--selftest"], capture_output=True).returncode == 0, f"{t} --selftest")
for name in sorted(os.listdir(os.path.join(ROOT, "tools"))):
    if name.endswith("_baseline.json"):
        text = rd(ROOT, os.path.join("tools", name))
        check(baseline_merge.merge(text, text, text) == text, f"tools/{name} comes back byte for byte (its layout is known)")

print(f"p2928_a_merge_drivers: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
