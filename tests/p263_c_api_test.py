#!/usr/bin/env python3
"""2.63.0 API tests, part C (#1523, follow-ups of 2.43): invented names only.
 - Undo of "Delete all times of this project" brings the entries back with every column: the timer's device id (client_id),
   created_at, the flags; a device id the person already uses again comes back empty instead of failing; a member gets only
   their own entries back
 - a list template saved from a project carries its notepads, the standard arrangement and the block colours; a list made
   from it has new notepads whose keys (np<id>) are rewritten in page_layout and page_style; a key without its notepad goes
 - the time window / entry list / report / CSV / v1 show other people's entries only to the list's owner, its admins and
   the admins of its organisation; editors see their own ("own_only" in the report); the entries of one task stay
usage: p263_c_api_test.py <datadir>      (a fresh container; P263C_NOSTART=1 = the server already runs)"""
import csv
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
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
    return dbxm.connect(DATA).execute(sql, args).fetchall()


if not os.environ.get("P263C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments", "time"]})
A.patch(B + "/api/settings", json={"lang": "en"})
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}
for s_ in (A, Bo, Ca, Da, Er):
    s_.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab,time", "tour": "done"})
ORG = dbx("INSERT INTO orgs(name, icon, domains, created_at) VALUES('Alpha', '', '', '2026-01-01T00:00:00+00:00') RETURNING id")[0][0]
for u, role in (("alice", "member"), ("bob", "member"), ("carol", "member"), ("dave", "member"), ("erin", "admin")):
    dbx("INSERT INTO org_members(org_id, user_id, role) VALUES(?, ?, ?)", (ORG, ids[u], role))

P = A.post(B + "/api/lists", json={"name": "Harbour site", "kind": "project", "time_tracking": True}).json()["id"]
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, P))
A.put(B + f"/api/lists/{P}/members", json={"user_id": ids["bob"], "role": "edit"})
A.put(B + f"/api/lists/{P}/members", json={"user_id": ids["carol"], "role": "edit"})
A.put(B + f"/api/lists/{P}/members", json={"user_id": ids["dave"], "role": "admin"})
A.put(B + f"/api/lists/{P}/members", json={"user_id": ids["erin"], "role": "edit"})  # an editor of the list, admin of its organisation
T = A.post(B + "/api/tasks", json={"title": "Survey", "list_id": P}).json()["id"]
now = datetime.now(timezone.utc).replace(microsecond=0)


def iso(d):
    return d.isoformat().replace("+00:00", "Z")


# ============================================================ 1. Undo of "delete all times" keeps the client_id
r = Bo.post(B + "/api/time/start", json={"task_id": T, "client_id": "dev-bob-1", "at": iso(now - timedelta(minutes=50))})
check(r.ok, f"bob starts a timer {r.status_code} {r.text[:200]}")
r = Bo.post(B + "/api/time/stop", json={"client_id": "dev-bob-1", "at": iso(now - timedelta(minutes=20))})
check(r.ok, f"bob stops it {r.status_code} {r.text[:200]}")
r = Bo.post(B + "/api/time/entries", json={"task_id": T, "start": iso(now - timedelta(hours=3)), "minutes": 15, "note": "bob manual"})
check(r.ok, "bob manual entry")
r = A.post(B + "/api/time/entries", json={"task_id": T, "start": iso(now - timedelta(hours=4)), "minutes": 60, "note": "alice work"})
check(r.ok, "alice entry")
before = {x[0]: x for x in dbx("SELECT client_id, created_at, user_id, seconds FROM time_entries WHERE list_id=? AND user_id=?", (P, ids["bob"]))}
check("dev-bob-1" in before, f"timer entry has its client_id {list(before)}")

r = Bo.post(B + f"/api/lists/{P}/time/delete-all", json={"confirm": "Harbour site"})
j = r.json()
check(r.ok and j["deleted"] == 2 and any(e.get("client_id") == "dev-bob-1" for e in j["entries"]), f"member delete returns client_id {r.text[:300]}")
r = Bo.post(B + f"/api/lists/{P}/time/restore", json={"entries": j["entries"]})
check(r.ok and r.json()["restored"] == 2, f"undo {r.status_code} {r.text[:200]}")
after = {x[0]: x for x in dbx("SELECT client_id, created_at, user_id, seconds FROM time_entries WHERE list_id=? AND user_id=?", (P, ids["bob"]))}
check("dev-bob-1" in after and after["dev-bob-1"][1] == before["dev-bob-1"][1] and after["dev-bob-1"][3] == before["dev-bob-1"][3],
      f"undo keeps client_id, created_at and seconds {after}")
# a replayed stop of the device still finds its entry (the reason the id matters)
check(Bo.post(B + "/api/time/stop", json={"client_id": "dev-bob-1"}).ok, "replayed stop after undo is fine")
check(len(dbx("SELECT id FROM time_entries WHERE user_id=? AND client_id='dev-bob-1'", (ids["bob"],))) == 1, "one entry with that device id")
# restoring the same entries again: the device id is taken -> the copy comes back without it (no error)
r = Bo.post(B + f"/api/lists/{P}/time/restore", json={"entries": j["entries"]})
check(r.ok and r.json()["restored"] == 2, f"second restore works {r.status_code} {r.text[:200]}")
check(len(dbx("SELECT id FROM time_entries WHERE user_id=? AND client_id='dev-bob-1'", (ids["bob"],))) == 1
      and len(dbx("SELECT id FROM time_entries WHERE user_id=? AND list_id=? AND client_id IS NULL", (ids["bob"], P))) == 3,
      "conflicting device id -> entry without it")
# a member cannot bring back entries for someone else, also not via the device id
r = Bo.post(B + f"/api/lists/{P}/time/restore", json={"entries": [{**j["entries"][0], "user_id": ids["alice"], "client_id": "dev-x"}]})
check(r.ok and r.json()["restored"] == 0, "member: no entries for others")
check(not dbx("SELECT id FROM time_entries WHERE client_id='dev-x'"), "no foreign device id planted")
# junk in the extra fields is cleaned, never stored
r = Bo.post(B + f"/api/lists/{P}/time/restore", json={"entries": [{**j["entries"][0], "client_id": 7, "pomo_id": 999999, "created_at": "x",
                                                                   "reminded": "yes"}]})
check(r.ok and r.json()["restored"] == 1, f"junk fields restore {r.text[:200]}")
row = dbx("SELECT client_id, pomo_id, reminded, created_at FROM time_entries WHERE user_id=? ORDER BY id DESC LIMIT 1", (ids["bob"],))[0]
check(row[0] is None and row[1] is None and row[2] == 0 and row[3] != "x", f"junk cleaned {row}")
dbx("DELETE FROM time_entries WHERE list_id=? AND user_id=? AND client_id IS NULL", (P, ids["bob"]))

# ============================================================ 3. who sees whose time (window, report, CSV, v1)
q = {"scope": "all", "lists": str(P)}
rep = Bo.get(B + "/api/time/report", params=q).json()
check(rep["total"]["count"] == 1 and all(e["user_id"] == ids["bob"] for e in rep["entries"]) and rep["own_only"],
      f"editor: own entries only, own_only {rep['total']} {rep.get('own_only')}")
check([u["id"] for u in rep["users"]] == [ids["bob"]], "editor: by person only themselves")
csvt = Bo.get(B + "/api/time/export.csv", params=q).text
rows = list(csv.reader(io.StringIO(csvt.lstrip("﻿"))))
check(len(rows) == 2 and "Alice" not in csvt, f"editor CSV: own row only {rows}")
ent = Bo.get(B + "/api/time/entries", params=q).json()["entries"]
check(len(ent) == 1 and ent[0]["mine"], "editor: entry list own only")
check(len(Bo.get(B + "/api/time/entries", params={"task_id": T}).json()["entries"]) == 2, "editor: the entries of one task stay everyone's")
for who, s_ in (("owner", A), ("list admin", Da), ("org admin", Er)):
    rep = s_.get(B + "/api/time/report", params=q).json()
    check(rep.get("total", {}).get("count") == 2 and not rep.get("own_only"), f"{who}: all entries {rep.get('total')}")
csvt = Da.get(B + "/api/time/export.csv", params=q).text
check("Alice" in csvt and "Bob" in csvt, "list admin CSV: everyone")
rep = Ca.get(B + "/api/time/report", params=q).json()
check(rep["total"]["count"] == 0 and rep["own_only"], "editor without entries: nothing, own_only")
# v1 with a person's token
tok = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "time"], "expires_days": 30}).json().get("token")
V1 = {"Authorization": "Bearer " + str(tok)}
d = requests.get(B + "/api/v1/time/entries", params={"scope": "all", "from": (now - timedelta(days=1)).date().isoformat()}, headers=V1).json()
check(len(d.get("data", [])) == 1, f"v1 editor: own only {d}")
d = requests.get(B + "/api/v1/time/entries", params={"scope": "all", "task_id": T, "from": (now - timedelta(days=1)).date().isoformat()},
                 headers=V1).json()
check(len(d.get("data", [])) == 2, f"v1 editor, one task: everyone's {d}")
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "time"], "expires_days": 30}).json().get("token")
d = requests.get(B + "/api/v1/time/entries", params={"scope": "all", "from": (now - timedelta(days=1)).date().isoformat()},
                 headers={"Authorization": "Bearer " + str(tok)}).json()
check(len(d.get("data", [])) == 2, f"v1 owner: everyone's {d}")

# ============================================================ 2. templates carry notepads, arrangement and colours
r = A.post(B + f"/api/lists/{P}/notepads", json={"title": "Gate codes", "body": "- north gate\n- south gate"})
check(r.ok, f"notepad 1 {r.status_code} {r.text[:200]}")
N1 = r.json()["id"]
N2 = A.post(B + f"/api/lists/{P}/notepads", json={"title": "Contacts", "body": "site office"}).json()["id"]
lay = {"order": ["kpis", f"np{N2}", "desc", f"np{N1}", "time"], "hidden": ["chat"], "half": [f"np{N1}"],
       "opts": {f"np{N1}": {"lw": 2}}, "mobile": {"order": [f"np{N1}", "kpis"]}}
r = A.put(B + f"/api/lists/{P}/layout", json={"layout": json.dumps(lay), "scope": "standard"})
check(r.ok, f"standard arrangement {r.status_code} {r.text[:200]}")
for blk, col in ((f"np{N1}", "yellow"), ("desc", "blue")):
    check(A.put(B + f"/api/lists/{P}/page-style", json={"block": blk, "color": col}).ok, f"colour {blk}")
# 2.148.1 H (#2483): a template of an organisation's list leaves the organisation -> only one of its admins makes it
r = A.post(B + "/api/templates", json={"list_id": P, "name": "Site template"})
check(r.status_code == 403, f"template from list: a plain member of the organisation may not {r.status_code} {r.text[:200]}")
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=?", (ORG, ids["alice"]))  # admin for the rest of the suite
r = A.post(B + "/api/templates", json={"list_id": P, "name": "Site template"})
check(r.ok, f"template from list {r.status_code} {r.text[:200]}")
TP = r.json()["id"]
td = r.json().get("data") or {}
if isinstance(td, str):
    td = json.loads(td)
check(len(td.get("notepads") or []) == 2 and td.get("page_style", {}).get(f"np{N1}") == "yellow", f"template data carries the page {str(td)[:300]}")
# the template editor sends the data back unchanged: the page survives
check(A.patch(B + f"/api/templates/{TP}", json={"data": td}).ok, "template edit")

r = A.post(B + f"/api/templates/{TP}/apply", json={"name": "Harbour site 2"})
check(r.ok, f"list from template {r.status_code} {r.text[:200]}")
P2 = r.json()["list_id"]
pads = dbx("SELECT id, title, body FROM list_notepads WHERE list_id=? ORDER BY id", (P2,))
check([p[1] for p in pads] == ["Gate codes", "Contacts"] and pads[0][2].startswith("- north gate"), f"notepads copied {pads}")
M1, M2 = pads[0][0], pads[1][0]
check(M1 not in (N1, N2) and M2 not in (N1, N2), "new notepad ids")
pl, ps = dbx("SELECT page_layout, page_style FROM lists WHERE id=?", (P2,))[0]
pl, ps = json.loads(pl or "{}"), json.loads(ps or "{}")
check(pl.get("order") == ["kpis", f"np{M2}", "desc", f"np{M1}", "time"] and pl.get("half") == [f"np{M1}"] and pl.get("hidden") == ["chat"],
      f"layout keys rewritten {pl}")
check(pl.get("opts") == {f"np{M1}": {"lw": 2}} and pl.get("mobile", {}).get("order") == [f"np{M1}", "kpis"], f"opts + mobile rewritten {pl}")
check(ps == {f"np{M1}": "yellow", "desc": "blue"}, f"colours rewritten {ps}")
ov = A.get(B + f"/api/lists/{P2}/layout").json()
check(len(ov.get("pads") or []) == 2 and ov.get("style", {}).get(f"np{M1}") == "yellow", f"project page shows the new notepads {str(ov)[:300]}")
check(len(dbx("SELECT id FROM list_notepads WHERE list_id=?", (P,))) == 2, "the source keeps its notepads")

# a template whose arrangement names a notepad it does not carry: that key goes, the rest stays
bad = dict(td, notepads=[n for n in td["notepads"] if n["k"] == f"np{N1}"], page_style={f"np{N2}": "red", "desc": "green"})
r = A.post(B + "/api/templates", json={"kind": "list", "data": bad, "name": "Partial"})
check(r.ok, f"template from data {r.status_code} {r.text[:200]}")
P3 = A.post(B + f"/api/templates/{r.json()['id']}/apply", json={"name": "Partial site"}).json()["list_id"]
pads = dbx("SELECT id FROM list_notepads WHERE list_id=?", (P3,))
pl, ps = dbx("SELECT page_layout, page_style FROM lists WHERE id=?", (P3,))[0]
pl, ps = json.loads(pl or "{}"), json.loads(ps or "{}")
check(len(pads) == 1 and pl.get("order") == ["kpis", "desc", f"np{pads[0][0]}", "time"] and ps == {"desc": "green"}, f"missing notepad key dropped {pl} {ps}")
# junk in the template's page is dropped, never an error
r = A.post(B + "/api/templates", json={"kind": "list", "data": {"name": "Junk", "notepads": [{"k": "x1", "title": 5}, "a"],
                                                               "page_layout": "{not json", "page_style": {"np1": "pink", "BAD KEY": "red"}}})
check(r.ok, f"junk template saved {r.status_code} {r.text[:200]}")
jd = r.json().get("data") or {}
jd = json.loads(jd) if isinstance(jd, str) else jd
check(jd.get("notepads") == [] and jd.get("page_layout") == "" and jd.get("page_style") == {}, f"junk cleaned {jd}")
# agents' own notepads stay with their list
dbx("INSERT INTO list_notepads(list_id,title,body,created_by,created_at,updated_by,updated_at,agent_id) VALUES(?,?,?,?,?,?,?,?)",
    (P, "agent status", "x", ids["alice"], "2026-01-01", ids["alice"], "2026-01-01", ids["alice"]))
td2 = A.post(B + "/api/templates", json={"list_id": P, "name": "Again"}).json().get("data") or {}
td2 = json.loads(td2) if isinstance(td2, str) else td2
check(len(td2.get("notepads") or []) == 2, "agent notepads are not copied")
# a member (editor) may save the template too; a participant may not (unchanged).
# 2.148.1 H (#2483): not of an organisation's list -- bob is a plain member of its organisation
check(Bo.post(B + "/api/templates", json={"list_id": P, "name": "Bob copy"}).status_code == 403, "editor of an organisation list (no org admin) saves no template")
dbx("UPDATE lists SET org_id=NULL WHERE id=?", (P,))
check(Bo.post(B + "/api/templates", json={"list_id": P, "name": "Bob copy"}).ok, "editor saves a template (private list)")

print(f"p263_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
