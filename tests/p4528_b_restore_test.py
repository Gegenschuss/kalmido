#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.550.0 (#4528): deleting a field and removing a member no longer lose data without a way back.
Own container (kt.fresh). Invented people and titles only (example.com); every step as the person without an organisation
with an invited member and her own agent. freelancer-matrix: lists
 - DELETE /api/fields/<id>: the field leaves the project (state, task values, API v1), its definition and values (also of a
   task in the trash) wait in the field trash (trash_id); GET /api/lists/<id>/fields/trash lists it for the owner (a member
   403, an outsider 404, an agent 403); its name can be given again; POST /api/fields/trash/<id>/restore brings it back with
   its id, values and grouping (a second restore 404); an agent's delete waits for an approval; the trash run only counts
   while the switch is off and deletes the row after the trash period with KALMIDO_PURGE_TRASH=1
 - removing a member: ?dry=1 names assignments, person values, delegations and watching (days); the removal keeps a memo;
   adding the person again answers restore_offer; GET member-memos and the restore are the owner's (a member 403); the restore
   brings back only what is still free (an assignment taken over meanwhile stays), once (then 404); not a member: 409; an
   agent's delegation comes back with the agent; leaving the project on your own keeps a memo too; an old memo is not offered
   and the trash run deletes it
usage: p4528_b_restore_test.py <datadir>      (KMT_NOSTART=1 / P4528B_NOSTART=1: a running server)"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

from freelancer_fixture import freelancer
from kt import B, CT, check, dbx, done, fresh, setup

V = B + "/api/v1"
fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="P4528B")
A = setup()
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
BID, Bo = freelancer(B, A, "bob")
OID, Ou = freelancer(B, A, "olga")  # an outsider


def box(code, env=()):
    """Python inside the app container (a fresh process)."""
    cmd = ["docker", "exec"]
    for e in env:
        cmd += ["-e", e]
    out = subprocess.run(cmd + [CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.commit()\nc.close()"],
                         capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def run_purge(switch):
    # 2.783.0 (#5368): deleted fields and member memos are the core's trash (core/writes.py obj_trash_tick), no longer tp_tick's
    return box("from kalmido.core.writes import obj_trash_tick\nprint('counts', obj_trash_tick(c, force=True))",
               ("KALMIDO_PURGE_TRASH=1",) if switch else ())


FTRQ = "FROM list_part_trash WHERE kind='list_field'"  # 2.783.0 (#5368): the field trash is the core's copy trash


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def val(tid, fid):
    x = dbx("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (tid, fid))
    return x[0][0] if x else None


def one(sql, args=()):
    x = dbx(sql, args)
    return x[0][0] if x else None


r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": ["read", "tasks:write", "structure", "delete"]})
assert r.status_code in (200, 201), r.text
AG = r.json()["id"]
TA = requests.Session()
TA.headers.update({"Authorization": "Bearer " + r.json()["token"]})
L = F.post(B + "/api/lists", json={"name": "Garden plan", "kind": "project"}).json()["id"]
check(F.put(B + f"/api/lists/{L}/members", json={"user_id": BID, "role": "edit"}).ok, "setup: bob is a member")
check(F.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the agent is a member")

# ================================================================== the field trash
r = F.post(B + f"/api/lists/{L}/fields", json={"name": "Stage", "type": "text"})
check(r.ok, f"setup: a field {r.text[:160]}")
FS = r.json()["id"]
T1, T2 = task(F, L, "Order seeds"), task(F, L, "Old idea")
check(F.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FS): "Draft"}}).ok and F.patch(B + f"/api/tasks/{T2}", json={"fields": {str(FS): "Old"}}).ok,
      "setup: two values")
check(F.delete(B + f"/api/tasks/{T2}").ok, "setup: a task with a value into the trash")
dbx("UPDATE lists SET group_field=? WHERE id=?", (f"cf:{FS}", L))
r = F.delete(B + f"/api/fields/{FS}")
TR = r.json().get("trash_id")
check(r.ok and r.json().get("values") == 2 and TR, f"delete: both values counted, a trash row {r.text[:160]}")
st = F.get(B + "/api/state").json()
check(not any(f["id"] == FS for f in st["fields"]), "delete: the field is gone from the state")
check(str(FS) not in (F.get(B + f"/api/tasks/{T1}").json().get("fields") or {}), "delete: the task has no value of it")
check(not one("SELECT 1 FROM list_fields WHERE id=?", (FS,)) and val(T1, FS) is None, "delete: no live row reads it any more")
check(one("SELECT group_field FROM lists WHERE id=?", (L,)) == "", "delete: no grouping by a gone field")
vals = json.loads(one(f"SELECT held {FTRQ} AND id=?", (TR,)) or "{}").get("vals") or []  # 2.783.0 (#5368): the core's copy
check(sorted(vals) == sorted([[T1, "Draft"], [T2, "Old"]]), f"trash: the values are kept, the trashed task's too {vals}")
r = F.get(B + f"/api/lists/{L}/fields/trash")
check(r.ok and [(x["id"], x["name"], x["tasks"]) for x in r.json()["fields"]] == [(TR, "Stage", 2)] and r.json()["days"] >= 1,
      f"trash list: the owner sees it {r.text[:200]}")
check(Bo.get(B + f"/api/lists/{L}/fields/trash").status_code == 403, "trash list: a member (no admin) 403")
check(Ou.get(B + f"/api/lists/{L}/fields/trash").status_code == 404, "trash list: an outsider 404")
check(Bo.post(B + f"/api/fields/trash/{TR}/restore").status_code == 403, "restore: a member (no admin) 403")
check(Ou.post(B + f"/api/fields/trash/{TR}/restore").status_code == 404, "restore: an outsider 404")
check(TA.get(B + f"/api/lists/{L}/fields/trash").status_code in (401, 403), "trash list: not for an agent")
r = F.post(B + f"/api/lists/{L}/fields", json={"name": "Stage", "type": "text"})
check(r.ok, f"the name of a deleted field can be given again {r.text[:160]}")
check(F.delete(B + f"/api/fields/{r.json()['id']}").ok, "the new one deleted again")
r = F.post(B + f"/api/fields/trash/{TR}/restore")
check(r.ok and r.json().get("values") == 2 and r.json()["field"]["id"] == FS, f"restore: the field with its id and values {r.text[:200]}")
check(val(T1, FS) == "Draft" and val(T2, FS) == "Old", "restore: the values are back (also of the task in the trash)")
check(any(f["id"] == FS for f in F.get(B + "/api/state").json()["fields"]), "restore: in the state again")
check(one("SELECT group_field FROM lists WHERE id=?", (L,)) == f"cf:{FS}", "restore: the grouping by it is back")
check(F.post(B + f"/api/fields/trash/{TR}/restore").status_code == 404, "restore: a second time 404")
check(F.post(B + f"/api/tasks/{T2}/restore").ok and val(T2, FS) == "Old", "the task out of the trash keeps its value")
r = TA.delete(V + f"/fields/{FS}")
# an agent is never a project admin: refused (403), the field stays
# 2.736.0 (p2501_a_nosham): one status, not "success or refusal" (measured: 403)
check(r.status_code == 403 and one("SELECT 1 FROM list_fields WHERE id=?", (FS,)), f"an agent cannot delete the field at once {r.status_code}")
# the trash run
TR2 = F.delete(B + f"/api/fields/{FS}").json().get("trash_id")
dbx("UPDATE list_part_trash SET deleted_at=? WHERE id=?", (ago(400), TR2))  # 2.783.0 (#5368): the core's copy trash
out = run_purge(False)
check(one(f"SELECT 1 {FTRQ} AND id=?", (TR2,)), f"trash run, switch off: only counted {out[-200:]}")
out = run_purge(True)
check(not one(f"SELECT 1 {FTRQ} AND id=?", (TR2,)), f"trash run, switch on: the old field is gone for good {out[-200:]}")
check(F.post(B + f"/api/fields/trash/{TR2}/restore").status_code == 404, "after the trash run: nothing to restore")

# 2.550.0 (#4528, review F1): a task value comes back only to a task that is still there (not one gone to the trash since)
r = F.post(B + f"/api/lists/{L}/fields", json={"name": "Blocked by", "type": "task"})
check(r.ok, f"review F1 setup: a task field {r.text[:160]}")
FT = r.json()["id"]
TX, TY = task(F, L, "Fence first"), task(F, L, "Gate")
check(F.patch(B + f"/api/tasks/{TY}", json={"fields": {str(FT): str(TX)}}).ok and val(TY, FT) == str(TX), "review F1 setup: a task value")
TRT = F.delete(B + f"/api/fields/{FT}").json().get("trash_id")
check(F.delete(B + f"/api/tasks/{TX}").ok, "review F1 setup: the task it pointed at goes into the trash")
r = F.post(B + f"/api/fields/trash/{TRT}/restore")
check(r.ok and val(TY, FT) is None, f"review F1: no task value back that points at a task in the trash {r.text[:160]} {val(TY, FT)}")
# 2.550.0 (#4528, review F2): the field trash keeps at most 100 deleted fields per project, the oldest go first
# 2.783.0 (#5368): the field trash is the core's copy trash (list_part_trash, kind list_field, ref_id = the field's id)
dbx("INSERT INTO list_part_trash(list_id,kind,ref_id,snap,deleted_at) SELECT ?, 'list_field', 900000 + g, '{\"name\": \"old\"}', ? "
    "FROM generate_series(1, 100) g", (L, ago(1)))
check(F.delete(B + f"/api/fields/{FT}").ok, "review F2: one more field deleted")
check(one(f"SELECT COUNT(*) {FTRQ} AND list_id=?", (L,)) == 100 and one(f"SELECT 1 {FTRQ} AND list_id=? AND ref_id=?", (L, FT)),
      f"review F2: at most 100 rows, the newest stays {one(f'SELECT COUNT(*) {FTRQ} AND list_id=?', (L,))}")
dbx(f"DELETE {FTRQ} AND list_id=? AND ref_id > 900000", (L,))

# ================================================================== removing a member and adding them again
FP = F.post(B + f"/api/lists/{L}/fields", json={"name": "Owner", "type": "person"}).json()["id"]
TA1, TA2 = task(F, L, "Dig the bed", assignee_id=BID), task(F, L, "Buy soil", assignee_id=BID)
TV, TW = task(F, L, "Plant tomatoes"), task(F, L, "Water plan")
TD = task(F, L, "Sort the shed", delegate_agent_id=AG)
check(F.patch(B + f"/api/tasks/{TV}", json={"fields": {str(FP): str(BID)}}).ok and val(TV, FP) == str(BID), "setup: bob in the person field")
check(Bo.post(B + f"/api/tasks/{TW}/watchers", json={}).ok, "setup: bob watches a task")
check(one("SELECT delegate_agent_id FROM tasks WHERE id=?", (TD,)) == AG, "setup: delegated to the agent")
r = F.delete(B + f"/api/lists/{L}/members/{BID}?dry=1")
d = r.json()
check(r.ok and (d.get("assigned"), d.get("values"), d.get("delegate"), d.get("watch")) == (2, 1, 0, 1) and d.get("days", 0) >= 1,
      f"dry: assignments, person value, watching, the days {r.text[:200]}")
r = F.delete(B + f"/api/lists/{L}/members/{AG}?dry=1")
check(r.ok and r.json().get("delegate") == 1, f"dry: the agent's delegation counts {r.text[:200]}")
check(one("SELECT COUNT(*) FROM member_memos") == 0 and one("SELECT assignee_id FROM tasks WHERE id=?", (TA1,)) == BID, "dry: nothing changes")
check(F.delete(B + f"/api/lists/{L}/members/{BID}").ok, "bob removed")
check(one("SELECT assignee_id FROM tasks WHERE id=?", (TA1,)) is None and val(TV, FP) is None
      and not one("SELECT 1 FROM task_watchers WHERE task_id=? AND user_id=?", (TW, BID)), "removed: as before, his rows end")
check(one("SELECT COUNT(*) FROM member_memos WHERE list_id=? AND user_id=? AND by_id=?", (L, BID, FID)) == 1, "removed: a memo")
r = F.get(B + f"/api/lists/{L}/member-memos")
check(r.ok and [(m["user_id"], m["member"], m["assigned"]) for m in r.json()["memos"]] == [(BID, False, 2)], f"memos: bob, not a member {r.text[:200]}")
check(F.post(B + f"/api/lists/{L}/members/{BID}/restore").status_code == 409, "restore before adding him again: 409")
check(F.patch(B + f"/api/tasks/{TA2}", json={"assignee_id": FID}).ok, "meanwhile frida takes over one of his tasks")
r = F.put(B + f"/api/lists/{L}/members", json={"user_id": BID, "role": "edit"})
o = r.json().get("restore_offer") or {}
check(r.ok and (o.get("assigned"), o.get("values"), o.get("watch")) == (2, 1, 1), f"added again: the answer offers the way back {r.text[:200]}")
check(Bo.get(B + f"/api/lists/{L}/member-memos").status_code == 403 and Bo.post(B + f"/api/lists/{L}/members/{BID}/restore").status_code == 403,
      "memos and restore: not for a member without admin rights")
check(Ou.get(B + f"/api/lists/{L}/member-memos").status_code == 404, "memos: an outsider 404")
r = F.post(B + f"/api/lists/{L}/members/{BID}/restore")
j = r.json()
check(r.ok and j.get("restored") == {"assigned": 1, "values": 1, "delegate": 0, "watch": 1} and j.get("skipped") == 1,
      f"restore: what is still free, the taken one skipped {r.text[:200]}")
check(one("SELECT assignee_id FROM tasks WHERE id=?", (TA1,)) == BID and one("SELECT assignee_id FROM tasks WHERE id=?", (TA2,)) == FID,
      "restore: his assignment back, frida's new one stays")
check(val(TV, FP) == str(BID) and one("SELECT 1 FROM task_watchers WHERE task_id=? AND user_id=?", (TW, BID)), "restore: person value and watching back")
check(F.post(B + f"/api/lists/{L}/members/{BID}/restore").status_code == 404, "restore: a second time 404")
# the agent's delegation
check(F.delete(B + f"/api/lists/{L}/members/{AG}").ok and one("SELECT delegate_agent_id FROM tasks WHERE id=?", (TD,)) is None, "the agent removed: the delegation ends")
r = F.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"})
check(r.ok and (r.json().get("restore_offer") or {}).get("delegate") == 1, f"the agent added again: offered {r.text[:200]}")
r = F.post(B + f"/api/lists/{L}/members/{AG}/restore")
check(r.ok and r.json()["restored"]["delegate"] == 1 and one("SELECT delegate_agent_id FROM tasks WHERE id=?", (TD,)) == AG,
      f"restore: delegated to the agent again {r.text[:200]}")
# leaving on your own
check(Bo.delete(B + f"/api/lists/{L}/members/{BID}").ok, "bob leaves the project")
check(one("SELECT by_id FROM member_memos WHERE list_id=? AND user_id=?", (L, BID)) == BID, "leaving: a memo too (by himself)")
check(F.put(B + f"/api/lists/{L}/members", json={"user_id": BID, "role": "edit"}).ok, "frida adds him again")
r = F.post(B + f"/api/lists/{L}/members/{BID}/restore")
check(r.ok and r.json()["restored"]["assigned"] == 1 and one("SELECT assignee_id FROM tasks WHERE id=?", (TA1,)) == BID, f"after leaving: restored {r.text[:200]}")
# an old memo
check(F.delete(B + f"/api/lists/{L}/members/{BID}").ok and F.put(B + f"/api/lists/{L}/members", json={"user_id": BID, "role": "edit"}).ok,
      "removed and added again")
dbx("UPDATE member_memos SET deleted_at=? WHERE list_id=? AND user_id=?", (ago(400), L, BID))
check(not F.get(B + f"/api/lists/{L}/member-memos").json()["memos"] and F.post(B + f"/api/lists/{L}/members/{BID}/restore").status_code == 404,
      "an old memo is no longer offered")
out = run_purge(True)
check(not one("SELECT 1 FROM member_memos WHERE list_id=? AND user_id=?", (L, BID)), f"the trash run deletes the old memo {out[-200:]}")

sys.exit(done("p4528_b_restore"))
