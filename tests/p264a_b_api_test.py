#!/usr/bin/env python3
"""2.64.1 API tests (part B): the lock per list on the other ways out of the server (#1817, findings H2, M4, M5, M7, L6).
A list is brought into the state "encrypted in the browser" straight in the database (lists.e2e = 'on', texts replaced by
synthetic ciphertexts "e2e1:{v, g, iv, ct}"; the server never reads them) and the copies are removed with le2b_scrub (run in
the app container, no test route in the app). Then:
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
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
MK = "Zqxv"  # every marker word starts with it (the sweep looks for it)


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
due = date.today().isoformat()
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
r = A.post(B + "/api/sections", json={"list_id": L, "name": MK + "Section"})
check(r.ok, f"a section {r.text[:200]}")
r = A.post(B + "/api/time/entries", json={"task_id": T, "start": (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds"), "minutes": 30})
check(r.ok, f"a time entry on the task {r.text[:200]}")
SEC = dbx("SELECT id FROM sections WHERE list_id=?", (L,))[0][0]
# copies the app writes in other places (shopping memory, a mail address, an agent proposal): written here like the app does
dbx("INSERT INTO shop_memory(list_id,item,section_id,at) VALUES(?,?,?,?)", (L, MK.lower() + "milk", SEC, "2026-01-01T00:00:00Z"), write=True)
dbx("INSERT INTO mail_tokens(token,user_id,list_id,created_at) VALUES(?,?,?,?)", ("tok264b", 1, L, "2026-01-01T00:00:00Z"), write=True)
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

# ================================================================== the switch (stands in for part A's routes)
for i, (tbl, col, where, args) in enumerate((("tasks", "title", "list_id=?", (L,)), ("tasks", "content", "list_id=?", (L,)),
                                              ("tasks", "url", "list_id=?", (L,)), ("notes", "title", "list_id=?", (L,)),
                                              ("notes", "body", "list_id=?", (L,)), ("sections", "name", "list_id=?", (L,)),
                                              ("comments", "body", "task_id IN (SELECT id FROM tasks WHERE list_id=?)", (L,)))):
    dbx(f"UPDATE {tbl} SET {col}=? WHERE {where}", (cipher(i),) + args, write=True)
dbx("UPDATE lists SET e2e='on', e2e_gen=1 WHERE id=?", (L,), write=True)
rc, out, er = py(f"from kalmido.collab.liste2eguard import le2b_scrub\nc=app.connect()\nn=le2b_scrub(c, {L})\nc.commit()\nimport json\nprint(json.dumps(n))")
check(rc == 0, f"le2b_scrub runs {out} {er}")
try:
    n = json.loads(out.splitlines()[-1])
except (ValueError, IndexError):
    n = {}
check(n.get("shop_memory") == 1 and n.get("mail_tokens") == 1 and n.get("webhook_queue", 0) >= 1 and n.get("activity", 0) >= 1,
      f"scrub counts {n}")
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
check(r.status_code in (200, 403, 404) and "e2e1:" not in r.text, f"v1 comments: no ciphertext {r.status_code} {r.text[:200]}")
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
check(r.status_code in (200, 404) and "e2e1:" not in r.text and f'"id": {T},' not in r.text.replace('"id":', '"id": '),
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
    check(pr.status_code in (200, 201, 204) and dbx("SELECT title FROM tasks WHERE id=?", (T,))[0][0] == cipher(0),
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
check(rc == 0 and out.endswith("(None, None)"), f"mail to the locked list's address: nobody (like an unknown address) {out} {er}")
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
check(r.status_code in (200, 404) and "e2e1:" not in r.text, f"message search: no ciphertext {r.status_code}")
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

print(f"\n{OKS[0]} checks ok, {len(FAILS)} failed", flush=True)
if FAILS:
    print("FAILED:\n - " + "\n - ".join(FAILS))
    sys.exit(1)
print("ALL OK")
