#!/usr/bin/env python3
# kalmido-suite:
"""2.410.0 B (#3515) API tests, own container (kt.fresh): the board shows how long a card is in its column.
 - tasks.section_at: unset on a new task (the board counts from created_at); a change of the section sets it, the same
   section again or another field does not; a move into another list sets it, deleting the section the task is in (ON DELETE
   SET NULL) too; the history of tasks from before fills it once (migration step, checked on the column only)
 - a task's place in a further list (task_links.section_at): set when the link is made, a new place there sets it again,
   the same place not; the task's "also" carries it
 - the column limits sections.dwell_warn_h / dwell_alert_h (hours): set / clear (null, 0), bad values 400, red must stay
   above yellow (also when only one of them is sent), a stranger 404; the undo's _prev keeps limits changed meanwhile
   (conflict); a deleted section returns them and the undo's re-create takes them back
 - task_field_values.set_at (for #3514's "since"): a new value sets it, the same value again or another field does not,
   another value does; the task carries field_at {field id: ISO} with the known ones only, a cleared value drops it
 - freelancer-matrix: a person without an organisation: the same on a private project
usage: p24100_b_api_test.py <datadir>"""
import sys

import kt
from kt import B, FAILS, OKS, check, sess  # noqa: F401
from freelancer_fixture import freelancer

kt.fresh()
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments,kanban"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")
FID, Fr = freelancer(B, A, "frida")
OLD = "2026-01-02T03:04:05+00:00"

for t, col in (("tasks", "section_at"), ("task_links", "section_at"), ("task_field_values", "set_at"), ("sections", "dwell_warn_h"), ("sections", "dwell_alert_h")):
    check(kt.dbx("SELECT 1 FROM information_schema.columns WHERE table_name=? AND column_name=?", (t, col)), f"{t}.{col} exists")
check(kt.dbx("SELECT 1 FROM pg_trigger WHERE tgname IN ('kalmido_sec_at', 'kalmido_sec_at_link', 'kalmido_field_at') HAVING COUNT(*) = 3"), "the three triggers exist")


def sec(s, lid, name):
    r = s.post(B + "/api/sections", json={"list_id": lid, "name": name})
    assert r.ok, r.text
    return r.json()["id"]


def task(s, tid):
    r = s.get(B + f"/api/tasks/{tid}")
    return r.json() if r.ok else {}


def at(tid):
    return kt.dbx("SELECT section_at FROM tasks WHERE id=?", (tid,))[0][0]


def moves(s, who):
    """A project with two columns: the section's time follows every move and only a move -> the project id."""
    P = s.post(B + "/api/lists", json={"name": f"Board {who}"}).json()["id"]
    S1, S2 = sec(s, P, "Doing"), sec(s, P, "Review")
    r = s.post(B + "/api/tasks", json={"title": f"Card {who}", "list_id": P, "section_id": S1})
    check(r.ok, f"{who}: task created ({r.status_code})")
    T = r.json()["id"]
    check(at(T) is None and "section_at" not in task(s, T), f"{who}: a new task has no section_at (the board counts from created_at)")
    r = s.patch(B + f"/api/tasks/{T}", json={"section_id": S2})
    got = at(T)
    check(r.ok and got and got > OLD and task(s, T).get("section_at") == got, f"{who}: a move into another column sets section_at ({got})")
    kt.dbx("UPDATE tasks SET section_at=? WHERE id=?", (OLD, T))
    s.patch(B + f"/api/tasks/{T}", json={"title": f"Card {who} renamed", "priority": 3})
    check(at(T) == OLD, f"{who}: another field leaves section_at ({at(T)})")
    s.patch(B + f"/api/tasks/{T}", json={"section_id": S2})
    check(at(T) == OLD, f"{who}: the same column again leaves section_at ({at(T)})")
    s.patch(B + f"/api/tasks/{T}", json={"section_id": S1})
    check(at(T) != OLD, f"{who}: back into the first column sets it again ({at(T)})")
    kt.dbx("UPDATE tasks SET section_at=? WHERE id=?", (OLD, T))
    r = s.delete(B + f"/api/sections/{S1}")
    check(r.ok and at(T) != OLD, f"{who}: deleting the task's column (it stays, without one) sets section_at ({at(T)})")
    Q = s.post(B + "/api/lists", json={"name": f"Other {who}"}).json()["id"]
    kt.dbx("UPDATE tasks SET section_at=? WHERE id=?", (OLD, T))
    r = s.patch(B + f"/api/tasks/{T}", json={"list_id": Q})
    check(r.ok and at(T) != OLD, f"{who}: a move into another list sets section_at ({r.status_code} {at(T)})")
    return P, S2


def field_since(s, who):
    """A select field's value: field_at follows a change of the value and only that."""
    L = s.post(B + "/api/lists", json={"name": f"Stages {who}"}).json()["id"]
    r = s.post(B + f"/api/lists/{L}/fields", json={"name": "Stage", "type": "select", "options": {"options": [
        {"id": "s1", "name": "Plan", "color": "blue"}, {"id": "s2", "name": "Build", "color": "green"}]}})
    check(r.ok, f"{who}: select field created ({r.status_code} {r.text[:120]})")
    F = str(r.json().get("id"))
    N = str(s.post(B + f"/api/lists/{L}/fields", json={"name": "Notes", "type": "text"}).json().get("id"))
    T = s.post(B + "/api/tasks", json={"title": f"Staged {who}", "list_id": L}).json()["id"]
    check("field_at" not in task(s, T), f"{who}: no value, no field_at")
    s.patch(B + f"/api/tasks/{T}", json={"fields": {F: "s1"}})
    fa = task(s, T).get("field_at") or {}
    sat = lambda: kt.dbx("SELECT set_at FROM task_field_values WHERE task_id=? AND field_id=?", (T, int(F)))[0][0]  # noqa: E731
    check(fa.get(F) and fa.get(F) == sat() and list(fa) == [F], f"{who}: a new value sets field_at of that field only ({fa})")
    kt.dbx("UPDATE task_field_values SET set_at=? WHERE task_id=? AND field_id=?", (OLD, T, int(F)))
    s.patch(B + f"/api/tasks/{T}", json={"fields": {F: "s1", N: "a note"}})
    fa = task(s, T).get("field_at") or {}
    check(fa.get(F) == OLD and fa.get(N) and fa.get(N) != OLD, f"{who}: the same value again keeps it, the other field gets its own ({fa})")
    s.patch(B + f"/api/tasks/{T}", json={"fields": {F: "s2"}})
    check((task(s, T).get("field_at") or {}).get(F, OLD) != OLD, f"{who}: another value sets it again")
    s.patch(B + f"/api/tasks/{T}", json={"fields": {F: None}})
    check(F not in (task(s, T).get("field_at") or {}), f"{who}: a cleared value drops it")


P, S2 = moves(A, "alice")
FP, FS2 = moves(Fr, "frida")  # freelancer-matrix: section_at
field_since(A, "alice")
field_since(Fr, "frida")  # freelancer-matrix: field_at

# ================================================================== a task's place in a further list
L1 = A.post(B + "/api/lists", json={"name": "Origin"}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Further"}).json()["id"]
X1, X2 = sec(A, L2, "Inbox column"), sec(A, L2, "Done column")
T = A.post(B + "/api/tasks", json={"title": "Linked card", "list_id": L1}).json()["id"]
r = A.post(B + f"/api/tasks/{T}/links", json={"list_id": L2, "section_id": X1})
lat = lambda: kt.dbx("SELECT section_at FROM task_links WHERE task_id=? AND list_id=?", (T, L2))[0][0]  # noqa: E731
check(r.ok and lat(), f"#3515: a new link has its section_at ({r.status_code} {r.text[:120]})")
also = (task(A, T).get("also") or [{}])[0]
check(also.get("list_id") == L2 and also.get("section_at") == lat(), f"#3515: also carries the place's section_at ({also})")
kt.dbx("UPDATE task_links SET section_at=? WHERE task_id=? AND list_id=?", (OLD, T, L2))
A.patch(B + f"/api/tasks/{T}/links/{L2}", json={"section_id": X1, "sort": 3})
check(lat() == OLD, f"#3515: the same place there leaves it ({lat()})")
r = A.patch(B + f"/api/tasks/{T}/links/{L2}", json={"section_id": X2})
check(r.ok and lat() != OLD, f"#3515: another column there sets it ({r.status_code} {lat()})")


# ================================================================== the column limits
def lim(sid):
    r = kt.dbx("SELECT dwell_warn_h, dwell_alert_h FROM sections WHERE id=?", (sid,))
    return tuple(r[0]) if r else None


def limits(s, sid, who):
    r = s.patch(B + f"/api/sections/{sid}", json={"dwell_warn_h": 8, "dwell_alert_h": 48})
    check(r.ok and lim(sid) == (8, 48), f"{who}: limits set ({r.status_code} {lim(sid)})")
    st = next((x for x in s.get(B + "/api/state").json()["sections"] if x["id"] == sid), {})
    check(st.get("dwell_warn_h") == 8 and st.get("dwell_alert_h") == 48, f"{who}: the state carries the limits ({st})")
    for bad in (-1, "x", 9000, 1.5, True, "2.5", [3]):
        r = s.patch(B + f"/api/sections/{sid}", json={"dwell_warn_h": bad})
        check(r.status_code == 400 and lim(sid) == (8, 48), f"{who}: dwell_warn_h {bad!r}: 400, unchanged ({r.status_code} {lim(sid)})")
    r = s.patch(B + f"/api/sections/{sid}", json={"dwell_warn_h": 24, "dwell_alert_h": 24})
    check(r.status_code == 400 and "red limit" in r.text and lim(sid) == (8, 48), f"{who}: red = yellow: 400 ({r.status_code} {r.text[:100]})")
    r = s.patch(B + f"/api/sections/{sid}", json={"dwell_alert_h": 4})
    check(r.status_code == 400 and lim(sid) == (8, 48), f"{who}: only red, below the stored yellow: 400 ({r.status_code})")
    r = s.patch(B + f"/api/sections/{sid}", json={"dwell_alert_h": "72"})
    check(r.ok and lim(sid) == (8, 72), f"{who}: only red (a digit string) keeps yellow ({lim(sid)})")
    r = s.patch(B + f"/api/sections/{sid}", json={"dwell_warn_h": 0, "dwell_alert_h": None})
    check(r.ok and lim(sid) == (None, None), f"{who}: 0 / null clear both ({lim(sid)})")
    r = s.patch(B + f"/api/sections/{sid}", json={"dwell_alert_h": 5})
    check(r.ok and lim(sid) == (None, 5), f"{who}: red alone ({lim(sid)})")


limits(A, S2, "alice")
limits(Fr, FS2, "frida")  # freelancer-matrix: the column limits
r = Bo.patch(B + f"/api/sections/{S2}", json={"dwell_warn_h": 1})
check(r.status_code in (403, 404) and lim(S2) == (None, 5), f"#3515: a stranger cannot set them ({r.status_code})")
r = Fr.patch(B + f"/api/sections/{S2}", json={"dwell_warn_h": 1})
check(r.status_code in (403, 404) and lim(S2) == (None, 5), f"#3515: nor a freelancer outside the project ({r.status_code})")

# the undo's _prev: a limit changed meanwhile stays
A.patch(B + f"/api/sections/{S2}", json={"dwell_warn_h": 2, "dwell_alert_h": 6})
r = A.patch(B + f"/api/sections/{S2}", json={"dwell_warn_h": None, "dwell_alert_h": 5, "_prev": {"dwell_warn_h": 1, "dwell_alert_h": 3}})
check(r.ok and r.json().get("conflicts") and lim(S2) == (2, 6), f"#3515: undo over a newer value: conflict, kept ({r.text[:120]} {lim(S2)})")
r = A.patch(B + f"/api/sections/{S2}", json={"dwell_warn_h": None, "dwell_alert_h": 5, "_prev": {"dwell_warn_h": 2, "dwell_alert_h": 6}})
check(r.ok and not r.json().get("conflicts") and lim(S2) == (None, 5), f"#3515: undo of the own change ({lim(S2)})")

# a deleted section returns its limits, its undo brings them back
A.patch(B + f"/api/sections/{S2}", json={"dwell_warn_h": 12, "dwell_alert_h": 36})
r = A.delete(B + f"/api/sections/{S2}")
s2 = r.json().get("section") or {}
check(r.ok and s2.get("dwell_warn_h") == 12 and s2.get("dwell_alert_h") == 36, f"#3515: delete returns the limits ({s2})")
r = A.post(B + "/api/sections", json={"list_id": P, "name": s2.get("name"), "sort": s2.get("sort"), "tasks": [],
                                      "dwell_warn_h": s2.get("dwell_warn_h"), "dwell_alert_h": s2.get("dwell_alert_h")})
check(r.ok and r.json().get("dwell_warn_h") == 12 and r.json().get("dwell_alert_h") == 36, f"#3515: the undo re-creates them ({r.text[:160]})")
r = A.post(B + "/api/sections", json={"list_id": P, "name": "Bad", "dwell_warn_h": 10, "dwell_alert_h": 3})
check(r.status_code == 400 and not kt.dbx("SELECT 1 FROM sections WHERE list_id=? AND name='Bad'", (P,)), f"#3515: a new section with red below yellow: 400 ({r.status_code})")

sys.exit(kt.done("p24100_b_api"))
