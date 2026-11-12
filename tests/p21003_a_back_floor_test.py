#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1003.0 part A (#5718, #5724-#5732): the database's back limit (kalmido_meta back_floor / back_floor_how,
core/kernretire.py kern_retire_floor) names every step of this image's minor, not only the first one.
Since 2.981 (#5274, review D1) the key of obj_comment_trash raises the limit on every fresh database; the steps that came
later in the same start (or a later start of the same image: a stage's move, a DROP) found the limit on this minor already and
their reason was lost - the start check of an older image named only the trash.
 - a fresh database: back_floor = the minor of this image, the reason names #5274
 - the limit on this minor: a new reason is added (both named), the same reason a second time is not added again, an empty
   reason changes nothing; the function answers the minor when it added a reason, "" when nothing changed
 - a newer limit stays as it is (never lowered, its reason untouched); an older limit is raised and gets the new reason alone
 - the start check (core/db.py appver_guard) of an image below the limit names both reasons
Each case runs inside one transaction that is rolled back (the database of the container stays as the start made it).
usage: p21003_a_back_floor_test.py <datadir>"""
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import requests  # noqa: E402
from kt import B, check, done, until  # noqa: E402

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")


def _health():
    try:
        return requests.get(B + "/api/health", timeout=3).ok
    except requests.RequestException:
        return False


def in_app(code, *args):
    """Python inside the test container (the app's modules, its database) -> the JSON of its last output line."""
    r = subprocess.run(["docker", "exec", "-i", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", code, *map(str, args)],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (r.stdout + r.stderr)[-600:]}


check(until(_health, timeout=90), "the server is up (its start made the database)")

CASES = r"""
import io, json, contextlib
from kalmido.core.config import APP_VERSION, DATABASE_URL
from kalmido.core.pg import connect_direct
from kalmido.core.kernretire import kern_retire_floor
from kalmido.core import db as kdb

x = APP_VERSION.split(".")
MINOR = f"{x[0]}.{x[1]}.0"
NEWER = f"{x[0]}.{int(x[1]) + 1}.0"
out = {"minor": MINOR}
c = connect_direct(DATABASE_URL)


def meta():
    return dict(c.execute("SELECT key, value FROM kalmido_meta WHERE key IN ('back_floor','back_floor_how')").fetchall())


def put(floor, how):
    for k, v in (("back_floor", floor), ("back_floor_how", how)):
        c.execute("INSERT INTO kalmido_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))


try:
    out["fresh"] = meta()
    put(MINOR, "reason A (#1)")
    out["add"] = [kern_retire_floor(c, how="reason B (#2)"), meta()]
    out["again"] = [kern_retire_floor(c, how="reason B (#2)"), kern_retire_floor(c, how="reason A (#1)"), kern_retire_floor(c, how=""), meta()]
    put(MINOR, "")
    out["empty_before"] = [kern_retire_floor(c, how="reason C (#3)"), meta()]
    put(NEWER, "a newer step")
    out["newer"] = [kern_retire_floor(c, how="reason D (#4)"), meta()]
    put("2.149.0", "the old step")
    out["older"] = [kern_retire_floor(c, how="reason E (#5)"), meta()]
    put(MINOR, "reason A (#1)")
    kern_retire_floor(c, how="reason B (#2)")
    m = meta()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            kdb.APP_VERSION = "2.149.0"
            kdb.appver_guard(None, None, m["back_floor"], m["back_floor_how"])
            out["guard"] = ["started", buf.getvalue()]
        except BaseException as e:  # DataDirError is a SystemExit
            out["guard"] = [type(e).__name__, buf.getvalue()]
finally:
    c.rollback()
    c.close()
print(json.dumps(out))
"""
r = in_app(CASES)
check("error" not in r, f"the cases ran {r}")
MINOR = r.get("minor")
fr = r.get("fresh") or {}
check(fr.get("back_floor") == MINOR and "#5274" in (fr.get("back_floor_how") or ""),
      f"a fresh database: the limit is this minor, its reason names #5274 (obj_comment_trash's key) {fr}")
check((fr.get("back_floor_how") or "").count("#5274") == 1, f"a fresh database: the reason stands once {fr}")
add = r.get("add") or ["", {}]
check(add[0] == MINOR and add[1].get("back_floor") == MINOR and add[1].get("back_floor_how") == "reason A (#1); reason B (#2)",
      f"the limit on this minor: a second step's reason is added, the first one stays {add}")
again = r.get("again") or ["x", "x", "x", {}]
check(again[:3] == ["", "", ""] and again[3].get("back_floor_how") == "reason A (#1); reason B (#2)",
      f"the same reason again (or an empty one): nothing changes, nothing doubled {again}")
eb = r.get("empty_before") or ["", {}]
check(eb[0] == MINOR and eb[1].get("back_floor_how") == "reason C (#3)", f"an empty reason before: the new one alone {eb}")
nw = r.get("newer") or ["x", {}]
check(nw[0] == "" and nw[1].get("back_floor") != MINOR and nw[1].get("back_floor_how") == "a newer step",
      f"a newer limit stays, its reason untouched {nw}")
old = r.get("older") or ["", {}]
check(old[0] == MINOR and old[1].get("back_floor") == MINOR and old[1].get("back_floor_how") == "reason E (#5)",
      f"an older limit is raised to this minor with the new reason alone {old}")
g = r.get("guard") or ["", ""]
check(g[0] == "DataDirError" and "reason A (#1)" in g[1] and "reason B (#2)" in g[1],
      f"the start check of an older image names both reasons {g}")

sys.exit(done("p21003_a_back_floor"))
