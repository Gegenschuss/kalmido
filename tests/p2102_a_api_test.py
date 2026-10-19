#!/usr/bin/env python3
"""2.102.0 API tests, part A (#1988 with #2166: the list trash; #2003: the invitation count of ev_sig), own container
(start.sh). Invented people, lists and addresses only (example.com).
tenant-matrix: list
freelancer-matrix: lists
 - an organisation admin deletes an archived organisation list of another owner: the list goes into the ORGANISATION's list
   trash with everything (tasks stay in it, fields + values, sections, list chat); nothing lands in the owner's private inbox,
   a single task comes back only with its list (409), never into the private space; a plain member neither sees nor restores
   nor purges it; the admin restores it into the organisation (archived) with fields, values and chat
 - the former owner who left the organisation no longer sees it in any trash (404 on restore); the admin still restores it
 - a person without an organisation (freelancer): a private list into the own trash, restore, delete for good from the
   trash (rows and the attachment file on disk gone); the watchdog's purge after 30 days removes list, tasks and files
 - deleted lists are hidden from the state, the archive, the organisation admin's overview and the agent API
 - #2003: an invitation to an event of an organisation the person left no longer counts in the state's evsig
usage: p2102_a_api_test.py <datadir>      (P2102A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,fields,events,files,time"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def app_log():
    out = subprocess.run(["docker", "logs", "--tail", "400", CT], capture_output=True, text=True)
    text = out.stdout + out.stderr
    i = text.rfind("Traceback")
    print(text[i:i + 4000] if i >= 0 else text[-2000:], flush=True)


def state(s):
    return s.get(B + "/api/state").json()


def trash_ids(s):
    r = s.get(B + "/api/trash/lists")
    return [x["id"] for x in r.json()["lists"]] if r.ok else None


def att_path(tid):
    rows = sql("SELECT path FROM attachments WHERE task_id=?", (tid,))
    return os.path.join(DATA, "attachments", rows[0][0]) if rows else None


if os.environ.get("P2102A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Owner"), ("carol", "Carol Member")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = state(A)["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
BOB, CAROL = state(Bo)["me"]["id"], state(Ca)["me"]["id"]
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": ALICE}).json()["id"]
for e in ("bob@example.com", "carol@example.com"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": e, "role": "member"}).ok
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], **H}
BINBOX = sql("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (BOB,))[0][0]

# ================================================================== #1988 an organisation list of Bob, deleted by the org admin
LT = Bo.post(B + "/api/lists", json={"name": "Spring campaign", "org_id": ORG, "kind": "project"}).json()["id"]
check(Bo.put(B + f"/api/lists/{LT}/members", json={"user_id": CAROL, "role": "edit"}).ok, "setup: carol in bob's list")
FLD = Bo.post(B + f"/api/lists/{LT}/fields", json={"name": "Budget", "type": "number"}).json()["id"]
SEC = Bo.post(B + "/api/sections", json={"list_id": LT, "name": "Shooting"}).json()
SEC = SEC.get("id") or SEC.get("section", {}).get("id")
T1 = Bo.post(B + "/api/tasks", json={"title": "Book the studio", "list_id": LT, "section_id": SEC}).json()["id"]
T2 = Bo.post(B + "/api/tasks", json={"title": "Old idea", "list_id": LT}).json()["id"]
Bo.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FLD): "1200"}})
Bo.delete(B + f"/api/tasks/{T2}")  # already in the trash before the list: stays there after the restore
T2_DEL = sql("SELECT deleted_at FROM tasks WHERE id=?", (T2,))[0][0]
room = next((x for x in Bo.get(B + "/api/team").json().get("rooms", []) if x["kind"] == "list" and x["list_id"] == LT), None)
check(room is not None, "setup: the shared list has its chat")
if room:
    Bo.post(B + f"/api/team/rooms/{room['id']}/messages", json={"body": "Studio is booked for Monday"})
n_msg = sql("SELECT COUNT(*) FROM tchat_msgs WHERE room_id=?", (room["id"],))[0][0] if room else 0
check(n_msg >= 1, f"setup: one chat message ({n_msg})")
check(A.post(B + f"/api/orgs/{ORG}/lists/{LT}/archive", json={"archived": True}).ok, "setup: the admin archives it")

r = A.delete(B + f"/api/orgs/{ORG}/lists/{LT}", json={"confirm": "Spring campaign"})
if not r.ok:
    app_log()
check(r.ok and r.json().get("trash") and LT not in {x["id"] for x in r.json()["lists"]}, "the org admin deletes it: into the trash " + r.text[:160])
row = sql("SELECT deleted_at, deleted_by, org_id FROM lists WHERE id=?", (LT,))
check(row and row[0][0] and row[0][1] == ALICE and row[0][2] == ORG, f"lists.deleted_at / deleted_by set, still the organisation's {row}")
rows = dict(sql("SELECT id, list_id FROM tasks WHERE id IN (?, ?)", (T1, T2)))
check(rows == {T1: LT, T2: LT} and sql("SELECT deleted_at IS NOT NULL FROM tasks WHERE id=?", (T1,))[0][0], "the tasks stay in the list, in the trash")
check(not sql("SELECT 1 FROM tasks WHERE list_id=? AND title IN ('Book the studio', 'Old idea')", (BINBOX,)), "nothing in the owner's private inbox")
check(sql("SELECT COUNT(*) FROM list_fields WHERE list_id=?", (LT,))[0][0] == 1 and sql("SELECT COUNT(*) FROM task_field_values WHERE task_id=?", (T1,))[0][0] == 1
      and sql("SELECT COUNT(*) FROM sections WHERE list_id=?", (LT,))[0][0] >= 1, "fields, values and sections are kept")
check(not room or sql("SELECT COUNT(*) FROM tchat_msgs WHERE room_id=?", (room["id"],))[0][0] == n_msg, "the list chat is kept")
# hidden everywhere
sb = state(Bo)
check(LT not in {x["id"] for x in sb["lists"]} and not {T1, T2} & {t["id"] for t in sb["tasks"]}, "bob's state: neither the list nor its tasks")
tb = Bo.get(B + "/api/tasks?scope=trash&limit=500").json()
tb = tb.get("tasks", tb) if isinstance(tb, dict) else tb
check(not {T1, T2} & {t["id"] for t in tb}, "bob's task trash does not show them (only the list trash)")
check(LT not in {x["id"] for x in A.get(B + f"/api/orgs/{ORG}/lists").json()["lists"]}, "the org admin's overview leaves it out")
check(requests.get(B + f"/api/v1/lists/{LT}", headers=AGH).status_code in (403, 404), "the agent API does not reach it")
check(Bo.get(B + f"/api/lists/{LT}/fields").status_code in (403, 404), "a list route answers 404")
# a single task never comes back on its own (and never into the private space)
r = Bo.post(B + f"/api/tasks/{T1}/restore")
check(r.status_code in (403, 409) and sql("SELECT deleted_at IS NOT NULL, list_id FROM tasks WHERE id=?", (T1,))[0] == (1, LT),
      f"bob restores a single task: refused, still in the list ({r.status_code})")
r = Bo.patch(B + f"/api/tasks/{T1}", json={"list_id": BINBOX})
check(r.status_code in (403, 404) and sql("SELECT list_id FROM tasks WHERE id=?", (T1,))[0][0] == LT, f"bob cannot move it into his inbox ({r.status_code})")
# who sees the trash
tl = A.get(B + "/api/trash/lists").json()
x = next((y for y in tl["lists"] if y["id"] == LT), None)
check(x and x["org_id"] == ORG and x["tasks"] == 1 and x["by_name"] == "Alice Admin" and tl["days"] == 30, f"the org admin's trash: the list with 1 task {tl}")
check(LT in (trash_ids(Bo) or []), "the owner (a member of the organisation) sees it in the organisation's trash")
check(LT not in (trash_ids(Ca) or []) and Ca.post(B + f"/api/trash/lists/{LT}/restore").status_code == 404
      and Ca.delete(B + f"/api/trash/lists/{LT}").status_code == 404, "a plain member: not in the trash, restore / purge 404")
check(requests.post(B + f"/api/trash/lists/{LT}/restore", headers=AGH).status_code in (401, 403, 404), "an agent cannot restore")
# the admin restores it with everything
r = A.post(B + f"/api/trash/lists/{LT}/restore")
check(r.ok, "the org admin restores it " + r.text[:160])
check(sql("SELECT deleted_at, org_id, archived FROM lists WHERE id=?", (LT,))[0] == (None, ORG, 1), "back in the organisation, archived")
check(sql("SELECT deleted_at FROM tasks WHERE id=?", (T1,))[0][0] is None and sql("SELECT section_id FROM tasks WHERE id=?", (T1,))[0][0] == SEC,
      "its task is back, in its section")
check(sql("SELECT deleted_at FROM tasks WHERE id=?", (T2,))[0][0] == T2_DEL, "the task deleted before stays in the trash")
check(sql("SELECT value FROM task_field_values WHERE task_id=?", (T1,)) == [("1200",)] or
      str(sql("SELECT value FROM task_field_values WHERE task_id=?", (T1,))[0][0]).startswith("1200"), "the field value is back")
check(LT in {x["id"] for x in state(Ca)["lists"]}, "carol sees the list again")
check(any(x["action"] == "undelete" for x in A.get(B + f"/api/orgs/{ORG}/lists").json()["log"]), "the history names the restore")

# ---- the owner leaves the organisation: the deleted list never shows in his (private) trash
check(A.delete(B + f"/api/orgs/{ORG}/lists/{LT}", json={"confirm": "Spring campaign"}).ok, "deleted again")
check(A.delete(B + f"/api/orgs/{ORG}/members/{BOB}").ok, "bob leaves the organisation")
check(LT not in (trash_ids(Bo) or []) and Bo.post(B + f"/api/trash/lists/{LT}/restore").status_code == 404, "the former owner: not in his trash, restore 404")
check(Bo.post(B + f"/api/tasks/{T1}/restore").status_code == 404, "the former owner: the task is not his (404)")
check(A.post(B + f"/api/trash/lists/{LT}/restore").ok and sql("SELECT org_id FROM lists WHERE id=?", (LT,))[0][0] == ORG, "the admin restores it, still the organisation's")

# ================================================================== #1988 a person without an organisation
FID, Fr = freelancer(B, A)
# freelancer-matrix: lists
LF = Fr.post(B + "/api/lists", json={"name": "Portfolio", "org_id": None}).json()["id"]
TF = Fr.post(B + "/api/tasks", json={"title": "Pick photos", "list_id": LF}).json()["id"]
r = Fr.post(B + f"/api/tasks/{TF}/attachments", files={"file": ("brief.txt", b"photo brief\n" * 20, "text/plain")})
check(r.ok, "freelancer: an attachment " + r.text[:120])
PF = att_path(TF)
check(PF and os.path.isfile(PF), f"the attachment file is on disk {PF}")
check(Fr.patch(B + f"/api/lists/{LF}", json={"archived": True}).ok, "freelancer: archive")
r = Fr.delete(B + f"/api/lists/{LF}")
check(r.ok and r.json().get("trash"), "freelancer: delete -> into the own trash " + r.text[:120])
check(trash_ids(Fr) == [LF] and LF not in {x["id"] for x in state(Fr)["lists"]}, "freelancer: in the list trash, not among the lists")
check(LF not in (trash_ids(A) or []) and A.post(B + f"/api/trash/lists/{LF}/restore").status_code == 404, "another person (the server admin): 404")
check(Fr.post(B + f"/api/trash/lists/{LF}/restore").ok and LF in {x["id"] for x in state(Fr)["lists"]}
      and sql("SELECT deleted_at FROM tasks WHERE id=?", (TF,))[0][0] is None, "freelancer: restore (the undo): list and task back")
check(Fr.delete(B + f"/api/lists/{LF}").ok, "freelancer: delete again")
r = Fr.delete(B + f"/api/trash/lists/{LF}")
check(r.ok and not sql("SELECT 1 FROM lists WHERE id=?", (LF,)) and not sql("SELECT 1 FROM tasks WHERE id=?", (TF,)), "freelancer: deleted for good from the trash")
check(not os.path.exists(PF), "... the attachment file is gone from the disk")
check(Fr.delete(B + f"/api/trash/lists/{LF}").status_code == 404 and trash_ids(Fr) == [], "gone: 404, the trash is empty")

# ---- the watchdog's purge after the period (30 days)
LW = Fr.post(B + "/api/lists", json={"name": "Old shoot", "org_id": None}).json()["id"]
TW = Fr.post(B + "/api/tasks", json={"title": "Raw files", "list_id": LW}).json()["id"]
Fr.post(B + f"/api/tasks/{TW}/attachments", files={"file": ("raw.txt", b"raw\n" * 50, "text/plain")})
Fr.post(B + f"/api/tasks/{TW}/comments", json={"body": "Keep the raw files until the end"})
PW = att_path(TW)
Fr.patch(B + f"/api/lists/{LW}", json={"archived": True})
check(Fr.delete(B + f"/api/lists/{LW}").ok, "watchdog: a list in the trash")
LK = Fr.post(B + "/api/lists", json={"name": "Fresh delete", "org_id": None}).json()["id"]
Fr.patch(B + f"/api/lists/{LK}", json={"archived": True})
Fr.delete(B + f"/api/lists/{LK}")
old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(timespec="seconds")
sql("UPDATE lists SET deleted_at=? WHERE id=?", (old, LW), write=True)
out = subprocess.run(["docker", "exec", CT, "python", "-c",
                      "import app\nfrom kalmido.core.db import connect\nfrom kalmido.lists.listtrash import otr_prune\n"
                      "c = connect()\nprint('purged', otr_prune(c, True))\nc.close()"], capture_output=True, text=True)
check("purged 1" in out.stdout, "watchdog: one list purged " + (out.stdout + out.stderr)[-400:])
check(not sql("SELECT 1 FROM lists WHERE id=?", (LW,)) and not sql("SELECT 1 FROM tasks WHERE id=?", (TW,))
      and not sql("SELECT 1 FROM comments WHERE task_id=?", (TW,)), "watchdog: list, task and comment gone")
check(PW and not os.path.exists(PW), "watchdog: the attachment file is gone")
check(sql("SELECT deleted_at IS NOT NULL FROM lists WHERE id=?", (LK,)) == [(1,)], "watchdog: a list deleted today stays in the trash")

# ================================================================== #2003 ev_sig counts only invitations that still count
CAL = A.post(B + "/api/evcals", json={"name": "Studio", "org_id": ORG}).json()
CAL = CAL.get("id") or CAL.get("cal", {}).get("id")
day = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
r = A.post(B + "/api/events", json={"title": "Shooting day", "cal_id": CAL, "start": day + "T10:00", "end": day + "T12:00",
                                     "attendees": [{"user_id": CAROL}]})
check(r.status_code in (200, 201), "an event of the organisation with carol invited " + r.text[:160])
sig = str(state(Ca).get("evsig", ""))
check(sig.split("|")[0] == "1", f"carol's evsig counts the invitation: {sig}")
check(A.delete(B + f"/api/orgs/{ORG}/members/{CAROL}").ok, "carol leaves the organisation")
sig2 = str(state(Ca).get("evsig", ""))
check(sig2.split("|")[0] == "0" and sig2 != sig, f"#2003: the invitation no longer counts: {sig2}")

print(f"p2102_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
