#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.543.0 (#4625) tools/semgrep_baseline.py: semgrep is red for NEW findings only; no container:
 1. a known finding (an entry with the same rule, file and code) is green
 2. a new finding is red (exit 1, one ::error line with file and line)
 3. the known finding on another line (code shifted by an edit above it) is green
 4. an entry whose finding is gone is a notice only (green), red with --strict
 5. --accept writes the new finding into the baseline with the reason, the date and the task
 6. the baseline of the repo: every entry complete (rule, file, code, reason, date), no entry twice, every file exists
    and its code line is still in the file (else the entry is stale and the finding would be new)
usage: python3 tests/semgrep_baseline_test.py"""
import json
import os
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from kt import FAILS, OKS, check  # noqa: E402
from semgrep_baseline import norm, split_stale  # noqa: E402

TOOL = os.path.join(ROOT, "tools", "semgrep_baseline.py")
RULE = "python.flask.security.injection.tainted-sql-string.tainted-sql-string"


def result(path, line, code, rule=RULE):
    return {"check_id": rule, "path": path, "start": {"line": line, "col": 5}, "end": {"line": line, "col": 60},
            "extra": {"lines": code, "severity": "ERROR", "message": "Detected user input used to manually construct a SQL string."}}


def run(results, entries, *flags, files=None):
    """(exit code, output) of the tool with a results JSON and a baseline written into a temp folder (files: {path: text}
    of the scanned tree in it)."""
    with tempfile.TemporaryDirectory() as d:
        for rel, text in (files or {}).items():
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
            with open(os.path.join(d, rel), "w", encoding="utf-8") as f:
                f.write(text)
        rj, bj = os.path.join(d, "semgrep.json"), os.path.join(d, "baseline.json")
        with open(rj, "w", encoding="utf-8") as f:
            json.dump({"results": results, "errors": []}, f)
        with open(bj, "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f)
        r = subprocess.run([sys.executable, TOOL, rj, "--baseline", bj, "--root", d, *flags], capture_output=True, text=True)
        with open(bj, encoding="utf-8") as f:
            after = json.load(f)
        return r.returncode, r.stdout + r.stderr, after


KNOWN = result("kalmido/a.py", 10, '    rows = c.execute(f"SELECT * FROM users WHERE {where}", args)')
ENTRY = {"rule": RULE, "file": "kalmido/a.py", "code": norm(KNOWN["extra"]["lines"]), "reason": "fixed fragments", "date": "2026-11-05"}

# 1. known = green
rc, out, _ = run([KNOWN], [ENTRY])
check(rc == 0 and "1 known, 0 new" in out and "::error" not in out, f"a known finding is green: {rc} {out[-300:]}")

# 2. new = red, with the annotation
new = result("kalmido/b.py", 7, '    c.execute(f"DELETE FROM x WHERE {cond}")')
rc, out, _ = run([KNOWN, new], [ENTRY])
check(rc == 1 and "::error file=kalmido/b.py,line=7" in out and "1 new" in out, f"a new finding is red with file and line: {rc} {out[-400:]}")
check("kalmido/a.py" not in out.split("::error")[1].split("\n")[0], "the annotation names the new finding, not the known one")

# 3. the same code on another line (and with other indentation) = green
moved = result("kalmido/a.py", 42, '\t\trows = c.execute(f"SELECT * FROM users WHERE {where}",   args)')
rc, out, _ = run([moved], [ENTRY])
check(rc == 0 and "1 known, 0 new" in out, f"a shifted line is still known: {rc} {out[-300:]}")

# the same code in another file or under another rule = new
rc, out, _ = run([result("kalmido/c.py", 10, KNOWN["extra"]["lines"])], [ENTRY])
check(rc == 1, "the same code in another file is a new finding")
rc, out, _ = run([result("kalmido/a.py", 10, KNOWN["extra"]["lines"], rule="python.lang.security.audit.formatted-sql-query.formatted-sql-query")], [ENTRY])
check(rc == 1, "the same code under another rule is a new finding")

# 4. an entry without a finding: a notice, green; red with --strict
rc, out, _ = run([], [ENTRY])
check(rc == 0 and "::notice" in out and "1 stale" in out, f"a stale entry is a notice only: {rc} {out[-300:]}")
rc, out, _ = run([], [ENTRY], "--strict")
check(rc == 1 and "::error" in out, f"--strict makes a stale entry red: {rc} {out[-300:]}")
# 2.649.0 (#5056): an entry whose code line still stands in the file was only not reported (semgrep skips a rule / a big file
# on a timeout under load): told apart from a gone line; the check of a package's changed files (kalmido-semgrep.py) names
# only the gone ones
rc, out, _ = run([], [ENTRY], files={"kalmido/a.py": "def f(c, where, args):\n" + KNOWN["extra"]["lines"] + "\n"})
check(rc == 0 and "finding not reported" in out and "code line is gone" not in out, f"a still standing line: not reported, not gone: {rc} {out[-300:]}")
rc, out, _ = run([], [ENTRY], files={"kalmido/a.py": "def f(c, where, args):\n    rows = c.execute(\"SELECT 1\")\n"})
check(rc == 0 and "code line is gone" in out and "finding not reported" not in out, f"a changed line: gone: {rc} {out[-300:]}")
with tempfile.TemporaryDirectory() as d5056:
    os.makedirs(os.path.join(d5056, "kalmido"))
    with open(os.path.join(d5056, "kalmido", "a.py"), "w", encoding="utf-8") as f:
        f.write("x = 1\n" + KNOWN["extra"]["lines"] + "\n")
    other = dict(ENTRY, file="kalmido/b.py")
    g, k = split_stale([ENTRY, other], d5056)
    check(k == [ENTRY] and g == [other], f"split_stale: the standing line is kept, a missing file is gone: {g} {k}")

# 2.543.0 review: counted, a second occurrence of a known code line in the same file is new
rc, out, _ = run([KNOWN, moved], [ENTRY])
check(rc == 1 and "1 new" in out, f"a second occurrence of a known line is new: {rc} {out[-300:]}")
# a semgrep error, a missing results list, nothing scanned or most known findings gone at once = red, never a clean tree
tmp_dir = tempfile.mkdtemp()
def raw(obj, entries):
    rp, bp = os.path.join(tmp_dir, "r.json"), os.path.join(tmp_dir, "b.json")
    json.dump(obj, open(rp, "w")); json.dump({"entries": entries}, open(bp, "w"))
    pr = subprocess.run([sys.executable, TOOL, rp, "--baseline", bp, "--root", ROOT], capture_output=True, text=True)
    return pr.returncode, pr.stdout
rc, out = raw({"results": [], "errors": [{"level": "error", "message": "boom"}]}, [ENTRY])
check(rc == 1, f"a semgrep error is red: {rc} {out[-300:]}")
rc, out = raw({"errors": []}, [ENTRY])
check(rc == 1, f"no results list is red: {rc} {out[-300:]}")
rc, out = raw({"results": [], "errors": [], "paths": {"scanned": []}}, [ENTRY])
check(rc == 1, f"nothing scanned is red: {rc} {out[-300:]}")
many = [dict(ENTRY, code=f"x = {i}") for i in range(12)]
rc, out = raw({"results": [], "errors": []}, many)
check(rc == 1 and "scan broken" in out, f"most known findings gone at once is red: {rc} {out[-300:]}")

# 2.543.0 review: .zap/rules.tsv ignores plugin 10055 (CSP) as a whole, so ZAP would not see a weaker CSP - the app's
# CSP is pinned here instead: own scripts only, no eval, no plugins, no framing, no base tag
import re  # noqa: E402
_src = open(os.path.join(ROOT, "kalmido", "core", "pages.py"), encoding="utf-8").read()
_m = re.search(r"^CSP = \((.*?)\)\s*$", _src, re.S | re.M)
_csp = "".join(re.findall(r'"([^"]*)"', _m.group(1))) if _m else ""
_dir = {d.split()[0]: d.split()[1:] for d in (x.strip() for x in _csp.split(";")) if d}
check(_dir.get("script-src") == ["'self'"] and _dir.get("default-src") == ["'self'"], f"CSP script-src / default-src stay 'self': {_dir}")
check(_dir.get("object-src") == ["'none'"] and _dir.get("frame-ancestors") == ["'none'"] and _dir.get("base-uri") == ["'none'"],
      f"CSP object-src / frame-ancestors / base-uri stay 'none': {_dir}")
check("'unsafe-eval'" not in _csp and "*" not in _csp, f"CSP without unsafe-eval or wildcards: {_csp}")

# 2.551.0 (#4625): semgrep without a sign-in writes "requires login" into extra.lines instead of the code (CI v2.551.0:
# 65 known findings all new): the code line comes from the file, the placeholder never counts as code
SRC = "\n" * 9 + KNOWN["extra"]["lines"] + "\n"
login = {**KNOWN, "extra": {**KNOWN["extra"], "lines": "requires login"}}
rc, out, _ = run([login], [ENTRY], files={"kalmido/a.py": SRC})
check(rc == 0 and "1 known, 0 new" in out, f"'requires login' in extra.lines: the line is read from the file, known: {rc} {out[-300:]}")
moved = {**login, "start": {"line": 12, "col": 5}}
rc, out, _ = run([moved], [ENTRY], files={"kalmido/a.py": "\n" * 2 + SRC})
check(rc == 0 and "1 known, 0 new" in out, f"'requires login', the code two lines lower: still known: {rc} {out[-300:]}")
rc, out, _ = run([{**login, "path": "kalmido/gone.py"}], [ENTRY])
check(rc == 1 and "1 new" in out, f"'requires login' without the file: no code to match, new (red), never matched by the placeholder: {rc} {out[-300:]}")
lone = {**ENTRY, "code": "requires login"}
rc, out, _ = run([{**login, "path": "kalmido/gone.py"}], [{**lone, "file": "kalmido/gone.py"}])
check(rc == 1, f"an entry with the placeholder as code matches nothing: {rc} {out[-300:]}")

# 5. --accept writes the new finding into the baseline
rc, out, after = run([KNOWN, new], [ENTRY], "--accept", "a '?' list", "--task", "4625")
added = [e for e in after["entries"] if e["file"] == "kalmido/b.py"]
check(rc == 0 and len(after["entries"]) == 2 and added and added[0]["reason"] == "a '?' list" and added[0]["task"] == 4625
      and added[0]["code"] == norm(new["extra"]["lines"]) and len(added[0]["date"]) == 10, f"--accept adds the finding with reason, task and date: {rc} {after}")
rc, out, _ = run([KNOWN, new], after["entries"])
check(rc == 0 and "2 known, 0 new" in out, "the accepted finding is known from then on")

# an incomplete entry (no reason) is refused
rc, out, _ = run([KNOWN], [dict(ENTRY, reason="")])
check(rc != 0 and "without rule/file/code/reason/date" in out, f"an entry without a reason is refused: {rc} {out[-200:]}")

# a finding without extra.lines: the code comes from the file
with tempfile.TemporaryDirectory() as d:
    os.makedirs(os.path.join(d, "kalmido"))
    with open(os.path.join(d, "kalmido", "a.py"), "w", encoding="utf-8") as f:
        f.write("x = 1\n" + KNOWN["extra"]["lines"] + "\n")
    rj, bj = os.path.join(d, "r.json"), os.path.join(d, "b.json")
    with open(rj, "w", encoding="utf-8") as f:
        json.dump({"results": [result("kalmido/a.py", 2, "")]}, f)
    with open(bj, "w", encoding="utf-8") as f:
        json.dump({"entries": [ENTRY]}, f)
    r = subprocess.run([sys.executable, TOOL, rj, "--baseline", bj, "--root", d], capture_output=True, text=True)
    check(r.returncode == 0 and "1 known" in r.stdout, f"without extra.lines the code line is read from the file: {r.stdout[-200:]}")

# 6. the baseline of the repo
with open(os.path.join(ROOT, "tools", "semgrep_baseline.json"), encoding="utf-8") as f:
    real = json.load(f)["entries"]
keys = [(e.get("rule"), e.get("file"), e.get("code")) for e in real]
check(real and all(all(str(e.get(k) or "").strip() for k in ("rule", "file", "code", "reason", "date")) for e in real), "every entry of the repo's baseline is complete")
check(len(keys) == len(set(keys)), f"no entry twice: {[k for k in keys if keys.count(k) > 1][:2]}")
check(all(len(str(e["date"])) == 10 and str(e["date"])[4] == "-" for e in real), "every date is YYYY-MM-DD")
check(all(not str(e.get("task") or "").strip() or isinstance(e["task"], int) for e in real), "a task is a number")
missing, gone = [], []
for e in real:
    p = os.path.join(ROOT, e["file"])
    if not os.path.exists(p):
        missing.append(e["file"])
        continue
    with open(p, encoding="utf-8", errors="replace") as f:
        if not any(norm(s) == e["code"] for s in f):
            gone.append(f"{e['file']}: {e['code'][:60]}")
check(not missing, f"every file of the baseline exists: {missing[:3]}")
check(not gone, f"every code line of the baseline is still in its file (else remove the entry / re-add the finding): {gone[:3]}")
rc, out, _ = run([result(e["file"], 1, e["code"], rule=e["rule"]) for e in real], real)
check(rc == 0 and f"{len(real)} known, 0 new" in out, f"the repo's baseline matches itself: {out[-200:]}")

print(f"semgrep_baseline: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
