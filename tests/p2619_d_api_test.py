#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.619.0 D (#3890) API test: reload waves. Own container (start.sh). Invented people and texts only.
freelancer-matrix: tasks
 - GET /api/state carries lva, the change counters per area as GET /api/version has them in "a" (the app takes them as the
   areas of its first poll: a delta instead of the whole state again); the same for a person without an organisation
 - the herd brake: at most KALMIDO_STATE_AUTO_MAX reloads of the live update (?auto=1) at the same time; the places are
   given back at the end of each request (six reloads of six sign-ins one after the other all load), the gate itself
   refuses the place over the limit and takes one again after a give back; 0 = off; without auto never held
usage: p2619_d_api_test.py <datadir>   (KMT_NOSTART=1: the container runs already)"""
import os
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, check, done, fresh, sess, setup  # noqa: E402

fresh()
A = setup()
assert A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"}).ok
FID, Fr = freelancer(B, A)  # freelancer-matrix: tasks
L = A.post(B + "/api/lists", json={"name": "Launch plan"}).json()["id"]
assert A.post(B + "/api/tasks", json={"title": "Write the invitation", "list_id": L}).ok

# ================================================================ lva
for who, s in (("alice", A), ("frida", Fr)):
    st = s.get(B + "/api/state").json()
    a = s.get(B + "/api/version").json()["a"]
    check(isinstance(st.get("lva"), dict) and set(st["lva"]) == set(a), f"#3890 {who}: /api/state names the areas like /api/version ({sorted(st.get('lva') or {})})")
    check(st.get("lva") == a, f"#3890 {who}: nothing written in between: the same counters {st.get('lva')} vs {a}")
    lid = L if who == "alice" else s.post(B + "/api/lists", json={"name": "Frida's calls"}).json()["id"]
    assert s.post(B + "/api/tasks", json={"title": f"Another one of {who}", "list_id": lid}).ok
    a2 = s.get(B + "/api/version").json()["a"]
    check(a2["tasks"] > st["lva"]["tasks"], f"#3890 {who}: a write after the state moves the tasks counter past lva (the first poll sees it)")

# ================================================================ the herd brake over HTTP
# six sign-ins of alice (the per-sign-in brake of 2.280.0 does not hold them back): one after the other each loads; were the
# places not given back at the end of a request, the fifth would be braked (default 4)
S6 = [sess("alice", ip=f"192.0.2.{i + 10}") for i in range(6)]
got = [s.get(B + "/api/state", params={"auto": "1"}).json() for s in S6]
check(all("tasks" in j and not j.get("brake") for j in got), f"#3890 six reloads one after the other all load (places given back): {[sorted(j)[:3] for j in got]}")
check("tasks" in S6[0].get(B + "/api/state").json(), "#3890 without auto never held")
check(Fr.get(B + "/api/state", params={"auto": "1"}).json().get("tasks") is not None, "#3890 a person without organisation loads too (freelancer-matrix: tasks)")


# ================================================================ the gate itself (inside the app container)
def py_in_app(code):
    for _ in range(4):
        r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app, json\n" + code],
                           capture_output=True, text=True)
        if "deadlock detected" not in r.stderr:
            break
        time.sleep(2)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ERR " + r.stderr[-400:]


out = py_in_app("from kalmido.core import state as s\n"
                "r = [s.st_herd_take(2), s.st_herd_take(2), s.st_herd_take(2)]\n"
                "s.st_herd_give(); r.append(s.st_herd_take(2)); s.st_herd_give(); s.st_herd_give()\n"
                "r += [s.st_herd_take(0), s.st_herd_max(), s._st_herd['n']]\n"
                "print(json.dumps(r))")
check(out == "[true, true, false, true, null, 4, 0]", f"#3890 the gate: two places, the third refused, one again after a give back; 0 = off; default 4; all given back ({out})")

sys.exit(done("p2619_d_api"))
