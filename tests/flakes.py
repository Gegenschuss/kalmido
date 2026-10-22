#!/usr/bin/env python3
"""Flaky suites from the CI timings (2.180.0 A, #2693).

Every CI shard uploads tests/timings.csv (the first pass, rc per suite) and, when a suite failed, tests/timings-rerun.csv
(the rerun of the whole groups of the failed suites). A suite red in the first pass and green in the rerun of the same run
is a flake; red in both is a real failure. This tool counts both over a set of runs (ci.yml job "flakes", nightly and by
hand: the last ~10 finished runs on main). Python standard library only.

  python3 tests/flakes.py [--csv OUT] [--summary FILE] [--annotate] [--top 10] DIR
    DIR/<run id>/**/timings.csv + timings-rerun.csv   (gh run download <id> -p 'timings-shard-*' -D DIR/<id>)
    DIR/runs.tsv  optional: "<run id>\t<created at>\t<sha>" per run (for the column "last")
    --csv OUT     suite,red_first,green_rerun,red_rerun,runs,last_run,last_at (one row per suite red at least once)
    --summary F   a Markdown table appended to F ($GITHUB_STEP_SUMMARY)
    --annotate    the top suites as GitHub "::warning title=flaky suite::" lines (readable without signing in)
"""
import argparse
import csv
import os
import sys


def rcs(path):
    """{suite: rc} of one timings file (rows of whole groups "*" and rows without rc left out)."""
    out = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                s, rc = (r.get("suite") or "").strip(), (r.get("rc") or "").strip()
                if s and s != "*" and rc.lstrip("-").isdigit():
                    out[s] = int(rc)  # a later row of the same suite (a second pass in one file) wins
    except OSError:
        pass
    return out


def run_result(run_dir):
    """({suite: first-pass rc}, {suite: rerun rc}) over all shards of one run."""
    first, rerun = {}, {}
    for d, _, files in os.walk(run_dir):
        if "timings.csv" in files:
            first.update(rcs(os.path.join(d, "timings.csv")))
        if "timings-rerun.csv" in files:
            rerun.update(rcs(os.path.join(d, "timings-rerun.csv")))
    return first, rerun


def runs_meta(base):
    meta = {}
    try:
        with open(os.path.join(base, "runs.tsv"), encoding="utf-8") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if p and p[0]:
                    meta[p[0]] = p[1] if len(p) > 1 else ""
    except OSError:
        pass
    return meta


def stats(base):
    """(rows sorted worst first, number of runs with timings)"""
    meta = runs_meta(base)
    ids = sorted((d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))),
                 key=lambda d: (meta.get(d, ""), d))  # oldest first: the last one seen is the latest
    per, ran = {}, {}
    n = 0
    for rid in ids:
        first, rerun = run_result(os.path.join(base, rid))
        if not first:
            continue
        n += 1
        for s, rc in first.items():
            if rc == 0:
                continue
            row = per.setdefault(s, {"suite": s, "red_first": 0, "green_rerun": 0, "red_rerun": 0, "runs": 0,
                                     "last_run": "", "last_at": ""})
            row["red_first"] += 1
            if s in rerun:
                row["green_rerun" if rerun[s] == 0 else "red_rerun"] += 1
            row["last_run"], row["last_at"] = rid, meta.get(rid, "")
        for s in first:
            ran[s] = ran.get(s, 0) + 1
    for s, row in per.items():
        row["runs"] = ran[s]
    rows = sorted(per.values(), key=lambda r: (-r["green_rerun"], -r["red_first"], r["last_at"], r["suite"]))
    return rows, n


def main(argv=None):
    ap = argparse.ArgumentParser(description="flaky suites from CI timings (first pass red, rerun green)")
    ap.add_argument("dir")
    ap.add_argument("--csv")
    ap.add_argument("--summary")
    ap.add_argument("--annotate", action="store_true")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args(argv)
    if not os.path.isdir(a.dir):
        print(f"flakes.py: {a.dir}: no such directory", file=sys.stderr)
        return 2
    rows, n = stats(a.dir)
    cols = ["suite", "red_first", "green_rerun", "red_rerun", "runs", "last_run", "last_at"]
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    flaky = [r for r in rows if r["green_rerun"]]
    print(f"{n} runs with timings, {len(rows)} suites red in a first pass, {len(flaky)} of them green on the rerun")
    for r in rows[:a.top]:
        print(f"  {r['suite']}: red {r['red_first']}x, rerun green {r['green_rerun']}x / red {r['red_rerun']}x, "
              f"last {r['last_at'] or r['last_run']}")
    if a.summary:
        with open(a.summary, "a", encoding="utf-8") as f:
            f.write(f"### Flaky suites ({n} runs)\n\n")
            if not rows:
                f.write("No suite was red in a first pass.\n")
            else:
                f.write("| Suite | red in the first pass | green on the rerun | red on the rerun | last |\n"
                        "|---|---:|---:|---:|---|\n")
                for r in rows:
                    f.write(f"| {r['suite']} | {r['red_first']} | {r['green_rerun']} | {r['red_rerun']} | "
                            f"{r['last_at'] or r['last_run']} |\n")
    if a.annotate:
        for r in flaky[:a.top]:
            print(f"::warning title=flaky suite::{r['suite']}: first pass red in {r['red_first']} of {n} runs, "
                  f"green on the rerun {r['green_rerun']}x, last {r['last_at'] or r['last_run']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
