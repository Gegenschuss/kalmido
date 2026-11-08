#!/usr/bin/env python3
"""2.755.0 (#5294): ruff (rules E, F, BLE; ruff.toml) is red for NEW findings only. The findings of the existing code stand in
tools/ruff_baseline.json; this script compares the JSON output of ruff against it (the pattern of tools/semgrep_baseline.py).

  ruff check --output-format json --exit-zero . > ruff.json
  python3 tools/ruff_baseline.py ruff.json [--baseline tools/ruff_baseline.json] [--strict]
  python3 tools/ruff_baseline.py ruff.json --update      # write the baseline anew from this output (after a reviewed clean-up)

A finding is known when the baseline holds the same rule in the same file for the same code line (whitespace collapsed,
kept as a short hash) - the line NUMBER does not count, so moving code or an edit above it does not make it new; changing
the line itself does (touched code gets cleaned). Counted, not a set: a second, new copy of a known line is new.
Exit 1 and one `::error` annotation per NEW finding; exit 0 when every finding is known. Entries without a finding any more
(fixed) are a notice only (--strict: red). A scan with no finding at all while the baseline is big is red (ruff broken).
The baseline is compact ({file: {rule: [hash, ...]}}): the existing code has ~2 100 findings (E501 is not in the gate).
The ruff version is pinned in the CI step (pip install ruff==0.17.4); a ruff update that finds more needs --update.
Python standard library only."""
import argparse
import collections
import hashlib
import json
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BASELINE = os.path.join(ROOT, "tools", "ruff_baseline.json")


def norm(s):
    """The code line with its whitespace collapsed (indentation, tabs, trailing blanks do not count)."""
    return " ".join(str(s or "").split())


def code_hash(line):
    return hashlib.sha256(norm(line).encode("utf-8")).hexdigest()[:12]


def _lines(path, cache):
    if path not in cache:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                cache[path] = f.read().split("\n")
        except OSError:
            cache[path] = []
    return cache[path]


def findings(results, root=ROOT):
    """[{rule, file, line, code, message}] of ruff's JSON list (rule "syntax" for a file ruff could not parse)."""
    out, cache = [], {}
    for r in results:
        fn = str(r.get("filename") or "")
        ab = fn if os.path.isabs(fn) else os.path.join(root, fn)
        rel = os.path.relpath(ab, root).replace(os.sep, "/")
        row = int((r.get("location") or {}).get("row") or 0)
        src = _lines(ab, cache)
        code = src[row - 1] if 0 < row <= len(src) else ""
        out.append({"rule": str(r.get("code") or "syntax"), "file": rel, "line": row, "code": norm(code),
                    "message": str(r.get("message") or "").split("\n")[0][:200]})
    return out


def key(x):
    return (x["file"], x["rule"], code_hash(x["code"]))


def load_baseline(path):
    """Counter of (file, rule, hash)."""
    if not os.path.exists(path):
        return collections.Counter()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = collections.Counter()
    for fn, rules in (data.get("files") or {}).items():
        for rule, hashes in rules.items():
            for h in hashes:
                out[(fn, rule, h)] += 1
    return out


def save_baseline(path, found):
    files = {}
    for fn, rule, h in sorted(key(x) for x in found):
        files.setdefault(fn, {}).setdefault(rule, []).append(h)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"_doc": "#5294: ruff findings of the existing code (ruff.toml: E, F, BLE). Matching: file + rule + hash of "
                           "the code line (whitespace collapsed), not the line number. tools/ruff_baseline.py compares; "
                           "regenerate with --update.", "files": files}, f, indent=0, sort_keys=True, separators=(",", ":"))
        f.write("\n")


def compare(found, base):
    """(new findings, stale count, known count)."""
    left = collections.Counter(base)
    new = []
    for x in found:
        k = key(x)
        if left[k] > 0:
            left[k] -= 1
        else:
            new.append(x)
    stale = sum(v for v in left.values() if v > 0)
    return new, stale, len(found) - len(new)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("results", help="the JSON output of ruff check --output-format json")
    ap.add_argument("--baseline", default=BASELINE)
    ap.add_argument("--root", default=ROOT, help="the tree the paths of the results are relative to")
    ap.add_argument("--update", action="store_true", help="write the baseline anew from these results")
    ap.add_argument("--strict", action="store_true", help="entries without a finding are red too")
    a = ap.parse_args(argv)
    with open(a.results, encoding="utf-8") as f:
        results = json.load(f)
    if not isinstance(results, list):
        print("::error title=ruff baseline::the ruff output is not a JSON list - lint broken, not green")
        return 1
    found = findings(results, a.root)
    if a.update:
        save_baseline(a.baseline, found)
        print(f"ruff_baseline: {len(found)} findings written to {os.path.relpath(a.baseline, a.root)}")
        return 0
    base = load_baseline(a.baseline)
    new, stale, nknown = compare(found, base)
    for x in new:
        print(f"::error file={x['file']},line={x['line']},title=ruff {x['rule']}::{x['message']} (only new code is checked; "
              f"known findings: tools/ruff_baseline.json)")
        print(f"NEW  {x['file']}:{x['line']}  {x['rule']}  {x['message'][:100]}\n     {x['code'][:160]}")
    total = sum(base.values())
    if stale:
        print(f"::{'error' if a.strict else 'notice'} title=ruff baseline::{stale} entries without a finding (fixed code) - "
              "python3 tools/ruff_baseline.py ruff.json --update shrinks the list")
    print(f"ruff_baseline: {len(found)} findings, {nknown} known, {len(new)} new, {stale} stale entries, {total} entries")
    broken = total >= 100 and stale * 2 > total
    if broken:
        print(f"::error title=ruff baseline::{stale} of {total} known findings are gone at once - wrong config or paths? "
              "(after a real big clean-up: --update)")
    return 1 if new or broken or (a.strict and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
