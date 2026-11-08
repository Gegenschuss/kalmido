#!/usr/bin/env python3
"""2.755.0 (#5261): no silent green in tests/ - the static part of tests/p2501_a_nosham_test.py (2.501.0, #4296) as a lint step.

It was red in the full CI only (#4731, #5131, tests/p4528_b_restore_test.py in 2.740.0); now it runs in the lint (seconds, no
container) and the suite calls this same logic (its ff.js and run_all.sh parts need node / bash and stay there).

  - tests/*.py / *.js: no check that cannot fail (`check(True`, `.ok or True`, `else True,` in a check, `|| true,`,
    `: true, '...'`); the ones with a reason stand in ALLOWED with it (a line there whose piece is gone is a finding too)
  - a status list that takes success and refusal (`status_code in (201, 409)`) passes either way: say which one is right.
    MIXED_OLD (the old ones) may only shrink; it is empty since 2.663.0 (#4341)
  - a test that asks for Firefox itself (execFileSync('firefox' ...) instead of tests/ff.js

usage: python3 tools/check_nosham.py [-v]      exit 1 on a finding
Standard library only.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ME = "tools/check_nosham.py"
SKIP = {"p2501_a_nosham_test.py"}  # it quotes the forms on purpose (its self checks of this logic)
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
    ("p2641_c_weekly_test.py", 'check(True, f"safe_path refuses {bad}")'): "counts the expected ValueError; the try fails with check(False)",  # 2.663.0 (#4341)
}
# 2.501.0 (#4296): the old ones, one by one into real checks; (file, status codes)
# 2.663.0 (#4341): emptied - every old list now names the one right code (or < 500 where only 'no crash' is meant)
MIXED_OLD = set()


def sham(fn, line):
    """The reason a line is a check that cannot fail, or None."""
    rx = SHAM_JS if fn.endswith(".js") else SHAM_PY
    code = re.sub(r"(^|\s)(#|//)\s.*$", "", line)  # a comment may quote the old form
    if not rx.search(code):
        return None
    return None if any(f == fn and piece in line for f, piece in ALLOWED) else line.strip()[:110]


def mixed(line):
    """The status lists of a line that take success and refusal: ['201, 409', ...]."""
    return [re.search(r"\((.*)\)", m.group(0)).group(1) for m in MIXED.finditer(line)]


def file_findings(fn, src, mixed_now=None):
    """The findings of one test file (fn: its name in tests/, src: its text)."""
    bad = []
    for no, line in enumerate(src.split("\n"), 1):
        s = sham(fn, line)
        if s:
            bad.append(f"tests/{fn}:{no}: a check that cannot fail: {s} - make it a real one, or name the reason in {ME} ALLOWED")
        for codes in mixed(line):
            if mixed_now is not None:
                mixed_now.add((fn, codes))
            if (fn, codes) not in MIXED_OLD:
                bad.append(f"tests/{fn}:{no}: status_code in ({codes}) passes on success and on refusal - say which one is right")
    if fn.endswith(".js") and fn != "ff.js" and ("execFileSync('firefox'" in src or "spawnSync('firefox'" in src):
        bad.append(f"tests/{fn}: asks for Firefox itself, without it nothing would fail: use tests/ff.js (firefox or noFirefox)")
    return bad


def findings(root=ROOT):
    """Every finding in root/tests as lines (empty: all fine)."""
    tests = os.path.join(root, "tests")
    bad, mixed_now = [], set()
    for fn in sorted(f for f in os.listdir(tests) if f.endswith((".py", ".js")) and f not in SKIP):
        with open(os.path.join(tests, fn), encoding="utf-8", errors="replace") as f:
            bad += file_findings(fn, f.read(), mixed_now)
    for f, c in sorted(MIXED_OLD - mixed_now):
        bad.append(f"{ME} MIXED_OLD: {f} ({c}) is gone - take the line out, the list only shrinks")
    for f, piece in sorted(ALLOWED):
        p = os.path.join(tests, f)
        if not os.path.exists(p) or piece not in open(p, encoding="utf-8").read():
            bad.append(f"{ME} ALLOWED: {f} {piece!r} is gone - take the line out")
    return bad


if __name__ == "__main__":
    out = findings()
    for x in out:
        print(x)
    if "-v" in sys.argv or out:
        print(f"check_nosham: {len(ALLOWED)} allowed line(s), {len(out)} finding(s)")
    sys.exit(1 if out else 0)
