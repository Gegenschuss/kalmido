#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.755.0 part D (#5294) tools/ruff_baseline.py: ruff is red for NEW findings only; no container, no ruff needed (the tool
reads ruff's JSON output, written here by hand):
 1. a known finding (same file, rule and code line) is green
 2. a new finding is red (exit 1, one ::error line with file and line)
 3. the known finding on another line (code moved, other indentation) is green; in another file / under another rule it is new
 4. counted, not a set: a second copy of a known line in the same file is new
 5. an entry without a finding is a notice (green), red with --strict; most entries gone at once is red (scan broken)
 6. --update writes the baseline from the output (and that output is then green)
 7. the repo: ci.yml installs the ruff version ruff.toml names, runs this tool; the baseline is well formed
 8. #5294: no silent `except Exception: pass` in kalmido/ without a reason (a comment after the noqa marker, or a log)
usage: python3 tests/p2755_d_ruff_baseline_test.py"""
import json
import os
import re
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(N, ".."))
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402

TOOL = os.path.join(ROOT, "tools", "ruff_baseline.py")
SRC = {"kalmido/a.py": "import os\nx = 1\n\n\n\nimport sys\n", "kalmido/b.py": "import os\n"}


def item(path, row, code="F401", msg="`os` imported but unused"):
    return {"code": code, "filename": path, "location": {"row": row, "column": 1}, "message": msg}


def run(results, files=None, base=None, *flags):
    """(exit code, output, baseline after) of the tool on a temp tree with files {path: text}; base: the results the
    baseline is made of first (--update), None = no baseline."""
    with tempfile.TemporaryDirectory() as d:
        for rel, text in (files or SRC).items():
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
            with open(os.path.join(d, rel), "w", encoding="utf-8") as f:
                f.write(text)
        rj, bj = os.path.join(d, "ruff.json"), os.path.join(d, "baseline.json")
        if base is not None:
            with open(rj, "w", encoding="utf-8") as f:
                json.dump(base, f)
            subprocess.run([sys.executable, TOOL, rj, "--baseline", bj, "--root", d, "--update"], check=True, capture_output=True)
        with open(rj, "w", encoding="utf-8") as f:
            json.dump(results, f)
        r = subprocess.run([sys.executable, TOOL, rj, "--baseline", bj, "--root", d, *flags], capture_output=True, text=True)
        after = json.load(open(bj, encoding="utf-8")) if os.path.exists(bj) else None
        return r.returncode, r.stdout + r.stderr, after


KNOWN = item("kalmido/a.py", 1)

# 1. known = green
rc, out, _ = run([KNOWN], base=[KNOWN])
check(rc == 0 and "1 known, 0 new" in out and "::error" not in out, f"a known finding is green: {rc} {out[-300:]}")

# 2. new = red with the annotation
rc, out, _ = run([KNOWN, item("kalmido/a.py", 6, msg="`sys` imported but unused")], base=[KNOWN])
check(rc == 1 and "::error file=kalmido/a.py,line=6" in out and "1 new" in out, f"a new finding is red: {out[-200:]}")

# 3. moved = green; other file / other rule = new
moved = {"kalmido/a.py": "\n\n\n    import os  \nx = 1\n", "kalmido/b.py": "import os\n"}
with tempfile.TemporaryDirectory() as d:
    for rel, text in SRC.items():
        os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
        open(os.path.join(d, rel), "w", encoding="utf-8").write(text)
    rj, bj = os.path.join(d, "ruff.json"), os.path.join(d, "baseline.json")
    json.dump([KNOWN], open(rj, "w", encoding="utf-8"))
    subprocess.run([sys.executable, TOOL, rj, "--baseline", bj, "--root", d, "--update"], check=True, capture_output=True)
    for rel, text in moved.items():  # the code moves down three lines and gets indented
        open(os.path.join(d, rel), "w", encoding="utf-8").write(text)
    json.dump([item("kalmido/a.py", 4)], open(rj, "w", encoding="utf-8"))
    r = subprocess.run([sys.executable, TOOL, rj, "--baseline", bj, "--root", d], capture_output=True, text=True)
    check(r.returncode == 0 and "1 known, 0 new" in r.stdout, f"a moved line is still known: {r.stdout[-300:]}")
rc, out, _ = run([item("kalmido/b.py", 1)], base=[KNOWN])
check(rc == 1, "the same code in another file is new")
rc, out, _ = run([item("kalmido/a.py", 1, code="E401")], base=[KNOWN])
check(rc == 1, "the same line under another rule is new")

# 4. counted: a second copy of the known line in the same file
two = {"kalmido/a.py": "import os\nimport os\n", "kalmido/b.py": ""}
rc, out, _ = run([item("kalmido/a.py", 1), item("kalmido/a.py", 2)], files=two, base=[item("kalmido/a.py", 1)])
check(rc == 1 and "1 new" in out, f"a second copy of a known line is new: {out[-200:]}")

# 5. stale: notice, --strict red; most gone at once red
rc, out, _ = run([], base=[KNOWN])
check(rc == 0 and "::notice" in out and "1 stale" in out, f"a stale entry is a notice only: {rc} {out[-300:]}")
rc, out, _ = run([], None, [KNOWN], "--strict")
check(rc == 1, "--strict: a stale entry is red")
many = {"kalmido/a.py": "".join(f"import m{i}\n" for i in range(120)), "kalmido/b.py": ""}
rc, out, _ = run([], files=many, base=[item("kalmido/a.py", i + 1) for i in range(120)])
check(rc == 1 and "gone at once" in out, f"all findings gone at once is red (lint broken): {out[-300:]}")
rc, out, _ = run({"not": "a list"}, base=[KNOWN])
check(rc == 1 and "not a JSON list" in out, "an output that is no list is red")

# 6. --update
rc, out, after = run([KNOWN], None, [KNOWN, item("kalmido/b.py", 1)])
check(rc == 0 and after and set(after["files"]) == {"kalmido/a.py", "kalmido/b.py"}, f"--update writes every finding: {after}")

# 7. the repo
ci = open(os.path.join(ROOT, ".github/workflows/ci.yml"), encoding="utf-8").read()
toml = open(os.path.join(ROOT, "ruff.toml"), encoding="utf-8").read()
pin = re.search(r"pip install ruff==(\d+\.\d+\.\d+)", ci)
check(pin and f"ruff=={pin.group(1)}" in toml, f"ci.yml installs the ruff version ruff.toml names: {pin and pin.group(1)}")
check("python tools/ruff_baseline.py /tmp/ruff.json" in ci and "--exit-zero" in ci, "ci.yml compares with the baseline")
check(re.search(r'select = \["E", "F", "BLE"\]', toml) and "line-length = 130" in toml, "ruff.toml: E, F, BLE, 130")
check(re.search(r'ignore = \["E501"\]', toml), "ruff.toml: E501 is out of the gate (2.755.0, #5294 - an edit of one of ~39 500 long lines would be new)")
base = json.load(open(os.path.join(ROOT, "tools", "ruff_baseline.json"), encoding="utf-8"))
bad = [(f, r) for f, rules in base["files"].items() for r, hs in rules.items()
       if not all(re.fullmatch(r"[0-9a-f]{12}", h) for h in hs) or not os.path.exists(os.path.join(ROOT, f))]
check(not bad, f"the baseline: 12-digit hashes, every file exists: {bad[:3]}")

# 8. no silent except-pass without a reason in kalmido/
silent = []
for d, _, fs in os.walk(os.path.join(ROOT, "kalmido")):
    for fn in fs:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(d, fn)
        lines = open(p, encoding="utf-8").read().split("\n")
        for i, s in enumerate(lines[:-1]):
            m = re.match(r"\s*except (?:Exception|BaseException)(?:\s+as\s+\w+)?:\s*(#.*)?$", s)
            if m and lines[i + 1].strip() == "pass":
                why = re.sub(r"noqa:\s*[A-Z0-9, ]+", "", (m.group(1) or "").lstrip("#")).strip(" -()")
                if len(why) < 8:
                    silent.append(f"{os.path.relpath(p, ROOT)}:{i + 1}")
check(not silent, f"every `except Exception: pass` in kalmido/ names its reason: {silent[:5]} ({len(silent)})")

print(f"p2755_d_ruff_baseline: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
