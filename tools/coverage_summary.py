#!/usr/bin/env python3
"""#5298 (Profi-Bewertung F14): the coverage figure of the full CI run and the modules without any coverage.

Reads the JSON report of `coverage json` (data of all shards combined, paths mapped to the checkout by tests/coveragerc)
and the server's source tree (app.py + kalmido/**/*.py). A module counts as "without any coverage" when not one of its
lines ran during the suites - also when the server never imported it (then it is missing from the report altogether).
No gate (decision 08.11.2026): always exits 0; the figure is a floor (tools/cov_boot.py: SIGKILLed containers lose their
last seconds, isolated sub-processes are not measured).

usage:
  python3 tools/coverage_summary.py REPORT.json [--zero-out FILE]   Markdown on stdout ($GITHUB_STEP_SUMMARY),
                                                                    the zero list (one path per line) into FILE
  python3 tools/coverage_summary.py --selftest
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOW_ZERO = 80  # the summary names at most this many modules; the full list is the artifact file


def sources(root=ROOT):
    """-> sorted repo-relative paths of the measured server code (app.py and every kalmido/**/*.py with code in it)."""
    out = ["app.py"] if os.path.isfile(os.path.join(root, "app.py")) else []
    for d, dirs, files in os.walk(os.path.join(root, "kalmido")):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for f in sorted(files):
            if f.endswith(".py"):
                p = os.path.join(d, f)
                if os.path.getsize(p) > 0:
                    out.append(os.path.relpath(p, root).replace(os.sep, "/"))
    return sorted(out)


def summarise(report, srcs):
    """-> (percent or None, measured statements, covered statements, zero list) from a coverage JSON report."""
    files = {}
    for path, f in (report.get("files") or {}).items():
        p = path.replace(os.sep, "/")
        for pre in ("/app/", ROOT.replace(os.sep, "/") + "/"):
            if p.startswith(pre):
                p = p[len(pre):]
        files[p] = f.get("summary") or {}
    tot = report.get("totals") or {}
    pct = tot.get("percent_covered")
    zero = [s for s in srcs if not (files.get(s) or {}).get("covered_lines")]
    return pct, tot.get("num_statements", 0), tot.get("covered_lines", 0), zero


def markdown(pct, stmts, covered, zero, total_files):
    lines = ["### Test coverage of the server (Python)", ""]
    if pct is None:
        lines.append("_No coverage data - the shards wrote none (see the step log)._")
    else:
        lines.append(f"**{pct:.1f} %** of {stmts} statements ran during the suites ({covered} covered) - a floor, no gate.")
    lines += ["", f"**{len(zero)} of {total_files} modules without any coverage**" + (":" if zero else "."), ""]
    lines += [f"- `{z}`" for z in zero[:SHOW_ZERO]]
    if len(zero) > SHOW_ZERO:
        lines.append(f"- ... and {len(zero) - SHOW_ZERO} more (artifact coverage-report, zero-coverage.txt)")
    return "\n".join(lines) + "\n"


def selftest():
    import tempfile
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "kalmido", "a", "__pycache__"))
    for rel, body in (("app.py", "x = 1\n"), ("kalmido/__init__.py", ""), ("kalmido/a/one.py", "y = 2\n"),
                      ("kalmido/a/two.py", "z = 3\n"), ("kalmido/a/__pycache__/one.py", "q = 1\n")):
        with open(os.path.join(d, rel), "w", encoding="utf-8") as fh:
            fh.write(body)
    srcs = sources(d)
    assert srcs == ["app.py", "kalmido/a/one.py", "kalmido/a/two.py"], srcs
    rep = {"totals": {"percent_covered": 41.25, "num_statements": 80, "covered_lines": 33},
           "files": {"/app/app.py": {"summary": {"covered_lines": 1}},
                     "/app/kalmido/a/one.py": {"summary": {"covered_lines": 0}}}}
    pct, st, cv, zero = summarise(rep, srcs)
    assert (pct, st, cv) == (41.25, 80, 33) and zero == ["kalmido/a/one.py", "kalmido/a/two.py"], zero
    md = markdown(pct, st, cv, zero, len(srcs))
    assert "**41.2 %**" in md and "2 of 3 modules" in md and "`kalmido/a/two.py`" in md, md
    assert "No coverage data" in markdown(None, 0, 0, srcs, 3)
    print("coverage_summary selftest: ok")
    return 0


def main(argv):
    if argv[1:2] == ["--selftest"]:
        return selftest()
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 0
    try:
        with open(argv[1], encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"coverage_summary: no report ({e})", file=sys.stderr)
        report = {}
    srcs = sources()
    pct, stmts, covered, zero = summarise(report, srcs)
    if "--zero-out" in argv:
        with open(argv[argv.index("--zero-out") + 1], "w", encoding="utf-8") as fh:
            fh.write("".join(z + "\n" for z in zero))
    sys.stdout.write(markdown(pct, stmts, covered, zero, len(srcs)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
