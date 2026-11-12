#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1013.0 (#5773): a setting the app saves by itself is no undo step. Invented names only.
 - a task changed (a step of the person), right after it the app saves settings by itself (PATCH /api/settings with
   {_auto: 1}: a view's block switch, a folder a list edit adds): no new step group; the newest step of the list "Recent
   steps" (the one Ctrl+Z / the arrow takes, static/js/undo.js histNext) is still the task's, and taking it back puts the
   task's title back; the settings saved by the app stay
 - the same setting changed by the person (no _auto) is still a step of its own
freelancer-matrix: undo (a person without an organisation: the same)
usage: p21013_b_autoset_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx  # noqa: E402

kt.fresh(prefix="P21013B")
kt.docker_logs_on_first_fail()
A = kt.setup()
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ALICE = kt.me_id(A)
FID, Fr = freelancer(B, A)


def ngroups(u):
    return dbx("SELECT COUNT(*) FROM undo_groups WHERE user_id=?", (u,))[0][0]


def newest(s):
    r = s.get(B + "/api/undo")
    x = r.json().get("items", []) if r.ok else []
    return x[0] if x else {}


def state(s):
    return s.get(B + "/api/state").json()["settings"]


def run(s, uid, who):
    lid = s.post(B + "/api/lists", json={"name": "Garden " + who, "kind": "project"}).json()["id"]
    r = s.post(B + "/api/tasks", json={"list_id": lid, "title": "Water the roses"})
    check(r.ok, f"{who} (setup): a task {r.status_code} {r.text[:160]}")
    tid = r.json()["id"]
    r = s.patch(B + f"/api/tasks/{tid}", json={"title": "Water the tulips"})
    g = newest(s)
    check(r.ok and g.get("area") == "tasks", f"{who} (setup): the task's change is the newest step {r.status_code} {g}")
    n0 = ngroups(uid)

    # ------------------------------------------------------------ the app saves by itself right after the action
    r1 = s.patch(B + "/api/settings", json={"start_page": "today", "_auto": 1})
    r2 = s.patch(B + "/api/settings", json={"set_delta": {"folders": {"add": ["Auto folder"]}}, "_auto": 1})
    st = state(s)
    check(r1.ok and r2.ok and st.get("start_page") == "today" and "Auto folder" in (st.get("folders") or ""),
          f"{who}: the settings the app saved are stored {r1.status_code} {r2.status_code} {st.get('start_page')} {st.get('folders')}")
    g2 = newest(s)
    check(ngroups(uid) == n0 and g2.get("id") == g.get("id"),
          f"{who}: #5773 a save the app makes by itself records no step - the newest is still the task's {ngroups(uid)} != {n0} {g2}")

    # ------------------------------------------------------------ Ctrl+Z takes the action back, not the setting
    r = s.post(B + f"/api/undo/to/{g2.get('id')}")
    t = dbx("SELECT title FROM tasks WHERE id=?", (tid,))
    check(r.ok and r.json().get("undone") == [g["id"]] and t and t[0][0] == "Water the roses",
          f"{who}: #5773 back takes the task's change, not the setting {r.status_code} {r.text[:200]} {t}")
    check(state(s).get("start_page") == "today", f"{who}: the setting the app saved stays")

    # ------------------------------------------------------------ the person's own change is still a step
    n1 = ngroups(uid)
    r = s.patch(B + "/api/settings", json={"start_page": "inbox"})
    g3 = newest(s)
    check(r.ok and ngroups(uid) == n1 + 1 and g3.get("area") == "self", f"{who}: the person's own change of a setting is a step {g3}")


run(A, ALICE, "alice")
run(Fr, FID, "frida (no organisation)")
sys.exit(kt.done("p21013_b_autoset"))
