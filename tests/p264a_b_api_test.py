#!/usr/bin/env python3
"""2.64.1 API tests (part B): the lock per list on the other ways out of the server (#1817, findings H2, M4, M5, M7, L6).
A list is switched on through part A's routes (start, todo / bulk with synthetic ciphertexts "e2e1:{v, g, iv, ct}" -- the
server never reads them --, finish, which removes the copies with le2b_scrub). Then:
 - API v1 (token of a member): texts empty + encrypted: true (tasks, comments), any ciphertext empty; writes 403 (list_e2e)
 - agents: PUT /api/lists/{id}/agent 409, share-all skips the list, the agent's own token does not see the list
 - CalDAV: SUMMARY is the neutral word, no DESCRIPTION / URL, the due date stays; a text change from the calendar app is
   ignored, a new task 403; the iCal feed the same
 - mail: an address of the list takes no mail (mail_import), GET /api/me/mail shows it off, a new address 409
 - templates from the task / the list and into the list 409
 - search: the web search and the message search find nothing of the list
 - history: a title change is {"e2e": true}; time entry snapshots stay empty; news without title / excerpt (enc)
 - push / mail texts: le2b_net turns ciphertexts into the neutral word; the digest has one line per locked list
 - webhooks: the payload has ids + encrypted: true, no text
 - THE sweep (H2): marker words written everywhere before; after the switch no text or JSON column of any table holds one
usage: p264a_b_api_test.py <datadir>"""
import base64
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta

import requests

import dbx as dbxm
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
MK = "Zqxv"  # every marker word starts with it (the sweep looks for it)


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall() if not write else c.execute(sql, args)
        if write:
            c.commit()
            return None
        return r
    finally:
        c.close()


def cipher(n=0):
    """A synthetic ciphertext of generation 1 (only its shape is right; nobody can open it)."""
    iv = "A" * 15 + "BCDEFGHIJ"[n % 9]
    return "e2e1:" + json.dumps({"v": 1, "g": 1, "iv": iv, "ct": "Q" * (40 + 4 * n)}, separators=(",", ":"))


def py(code):
    """Python in the app container (the app's own functions, background context)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import os; os.environ['TASKS_WATCHDOG']='0'\nimport app\n" + code],
                         capture_output=True, text=True)
    return out.returncode, out.stdout.strip(), out.stderr.strip()[-600:]


class Api:
    def __init__(self, token):
        self.h = {"Authorization": "Bearer " + token}

    def get(self, path, **kw):
        return requests.get(V + path, headers=self.h, **kw)

    def post(self, path, body=None):
        return requests.post(V + path, headers=self.h, json=body if body is not None else {})

    def patch(self, path, body):
        return requests.patch(V + path, headers=self.h, json=body)


subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
subprocess.run(["rm", "-rf", DATA])
os.makedirs(DATA, exist_ok=True)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA],
                   env=dict(os.environ, KEEP="1", EXTRA="-e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8099 -e KALMIDO_WEBHOOK_TICK=3600"),
                   capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments", "time"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en"})

# ================================================================== before: a list full of marker words everywhere
L = A.post(B + "/api/lists", json={"name": "Strongbox", "org_id": None}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Open list", "org_id": None}).json()["id"]  # stays open: its texts stay readable
dbx("UPDATE lists SET time_tracking=1 WHERE id IN (?, ?)", (L, L2), write=True)
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"})
check(r.ok, f"bob joins the list {r.status_code} {r.text[:200]}")
wh = A.post(B + "/api/me/webhooks", json={"name": "hook", "url": "http://127.0.0.1:8099/hook",
                                           "events": ["task.created", "task.updated", "comment.created"]})
check(wh.status_code in (200, 201), f"webhook created {wh.status_code} {wh.text[:200]}")
due = testclock.today().isoformat()
r = A.post(B + "/api/tasks", json={"list_id": L, "title": MK + "Title1", "content": MK + "Note1", "url": "https://example.com/" + MK + "Url1",
                                   "due": due, "reminders": "0"})
assert r.ok, r.text
T = r.json()["id"]
T2 = A.post(B + "/api/tasks", json={"list_id": L2, "title": "Open " + MK[:2] + " task", "due": due}).json()["id"]
check(A.patch(B + f"/api/tasks/{T}", json={"title": MK + "Title2"}).ok, "title change before the lock (history: to)")
r = Bo.post(B + f"/api/tasks/{T}/comments", json={"body": MK + "Comment1 for @alice"})
check(r.ok, f"comment by bob {r.text[:200]}")
r = A.post(B + f"/api/lists/{L}/notes", json={"title": MK + "NoteTitle", "body": MK + "NoteBody"})
check(r.ok, f"a note of the list {r.text[:200]}")
# #5549: the trash copies made before the lock (core/objparts.py part_copy, list_part_trash): a deleted section keeps its name,
# a deleted text field the values of the tasks, the Undo copy of "Delete all times" the entries' notes and task titles
r = A.post(B + "/api/sections", json={"list_id": L, "name": MK + "GoneSection"})
check(r.ok and A.delete(B + f"/api/sections/{r.json()['id']}").ok, f"#5549: a section deleted before the lock {r.text[:200]}")
r = A.post(B + f"/api/lists/{L}/fields", json={"name": "Budget", "type": "text"})
FLD = r.json().get("id")
check(r.ok and A.patch(B + f"/api/tasks/{T}", json={"fields": {str(FLD): MK + "FieldValue"}}).ok, f"#5549: a text field with a value {r.text[:200]}")
r = A.delete(B + f"/api/fields/{FLD}")
check(r.ok and r.json().get("trash_id"), f"#5549: the field deleted before the lock (field trash) {r.text[:200]}")
r = A.post(B + "/api/time/entries", json={"task_id": T, "start": (datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds"),
                                          "minutes": 20, "note": MK + "WipeNote"})
check(r.ok, f"#5549: a time entry with a note {r.text[:200]}")
r = Bo.post(B + "/api/time/entries", json={"task_id": T, "start": (datetime.now() - timedelta(hours=4)).isoformat(timespec="seconds"),
                                           "minutes": 10, "note": MK + "BobNote"})
check(r.ok, f"#5549: bob's time entry with a note (sealed in the Undo copy) {r.text[:200]}")
r = A.post(B + f"/api/lists/{L}/time/delete-all", json={"confirm": "Strongbox"})
WIPE = r.json().get("wipe") if r.ok else None
check(r.ok and WIPE and r.json().get("deleted") == 2, f"#5549: delete all times (Undo copy on the server) {r.status_code} {r.text[:200]}")
check(len(dbx("SELECT id FROM list_part_trash WHERE list_id=? AND CAST(snap AS text) || CAST(held AS text) LIKE ?", (L, f"%{MK}%"))) == 3,
      "#5549: before the lock the three trash copies hold plain text")
r = A.post(B + "/api/sections", json={"list_id": L, "name": MK + "Section"})
check(r.ok, f"a section {r.text[:200]}")
r = A.post(B + "/api/time/entries", json={"task_id": T, "start": (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds"), "minutes": 30})
check(r.ok, f"a time entry on the task {r.text[:200]}")
# 2.900.0 (#5550): a deleted time entry with a note: its undo step ("time_life") holds the whole row in its copy, the row
# itself is gone (a match on time_entries misses it); the sweep below finds it left in obj_undo
r = A.post(B + "/api/time/entries", json={"list_id": L, "start": (datetime.now() - timedelta(hours=6)).isoformat(timespec="seconds"),
                                          "minutes": 20, "note": MK + "LifeNote"})
check(r.ok, f"(setup) a project time entry with a note {r.status_code} {r.text[:200]}")
r = A.delete(B + f"/api/time/entries/{r.json()['id']}")
check(r.ok and r.json().get("undo_group"), f"#5550: deleted: an undo step holding the row {r.status_code} {r.text[:200]}")
# review (Fable): an undo before the lock writes the row's changes into obj_history (note before / after): the sweep finds it
r = A.post(B + "/api/time/entries", json={"list_id": L, "start": (datetime.now() - timedelta(hours=8)).isoformat(timespec="seconds"),
                                          "minutes": 15, "note": MK + "HistNote"})
check(r.ok, f"(setup) another project time entry with a note {r.status_code} {r.text[:200]}")
r = A.patch(B + f"/api/time/entries/{r.json()['id']}", json={"note": MK + "HistNote2"})
GH = r.json().get("undo_group") if r.ok else None
check(bool(GH) and A.post(B + f"/api/undo/to/{GH}").ok
      and dbx("SELECT 1 FROM obj_history WHERE kind='time_entry' AND vals_before::text || vals_after::text LIKE ?", (f"%{MK}HistNote%",)),
      f"(setup) its note change undone: a history row with both notes {GH}")
# 2.900.0 (#5551): the project's settings step ("listset") holds the description / status note, a notepad emptied for the
# lock ("notepad") its texts before -- both in the copy; the sweep below finds any of them left in obj_undo
dbx("UPDATE lists SET description=?, status_note=? WHERE id=?", (MK + "Desc", MK + "StatusNote", L), write=True)
r = A.patch(B + f"/api/lists/{L}", json={"color": "#336699"})
check(r.ok and dbx("SELECT 1 FROM obj_undo WHERE kind='listset' AND ref_id=? AND snap LIKE ?", (L, f"%{MK}Desc%")),
      f"#5551: a settings change: an undo step whose copy holds the description {r.status_code} {r.text[:200]}")
r = A.post(B + f"/api/lists/{L}/notepads", json={"title": MK + "PadTitle", "body": MK + "PadBody"})
check(r.ok, f"(setup) a notepad {r.status_code} {r.text[:200]}")
PAD = r.json()["id"]
r = A.patch(B + f"/api/notepads/{PAD}", json={"title": "", "body": ""})
check(r.ok and dbx("SELECT 1 FROM obj_undo WHERE kind='notepad' AND ref_id=? AND snap LIKE ?", (PAD, f"%{MK}PadBody%")),
      f"#5551: emptied for the lock: an undo step whose copy holds the texts {r.status_code} {r.text[:200]}")
SEC = dbx("SELECT id FROM sections WHERE list_id=?", (L,))[0][0]
# copies the app writes in other places (shopping memory, a mail address, an agent proposal): written here like the app does
dbx("INSERT INTO shop_memory(list_id,item,section_id,at) VALUES(?,?,?,?)", (L, MK.lower() + "milk", SEC, "2026-01-01T00:00:00Z"), write=True)
dbx("INSERT INTO mail_tokens(token,user_id,list_id,created_at) VALUES(?,?,?,?)", ("tok264b", 1, L, "2026-01-01T00:00:00Z"), write=True)
# 2.879.0 (#5552): a section deleted before the switch (its copy in the trash, list_part_trash.snap) and a task in the trash
# that remembers its name (tasks.trash_section): both held the plain name after the lock; the sweep below finds them
SG = A.post(B + "/api/sections", json={"list_id": L, "name": MK + "GoneSection"}).json()["id"]
TG = A.post(B + "/api/tasks", json={"list_id": L, "title": MK + "TrashTask", "section_id": SG}).json()["id"]
check(A.delete(B + f"/api/tasks/{TG}").ok, "#5552: a task of the section into the trash")
check(A.delete(B + f"/api/sections/{SG}").ok and dbx("SELECT 1 FROM list_part_trash WHERE kind='section' AND ref_id=?", (SG,)),
      "#5552: the section into the trash before the lock (its copy holds the plain name)")
check(dbx("SELECT trash_section FROM tasks WHERE id=?", (TG,))[0][0] == MK + "GoneSection", "#5552: the task in the trash remembers the name")
n_queue0 = dbx("SELECT COUNT(*) FROM webhook_queue")[0][0]
check(n_queue0 >= 1 and dbx("SELECT COUNT(*) FROM webhook_queue WHERE payload LIKE ?", (f"%{MK}%",))[0][0] >= 1,
      f"webhook deliveries with the texts wait in the queue ({n_queue0})")
check(dbx("SELECT COUNT(*) FROM activity WHERE task_id=? AND data::text LIKE ?", (T, f"%{MK}Title2%"))[0][0] >= 1, "the history holds the old title")
check(dbx("SELECT task_title FROM time_entries WHERE task_id=?", (T,))[0][0] == MK + "Title2", "the time entry holds a title snapshot")

# an agent and a token of alice (before the switch)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
check(r.status_code in (200, 201), f"agent created {r.text[:200]}")
ag = r.json().get("agent", r.json())
AID, ATOK = ag.get("id"), ag.get("token") or r.json().get("token")
r = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]})
check(r.status_code == 201, f"API token {r.text[:200]}")
TA = Api(r.json()["token"])
AG = Api(ATOK) if ATOK else None
# 2.64.1 review 2 (M5): an agent's chat answer about the task and its step texts (an agent that was a member before) quote texts
if AID:
    dbx("INSERT INTO agent_chat(agent_id,user_id,sender,body,task_id,created_at) VALUES(?,?,?,?,?,?)",
        (AID, 1, "agent", MK + "AgentQuote", T, "2026-01-01T00:00:00Z"), write=True)
    MID = dbx("SELECT id FROM agent_chat WHERE body=?", (MK + "AgentQuote",))[0][0]
    dbx("INSERT INTO agent_steps(agent_id,user_id,message_id,state,text,created_at) VALUES(?,?,?,?,?,?)",
        (AID, 1, MID, "done", MK + "AgentStep", "2026-01-01T00:00:00Z"), write=True)

# ================================================================== the switch through part A's routes (start, todo / bulk, finish)
def keys():
    b64 = lambda n: base64.b64encode(os.urandom(n)).decode()  # noqa: E731
    b64u = lambda n: base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")  # noqa: E731
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}


def wrapped():
    return {"v": 1, "iv": base64.b64encode(os.urandom(12)).decode(), "ct": base64.b64encode(os.urandom(48)).decode()}


for s_ in (A, Bo):
    check(s_.put(B + "/api/e2e/keys", json=keys()).ok, "the person's own keys are set up")
r = A.post(B + f"/api/lists/{L}/e2e/start", json={"keys": [{"user_id": 1, "wrapped": wrapped()}, {"user_id": BOB, "wrapped": wrapped()}]})
check(r.ok, f"switch on (start) {r.status_code} {r.text[:300]}")
k = [0]
for _ in range(10):
    todo = A.get(B + f"/api/lists/{L}/e2e/todo?limit=200").json()
    out_ = {}
    for kind in ("tasks", "comments", "notes", "sections"):
        rows = []
        for x in todo.get(kind) or []:
            y = {"id": x["id"]}
            for f, v in x.items():
                if f != "id" and v is not None:
                    k[0] += 1
                    y[f] = cipher(k[0])
            rows.append(y)
        if rows:
            out_[kind] = rows
    if todo.get("fields"):
        out_["fields"] = [{"task_id": x["task_id"], "field_id": x["field_id"], "value": cipher(1)} for x in todo["fields"]]
    if not out_:
        break
    r = A.post(B + f"/api/lists/{L}/e2e/bulk", json=out_)
    check(r.ok, f"bulk {r.status_code} {r.text[:300]}")
r = A.post(B + f"/api/lists/{L}/e2e/finish")
check(r.ok and dbx("SELECT e2e FROM lists WHERE id=?", (L,))[0][0] == "on", f"finish: the lock is on (le2b_scrub ran) {r.status_code} {r.text[:300]}")
check(not dbx("SELECT 1 FROM shop_memory WHERE list_id=?", (L,)), "scrub: no shopping memory of the list")
check(not dbx("SELECT 1 FROM webhook_queue WHERE payload LIKE ?", (f"%{MK}%",)), "scrub: no waiting webhook delivery with a text")
TITLE = dbx("SELECT title FROM tasks WHERE id=?", (T,))[0][0]
check(TITLE.startswith("e2e1:"), "the task's title is a ciphertext now")
check(dbx("SELECT task_title FROM time_entries WHERE task_id=?", (T,))[0][0] == "", "time entry snapshot emptied")
check(not dbx("SELECT 1 FROM mail_tokens WHERE list_id=?", (L,)), "the list's mail address is gone")

# ================================================================== THE sweep (H2): no marker word left anywhere
cols = dbx("""SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'
              AND data_type IN ('text', 'jsonb', 'json', 'character varying') ORDER BY table_name, column_name""")
ALLOWED = {("lists", "name")}  # not encrypted by design (E9: attachment names; the list name)
parts = [f"SELECT '{t}.{c_}' AS w FROM \"{t}\" WHERE \"{c_}\"::text LIKE '%{MK}%'" for t, c_ in cols if (t, c_) not in ALLOWED]
hits = sorted({r[0] for r in dbx(" UNION ".join(parts))}) if parts else []
# the open list's own task title stays (it holds only the first two letters of the marker, so it never matches)
check(not hits, f"H2 sweep: marker words of the locked list in {hits}")
for h in hits:
    t, c_ = h.split(".")
    print("  hit:", h, [str(x[0])[:160] for x in dbx(f"SELECT \"{c_}\"::text FROM \"{t}\" WHERE \"{c_}\"::text LIKE ? LIMIT 3", (f"%{MK}%",))])
# #5549: the section and field copies are gone for good, the Undo copy of the times stays and brings the entry back without note
check(not dbx("SELECT 1 FROM list_part_trash WHERE list_id=? AND kind IN ('section', 'list_field')", (L,)),
      "#5549: no trash copy of a section / field deleted before the lock")
r = A.post(B + f"/api/lists/{L}/time/restore", json={"wipe": WIPE})
back = sorted((x[0], x[1], x[2]) for x in dbx("SELECT seconds, note, task_title FROM time_entries WHERE list_id=? AND seconds IN (600, 1200)", (L,)))
check(r.ok and back == [(600, "", ""), (1200, "", "")],
      f"#5549: Undo of 'delete all times' still works - also bob's entry (sealed again) -, note and task title empty {back} {r.text[:200]}")

# ================================================================== API v1 / MCP
r = TA.get(f"/tasks?list_id={L}")
d = r.json().get("data") or []
check(r.ok and d and all(x["title"] == "" and x["notes"] == "" and x["url"] == "" and x.get("encrypted") is True for x in d),
      f"v1 tasks of the locked list: empty texts + encrypted {r.status_code} {str(d)[:300]}")
r = TA.get(f"/tasks/{T}")
check(r.ok and r.json()["title"] == "" and r.json().get("encrypted") is True, f"v1 one task {r.text[:200]}")
r = TA.get(f"/tasks/{T2}")
check(r.ok and r.json()["title"].startswith("Open") and not r.json().get("encrypted"), "a task of an open list is unchanged")
r = TA.get(f"/tasks/{T}/comments")
# 2.663.0 (#4341): v1_comments: alice owns the list, a GET passes le2b_v1_guard; le2b_v1_mask empties the texts -> 200
check(r.status_code == 200 and "e2e1:" not in r.text, f"v1 comments: 200, no ciphertext {r.status_code} {r.text[:200]}")
check("e2e1:" not in TA.get("/tasks?status=all").text, "no ciphertext anywhere in a v1 answer")
r = TA.patch(f"/tasks/{T}", {"due": due})
check(r.status_code == 403 and (r.json().get("error") or {}).get("code") == "list_e2e", f"v1 write into the locked list 403 {r.status_code} {r.text[:200]}")
r = TA.post("/tasks", {"list_id": L, "title": "via api"})
check(r.status_code == 403, f"v1 new task in the locked list 403 {r.status_code}")
r = TA.post(f"/tasks/{T}/comments", {"body": "hi"})
check(r.status_code == 403, f"v1 comment 403 {r.status_code}")
r = TA.post(f"/tasks/{T2}/move", {"list_id": L})
check(r.status_code == 403, f"v1 move into the locked list 403 {r.status_code}")
check(TA.patch(f"/tasks/{T2}", {"due": due}).ok, "v1 writes in an open list still work")
r = TA.get("/search?q=e2e1")
# 2.663.0 (#4341): v1_search: q given, a GET (no write guard) -> 200 with the locked list's texts masked
check(r.status_code == 200 and "e2e1:" not in r.text and f'"id": {T},' not in r.text.replace('"id":', '"id": '),
      f"v1 search finds nothing of the locked list {r.text[:200]}")

# ================================================================== agents (M4)
if AID:
    r = A.put(B + f"/api/lists/{L}/agent", json={"agent_id": AID})
    check(r.status_code == 409, f"agent of the locked list: 409 {r.status_code} {r.text[:200]}")
    r = A.post(B + f"/api/agents/{AID}/share-all")
    check(r.status_code == 200, f"share-all runs {r.status_code} {r.text[:200]}")
    check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (L, AID)), "share-all skips the locked list")
    if AG:
        ls = AG.get("/lists").json().get("data") or []
        check(L not in [x.get("id") for x in ls], "the agent's token never sees the locked list")
        check(AG.get(f"/tasks/{T}").status_code in (403, 404), "the agent cannot read a task of the locked list")

# ================================================================== CalDAV / iCal (E6)
r = A.post(B + "/api/me/app-passwords", json={"name": "phone"})
check(r.status_code == 201, f"app password {r.text[:120]}")
D = requests.Session()
D.auth = ("alice", r.json().get("password", ""))
QRY = ('<?xml version="1.0"?><C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/>'
       '<C:calendar-data/></D:prop><C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VTODO"/></C:comp-filter></C:filter>'
       '</C:calendar-query>')
r = D.request("REPORT", B + f"/dav/calendars/alice/{L}/", data=QRY.encode(), headers={"Depth": "1", "Content-Type": "application/xml"})
body = r.text.replace("\r\n ", "")
check(r.status_code == 207 and "SUMMARY:\U0001F512 Task" in body and "e2e1" not in body and "DESCRIPTION:Q" not in body
      and f"URL:" not in body.split("BEGIN:VTODO", 1)[-1].split("BEGIN:VALARM", 1)[0] and "DUE" in body,
      f"CalDAV: neutral SUMMARY, no text, the date stays {r.status_code} {body[:600]}")
href = (re.findall(r"<[a-zA-Z:]*href>([^<]*kalmido-\d+-[0-9a-f]{8}\.ics)</", r.text) or [""])[0]
if href:
    gr = D.get(B + href)
    ics = gr.text.replace("SUMMARY:\U0001F512 Task", "SUMMARY:changed by the phone")
    pr = D.put(B + href, data=ics.encode(), headers={"Content-Type": "text/calendar", "If-Match": gr.headers.get("ETag", "*")})
    check(pr.status_code in (200, 201, 204) and dbx("SELECT title FROM tasks WHERE id=?", (T,))[0][0] == TITLE,
          f"CalDAV: a text change of the calendar app is ignored {pr.status_code} {pr.text[:200]}")
new = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:new-264b\r\nSUMMARY:from the phone\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
pr = D.put(B + f"/dav/calendars/alice/{L}/new-264b.ics", data=new.encode(), headers={"Content-Type": "text/calendar"})
check(pr.status_code == 403, f"CalDAV: no new task in the locked list {pr.status_code}")
url = A.post(B + "/api/ical", json={"action": "create"}).json().get("url") or ""
feed = requests.get(B + "/ical/" + url.split("/ical/", 1)[-1]).text.replace("\r\n ", "") if url else ""
check(feed and "e2e1" not in feed and "SUMMARY:\U0001F512 Task" in feed and MK not in feed, f"iCal feed: the neutral word {feed[:300]}")

# ================================================================== mail (inbound, the dialog)
raw = "From: someone@example.com\r\nTo: x+tok264c@example.com\r\nSubject: hello\r\nMessage-ID: <m264b@example.com>\r\n\r\nbody\r\n"
dbx("INSERT INTO mail_tokens(token,user_id,list_id,created_at) VALUES(?,?,?,?)", ("tok264c", 1, L, "2026-01-01T00:00:00Z"), write=True)
rc, out, er = py("from kalmido.integrations.mail import mail_target\nimport email, email.policy\nc=app.connect()\n"
                 f"m=email.message_from_bytes({raw.encode()!r}, policy=email.policy.default)\nprint(mail_target(c, m))")
# #4071: mail_target also names how it found the person
check(rc == 0 and out.endswith("(None, None, None)"), f"mail to the locked list's address: nobody (like an unknown address) {out} {er}")
j = A.get(B + "/api/me/mail").json()
x = [y for y in j.get("lists") or [] if y.get("list_id") == L]
check(not x or (x[0].get("e2e") is True and x[0].get("address") == ""), f"mail dialog: the address is off {x}")
r = A.post(B + "/api/me/mail/token", json={"list_id": L})
check(r.status_code == 409, f"new mail address 409 {r.status_code} {r.text[:160]}")

# ================================================================== templates, search, history, news
check(A.post(B + "/api/templates", json={"task_id": T}).status_code == 409, "template from a task of the locked list 409")
check(A.post(B + "/api/templates", json={"list_id": L}).status_code == 409, "template from the locked list 409")
tp = A.post(B + "/api/templates", json={"task_id": T2})
if tp.ok:
    tid_ = tp.json().get("id") or (tp.json().get("template") or {}).get("id")
    r = A.post(B + f"/api/templates/{tid_}/apply", json={"list_id": L})
    check(r.status_code == 409, f"apply a template into the locked list 409 {r.status_code}")
r = A.get(B + "/api/tasks?scope=search&q=e2e1")
check(r.ok and T not in [x["id"] for x in r.json().get("tasks", [])], "web search: nothing of the locked list")
r = A.get(B + "/api/search/messages?q=QQQQ")
# 2.663.0 (#4341): msg_search_web: a valid q and no filters -> search_messages raises nothing -> 200
check(r.status_code == 200 and "e2e1:" not in r.text, f"message search: 200, no ciphertext {r.status_code}")
c2 = cipher(9)
r = A.patch(B + f"/api/tasks/{T}", json={"title": c2})
check(r.ok, f"the web app writes a ciphertext title {r.status_code} {r.text[:200]}")
last = dbx("SELECT data FROM activity WHERE task_id=? AND kind='title' ORDER BY id DESC LIMIT 1", (T,))
lv = last[0][0] if last else {}
lv = lv if isinstance(lv, dict) else json.loads(lv or "{}")
check(lv.get("e2e") is True and "e2e1" not in json.dumps(lv), f"history of a title change: no text {last}")
check(dbx("SELECT task_title FROM time_entries WHERE task_id=?", (T,))[0][0] == "", "time entry snapshot stays empty (trigger)")
te = A.get(B + "/api/time/entries").json()
tl = [e for e in (te.get("entries") or te.get("data") or []) if e.get("task_id") == T]
check(not tl or (tl[0].get("e2e") is True and "e2e1" not in tl[0]["title"]), f"time entry shows the neutral word {tl[:1]}")
Bo.post(B + f"/api/tasks/{T}/comments", json={"body": cipher(3)})
items = A.get(B + "/api/news").json().get("items", [])
mine = [x for x in items if x.get("task_id") == T]
check(mine and all(x.get("enc") is True and not x.get("task_title") and x.get("excerpt") == "" for x in mine) and "e2e1" not in json.dumps(items),
      f"news about the locked list: enc, no title, no excerpt {mine[:2]}")
q = dbx("SELECT payload FROM webhook_queue WHERE payload LIKE ? ORDER BY id DESC LIMIT 1", (f'%"id": {T}%',))
check(q and "e2e1" not in q[0][0] and '"encrypted": true' in q[0][0], f"webhook payload: ids + encrypted, no text {str(q)[:300]}")

# ================================================================== push / mail texts (M5)
code = (f"from kalmido.collab.liste2eguard import le2b_net\nfrom kalmido.notify.push import webpush_payload\n"
        f"x=le2b_net('Due: ' + {cipher(1)!r} + ' / ' + {cipher(2)!r}[:30])\n"
        f"p=webpush_payload({cipher(1)!r}, 'Due today', '4')\nprint(x)\nprint(p['title'])")
rc, out, er = py(code)
check(rc == 0 and "e2e1" not in out and out.count("\U0001F512") == 3, f"push texts: ciphertexts become the neutral word {out} {er}")
rc, out, er = py(f"from kalmido.integrations.mail import digest_mail_content\nc=app.connect()\nr=digest_mail_content(c, 1, {due!r})\n"
                 "print(r[1] if r else '')")
check(rc == 0 and "e2e1" not in out and "(encrypted)" in out and "Strongbox" in out, f"digest: one line per locked list {out[:300]} {er}")

# ================================================================== 2.787.0 (#5417, Fable review #5408): undo steps of a move
# A move into the locked list (PATCH with the ciphertexts) records no undo step for the task: its "before" would keep the plain
# texts in obj_undo.snap, written at the commit AFTER the move's scrub. The way back out of the lock and its undo: the undo moves
# it in again, whose scrub takes the step's own part and group with it (wanted: the step held the plain texts).
def undo_marks(m):
    return dbx("SELECT COUNT(*) FROM obj_undo WHERE CAST(snap AS text) LIKE ?", (f"%{m}%",))[0][0]


MV = MK + "Move"
T3 = A.post(B + "/api/tasks", json={"list_id": L2, "title": MV + "Title0", "content": MV + "Note"}).json()["id"]
check(A.patch(B + f"/api/tasks/{T3}", json={"title": MV + "Title"}).ok and undo_marks(MV) >= 1,
      "an open list's task: its edit is an undo step with the plain texts (fine there)")
# 2.900.0 (#5550): its time entries' steps hold note and task title -- one changed (time_entry), one deleted (time_life)
_st = (datetime.now() - timedelta(hours=5)).isoformat(timespec="seconds")
TE3 = A.post(B + "/api/time/entries", json={"task_id": T3, "start": _st, "minutes": 15, "note": MV + "TimeNote"}).json()["id"]
check(A.patch(B + f"/api/time/entries/{TE3}", json={"note": MV + "TimeNote2"}).ok, "(setup) a time entry of the task changed")
TE4 = A.post(B + "/api/time/entries", json={"task_id": T3, "start": _st, "minutes": 10, "note": MV + "LifeNote"}).json()["id"]
check(A.delete(B + f"/api/time/entries/{TE4}").ok and undo_marks(MV + "LifeNote") >= 1, "(setup) a time entry of the task deleted: a step")
ng0 = dbx("SELECT COUNT(*) FROM undo_groups WHERE user_id=1")[0][0]
r = A.patch(B + f"/api/tasks/{T3}", json={"list_id": L, "title": cipher(5), "content": cipher(6)})
check(r.ok and dbx("SELECT list_id FROM tasks WHERE id=?", (T3,))[0][0] == L, f"move into the locked list {r.status_code} {r.text[:200]}")
check(undo_marks(MV) == 0, "move in: no plain text of the task in obj_undo (no step, the old ones scrubbed)")
check(not dbx("SELECT 1 FROM obj_undo WHERE kind='task' AND ref_id=? AND CAST(snap AS text) LIKE ?", (T3, '%"fields"%')),
      "move in: no undo part of the move")
check(not dbx("SELECT 1 FROM undo_groups WHERE CAST(label_args AS text) LIKE ?", (f"%{MV}%",)), "move in: no undo label names the task")
check(dbx("SELECT COUNT(*) FROM undo_groups WHERE user_id=1")[0][0] <= ng0, "move in: no new undo group")
r = A.patch(B + f"/api/tasks/{T3}", json={"list_id": L2, "title": MV + "Out", "content": MV + "OutNote"})
check(r.ok and dbx("SELECT title FROM tasks WHERE id=?", (T3,))[0][0] == MV + "Out", f"move out with plain texts {r.status_code} {r.text[:200]}")
g = dbx("SELECT DISTINCT group_id FROM obj_undo WHERE kind='task' AND ref_id=? ORDER BY group_id DESC LIMIT 1", (T3,))
check(bool(g), "move out: an undo step (the task is in the open list now)")
if g:
    GO = g[0][0]
    r = A.post(B + f"/api/undo/to/{GO}")
    row = dbx("SELECT list_id, title FROM tasks WHERE id=?", (T3,))[0]
    check(r.ok and row[0] == L and str(row[1]).startswith("e2e1:"),
          f"undo of the move out: back in the locked list with the ciphertexts {r.status_code} {r.text[:200]} {row}")
    check(not dbx("SELECT 1 FROM undo_groups WHERE id=?", (GO,)) and not dbx("SELECT 1 FROM obj_undo WHERE group_id=?", (GO,)),
          "undo of the move out: the step's own part and group are scrubbed (wanted)")
    check(undo_marks(MV) == 0, "after the undo: no plain text of the task in obj_undo")

# 2.800.0 (#5447, Fable review 2.787): the move out of a task WITH a subtask: its way back would need the subtask's texts
# re-encrypted (le2a_move list_e2e_move), which the server cannot. The step marks the move as not undoable at recording
# (keep): the undo leaves the task in the open list and names it (UG_KEPT), the other fields of the step still go back.
MS = MK + "Sub"
T4 = A.post(B + "/api/tasks", json={"list_id": L2, "title": MS + "Top", "priority": 1}).json()["id"]
T4S = A.post(B + "/api/tasks", json={"list_id": L2, "title": MS + "Child", "parent_id": T4}).json()["id"]
r = A.patch(B + f"/api/tasks/{T4}", json={"list_id": L, "title": cipher(7), "le2e_move": {"tasks": [{"id": T4S, "title": cipher(8)}]}})
check(r.ok and dbx("SELECT list_id FROM tasks WHERE id=?", (T4S,))[0][0] == L, f"#5447: task with subtask into the lock {r.status_code} {r.text[:200]}")
r = A.patch(B + f"/api/tasks/{T4}", json={"list_id": L2, "title": MS + "Out", "priority": 3,
                                          "le2e_move": {"tasks": [{"id": T4S, "title": MS + "ChildOut"}]}})
check(r.ok and dbx("SELECT list_id FROM tasks WHERE id=?", (T4,))[0][0] == L2, f"#5447: move out with the subtask {r.status_code} {r.text[:200]}")
g = dbx("SELECT group_id, CAST(snap AS text) FROM obj_undo WHERE kind='task' AND ref_id=? ORDER BY id DESC LIMIT 1", (T4,))
check(bool(g) and '"keep"' in g[0][1] and "list_id" in g[0][1], f"#5447: the move out is marked as not undoable at recording {g}")
if g:
    r = A.post(B + f"/api/undo/to/{g[0][0]}")
    row = dbx("SELECT list_id, title, priority FROM tasks WHERE id=?", (T4,))[0]
    sub = dbx("SELECT list_id, title FROM tasks WHERE id=?", (T4S,))[0]
    st = (r.json().get("stayed") or [{}]) if r.ok else [{}]
    check(r.ok and row[0] == L2 and row[1] == MS + "Out" and sub[0] == L2 and sub[1] == MS + "ChildOut",
          f"#5447: undo leaves task and subtask in the open list with their texts {r.status_code} {r.text[:200]} {row} {sub}")
    check(row[2] == 1, f"#5447: the other field of the step (priority) goes back {row}")
    check(r.ok and g[0][0] in r.json().get("partial", []) and "list_id" in str(st[0].get("reason")) and st[0].get("code") == "conflict",
          f"#5447: the move is named as not undone (partial, UG_KEPT) {r.text[:300]}")

# ================================================================== 2.879.0 (#5552): the trash of sections and the lock (at the end: the restored task
# is not part of the v1 checks above)
check(not dbx("SELECT 1 FROM list_part_trash WHERE list_id=? AND kind='section'", (L,)), "#5552: switching on emptied the sections in the trash")
check(dbx("SELECT trash_section FROM tasks WHERE id=?", (TG,))[0][0] is None, "#5552: the task in the trash forgot its section's name")
# a copy with a plain name (as an older version left it) never comes back into the locked project: restore and undo 409
SP = 9905552
dbx("INSERT INTO list_part_trash(list_id,kind,ref_id,snap,held,deleted_by,deleted_at) VALUES(?,?,?,?,?,?,?)",
    (L, "section", SP, json.dumps({"name": MK + "OldPlain", "sort": 9}), "{}", 1, "2026-11-01T00:00:00Z"), write=True)
r = A.post(B + f"/api/sections/{SP}/restore")
check(r.status_code == 409 and r.json().get("code") == "list_e2e" and not dbx("SELECT 1 FROM sections WHERE id=?", (SP,)),
      f"#5552: restoring a plain-named section into the locked project 409 {r.status_code} {r.text[:200]}")
check(bool(dbx("SELECT 1 FROM list_part_trash WHERE ref_id=?", (SP,))), "#5552: the refused copy stays in the trash")
dbx("DELETE FROM list_part_trash WHERE ref_id=?", (SP,), write=True)
# a section deleted while locked (ciphertext name) comes back as before
SC = A.post(B + "/api/sections", json={"list_id": L, "name": cipher(31)})
check(SC.ok, f"#5552: a section with a ciphertext name in the locked project {SC.status_code} {SC.text[:200]}")
if SC.ok:
    SC = SC.json()["id"]
    check(A.delete(B + f"/api/sections/{SC}").ok, "#5552: deleted while locked")
    r = A.post(B + f"/api/sections/{SC}/restore")
    check(r.ok and dbx("SELECT name FROM sections WHERE id=?", (SC,))[0][0] == cipher(31), f"#5552: and restored with its ciphertext {r.status_code} {r.text[:200]}")
# a task in the trash with a plain section name: restoring it makes no plain-named section in the locked project
dbx("UPDATE tasks SET trash_section=? WHERE id=?", ("PlainLeft", TG), write=True)
r = A.post(B + f"/api/tasks/{TG}/restore")
check(r.ok and dbx("SELECT section_id FROM tasks WHERE id=?", (TG,))[0][0] is None
      and not dbx("SELECT 1 FROM sections WHERE list_id=? AND name=?", (L, "PlainLeft")),
      f"#5552: a restored task makes no plain-named section in the locked project {r.status_code} {r.text[:200]}")

# ================================================================== 2.898.0 (#5562): a task moved into the locked project
# leaves copies in the trash of its OLD project: the Undo copy of "Delete all times" (task title + note of its entries) and a
# deleted text field (its value in held.vals). The move empties / takes them out there; the other tasks' copies stay.
L3 = A.post(B + "/api/lists", json={"name": "Other open", "org_id": None}).json()["id"]
dbx("UPDATE lists SET time_tracking=1 WHERE id=?", (L3,), write=True)
T5 = A.post(B + "/api/tasks", json={"list_id": L3, "title": MK + "MoveTitle"}).json()["id"]
T6 = A.post(B + "/api/tasks", json={"list_id": L3, "title": "Stays here"}).json()["id"]
r = A.post(B + f"/api/lists/{L3}/fields", json={"name": "Detail", "type": "text"})
F3 = r.json().get("id")
check(r.ok and A.patch(B + f"/api/tasks/{T5}", json={"fields": {str(F3): MK + "MoveValue"}}).ok
      and A.patch(B + f"/api/tasks/{T6}", json={"fields": {str(F3): "StayValue"}}).ok, f"#5562: text field values {r.text[:200]}")
check(A.delete(B + f"/api/fields/{F3}").ok, "#5562: the field into the trash of the open project")
check(A.put(B + f"/api/lists/{L3}/members", json={"user_id": BOB, "role": "edit"}).ok, "#5562: bob joins the open project")
for s_, t_, note_, h_ in ((A, T5, MK + "MoveNote", 5), (A, T6, "StayNote", 6), (Bo, T5, MK + "BobMove", 7)):
    r = s_.post(B + "/api/time/entries", json={"task_id": t_, "start": (datetime.now() - timedelta(hours=h_)).isoformat(timespec="seconds"),
                                              "minutes": 15, "note": note_})
    check(r.ok, f"#5562: a time entry with a note {r.text[:200]}")
r = A.post(B + f"/api/lists/{L3}/time/delete-all", json={"confirm": "Other open"})
W3 = r.json().get("wipe") if r.ok else None
check(r.ok and W3, f"#5562: delete all times of the open project {r.status_code} {r.text[:200]}")
check(len(dbx("SELECT id FROM list_part_trash WHERE list_id=? AND held LIKE ?", (L3, f"%{MK}%"))) == 2,
      "#5562: before the move both copies quote the task")
r = A.patch(B + f"/api/tasks/{T5}", json={"list_id": L, "title": cipher(40)})
check(r.ok and dbx("SELECT list_id FROM tasks WHERE id=?", (T5,))[0][0] == L, f"#5562: the task moves into the locked project {r.status_code} {r.text[:200]}")
left_ = [x[0] for x in dbx("SELECT held FROM list_part_trash WHERE list_id=? AND held LIKE ?", (L3, f"%{MK}%"))]
check(not left_, f"#5562: no text of the moved task in the trash copies of its old project {left_}")
check(len(dbx("SELECT id FROM list_part_trash WHERE list_id=? AND (held LIKE '%StayValue%' OR held LIKE '%StayNote%')", (L3,))) == 2,
      "#5562: the copies keep the other task's value and note")
r = A.post(B + f"/api/lists/{L3}/time/restore", json={"wipe": W3})
back = sorted((x[0], x[1]) for x in dbx("SELECT note, task_title FROM time_entries WHERE list_id=?", (L3,)))
# review 4: bob's entry comes back only with an intact seal (alice restores it): the new seal holds
check(r.ok and r.json().get("restored") == 3 and back == [("", ""), ("", ""), ("StayNote", "Stays here")]
      and dbx("SELECT COUNT(*) FROM time_entries WHERE list_id=? AND user_id=?", (L3, BOB))[0][0] == 1,
      f"#5562: Undo of 'delete all times' still works (bob's entry sealed again), the moved task's entries without texts {back} {r.text[:200]}")
F3T = dbx("SELECT held FROM list_part_trash WHERE list_id=? AND kind='list_field'", (L3,))
check(F3T and json.loads(F3T[0][0]).get("n") == 1, f"#5562: the field copy counts one task left {F3T}")

# ================================================================== 2.900.0 (#5550): undo writes no note back into a locked project
# A step of before the lock that a scrub missed (a project locked by an older version, set here in the database): taking it
# back brings the entry back / its values back, but never a note or task title in plain text.
L4 = A.post(B + "/api/lists", json={"name": "Locked later", "org_id": None}).json()["id"]
dbx("UPDATE lists SET time_tracking=1 WHERE id=?", (L4,), write=True)
_st = (datetime.now() - timedelta(hours=7)).isoformat(timespec="seconds")
E1 = A.post(B + "/api/time/entries", json={"list_id": L4, "start": _st, "minutes": 25, "note": "Back note"}).json()["id"]
# review (Fable): the note emptied by the step itself, so the lock leaves the row as the step left it and only the guard refuses
r = A.patch(B + f"/api/time/entries/{E1}", json={"minutes": 35, "note": ""})
G1 = r.json().get("undo_group") if r.ok else None
E2 = A.post(B + "/api/time/entries", json={"list_id": L4, "start": _st, "minutes": 5, "note": "Gone note"}).json()["id"]
r = A.delete(B + f"/api/time/entries/{E2}")
G2 = r.json().get("undo_group") if r.ok else None
check(bool(G1 and G2), f"(setup) two time steps in the later locked project {G1} {G2}")
dbx("UPDATE lists SET e2e='on' WHERE id=?", (L4,), write=True)
dbx("UPDATE time_entries SET note='' WHERE list_id=?", (L4,), write=True)  # as le2b_scrub_free did at the lock
nh0 = dbx("SELECT COUNT(*) FROM obj_history WHERE vals_after LIKE ? OR vals_before LIKE ?", ("%Back note%", "%Back note%"))[0][0]
r = A.post(B + f"/api/undo/to/{G1}")
rows = {x[0]: (x[1], x[2]) for x in dbx("SELECT id, note, seconds FROM time_entries WHERE id IN (?, ?)", (E1, E2))}
check(r.ok and rows.get(E2, (None,))[0] == "" and rows.get(E1) == ("", 2100) and G1 in [x.get("group") for x in r.json().get("stayed") or []],
      f"#5550: undo into a locked project: the deleted entry back without its note, the note change refused (stays) {r.status_code} {r.text[:300]} {rows}")
check(dbx("SELECT COUNT(*) FROM obj_history WHERE vals_after LIKE ? OR vals_before LIKE ?", ("%Back note%", "%Back note%"))[0][0] == nh0,
      "#5550: the refused step writes no history row with the note")
check(not dbx("SELECT 1 FROM obj_undo WHERE kind='time_life' AND ref_id=? AND (snap LIKE ? OR COALESCE(redo, '') LIKE ?)",
              (E2, "%Gone note%", "%Gone note%")),
      "#5550: the taken back step keeps no note in its copy")
dbx("UPDATE lists SET e2e=NULL WHERE id=?", (L4,), write=True)

# ================================================================== 2.902.0 (#5574): an older window still holding the answer of
# "Delete all times" restores after a task moved into the locked project: its title / note stay empty, and the server's copy
# (sealed again by the move) is used up all the same -- an Undo by the copy afterwards brings nothing twice
T7 = A.post(B + "/api/tasks", json={"list_id": L3, "title": MK + "OldWinTitle"}).json()["id"]
for s_, note_, h_ in ((A, MK + "OldWinNote", 9), (Bo, MK + "OldWinBob", 10)):
    r = s_.post(B + "/api/time/entries", json={"task_id": T7, "start": (datetime.now() - timedelta(hours=h_)).isoformat(timespec="seconds"),
                                              "minutes": 15, "note": note_})
    check(r.ok, f"#5574: a time entry with a note {r.text[:200]}")
N3 = dbx("SELECT COUNT(*) FROM time_entries WHERE list_id=?", (L3,))[0][0]
r = A.post(B + f"/api/lists/{L3}/time/delete-all", json={"confirm": "Other open"})
W4, ENTS4 = (r.json().get("wipe"), r.json().get("entries")) if r.ok else (None, None)
check(r.ok and W4 and len(ENTS4 or []) == N3, f"#5574: delete all times again {r.status_code} {r.text[:200]}")
r = A.patch(B + f"/api/tasks/{T7}", json={"list_id": L, "title": cipher(41)})
check(r.ok and dbx("SELECT list_id FROM tasks WHERE id=?", (T7,))[0][0] == L, f"#5574: the task moves into the locked project {r.status_code} {r.text[:200]}")
r = A.post(B + f"/api/lists/{L3}/time/restore", json={"entries": ENTS4})  # the older window: its answer with the old seals
plain = dbx("SELECT note, task_title FROM time_entries WHERE list_id=? AND (note LIKE ? OR task_title LIKE ?)", (L3, f"%{MK}%", f"%{MK}%"))
check(r.ok and r.json().get("restored") == N3 and not plain,
      f"#5574: the older window's Undo brings no text of the moved task back {plain} {r.text[:200]}")
check(not dbx("SELECT 1 FROM list_part_trash WHERE id=?", (W4,)), "#5574: the server's copy is used up although the move sealed it again")
r = A.post(B + f"/api/lists/{L3}/time/restore", json={"wipe": W4})
check(r.status_code == 404 and dbx("SELECT COUNT(*) FROM time_entries WHERE list_id=?", (L3,))[0][0] == N3,
      f"#5574: a second Undo by the copy doubles nothing {r.status_code} {r.text[:200]}")

print(f"\n{OKS[0]} checks ok, {len(FAILS)} failed", flush=True)
if FAILS:
    print("FAILED:\n - " + "\n - ".join(FAILS))
    sys.exit(1)
print("ALL OK")
