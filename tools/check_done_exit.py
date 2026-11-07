#!/usr/bin/env python3
"""2.623.0 (#4950): a tests/*.py file must not end with a bare done(...) / kt.done(...) at module level.

kt.done() only returns 1 for a red case; without sys.exit(done(...)) the suite exits 0 and run_all.sh (which reads the exit
code) stays green. Runs inside tools/check_layout.py (CI lint) and on its own:

usage: python3 tools/check_done_exit.py [DIR]    exit code 1 when a file ends with a bare done(...)   (DIR: default tests/)
"""
import ast
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def errors(tests_dir=None):
    """List of error strings, one per tests/*.py file whose last module-level statement is a bare done(...) call."""
    out = []
    for p in sorted(glob.glob(os.path.join(tests_dir or os.path.join(ROOT, "tests"), "*.py"))):
        try:
            with open(p, encoding="utf-8") as f:
                body = ast.parse(f.read()).body
        except (SyntaxError, UnicodeDecodeError):
            continue
        if not body:
            continue
        last = body[-1]
        if isinstance(last, ast.Expr) and isinstance(last.value, ast.Call):
            fn = last.value.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if name == "done":
                out.append(f"{os.path.basename(p)}:{last.lineno}: ends with a bare done(...); use sys.exit(done(...)) "
                           "so a red case turns the suite red")
    return out


if __name__ == "__main__":
    errs = errors(sys.argv[1] if len(sys.argv) > 1 else None)
    for e in errs:
        print("ERROR:", e)
    print(f"check_done_exit: {len(errs)} error(s)")
    sys.exit(1 if errs else 0)
