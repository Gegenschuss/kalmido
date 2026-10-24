#!/usr/bin/env python3
"""tests/tiers.py (2.284.0, #3121 #3122): the verdict of a CI shard after its rerun, the notes of all shards, tiers.txt.
Static, no container (CI job "Lint, i18n, scanners")."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tiers  # noqa: E402

from kt import check as kt_check, done  # noqa: E402  (kt.check(cond, what): the shared counter)


def expect(name, cond, info=""):
    kt_check(cond, f"{name} {info}" if not cond else name)


T = {"core_ui": "kern", "edge_ui": "rand", "edge2_ui": "rand"}
PASS = "== edge_ui: passed\nALL SUITES PASSED\n"

rc, res, lines = tiers.ci(["edge_ui", "core_ui"], PASS, 0, tiers=T)
expect("rerun green: the shard is green", rc == 0, rc)
expect("rerun green: both are flaky", res["wackler"] == ["edge_ui", "core_ui"], res)
expect("rerun green: a warning per flaky suite", sum("title=flaky suite" in x for x in lines) == 2, lines)

rc, res, _ = tiers.ci(["core_ui", "edge_ui"], "FAILED suites: core_ui\n", 1, tiers=T)
expect("core red in the rerun: red", rc == 1, rc)
expect("core red in the rerun: edge_ui flaky, core_ui core red", res == {"wackler": ["edge_ui"], "rand-rot": [], "kern-rot": ["core_ui"]}, res)

rc, res, lines = tiers.ci(["edge_ui"], "== edge_ui: FAILED (exit 1)\nFAILED suites: edge_ui edge2_ui\n", 1, tiers=T)
expect("only edge suites red in the rerun: green", rc == 0, rc)
expect("only edge suites red: both noted (edge2_ui of the same group too)", res["rand-rot"] == ["edge_ui", "edge2_ui"], res)
expect("only edge suites red: an edge warning each", sum("title=edge suite" in x for x in lines) == 2, lines)

rc, res, _ = tiers.ci(["edge_ui"], "container start failed\n", 1, tiers=T)
expect("rerun red without a FAILED line (container / limit): red", rc == 1, rc)

rc, res, _ = tiers.ci(["new_ui"], "FAILED suites: new_ui\n", 1, tiers=T)
expect("a suite missing from tiers.txt is core", rc == 1 and res["kern-rot"] == ["new_ui"], res)

expect("the last FAILED line counts", tiers.failed_of("FAILED suites: a b\n...\nFAILED suites: b\n") == ["b"])

with tempfile.TemporaryDirectory() as d:
    for n, body in (("timings-shard-1", "wackler a_ui\nrand-rot edge_ui\n"), ("timings-shard-2", "wackler b_ui\nwackler a_ui\n"),
                    ("timings-shard-3", None)):
        os.makedirs(os.path.join(d, n))
        if body:
            with open(os.path.join(d, n, "timings-vermerk.txt"), "w") as f:
                f.write(body)
    os.makedirs(os.path.join(d, "timings-shard-4"))
    out = os.path.join(d, "timings-shard-4", "timings-vermerk.txt")
    tiers.ci(["x_ui"], PASS, 0, out=out, tiers=T)
    expect("ci --out writes the note file", open(out).read() == "wackler x_ui\n")
    summ = os.path.join(d, "summary.md")
    res, line = tiers.done(d, summ)
    expect("done: the notes of all shards, sorted, once", res["wackler"] == ["a_ui", "b_ui", "x_ui"] and res["rand-rot"] == ["edge_ui"], res)
    expect("done: one annotation line", line == "::notice title=kalmido-vermerk::wackler=a_ui b_ui x_ui; rand-rot=edge_ui; kern-rot=", line)
    expect("done: the summary names the edge suite", "edge_ui" in open(summ).read())

bad_t, missing, gone = tiers.check_file()
expect("tiers.txt is well formed", not bad_t, bad_t)
expect("tiers.txt lists every suite of run_all.sh (a new one: tests/tiers.py suggest)", not missing, missing[:10])
expect("tiers.txt names no suite that is gone", not gone, gone[:10])
real = tiers.load()
expect("tiers.txt: the core flows are kern", all(real.get(s) == "kern" for s in ("api", "ui", "security", "setup_ui")))
expect("tiers.txt: no server suite is rand", not [s for s, t in real.items() if t == "rand" and not os.path.exists(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), s + ".js")) and not os.path.exists(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), s + "_ui.js")) and not s.endswith("ui")])

sys.exit(done("tiers_test"))
