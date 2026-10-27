#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.321 B (#1368): the git merge drivers of the files every package touched - static/i18n/<code>.json by key
(tools/i18n_merge.py), the precache lists of static/sw.js entry by entry (tools/sw_lists.py), tests/skip.txt as a line union
(.gitattributes). Throwaway git repos, no server, no network.

- two packages that add different translation keys / modules / skip lines merge and rebase without a conflict
- the same key changed differently on both sides stays a conflict; code outside the sw.js lists stays a conflict
- tools/sw_lists.py rewrites / checks the lists against index.html + lazyload.js; the real tree is current"""
import os
import shutil
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402

SW = ("const CACHE = 'tasks-shell-v1';  // app 1.0.0\nconst SHELL = ['/', '/static/app.css', '/static/js/a.js'];\n"
      "const LAZY = ['/static/js/l1.js'];\nconst LAZY_CSS = ['/static/css/l1.css'];\nself.x = 1;\n")
I18N = '{\n  "_meta": {"name": "Deutsch"},\n  "A": "a",\n  "B": "b"\n}\n'


def git(repo, *a, ok=True):
    p = subprocess.run(["git", "-C", repo, "-c", "user.name=T", "-c", "user.email=t@example.invalid", *a], capture_output=True, text=True)
    if ok and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)}: {p.stderr.strip()[-300:]}")
    return p


def put(repo, rel, text):
    os.makedirs(os.path.dirname(os.path.join(repo, rel)), exist_ok=True)
    with open(os.path.join(repo, rel), "w", encoding="utf-8") as f:
        f.write(text)


def rd(repo, rel):
    with open(os.path.join(repo, rel), encoding="utf-8") as f:
        return f.read()


def fresh_repo():
    r = tempfile.mkdtemp(prefix="merge-")
    git(r, "init", "-q", "-b", "main")
    for t in ("i18n_merge.py", "sw_lists.py", "git_setup.sh"):
        shutil.copy(os.path.join(ROOT, "tools", t), os.path.join(r, "tools", t)) if os.path.isdir(os.path.join(r, "tools")) else (
            os.makedirs(os.path.join(r, "tools")), shutil.copy(os.path.join(ROOT, "tools", t), os.path.join(r, "tools", t)))
    put(r, ".gitattributes", "static/i18n/*.json merge=i18n\nstatic/sw.js merge=swlists\ntests/skip.txt merge=union\n")
    subprocess.run(["bash", os.path.join(r, "tools", "git_setup.sh")], capture_output=True, check=True)
    put(r, "static/sw.js", SW); put(r, "static/i18n/de.json", I18N); put(r, "tests/skip.txt", "x 2026-11-01 #1 ev\n")
    put(r, "static/index.html", '<script src="/static/js/a.js"></script>\n')
    put(r, "static/js/lazyload.js", "const LD_MODS = {\n  l1: ['l1'],\n};\nconst LD_CSS = {l1: ['l1']};\n")
    git(r, "add", "-A"); git(r, "commit", "-qm", "base")
    return r


def branch(r, name, files):
    git(r, "checkout", "-q", "main"); git(r, "checkout", "-qb", name)
    for rel, text in files.items():
        put(r, rel, text)
    git(r, "commit", "-qam", name)


r = fresh_repo()
branch(r, "p1", {"static/i18n/de.json": I18N.replace('  "B": "b"\n', '  "B": "b",\n  "P1": "p1"\n'),
                 "static/sw.js": SW.replace("'/static/js/a.js']", "'/static/js/a.js', '/static/js/p1.js']").replace("'/static/js/l1.js']", "'/static/js/l1.js', '/static/js/p1.js']"),
                 "tests/skip.txt": "x 2026-11-01 #1 ev\np1_ui 2026-11-01 #2 ev\n"})
branch(r, "p2", {"static/i18n/de.json": I18N.replace('  "B": "b"\n', '  "B": "b",\n  "P2": "p2"\n'),
                 "static/sw.js": SW.replace("'/static/js/l1.js']", "'/static/js/l1.js', '/static/js/p2.js']").replace("'/static/css/l1.css']", "'/static/css/l1.css', '/static/css/p2.css']"),
                 "tests/skip.txt": "x 2026-11-01 #1 ev\np2_ui 2026-11-01 #3 ev\n"})
git(r, "checkout", "-q", "main"); git(r, "merge", "-q", "p1")
p = git(r, "merge", "p2", ok=False)
check(p.returncode == 0, f"two packages adding different keys / modules / skip lines merge clean: {p.stderr.strip()[-200:]}")
check('"P1": "p1",\n  "P2": "p2"' in rd(r, "static/i18n/de.json"), "translations: both keys, ours first")
check("const LAZY = ['/static/js/l1.js', '/static/js/p1.js', '/static/js/p2.js'];" in rd(r, "static/sw.js") and
      "const LAZY_CSS = ['/static/css/l1.css', '/static/css/p2.css'];" in rd(r, "static/sw.js") and
      "const SHELL = ['/', '/static/app.css', '/static/js/a.js', '/static/js/p1.js'];" in rd(r, "static/sw.js"), f"sw.js lists: entry union\n{rd(r, 'static/sw.js')}")
check(rd(r, "tests/skip.txt") == "x 2026-11-01 #1 ev\np1_ui 2026-11-01 #2 ev\np2_ui 2026-11-01 #3 ev\n", "skip.txt: line union")
# rebase (what kalmido-livezug.py landen does): a third package built on the old base
base2 = git(r, "rev-parse", "main~2").stdout.strip()
git(r, "checkout", "-q", "-b", "p3", base2)
put(r, "static/i18n/de.json", I18N.replace('"A": "a"', '"A": "a-new"').replace('  "B": "b"\n', '  "B": "b",\n  "P3": "p3"\n'))
put(r, "static/sw.js", SW.replace("'/static/css/l1.css']", "'/static/css/l1.css', '/static/css/p3.css']"))
git(r, "commit", "-qam", "p3")
p = git(r, "rebase", "main", ok=False)
check(p.returncode == 0, f"rebase of a third package onto main: clean: {p.stderr.strip()[-200:]}")
t = rd(r, "static/i18n/de.json")
check('"A": "a-new"' in t and '"P1"' in t and '"P2"' in t and t.rstrip().endswith('"P3": "p3"\n}'), f"rebased translations: change kept, all keys\n{t}")
check("const LAZY_CSS = ['/static/css/l1.css', '/static/css/p2.css', '/static/css/p3.css'];" in rd(r, "static/sw.js"), "rebased sw.js list")
# real conflicts stay conflicts
git(r, "checkout", "-q", "-b", "p4", base2)
put(r, "static/i18n/de.json", I18N.replace('"A": "a"', '"A": "a-other"')); git(r, "commit", "-qam", "p4")
git(r, "checkout", "-q", "main"); git(r, "merge", "-q", "p3")
p = git(r, "merge", "p4", ok=False)
check(p.returncode != 0 and "<<<<<<< ours" in rd(r, "static/i18n/de.json") and '"A": "a-new"' in rd(r, "static/i18n/de.json"),
      "the same key changed differently on both sides stays a conflict with markers")
git(r, "merge", "--abort")
git(r, "checkout", "-q", "-b", "p5", base2)
put(r, "static/sw.js", SW.replace("self.x = 1;", "self.x = 5;")); git(r, "commit", "-qam", "p5")
git(r, "checkout", "-q", "main"); git(r, "checkout", "-q", "-b", "p6", base2)
put(r, "static/sw.js", SW.replace("self.x = 1;", "self.x = 6;")); git(r, "commit", "-qam", "p6")
git(r, "checkout", "-q", "main"); git(r, "merge", "-q", "p5")
p = git(r, "merge", "p6", ok=False)
check(p.returncode != 0 and rd(r, "static/sw.js").count("<<<<<<<") == 1, "code outside the sw.js lists: a normal conflict")
git(r, "merge", "--abort")
# the generator / check against index.html + lazyload.js
put(r, "static/index.html", '<script src="/static/js/a.js"></script>\n<script src="/static/js/n.js"></script>\n')
p = subprocess.run([sys.executable, os.path.join(r, "tools", "sw_lists.py"), "--check"], capture_output=True, text=True)
check(p.returncode == 1, "sw_lists.py --check: red when index.html has a module sw.js does not")
p = subprocess.run([sys.executable, os.path.join(r, "tools", "sw_lists.py")], capture_output=True, text=True)
check(p.returncode == 0 and "'/static/js/n.js']" in rd(r, "static/sw.js"), "sw_lists.py rewrites the lists from the sources")
check(subprocess.run([sys.executable, os.path.join(r, "tools", "sw_lists.py"), "--check"]).returncode == 0, "then --check is green")
shutil.rmtree(r, ignore_errors=True)
# the real tree
check(subprocess.run([sys.executable, os.path.join(ROOT, "tools", "sw_lists.py"), "--check"], capture_output=True).returncode == 0,
      "the repo's sw.js lists match index.html + lazyload.js")
check(subprocess.run([sys.executable, os.path.join(ROOT, "tools", "i18n_merge.py"), "--selftest"], capture_output=True).returncode == 0,
      "i18n_merge.py --selftest")
ga = open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8").read()
check("static/i18n/*.json merge=i18n" in ga and "static/sw.js merge=swlists" in ga and "tests/skip.txt merge=union" in ga, ".gitattributes names the drivers")

print(f"p2321_b_merge: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
