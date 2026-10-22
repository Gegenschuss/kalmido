#!/usr/bin/env python3
"""Shard report from measured suite times (2.149.0 E, #2514).

tests/run_all.sh is a list of groups (one `fresh` container and the suites after it; a group stays whole) split into shards by
`shard N` lines. Every run writes tests/timings.csv (shard,group,suite,seconds,rc; suite "*" = the whole group with its
container start). This tool reads the groups from run_all.sh and one or more timings files (CI artifacts timings-shard-*),
spreads the groups over the shards by measured time (LPT: longest group first onto the emptiest shard) and shows how far the
hand-set markers are off. 2.179 (#2691): CI takes the assignment (--assign) from the times of its last finished run
(ci.yml job "plan", tests/run_all.sh KALMIDO_SHARD_PLAN); the markers stay for runs without a plan (Mac, local).

  python3 tools/shards.py [--run-all tests/run_all.sh] [--shards 19] [--check PCT] [--assign] timings.csv ...
    --check PCT  exit 1 when the longest marker shard is more than PCT % over the longest LPT shard
    --assign     print "group shard" per group (the LPT assignment)
    --only F     2.180.0 A (#2695): only the groups whose first suite is a line of F (tests/stages.py --groups-out, the push
                 stage); --assign then starts with "# stage push" (run_all.sh skips the groups not in the plan)
    --target-min M  with --only: as many shards as M minutes each need (at most --shards, at least 1)
Groups without a measurement count as DEFAULT_SUITE_S per suite plus DEFAULT_FRESH_S (shown as "estimated").
"""
import argparse
import csv
import os
import re
import sys

DEFAULT_SUITE_S = 20.0  # a suite without a measurement (median of the jsdom / API suites is lower; on the safe side)
DEFAULT_FRESH_S = 8.0  # one container start (start.sh: stop, wipe, database, health wait)
FRESH_RE = re.compile(r"^(now [^;]*; *)?fresh;")
RUN_RE = re.compile(r"^(now [^;]*; *)?(fresh;)?[ \t]*run ([A-Za-z0-9_]+) ")
SHARD_RE = re.compile(r"^shard ([0-9]+)\b")


def groups(path):
    """[(first suite, [suites], marker shard)] in the order of run_all.sh (the same count as run_all.sh's mine())."""
    out, cur, marker = [], 1, 0
    with open(path, encoding="utf-8") as f:
        for no, line in enumerate(f, 1):
            m = SHARD_RE.match(line)
            if m:
                cur, marker = int(m.group(1)), no
                continue
            if FRESH_RE.match(line):
                out.append([None, [], cur])
                marker = 0
            m = RUN_RE.match(line)
            if m and marker and out:  # CI of 2.166.1 (#945): the group would run on past the marker (one 45+ min group)
                print(f"shards.py: {path}:{no}: `shard` marker of line {marker} without `fresh` - suite {m.group(3)} stays in "
                      f"the group {out[-1][0]} (add `fresh;`)", file=sys.stderr)
                marker = 0
            if m and out:
                g = out[-1]
                g[0] = g[0] or m.group(3)
                g[1].append(m.group(3))
    return [tuple(g) for g in out if g[0]]


def timings(paths):
    """{(group, suite): seconds} - the last row of a pair wins (a later file = a later run). CI of 2.166.1 (#945): also
    {(None, suite): seconds} (any group) and {(group, None): {suites}} (what ran in a group), for groups that were cut anew."""
    t = {}
    for p in paths:
        try:
            with open(p, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    try:
                        t[(r["group"], r["suite"])] = float(r["seconds"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if r["suite"] != "*":
                        t[(None, r["suite"])] = t[(r["group"], r["suite"])]
                        t.setdefault((r["group"], None), set()).add(r["suite"])
        except OSError as e:
            print(f"shards.py: {p}: {e.strerror}", file=sys.stderr)
    return t


def cost(g, t):
    """(seconds, measured?) of one group."""
    first, suites, _ = g
    # the whole-group time only when the measured group held no other suites (CI of 2.166.1, #945: after a `fresh` was added,
    # the old group p208_ui of 54 suites would count with its 45 min for the new one of 17)
    if (first, "*") in t and t.get((first, None), set()) <= set(suites):
        return t[(first, "*")], True
    known = [t.get((first, s), t.get((None, s))) for s in suites]
    known = [k for k in known if k is not None]
    if len(known) == len(suites):
        return sum(known) + DEFAULT_FRESH_S, True
    return sum(known) + DEFAULT_SUITE_S * (len(suites) - len(known)) + DEFAULT_FRESH_S, False


def lpt(costs, n):
    """Longest processing time first: [(shard number, [group indexes], seconds)] - the order of run_all.sh within a shard."""
    load = [0.0] * n
    pick = [[] for _ in range(n)]
    for i in sorted(range(len(costs)), key=lambda i: -costs[i]):
        k = min(range(n), key=lambda k: (load[k], k))
        load[k] += costs[i]
        pick[k].append(i)
    return [(k + 1, sorted(pick[k]), load[k]) for k in range(n)]


def mmss(s):
    return f"{int(s // 60):3d}:{int(s % 60):02d}"


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="shard report from tests/timings.csv (LPT over the run_all.sh groups)")
    ap.add_argument("--run-all", default=os.path.join(here, "..", "tests", "run_all.sh"))
    ap.add_argument("--shards", type=int, default=0, help="number of shards (default: SHARDS_DEFINED of run_all.sh)")
    ap.add_argument("--check", type=float, default=None, metavar="PCT")
    ap.add_argument("--assign", action="store_true")
    ap.add_argument("--only", metavar="F")
    ap.add_argument("--target-min", type=float, default=0, metavar="M")
    ap.add_argument("timings", nargs="*")
    a = ap.parse_args(argv)
    gs = groups(a.run_all)
    if not gs:
        print("shards.py: no groups in", a.run_all, file=sys.stderr)
        return 2
    n = a.shards
    if not n:
        with open(a.run_all, encoding="utf-8") as f:
            m = re.search(r"^SHARDS_DEFINED=([0-9]+)", f.read(), re.M)
        n = int(m.group(1)) if m else max(g[2] for g in gs)
    if a.only is not None:  # 2.180.0 A (#2695): the push stage
        with open(a.only, encoding="utf-8") as f:
            want = {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
        gs = [g for g in gs if g[0] in want]
        if not gs:
            print("shards.py: no group of", a.only, "in", a.run_all, file=sys.stderr)
            return 2
    t = timings(a.timings)
    cs = [cost(g, t) for g in gs]
    costs = [c for c, _ in cs]
    measured = sum(1 for _, ok in cs if ok)
    if a.only is not None and a.target_min > 0:
        n = max(1, min(n, -(-int(sum(costs)) // int(a.target_min * 60)), len(gs)))
    if a.assign:
        if a.only is not None:
            print("# stage push")
        for k, idx, _ in lpt(costs, n):
            for i in idx:
                print(gs[i][0], k)
        return 0
    marker = {}
    for g, c in zip(gs, costs):
        marker.setdefault(g[2], [0, 0.0])
        marker[g[2]][0] += 1
        marker[g[2]][1] += c
    plan = lpt(costs, n)
    print(f"{len(gs)} groups, {sum(len(g[1]) for g in gs)} suites, {measured} groups measured "
          f"({len(gs) - measured} estimated), total {mmss(sum(costs)).strip()} min:s")
    print("shard  markers: groups   time   |  LPT: groups   time")
    for k in range(1, n + 1):
        mg, mt = marker.get(k, [0, 0.0])
        _, idx, lt = plan[k - 1]
        print(f"{k:5d}  {mg:15d} {mmss(mt)}   |  {len(idx):11d} {mmss(lt)}")
    worst_m = max((v[1] for v in marker.values()), default=0.0)
    worst_l = max(p[2] for p in plan)
    off = (worst_m / worst_l - 1) * 100 if worst_l else 0.0
    print(f"longest shard: markers {mmss(worst_m).strip()}, LPT {mmss(worst_l).strip()} ({off:+.0f} %)")
    top = sorted(range(len(gs)), key=lambda i: -costs[i])[:10]
    print("longest groups: " + ", ".join(f"{gs[i][0]} {mmss(costs[i]).strip()}{'' if cs[i][1] else '*'}" for i in top))
    if a.check is not None and off > a.check:
        print(f"shards.py: the markers are {off:.0f} % over the LPT plan (limit {a.check:.0f} %)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
