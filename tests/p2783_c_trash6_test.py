#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.783.0 (#5368, stage 6 of the trash core): the last trashes of their own run through the core.
Own container (kt.fresh). Invented people and titles only (example.com); every step as a person without an organisation
(freelancer fixture), a second one as the stranger. freelancer-matrix: lists, team, time
 - inbound webhooks: delete = the core's part_trash (deleted_by), the URL 404; restore through the core (a stranger 404); the
   core's run (core/writes.py obj_trash_tick, kind hook_in) counts with the switch off and deletes after the trash period
 - a deleted custom field waits as the core's copy (list_part_trash, kind list_field) and comes back with its values; the
   core's run deletes an old copy (restore 404 then); an old row of field_trash (a version before) moves there (ftr_move)
   and is restorable with its values
 - the Undo copy of "Delete all times" is the core's copy (kind time_wipe): restore by wipe, once; the core's run deletes an
   old copy; an old time_wipes row moves there (tzw_move); a gone account takes its copies along (tzw_revoked)
 - a removed member's memo: the core's run deletes an old one (kind member_memo)
 - team chat: a deleted message restored, deleted again; the core's run deletes an old tombstone with its kept text, a
   thread's first message stays while a reply points at it (kind tchat_msg)
 - a section's copy (kind section) ends in the core's run too; the projects' trash list shows only sections / sprints
 - files/trashpurge.py tp_tick no longer counts any of them
usage: p2783_c_trash6_test.py <datadir>      (P2783C_NOSTART=1: a running server)"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

from freelancer_fixture import freelancer
from kt import B, CT, check, dbx, done, fresh, setup

fresh(prefix="P2783C")
A = setup()
FID, F = freelancer(B, A)
GID, G = freelancer(B, A, "gerda")


def box(code, purge=False):
    """Python inside the app container (a fresh process) -> its last output line."""
    cmd = ["docker", "exec"] + (["-e", "KALMIDO_PURGE_TRASH=1"] if purge else [])
    out = subprocess.run(cmd + [CT, "python", "-c", "import json, app\nfrom kalmido.core.db import connect\nc = connect()\n" + code
                                + "\nc.commit()\nc.close()"], capture_output=True, text=True)
    check(out.returncode == 0, f"the run works {out.stdout[-300:]} {out.stderr[-900:]}")
    lines = out.stdout.strip().splitlines()
    return lines[-1] if lines else ""


def core(purge):
    """The core's trash run (forced) -> its counts per kind."""
    return json.loads(box("from kalmido.core.writes import obj_trash_tick\nprint(json.dumps(obj_trash_tick(c, force=True)))", purge) or "{}")


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


def one(sql, args=()):
    x = dbx(sql, args)
    return x[0][0] if x else None


L = F.post(B + "/api/lists", json={"name": "Pond survey", "kind": "project"}).json()["id"]
check(isinstance(L, int), "setup: a project of the person without an organisation")

# ================================================================== inbound webhooks
r = F.post(B + f"/api/lists/{L}/hooks-in", json={"name": "Sensor"})
check(r.status_code == 201, f"webhook: made {r.status_code} {r.text[:160]}")
HID, URL = r.json()["id"], B + "/api/hooks/in/" + r.json()["url"].rsplit("/", 1)[1]
check(requests.post(URL, json={"title": "Water level"}).status_code == 201, "webhook: it creates a task")
check(G.delete(B + f"/api/hooks-in/{HID}").status_code == 404, "webhook: a stranger cannot delete it (404)")
check(F.delete(B + f"/api/hooks-in/{HID}").ok, "webhook: deleted")
check(dbx("SELECT deleted_at IS NOT NULL, deleted_by FROM hook_in WHERE id=?", (HID,)) == [(True, FID)], "webhook: in the core's trash, by whom")
check(requests.post(URL, json={"title": "Gone"}).status_code == 404, "webhook: its URL answers 404")
check(all(h["id"] != HID for h in F.get(B + f"/api/lists/{L}/hooks-in").json()["hooks"]), "webhook: gone from the settings")
check(G.post(B + f"/api/hooks-in/{HID}/restore").status_code == 404, "webhook: a stranger cannot restore it (404)")
r = F.post(B + f"/api/hooks-in/{HID}/restore")
check(r.ok and r.json()["id"] == HID and one("SELECT updated_at FROM hook_in WHERE id=?", (HID,)), f"webhook: restored through the core {r.text[:160]}")
check(requests.post(URL, json={"title": "Back"}).status_code == 201, "webhook: the same URL works again")
check(F.post(B + f"/api/hooks-in/{HID}/restore").status_code == 404, "webhook: a live one cannot be restored (404)")
check(F.delete(B + f"/api/hooks-in/{HID}").ok, "webhook: deleted again")
dbx("UPDATE hook_in SET deleted_at=? WHERE id=?", (ago(400), HID))

# ================================================================== custom fields
T1 = F.post(B + "/api/tasks", json={"title": "North bank", "list_id": L}).json()["id"]
FL = F.post(B + f"/api/lists/{L}/fields", json={"name": "Depth", "type": "text"}).json()["id"]
check(F.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FL): "2 m"}}).ok, "field: a value")
r = F.delete(B + f"/api/fields/{FL}")
TR = r.json().get("trash_id")
check(r.ok and dbx("SELECT kind, ref_id, list_id, deleted_by FROM list_part_trash WHERE id=?", (TR,)) == [("list_field", FL, L, FID)],
      f"field: the core's copy (list_part_trash) {r.text[:160]}")
r = G.get(B + f"/api/lists/{L}/fields/trash")
check(r.status_code in (403, 404), f"field: a stranger does not see the field trash {r.status_code}")
check(G.post(B + f"/api/fields/trash/{TR}/restore").status_code in (403, 404), "field: a stranger cannot restore it")
r = F.get(B + f"/api/lists/{L}/fields/trash")
check(r.ok and [(x["id"], x["name"], x["type"], x["tasks"]) for x in r.json()["fields"]] == [(TR, "Depth", "text", 1)], f"field: the trash list {r.text[:200]}")
r = F.post(B + f"/api/fields/trash/{TR}/restore")
check(r.ok and r.json()["field"]["id"] == FL and r.json()["values"] == 1 and r.json()["field"]["name"] == "Depth",
      f"field: restored with its id and value {r.text[:200]}")
check(one("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (T1, FL)) == "2 m"
      and not one("SELECT 1 FROM list_part_trash WHERE id=?", (TR,)), "field: the value is back, the copy is used up")
check(F.post(B + f"/api/fields/trash/{TR}/restore").status_code == 404, "field: a second restore 404")
TR2 = F.delete(B + f"/api/fields/{FL}").json().get("trash_id")
dbx("UPDATE list_part_trash SET deleted_at=? WHERE id=?", (ago(400), TR2))
# a row of the old field trash (written by a version before 2.783) moves into the core's copy trash
FO = F.post(B + f"/api/lists/{L}/fields", json={"name": "Width", "type": "text"}).json()["id"]
check(F.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FO): "4 m"}}).ok, "old field trash: a value")
dbx("DELETE FROM task_field_values WHERE field_id=?", (FO,))
dbx("DELETE FROM list_fields WHERE id=?", (FO,))
dbx("INSERT INTO field_trash(list_id,field_id,name,type,def,vals,n,grouped,deleted_by,deleted_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
    (L, FO, "Width", "text", json.dumps({"options": "{}", "pinned": 0, "sort": 2, "created_at": ago(3)}), json.dumps([[T1, "4 m"]]), 1, 0, FID, ago(2)))
# the start step (core/objhooks.START) runs when the process imports the app already: here once more, then nothing is left
out = box("from kalmido.lists.fields import ftr_move\nprint(ftr_move(c))")
check(out in ("0", "1") and not one("SELECT COUNT(*) FROM field_trash"), f"old field trash: moved at the start step {out}")
TRO = one("SELECT id FROM list_part_trash WHERE kind='list_field' AND ref_id=?", (FO,))
check(TRO and one("SELECT deleted_by FROM list_part_trash WHERE id=?", (TRO,)) == FID, "old field trash: one copy, who deleted it kept")
r = F.post(B + f"/api/fields/trash/{TRO}/restore")
check(r.ok and r.json()["field"]["id"] == FO and r.json()["values"] == 1
      and one("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (T1, FO)) == "4 m", f"old field trash: restored with its value {r.text[:200]}")

# ================================================================== "Delete all times"
for i in range(2):
    st0 = (datetime.now(timezone.utc) - timedelta(days=2, hours=i)).replace(microsecond=0)
    check(F.post(B + "/api/time/entries", json={"task_id": T1, "start": st0.isoformat(), "end": (st0 + timedelta(minutes=20)).isoformat()}).ok,
          f"time: entry {i}")
r = F.post(B + f"/api/lists/{L}/time/delete-all", json={"confirm": "Pond survey"})
W = r.json().get("wipe")
check(r.ok and r.json()["deleted"] == 2 and dbx("SELECT kind, ref_id, deleted_by FROM list_part_trash WHERE id=?", (W,)) == [("time_wipe", FID, FID)],
      f"time: the Undo copy is the core's {r.text[:160]}")
pv = F.get(B + f"/api/lists/{L}/time/delete-all").json()
check((pv.get("undo") or {}).get("wipe") == W and pv["undo"]["count"] == 2 and pv["undo"]["seconds"] == 2400, f"time: the preview names it {pv.get('undo')}")
check(G.post(B + f"/api/lists/{L}/time/restore", json={"wipe": W}).status_code in (403, 404), "time: a stranger cannot use it")
r = F.post(B + f"/api/lists/{L}/time/restore", json={"wipe": W})
check(r.ok and r.json()["restored"] == 2 and not one("SELECT 1 FROM list_part_trash WHERE id=?", (W,)), f"time: restored, the copy used up {r.text[:160]}")
check(F.post(B + f"/api/lists/{L}/time/restore", json={"wipe": W}).status_code == 404, "time: once (404)")
W2 = F.post(B + f"/api/lists/{L}/time/delete-all", json={"confirm": "Pond survey"}).json().get("wipe")
dbx("UPDATE list_part_trash SET deleted_at=? WHERE id=?", (ago(400), W2))
# an old time_wipes row moves; an account that goes takes its copies along
dbx("INSERT INTO time_wipes(user_id,list_id,entries,n,seconds,deleted_at) VALUES(?,?,?,?,?,?)", (GID, L, "[]", 0, 0, ago(1)))
out = box("from kalmido.personal.timewipe import tzw_move\nprint(tzw_move(c))")
check(out in ("0", "1") and not one("SELECT COUNT(*) FROM time_wipes")
      and one("SELECT COUNT(*) FROM list_part_trash WHERE kind='time_wipe' AND ref_id=?", (GID,)) == 1, f"time: the old copy moved {out}")
out = box(f"from kalmido.personal.timewipe import tzw_revoked\nprint(json.dumps(tzw_revoked(c, {GID}, None, 'delete')))")
check(json.loads(out or "{}") == {"time_wipes": 1} and not one("SELECT 1 FROM list_part_trash WHERE kind='time_wipe' AND ref_id=?", (GID,)),
      f"time: a gone account takes its copies along {out}")

# ================================================================== a removed member's memo
check(F.put(B + f"/api/lists/{L}/members", json={"user_id": GID, "role": "edit"}).ok, "memo: gerda is a member")
check(F.patch(B + f"/api/tasks/{T1}", json={"assignee_id": GID}).ok, "memo: she has a task")
check(F.delete(B + f"/api/lists/{L}/members/{GID}").ok and one("SELECT 1 FROM member_memos WHERE list_id=? AND user_id=?", (L, GID)),
      "memo: removed, a memo")
dbx("UPDATE member_memos SET deleted_at=? WHERE list_id=? AND user_id=?", (ago(400), L, GID))

# ================================================================== team chat
dbx("INSERT INTO groups(name,oidc_group,created_at,created_by) VALUES(?,?,?,?)", ("Pond 5368", "", ago(1), FID))
GR = one("SELECT id FROM groups WHERE name=?", ("Pond 5368",))
for x in (FID, GID):
    dbx("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (GR, x, ago(1)))
r = F.post(B + "/api/team/channels", json={"name": "Pond 5368", "members": [GID]})
check(r.status_code == 201, "chat: own channel " + r.text[:160])
CH = r.json().get("id")
M1 = F.post(B + f"/api/team/rooms/{CH}/messages", json={"body": "Frogs seen"}).json()["id"]
check(F.delete(B + f"/api/team/messages/{M1}").ok and one("SELECT body FROM tchat_trash_text WHERE message_id=?", (M1,)) == "Frogs seen",
      "chat: deleted, its text kept")
check(G.post(B + f"/api/team/messages/{M1}/restore").status_code in (403, 404), "chat: gerda may not restore it")
r = F.post(B + f"/api/team/messages/{M1}/restore")
check(r.ok and r.json()["body"] == "Frogs seen", f"chat: restored {r.status_code}")
check(F.delete(B + f"/api/team/messages/{M1}").ok, "chat: deleted again")
ROOT = F.post(B + f"/api/team/rooms/{CH}/messages", json={"body": "Thread start"}).json()["id"]
r = G.post(B + f"/api/team/rooms/{CH}/messages", json={"body": "A reply", "thread_of": ROOT})
check(r.ok, f"chat: a reply in the thread {r.text[:160]}")
check(F.delete(B + f"/api/team/messages/{ROOT}").ok, "chat: the thread's first message deleted")
dbx("UPDATE tchat_msgs SET deleted_at=? WHERE id IN (?,?)", (ago(400), M1, ROOT))

# ================================================================== a section's copy
SEC = F.post(B + "/api/sections", json={"list_id": L, "name": "Done"}).json()["id"]
check(F.delete(B + f"/api/sections/{SEC}").ok, "section: deleted (a copy)")
dbx("UPDATE list_part_trash SET deleted_at=? WHERE kind='section' AND ref_id=?", (ago(400), SEC))
r = F.get(B + "/api/trash/parts")
items = r.json().get("items") if r.ok else []
check(r.ok and any(x["kind"] == "section" and x["id"] == SEC for x in items) and not any(x["kind"] in ("list_field", "time_wipe") for x in items),
      f"projects' trash: the section, no field / time copies {str(items)[:300]}")

# ================================================================== the core's run
dry = core(False)
check(dry.get("hook_in") == 1 and dry.get("list_field") == 1 and dry.get("time_wipe") == 1 and dry.get("member_memo") == 1
      and dry.get("tchat_msg") == 1 and dry.get("section") == 1, f"switch off: the core's run counts each kind {dry}")
check(one("SELECT 1 FROM hook_in WHERE id=?", (HID,)) and one("SELECT 1 FROM list_part_trash WHERE id=?", (TR2,)), "switch off: nothing goes")
old = json.loads(box("from kalmido.files.trashpurge import tp_tick\nprint(json.dumps(tp_tick(c, True)))") or "{}")
check(not any(k in old for k in ("chat_tombstones", "time_wipes", "fields", "member_memos", "list_parts")),
      f"tp_tick no longer has a run of its own for them {old}")
got = core(True)
check(got.get("hook_in") == 1 and got.get("list_field") == 1 and got.get("time_wipe") == 1 and got.get("member_memo") == 1
      and got.get("tchat_msg") == 1 and got.get("section") == 1, f"switch on: deleted {got}")
check(not one("SELECT 1 FROM hook_in WHERE id=?", (HID,)) and F.post(B + f"/api/hooks-in/{HID}/restore").status_code == 404,
      "webhook: gone for good after the period")
check(not one("SELECT 1 FROM list_part_trash WHERE id=?", (TR2,)) and F.post(B + f"/api/fields/trash/{TR2}/restore").status_code == 404,
      "field: the old copy gone, nothing to restore")
check(not one("SELECT 1 FROM list_part_trash WHERE id=?", (W2,)) and F.post(B + f"/api/lists/{L}/time/restore", json={"wipe": W2}).status_code == 404,
      "time: the old copy gone")
check(not one("SELECT 1 FROM member_memos WHERE list_id=? AND user_id=?", (L, GID)), "memo: the old memo gone")
check(not one("SELECT 1 FROM tchat_msgs WHERE id=?", (M1,)) and not one("SELECT 1 FROM tchat_trash_text WHERE message_id=?", (M1,)),
      "chat: the old tombstone and its kept text gone")
check(one("SELECT 1 FROM tchat_msgs WHERE id=?", (ROOT,)), "chat: the thread's first message stays while its reply points at it")
check(not one("SELECT 1 FROM list_part_trash WHERE kind='section' AND ref_id=?", (SEC,))
      and F.post(B + f"/api/sections/{SEC}/restore").status_code == 404, "section: the old copy gone")
check(one("SELECT 1 FROM tasks WHERE id=?", (T1,)) and one("SELECT 1 FROM list_fields WHERE id=?", (FO,)), "live rows stay")

sys.exit(done("p2783_c_trash6"))
