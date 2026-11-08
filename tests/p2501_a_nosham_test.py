#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.501.0 (#4296): no silent green. Static, no container (the run_all.sh case runs the real script with a stubbed docker and suites).
 - tests/*: no check that cannot fail (`check(True`, `.ok or True`, `else True,` in a check, `|| true,`, `: true, '...'`); the ones
   with a reason stand in ALLOWED with it. A status list that takes success and refusal (`in (201, 409)`) is frozen: MIXED_OLD
   may only shrink, a new one fails here. A check that passes either way says nothing.
 - the Firefox question lives in tests/ff.js only; without Firefox a check fails, KALMIDO_SKIP_FIREFOX=1 gives a skip line
 - tests/run_all.sh writes SKIPPED / PARTLY SKIPPED suites before its last line, which stays what a test runner reads
usage: p2501_a_nosham_test.py"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from kt import FAILS, OKS, check

HERE = os.path.dirname(os.path.abspath(__file__))
ME = os.path.basename(__file__)
SHAM_PY = re.compile(r"\bcheck\(True\b|\bor True\b|\belse True\s*,")
SHAM_JS = re.compile(r"\bcheck\(true\b|\|\|\s*true\s*,|\bcheck\([^;]*\?[^;:]*:\s*true\s*,\s*['\"`]")
MIXED = re.compile(r"status_code in \((?=[^)]*\b2\d\d\b)(?=[^)]*\b[34]\d\d\b)[^)]*\)")
# (file, a piece of the line): the check can fail or the line is no check, and why
ALLOWED = {
    ("api_v1_test.py", 'check(True, "spec valid")'): "after validate(spec), which raises; the except branch fails",
    ("p2103_c_api_test.py", 'check(True, "")'): "counts the expected foreign key error; the try fails with check(False)",
    ("p2154_b_ubl_test.py", 'check(True, "")'): "counts the expected BadInput; the try fails with check(False)",
    ("p248_b_unit_test.py", 'check(True, "")'): "counts the expected RuleError; the try fails with check(False)",
    ("p2191_f2_i18nrobust_test.py", "check(True, "): "counts the expected error; the try fails with check(False)",
    ("pg_layer_test.py", "check(True, "): "counts the expected exception; the try fails with check(False)",
    ("webpush_test.py", 'check(True, "")'): "after verify(), which raises; the except branch fails",
    ("usage_hook_test.py", 'check(True, "released again'): "StateLock raises when it is not released",
    ("backup_test.py", "== code if code else True"): "not a check of its own: the code is compared when the case names one",
    ("p290_c_api_test.py", "if due30.month != d30.month else True"): "only a due date in another month has this rule",
    ("p2239_d_aufbewahrung_test.py", "list_purge(c, {LID}, None)[0] is None or True"): "a line of Python for the container, it only prints",
    ("p21481_c_api_test.py", "push.ntfy = lambda"): "a stub that returns true, no check",
}
# 2.501.0 (#4296): the old ones, one by one into real checks (task in the job's result); (file, status codes)
# 2.663.0 (#4341): emptied - every old list now names the one right code (or < 500 where only 'no crash' is meant)
MIXED_OLD = set()


def sham(fn, line):
    """The reason a line is a check that cannot fail, or None."""
    rx = SHAM_JS if fn.endswith(".js") else SHAM_PY
    code = re.sub(r"(^|\s)(#|//)\s.*$", "", line)  # a comment may quote the old form
    if not rx.search(code):
        return None
    return None if any(f == fn and piece in line for f, piece in ALLOWED) else line.strip()[:110]


# the rules themselves: red on the old forms, quiet on real checks
for bad in ('assert r.ok or True', 'check(x == 1 if y else True, "z")', 'check(True, "z")'):
    check(sham("x_test.py", bad), f"self check: {bad} is found")
for bad in ("check(/a/.test(t) || true, 'z');", "check(true, 'z');", "check(a ? b : true, 'z');"):
    check(sham("x_ui.js", bad), f"self check: {bad} is found")
for good in ('check(r.ok, "z")', 'check(a == 1 if b else c == 2, "z")', '# or True in a comment'):
    check(not sham("x_test.py", good), f"self check: {good} stays quiet")

names = sorted(f for f in os.listdir(HERE) if f.endswith((".py", ".js")) and f != ME)
mixed_now = set()
for fn in names:
    src = open(os.path.join(HERE, fn), encoding="utf-8", errors="replace").read()
    for no, line in enumerate(src.split("\n"), 1):
        s = sham(fn, line)
        check(not s, f"{fn}:{no}: a check that cannot fail: {s} - make it a real one, or name the reason in {ME} ALLOWED")
        for m in MIXED.finditer(line):
            codes = re.search(r"\((.*)\)", m.group(0)).group(1)
            mixed_now.add((fn, codes))
            check((fn, codes) in MIXED_OLD, f"{fn}:{no}: status_code in ({codes}) passes on success and on refusal - say which one is right")
    if fn.endswith(".js") and fn != "ff.js":
        check("execFileSync('firefox'" not in src and "spawnSync('firefox'" not in src, f"{fn}: asks for Firefox itself, without it nothing would fail: use tests/ff.js (firefox or noFirefox)")
for f, c in sorted(MIXED_OLD - mixed_now):
    check(False, f"{ME} MIXED_OLD: {f} ({c}) is gone - take the line out, the list only shrinks")
for f, piece in ALLOWED:
    check(os.path.exists(os.path.join(HERE, f)) and piece in open(os.path.join(HERE, f), encoding="utf-8").read(), f"{ME} ALLOWED: {f} {piece!r} is gone - take the line out")

# ---- Firefox missing: red; KALMIDO_SKIP_FIREFOX=1: a skip line. With a PATH that has no firefox, the real ff.js
NODE = shutil.which("node")
tmp = tempfile.mkdtemp(prefix="p2501a-")
PROBE = """const bad = []; let ran = 0;
require(%r)({tag: 'probe', check: (c, m) => { if (!c) bad.push(m); }})(async () => { ran = 1; }).then(() => { console.log(JSON.stringify({bad, ran})); process.exit(0); });""" % os.path.join(HERE, "ff.js")
empty = os.path.join(tmp, "nobin")
os.makedirs(empty)
env = {k: v for k, v in os.environ.items() if k != "KALMIDO_SKIP_FIREFOX"}
env["PATH"] = empty
r = subprocess.run([NODE, "-e", PROBE], env=env, cwd=HERE, capture_output=True, text=True, timeout=60)
check(r.returncode == 0 and '"ran":0' in r.stdout and "no firefox on PATH" in r.stdout, f"ff.js without firefox: a failed check, the part does not run: {r.stdout[-300:]} {r.stderr[-300:]}")
r = subprocess.run([NODE, "-e", PROBE], env=dict(env, KALMIDO_SKIP_FIREFOX="1"), cwd=HERE, capture_output=True, text=True, timeout=60)
check(r.returncode == 0 and '"bad":[]' in r.stdout and "Firefox part skipped" in r.stdout, f"ff.js with KALMIDO_SKIP_FIREFOX=1: no failure, a skip line: {r.stdout[-300:]} {r.stderr[-300:]}")

# ---- tests/run_all.sh: the real script in a folder of its own, with stub suites and a docker that does nothing
box = os.path.join(tmp, "t")
os.makedirs(box)
shutil.copy(os.path.join(HERE, "run_all.sh"), box)
LIST = r"""fresh; run s_ok bash -c 'echo fine; echo the skip link; echo skipped_files 1; echo 3 ok, 0 skipped'
run s_part bash -c 'echo "s_part: Firefox part skipped (KALMIDO_SKIP_FIREFOX=1)"'
run s_tool bash -c 'echo "s_tool: SKIP (no pwsh)"'
run s_gone bash -c 'echo never'
"""
stubs = {"suites.py": "import sys\nsys.stdout.write(open(sys.argv[0].replace('suites.py', 'list.txt')).read())\n", "list.txt": LIST,
         "skip.txt": "s_gone 2099-12-31 #1 flaky\n", "start.sh": "exit 0\n"}
for name, text in stubs.items():
    with open(os.path.join(box, name), "w", encoding="utf-8") as f:
        f.write(text)
bindir = os.path.join(tmp, "bin")
os.makedirs(bindir)
docker = os.path.join(bindir, "docker")
with open(docker, "w", encoding="utf-8") as f:
    f.write("#!/bin/sh\nexit 0\n")
os.chmod(docker, os.stat(docker).st_mode | stat.S_IEXEC)
base = {k: v for k, v in os.environ.items() if k not in ("ONLY", "ONLY_GROUPS", "KALMIDO_SHARD_PLAN", "KALMIDO_LIST_ONLY", "GITHUB_ACTIONS", "BUILD")}
base.update(PATH=bindir + os.pathsep + os.environ["PATH"], KALMIDO_TIMINGS=os.path.join(tmp, "timings.csv"), KALMIDO_TEST_DATA=os.path.join(tmp, "data"), PYTHON=sys.executable)


def run_all(**extra):
    p = subprocess.run(["bash", os.path.join(box, "run_all.sh")], env=dict(base, **extra), capture_output=True, text=True, timeout=120)
    return p.returncode, [x for x in p.stdout.split("\n") if x]


rc, out = run_all()
check(rc == 0 and out[-1] == "ALL SUITES PASSED", f"run_all: the last line stays as it is {rc} {out[-3:]}")
check("SKIPPED suites (1): s_gone" in out, f"run_all: names the suite of skip.txt {out[-4:]}")
check("PARTLY SKIPPED suites (2): s_part s_tool" in out, f"run_all: names the suites with a skip line, not s_ok {out[-4:]}")
check(any("Firefox part skipped" in x and x.startswith(" ") for x in out), f"run_all: says what was skipped under the suite {out}")
check(not any(x.startswith("::warning") for x in out), "run_all: no annotation outside GitHub")
rc, out = run_all(GITHUB_ACTIONS="true")
check(any(x.startswith("::warning") and "s_gone" in x and "s_part" in x for x in out), f"run_all: an annotation on GitHub {out[-4:]}")
with open(os.path.join(box, "list.txt"), "a", encoding="utf-8") as f:
    f.write("run s_bad bash -c 'exit 3'\n")
rc, out = run_all()
check(rc == 1 and out[-1] == "FAILED suites: s_bad" and "SKIPPED suites (1): s_gone" in out, f"run_all: red names the skipped ones too {rc} {out[-4:]}")
shutil.rmtree(tmp, ignore_errors=True)

print(f"p2501_a_nosham: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
