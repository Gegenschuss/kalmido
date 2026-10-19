#!/usr/bin/env python3
"""2.115.0 API tests, part A (#2061): inbound webhooks of a list, webhooks of an organisation and the new events. Own container
(start.sh with the webhook stub). Invented names only, addresses @example.com.
 - inbound: only the owner / a list admin adds one (a viewer, a member with edit, an agent: 403 / 404); the URL is shown once (the
   list never shows it again); POST JSON / form / text/plain without a cookie creates a task in exactly this list (activity via
   webhook + hook id, the list tags it has, its fields by name or id); unknown keys, tags and fields are ignored and named;
   an invalid date / priority: 400; a wrong token, a rotated (old) and a deleted token: 404; the body limit 413; the rate 429;
   the creator loses the write right -> 403 and paused; delete + restore (the undo) brings the same URL back
 - an organisation's webhooks: only its admins (a member 403, another organisation 404); an event of an organisation's list
   arrives, one of a member's private list never; list.shared of an organisation's list; the creator is no admin any more ->
   the webhook turns itself off ('admin'); the organisation's calendar event arrives, a private one only at the personal webhook
 - the new events: event.created / updated / deleted, file.created, time.created, invoice.created / sent / paid
 - a person without an organisation (freelancer-matrix: lists): an inbound webhook of a private list, a personal webhook
   with the new events from the private area (calendar, time, files, the personal office)
usage: p2115_a_api_test.py <datadir>      (a fresh container; P2115A_NOSTART=1 = the server already runs)"""
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
STUB = "http://127.0.0.1:8097"
D = "2031-05-12"
FAILS, OKS = [], [0]


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


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def hooks_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "wh.log")) if x.strip()]
    except FileNotFoundError:
        return []


def got(path, event, pred=None, timeout=15):
    """Payloads the stub received on path for event (and pred(data)), waiting up to timeout seconds for the first."""
    def f():
        out = []
        for r in hooks_log():
            if r["path"] != path or r["headers"].get("X-Kalmido-Event") != event:
                continue
            p = json.loads(r["body"])
            if pred is None or pred(p["data"]):
                out.append(p)
        return out
    t0 = time.time()
    while time.time() - t0 < timeout:
        x = f()
        if x:
            return x
        time.sleep(0.3)
    return f()


def none_after(path, event, pred, wait=4):
    time.sleep(wait)
    return not got(path, event, pred, timeout=0)


def post_in(url, **kw):
    """The inbound webhook: a plain client, no cookie, no CSRF header."""
    return requests.post(url, **kw)


if not os.environ.get("P2115A_NOSTART"):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_webhook.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA],
                       env=dict(os.environ, KEEP="1", EXTRA="-e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8097 -e KALMIDO_WEBHOOK_TICK=1 "
                                                         "-e KALMIDO_HOOK_IN_PER_MIN=6"),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_webhook.py"])
    time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "frank"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "frank" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
OB = r.json().get("id")
Bo, Ca, Fr = sess("bob"), sess("carol"), sess("frank")
for s in (A, Bo, Ca, Fr):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok

# ================================================================ 1. inbound webhook of a list
# tenant-matrix: webhook, list, token
L = Bo.post(B + "/api/lists", json={"name": "Inbox automations", "kind": "project", "org_id": None}).json()
LID = L["id"]
check(L.get("org_id") in (None, 0), "bob's list is private")
Bo.post(B + f"/api/lists/{LID}/tags", json={"name": "Urgent"})
FLD = Bo.post(B + f"/api/lists/{LID}/fields", json={"name": "Budget", "type": "number"}).json().get("id")
check(bool(FLD), "a field of the list")
Bo.put(B + f"/api/lists/{LID}/members", json={"user_id": uid["carol"], "role": "view"})
OTHER = Ca.post(B + "/api/lists", json={"name": "Carol's own", "org_id": None}).json()["id"]

check(Ca.post(B + f"/api/lists/{LID}/hooks-in", json={"name": "x"}).status_code == 403, "a viewer cannot add an inbound webhook")
check(Ca.get(B + f"/api/lists/{LID}/hooks-in").status_code == 403, "a viewer does not see the inbound webhooks")
check(Fr.get(B + f"/api/lists/{LID}/hooks-in").status_code == 404, "a stranger: 404")
check(Bo.post(B + f"/api/lists/{LID}/hooks-in", json={"name": "x", "secret": 1}).status_code == 400, "unknown fields: 400")
r = Bo.post(B + f"/api/lists/{LID}/hooks-in", json={"name": "Home Assistant"})
check(r.status_code == 201 and "/api/hooks/in/" in r.json().get("url", ""), f"created, the URL once: {r.status_code} {r.text[:200]}")
HK = r.json()
URL = HK["url"].replace(HK["url"].split("/api/hooks/in/")[0], B)
TOK = URL.rsplit("/", 1)[1]
lst = Bo.get(B + f"/api/lists/{LID}/hooks-in").json()
check(len(lst["hooks"]) == 1 and TOK not in json.dumps(lst) and "url" not in lst["hooks"][0], "the list never shows the URL again")
check(not dbx("SELECT 1 FROM hook_in WHERE token_hash=?", (TOK,)), "only the hash is stored")

r = post_in(URL, json={"title": "Washing machine done", "notes": "Take it out", "due": D, "priority": "high", "tags": ["urgent", "nope"],
                       "fields": {"Budget": 12, "Unknown": 3}, "colour": "red"})
check(r.status_code == 201 and r.json().get("id"), f"JSON: 201 {r.status_code} {r.text[:200]}")
T1 = r.json().get("id")
ign = r.json().get("ignored") or []
check("colour" in ign and "tags.nope" in ign and "fields.Unknown" in ign, f"unknown things are named: {ign}")
t = Bo.get(B + f"/api/tasks/{T1}").json()
check(t.get("list_id") == LID and t.get("title") == "Washing machine done" and t.get("content") == "Take it out"
      and t.get("due") == D and t.get("priority") == 5, f"the task in the webhook's list: {t.get('list_id')} {t.get('due')} {t.get('priority')}")
check(t.get("created_by") == uid["bob"], "created with the rights (and name) of its creator")
check([x[0] for x in dbx("SELECT g.name FROM task_list_tags x JOIN list_tags g ON g.id=x.tag_id WHERE x.task_id=?", (T1,))] == ["Urgent"],
      "the list tag it has (case-insensitive); no new tag")
check(len(dbx("SELECT 1 FROM list_tags WHERE list_id=?", (LID,))) == 1, "no tag was created")
check(dbx("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (T1, FLD)), "the field by its name")
a = dbx("SELECT data FROM activity WHERE task_id=? AND kind='created'", (T1,))
ad = a[0][0] if a else {}
ad = json.loads(ad) if isinstance(ad, str) else ad
check(ad.get("via") == "webhook" and ad.get("hook") == HK["id"], f"activity via webhook + hook id: {ad}")
r = post_in(URL, json={"title": "With id field", "fields": {str(FLD): 7}, "due": f"{D}T14:30:00"})
check(r.status_code == 201, f"a field by its id, a date-time: {r.status_code} {r.text[:200]}")
t = Bo.get(B + f"/api/tasks/{r.json().get('id')}").json()
check(t.get("due") == D and t.get("due_time") == "14:30", f"date + time: {t.get('due')} {t.get('due_time')}")
r = post_in(URL, data={"title": "From a form", "notes": "n", "tags": "Urgent, x"})
check(r.status_code == 201, f"form-encoded: {r.status_code} {r.text[:200]}")
r = post_in(URL, data="Buy milk\nand bread".encode(), headers={"Content-Type": "text/plain"})
check(r.status_code == 201, f"text/plain: {r.status_code}")
t = Bo.get(B + f"/api/tasks/{r.json().get('id')}").json()
check(t.get("title") == "Buy milk" and t.get("content") == "and bread", "text: first line title, the rest notes")
# the rate limit (KALMIDO_HOOK_IN_PER_MIN=6): four requests so far, two more pass, the seventh is 429
check(all(post_in(URL, json={"title": f"more {i}"}).status_code == 201 for i in (5, 6)), "the fifth and sixth request in the minute")
check(post_in(URL, json={"title": "seventh"}).status_code == 429, "the seventh: 429")
time.sleep(61)
check(post_in(URL, json={}).status_code == 400, "no title: 400")
check(post_in(URL, json={"title": "x", "due": "31.12.2031"}).status_code == 400, "an invalid date: 400")
check(post_in(URL, json={"title": "x", "priority": "urgent"}).status_code == 400, "an invalid priority: 400")
check(post_in(URL, json=["x"]).status_code == 400, "not an object: 400")
check(post_in(URL, data=b"{" + b" " * 70000 + b"}", headers={"Content-Type": "application/json"}).status_code == 413, "too large: 413")
check(post_in(B + "/api/hooks/in/khi_wrong", json={"title": "x"}).status_code == 404, "a wrong token: 404")
check(post_in(B + "/api/hooks/in/" + "x" * 300, json={"title": "x"}).status_code == 404, "a far too long token: 404")
n_before = dbx("SELECT COUNT(*) FROM tasks WHERE list_id=?", (OTHER,))[0][0]
check(dbx("SELECT COUNT(*) FROM tasks WHERE list_id=?", (OTHER,))[0][0] == n_before == 0, "nothing in another list")
# rotate: the old URL stops at once
r = Bo.post(B + f"/api/hooks-in/{HK['id']}/rotate")
check(r.ok and r.json().get("url") and r.json()["url"].rsplit("/", 1)[1] != TOK, "rotate: a new URL")
URL2 = B + "/api/hooks/in/" + r.json()["url"].rsplit("/", 1)[1]
check(post_in(URL, json={"title": "old"}).status_code == 404, "the old URL: 404")
check(post_in(URL2, json={"title": "new"}).status_code == 201, "the new URL works")
# the creator loses the write right -> 403 + paused; an owner takes it over
Bo.put(B + f"/api/lists/{LID}/members", json={"user_id": uid["carol"], "role": "admin"})
r = Ca.post(B + f"/api/lists/{LID}/hooks-in", json={"name": "Carol's"})
check(r.status_code == 201, f"a list admin adds one: {r.status_code}")
CH, CURL = r.json()["id"], B + "/api/hooks/in/" + r.json()["url"].rsplit("/", 1)[1]
check(post_in(CURL, json={"title": "by carol's hook"}).status_code == 201, "carol's webhook works")
Bo.put(B + f"/api/lists/{LID}/members", json={"user_id": uid["carol"], "role": "view"})
r = post_in(CURL, json={"title": "after the downgrade"})
check(r.status_code == 403, f"the creator may no longer write: 403 {r.status_code}")
h = [x for x in Bo.get(B + f"/api/lists/{LID}/hooks-in").json()["hooks"] if x["id"] == CH]
check(h and h[0]["paused_reason"] == "role" and h[0]["paused_text"], f"paused with the reason: {h}")
check(post_in(CURL, json={"title": "still paused"}).status_code == 403, "stays paused")
r = Bo.patch(B + f"/api/hooks-in/{CH}", json={"resume": True})
check(r.ok and not r.json()["paused_reason"] and r.json()["created_by"] == uid["bob"], "the owner takes it over with own rights")
check(post_in(CURL, json={"title": "resumed"}).status_code == 201, "resumed")
# delete + restore (the undo)
check(Bo.delete(B + f"/api/hooks-in/{CH}").ok, "delete")
check(post_in(CURL, json={"title": "deleted"}).status_code == 404, "a deleted webhook: 404")
check(Bo.post(B + f"/api/hooks-in/{CH}/restore").ok, "restore")
check(post_in(CURL, json={"title": "restored"}).status_code == 201, "restored: the same URL works again")
check(Fr.delete(B + f"/api/hooks-in/{CH}").status_code == 404, "a stranger cannot delete it (404)")
# agents never manage them
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}
check(requests.get(B + f"/api/lists/{LID}/hooks-in", headers=AGH).status_code in (401, 403, 404), "an agent token: refused")
# not in the basket / health lists
INBOX = [x for x in Bo.get(B + "/api/state").json()["lists"] if x.get("is_inbox")][0]["id"]
check(Bo.post(B + f"/api/lists/{INBOX}/hooks-in", json={}).status_code == 409, "not in the basket: 409")

# ================================================================ 2. webhooks of an organisation
OL = A.post(B + "/api/lists", json={"name": "Alpha board", "org_id": ORG}).json()["id"]
BL = Bo.post(B + "/api/lists", json={"name": "Bob private", "org_id": None}).json()["id"]
EVS = ["task.created", "list.shared", "event.created", "event.updated", "event.deleted", "file.created", "time.created",
       "invoice.created", "invoice.sent", "invoice.paid"]
check(Bo.get(B + f"/api/orgs/{ORG}/webhooks").status_code == 403, "a member: 403")
check(Bo.post(B + f"/api/orgs/{ORG}/webhooks", json={"url": STUB + "/org", "events": EVS}).status_code == 403, "a member cannot add one")
check(Fr.get(B + f"/api/orgs/{ORG}/webhooks").status_code == 404, "another organisation's admin: 404")
r = A.post(B + f"/api/orgs/{ORG}/webhooks", json={"name": "Alpha", "url": STUB + "/org", "events": EVS})
check(r.status_code == 201 and r.json().get("secret", "").startswith("whsec_"), f"the admin adds one, secret once: {r.status_code} {r.text[:200]}")
OW = r.json()["id"]
check(A.get(B + f"/api/orgs/{ORG}/webhooks").json()["hooks"][0]["id"] == OW, "listed for the organisation")
check(all(h["id"] != OW for h in A.get(B + "/api/me/webhooks").json()["hooks"]), "not among the admin's own webhooks")
check(A.patch(B + f"/api/me/webhooks/{OW}", json={"name": "x"}).status_code == 404, "not reachable as an own webhook")
check(Fr.patch(B + f"/api/orgs/{OB}/webhooks/{OW}", json={"name": "x"}).status_code == 404, "not reachable through another organisation")
check(A.post(B + f"/api/orgs/{ORG}/webhooks", json={"url": "http://10.0.0.5/x", "events": EVS}).status_code == 400, "internal addresses refused")
r = A.post(B + f"/api/orgs/{ORG}/webhooks/{OW}/test")
check(r.ok and r.json().get("ok"), f"send test: {r.text[:200]}")
check(A.get(B + f"/api/orgs/{ORG}/webhooks/{OW}/log").json()["items"], "the delivery log")
r = A.post(B + "/api/tasks", json={"list_id": OL, "title": "Org task by alice"})
check(r.ok, f"a task in the organisation's list {r.status_code}")
Bo.post(B + "/api/tasks", json={"list_id": BL, "title": "Bob's secret"})
check(bool(got("/org", "task.created", lambda d: d["task"]["title"] == "Org task by alice")), "an organisation's list: the event arrives")
check(none_after("/org", "task.created", lambda d: d["task"]["title"] == "Bob's secret"), "a member's private list: never")
A.put(B + f"/api/lists/{OL}/members", json={"user_id": uid["carol"], "role": "edit"})
check(bool(got("/org", "list.shared", lambda d: d["list"]["id"] == OL)), "list.shared of an organisation's list")
# a task created by an inbound webhook of an organisation's list reaches the organisation's webhook (normal create path)
r = A.post(B + f"/api/lists/{OL}/hooks-in", json={"name": "n8n"})
OURL = B + "/api/hooks/in/" + r.json()["url"].rsplit("/", 1)[1]
check(post_in(OURL, json={"title": "From n8n"}).status_code == 201, "the inbound webhook of an organisation's list")
w = got("/org", "task.created", lambda d: d["task"]["title"] == "From n8n")
check(bool(w) and w[0]["via"] == "webhook", f"... reaches the organisation's webhook, via webhook: {w[:1]}")

# calendars: the organisation's calendar -> the organisation's webhook; a private one -> only the personal webhook
r = A.post(B + "/api/me/webhooks", json={"name": "mine", "url": STUB + "/alice", "events": ["event.created", "task.created"]})
check(r.status_code == 201, "alice's own webhook")
OC = A.post(B + "/api/evcals", json={"name": "Alpha shoots", "org_id": ORG}).json()["id"]
PC = A.post(B + "/api/evcals", json={"name": "Alice private", "org_id": None}).json()["id"]
e1 = A.post(B + "/api/events", json={"title": "Org shoot", "cal_id": OC, "start": f"{D}T09:00", "end": f"{D}T17:00"}).json()
e2 = A.post(B + "/api/events", json={"title": "Dentist", "cal_id": PC, "start": f"{D}T08:00", "end": f"{D}T08:30"}).json()
w = got("/org", "event.created", lambda d: d["event"]["title"] == "Org shoot")
check(bool(w) and w[0]["data"]["calendar"]["id"] == OC and "description" not in w[0]["data"]["event"], "event.created of the organisation's calendar")
check(bool(got("/alice", "event.created", lambda d: d["event"]["title"] == "Dentist")), "the private event at the personal webhook")
check(none_after("/org", "event.created", lambda d: d["event"]["title"] == "Dentist", 2), "the private event never at the organisation's")
check(none_after("/alice", "event.created", lambda d: d["event"]["title"] == "Org shoot", 0), "the organisation's event not at the personal one")
A.patch(B + f"/api/events/{e1['id']}", json={"title": "Org shoot moved"})
check(bool(got("/org", "event.updated", lambda d: d["event"]["title"] == "Org shoot moved")), "event.updated")
A.delete(B + f"/api/events/{e1['id']}")
check(bool(got("/org", "event.deleted", lambda d: d["event"]["id"] == e1["id"] and d["event"]["deleted"])), "event.deleted")
# files of the organisation
r = A.post(B + "/api/files/upload", data={"space": f"org:{ORG}"}, files={"file": ("plan.txt", b"plan")})
check(r.status_code in (200, 201), f"an upload into the organisation's files {r.status_code} {r.text[:200]}")
check(bool(got("/org", "file.created", lambda d: d["file"]["name"] == "plan.txt")), "file.created of the organisation")
A.post(B + "/api/files/upload", data={"space": "private"}, files={"file": ("diary.txt", b"x")})
check(none_after("/org", "file.created", lambda d: d["file"]["name"] == "diary.txt", 2), "a private file never at the organisation's")
# time entries on an organisation's project
TL = A.post(B + "/api/lists", json={"name": "Alpha project", "org_id": ORG, "kind": "project", "time_tracking": True}).json()["id"]
r = A.post(B + "/api/time/entries", json={"list_id": TL, "start": "2026-09-01T09:00", "minutes": 30})
check(r.status_code in (200, 201), f"a time entry {r.status_code} {r.text[:200]}")
w = got("/org", "time.created", lambda d: (d.get("list") or {}).get("id") == TL)
check(bool(w) and w[0]["data"]["time"]["seconds"] == 1800 and "note" not in w[0]["data"]["time"], "time.created (short, no note)")
# the creator is no admin any more -> the webhook turns itself off
A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "admin"})
r = Bo.post(B + f"/api/orgs/{ORG}/webhooks", json={"name": "Bob's", "url": STUB + "/bob-org", "events": ["task.created"]})
check(r.status_code == 201, "a second admin adds one")
BW = r.json()["id"]
A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "member"})
A.post(B + "/api/tasks", json={"list_id": OL, "title": "After bob's demotion"})
time.sleep(2)
h = [x for x in A.get(B + f"/api/orgs/{ORG}/webhooks").json()["hooks"] if x["id"] == BW]
check(h and not h[0]["enabled"] and h[0]["disabled_reason"] == "admin", f"turned off: no admin any more {h}")
check(none_after("/bob-org", "task.created", lambda d: True, 2), "nothing delivered after the demotion")
r = A.patch(B + f"/api/orgs/{ORG}/webhooks/{BW}", json={"enabled": True})
check(r.ok and r.json()["enabled"], "another admin switches it on again (and owns it)")
check(A.delete(B + f"/api/orgs/{ORG}/webhooks/{BW}").ok and Bo.delete(B + f"/api/orgs/{ORG}/webhooks/{OW}").status_code == 403,
      "delete: an admin yes, a member no")

# ================================================================ 3. a person without an organisation
# freelancer-matrix: lists
FID, F = freelancer(B, A)
r = F.post(B + "/api/me/webhooks", json={"name": "all", "url": STUB + "/frida",
                                          "events": ["task.created", "event.created", "time.created", "file.created", "invoice.created",
                                                     "invoice.sent", "invoice.paid"]})
check(r.status_code == 201, f"a personal webhook with the new events {r.status_code} {r.text[:200]}")
FL = F.post(B + "/api/lists", json={"name": "Client work", "kind": "project", "time_tracking": True}).json()
check(FL.get("org_id") in (None, 0), "the freelancer's list is private")
r = F.post(B + f"/api/lists/{FL['id']}/hooks-in", json={"name": "Make"})
check(r.status_code == 201, f"an inbound webhook of the private list {r.status_code}")
FURL = B + "/api/hooks/in/" + r.json()["url"].rsplit("/", 1)[1]
check(F.get(B + f"/api/lists/{FL['id']}/hooks-in").json()["hooks"][0]["name"] == "Make", "listed")
check(post_in(FURL, json={"title": "Invoice reminder"}).status_code == 201, "it creates a task")
check(bool(got("/frida", "task.created", lambda d: d["task"]["title"] == "Invoice reminder")), "... and the own webhook hears it")
fc = F.post(B + "/api/evcals", json={"name": "Shoots"}).json()["id"]
F.post(B + "/api/events", json={"title": "Shoot day", "cal_id": fc, "start": f"{D}T09:00", "end": f"{D}T17:00"})
check(bool(got("/frida", "event.created", lambda d: d["event"]["title"] == "Shoot day")), "event.created from the private calendar")
r = F.post(B + "/api/time/entries", json={"list_id": FL["id"], "start": "2026-09-01T09:00", "minutes": 15})
check(r.status_code in (200, 201), f"a private time entry {r.status_code} {r.text[:200]}")
check(bool(got("/frida", "time.created", lambda d: d["time"]["seconds"] == 900)), "time.created from the private project")
F.post(B + "/api/files/upload", data={"space": "private"}, files={"file": ("brief.txt", b"brief")})
check(bool(got("/frida", "file.created", lambda d: d["file"]["name"] == "brief.txt")), "file.created from the own files")
cl = F.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"}).json()
F.put(B + "/api/office/settings", json={"company_fields": {"name": "Frida Film", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg",
                                                            "country": "DE", "tax_number": "12/345/67890",
                                                            "iban": "DE02120300000000202051", "bic": "BYLADEM1001"}})
q = F.post(B + "/api/office/docs", json={"project_title": "Imagefilm", "client_id": cl.get("id"), "service_from": "2026-09-01",
                                         "service_to": "2026-09-30"}).json()
F.put(B + f"/api/office/docs/{q.get('id')}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": 900}]})
inv = F.post(B + f"/api/office/docs/{q.get('id')}/invoice").json()
check(bool(inv.get("id")), f"an invoice of the personal office {inv}")
w = got("/frida", "invoice.created", lambda d: d["invoice"]["id"] == inv.get("id"))
check(bool(w) and "iban" not in json.dumps(w[0]).lower(), "invoice.created (no bank data)")
r = F.post(B + f"/api/office/docs/{inv.get('id')}/finalize")
check(r.ok, f"finalised {r.status_code} {r.text[:200]}")
r = F.post(B + f"/api/office/docs/{inv.get('id')}/status", json={"status": "sent"})
check(r.ok, f"marked sent {r.status_code} {r.text[:200]}")
check(bool(got("/frida", "invoice.sent", lambda d: d["invoice"]["id"] == inv.get("id"))), "invoice.sent")
r = F.post(B + f"/api/office/docs/{inv.get('id')}/status", json={"status": "paid"})
check(r.ok, f"marked paid {r.status_code} {r.text[:200]}")
check(bool(got("/frida", "invoice.paid", lambda d: d["invoice"]["id"] == inv.get("id") and d["invoice"]["status"] == "paid")), "invoice.paid")
check(F.get(B + f"/api/orgs/{ORG}/webhooks").status_code == 404, "the freelancer: no organisation's webhooks (404)")

print(f"\np2115_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
