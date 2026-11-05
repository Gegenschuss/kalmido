#!/usr/bin/env python3
"""2.543.0 (#4625): semgrep is red for NEW findings only. The known, reviewed findings stand in tools/semgrep_baseline.json
(the exception list, see SECURITY.md "Scanner exception lists"): one entry per finding with the rule, the file, the code
line, the reason and the date (and the task when the finding is a real gap that is being fixed).

  semgrep scan ... --json --output semgrep.json
  python3 tools/semgrep_baseline.py semgrep.json [--baseline tools/semgrep_baseline.json]
                                                 [--accept "reason" [--task N]] [--strict]

A finding is known when the baseline has an entry with the same rule id, the same file and the same code (the first line
of the match with its whitespace collapsed) - the line NUMBER does not count, so an edit above the finding does not make
it new. Exit 1 and one `::error` annotation per NEW finding; exit 0 when every finding is known. An entry whose finding
is gone (fixed, or the code line changed) is only reported as a notice: remove it, or re-add the finding with its reason
when it is the same one on a changed line (--strict makes stale entries red too, for a check of the list itself).

--accept REASON writes every new finding into the baseline with that reason and today's date (--task N: the task that
fixes it) - for the first run after a rule update, or when a reviewed finding was re-written; one reason per call, so a
reason that fits several findings is given once and a finding that needs its own gets its own call.
Python standard library only; works on the JSON of semgrep 1.x (results[].check_id / path / start.line / extra.lines)."""
import argparse
import collections
import datetime
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BASELINE = os.path.join(ROOT, "tools", "semgrep_baseline.json")
FIELDS = ("rule", "file", "code", "reason", "date")


def norm(s):
    """The code line with its whitespace collapsed (indentation, tabs, trailing blanks do not count)."""
    return " ".join(str(s or "").split())


def first_line(path, line, lines, root=ROOT):
    """The first line of the match: from the file (start.line); the JSON's extra.lines only when the file is not there.
    2.551.0 (#4625): semgrep without a sign-in (1.183.0) puts the placeholder "requires login" into extra.lines instead of
    the code - taken as the code it matched no entry and every known finding came back as new; it never counts as code."""
    try:
        with open(os.path.join(root, path), encoding="utf-8", errors="replace") as f:
            for i, s in enumerate(f, 1):
                if i == line:
                    return norm(s)
            return ""
    except OSError:
        pass
    txt = norm(str(lines or "").split("\n", 1)[0])
    return "" if txt.lower() == "requires login" else txt


def findings(results, root=ROOT):
    """[{rule, file, line, code, severity, message}] of a semgrep JSON document."""
    out = []
    for r in results.get("results") or []:
        extra = r.get("extra") or {}
        path, line = str(r.get("path") or ""), int((r.get("start") or {}).get("line") or 0)
        out.append({"rule": str(r.get("check_id") or ""), "file": path.replace(os.sep, "/"), "line": line,
                    "code": first_line(path, line, extra.get("lines"), root), "severity": str(extra.get("severity") or ""),
                    "message": str(extra.get("message") or "").strip().split("\n")[0][:200]})
    return out


def key(x):
    return (x["rule"], x["file"], norm(x["code"]))


def load_baseline(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    entries = data["entries"] if isinstance(data, dict) else data
    bad = [e for e in entries if not all(str(e.get(k) or "").strip() for k in FIELDS)]
    if bad:
        raise SystemExit(f"semgrep_baseline: {len(bad)} entries without rule/file/code/reason/date: {bad[0]}")
    return entries


def save_baseline(path, entries):
    entries = sorted(entries, key=lambda e: (e["file"], e["rule"], e["code"]))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"_doc": "#4625: known semgrep findings, reviewed (SECURITY.md 'Scanner exception lists'). Matching: rule + file "
                           "+ code line (whitespace collapsed), not the line number. tools/semgrep_baseline.py compares.",
                   "entries": entries}, f, indent=1, ensure_ascii=False)
        f.write("\n")


def compare(found, entries):
    """(new findings, stale entries, known count)."""
    # 2.543.0 review: counted, not a set - a second, new occurrence of a known code line in the same file is new
    left = collections.Counter(key(e) for e in entries)
    seen = collections.Counter(key(x) for x in found)
    new = []
    for x in found:
        if left[key(x)] > 0:
            left[key(x)] -= 1
        else:
            new.append(x)
    have = collections.Counter()
    stale = []
    for e in entries:
        have[key(e)] += 1
        if have[key(e)] > seen[key(e)]:
            stale.append(e)
    return new, stale, len(found) - len(new)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("results", help="the JSON output of semgrep scan --json")
    ap.add_argument("--baseline", default=BASELINE)
    ap.add_argument("--root", default=ROOT, help="the tree the paths of the results are relative to")
    ap.add_argument("--accept", metavar="REASON", help="write every new finding into the baseline with this reason")
    ap.add_argument("--task", type=int, help="with --accept: the task (#N) that fixes the finding")
    ap.add_argument("--strict", action="store_true", help="stale entries are red too")
    a = ap.parse_args(argv)
    with open(a.results, encoding="utf-8") as f:
        results = json.load(f)
    if not isinstance(results, dict) or not isinstance(results.get("results"), list):
        print("::error title=semgrep baseline::the semgrep output has no results list - scan broken, not green")
        return 1
    errors = [e for e in results.get("errors") or [] if str(e.get("level") or "") == "error"]
    found = findings(results, a.root)
    entries = load_baseline(a.baseline)
    new, stale, nknown = compare(found, entries)
    if a.accept and new:
        today = datetime.date.today().isoformat()
        for x in new:
            e = {"rule": x["rule"], "file": x["file"], "code": x["code"], "reason": a.accept, "date": today}
            if a.task:
                e["task"] = a.task
            entries.append(e)
        save_baseline(a.baseline, entries)
        print(f"semgrep_baseline: {len(new)} findings added to {os.path.relpath(a.baseline, a.root)}")
        new = []
    for x in new:
        print(f"::error file={x['file']},line={x['line']},title=semgrep: new finding {x['rule'].rsplit('.', 1)[-1]}::"
              f"{x['rule']} - {x['message'] or 'see the semgrep output'} (known findings: tools/semgrep_baseline.json, SECURITY.md)")
        print(f"NEW  {x['file']}:{x['line']}  {x['rule']}  {x['severity']}\n     {x['code'][:160]}")
    for e in stale:
        print(f"::{'error' if a.strict else 'notice'} file={e['file']},title=semgrep baseline: entry without a finding::"
              f"{e['rule']} - the code line is gone or changed; remove the entry or re-add the finding: {e['code'][:120]}")
    for e in errors[:20]:
        print(f"::warning title=semgrep error::{str(e.get('message') or '')[:300]}")
    print(f"semgrep_baseline: {len(found)} findings, {nknown} known, {len(new)} new, {len(stale)} stale entries, "
          f"{len(entries)} entries, {len(errors)} semgrep errors")
    # 2.543.0 review: a scan error (a file not parsed) or a scan with no finding at all while the list has some is red:
    # missing findings must not look like a clean tree
    if errors:
        print(f"::error title=semgrep baseline::{len(errors)} semgrep errors - files may be unscanned")
    scanned = (results.get("paths") or {}).get("scanned") if "paths" in results else True
    broken = not scanned or (len(entries) >= 10 and len(stale) * 2 > len(entries))
    if broken:
        print(f"::error title=semgrep baseline::{len(stale)} of {len(entries)} known findings are gone at once or no file "
              "was scanned - scan broken? (after a real big clean-up: remove the entries)")
    return 1 if new or errors or broken or (a.strict and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
