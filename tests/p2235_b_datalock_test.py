#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.235.0 B (#2902): data an agent may never see (its data lock) - the guard.
 - the gear: GET / PATCH /api/agents/<id>/data-lock for the owner of a personal agent (a person without an organisation,
   freelancer-matrix: agents) and the instance admin of a team agent; others 404; defaults: private e-mails locked, the
   journal / mood / health / budget / read later fixed (cannot be opened: 400); invalid values 400; event data_lock_changed;
   GET /api/v1/agent "data_lock" with area keys, list ids and the number of tags (never a tag name)
 - the guard: tasks with a marker word in a locked project, as a private e-mail (+ subtask), with a locked tag, in a locked
   contracts list (+ comment and attachment with the marker). EVERY GET route of the agent API (openapi.json) is called with
   all ids, plus search / filter queries and the agent's events: the marker shows up nowhere. Writes to locked tasks / lists
   are 404. Then the lock is opened: the same scan finds every marker again (the counter-check that the scan sees them).
 - a team agent (set by the instance admin): a locked project, the same scan, then opened
usage: p2235_b_datalock_test.py <datadir>      (KMT_NOSTART=1 / P2235B_NOSTART=1: a running server)"""
import itertools
import os
import re
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, done, dbx, fresh, setup

V = B + "/api/v1"
MARKS = ("ZQXPROJ", "ZQXMAIL", "ZQXTAG", "ZQXCONTR")

fresh(prefix="P2235B", env={"KALMIDO_API_RATE": "100000"})
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
OID, O = freelancer(B, A, "otto")
AGENT_SCOPES = ["read", "tasks:write", "comments", "attachments:read", "files:read", "calendar", "contacts", "time", "export",
                "structure", "sheets:read", "wiki:read"]


def lock(s, aid, method="get", **kw):
    return getattr(s, method)(B + f"/api/agents/{aid}/data-lock", **kw)


def share(s, lid, aid):
    r = s.put(B + f"/api/lists/{lid}/members", json={"user_id": aid, "role": "edit"})
    check(r.ok, f"list {lid} shared with agent {aid}: {r.status_code} {r.text[:120]}")


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    check(r.ok, f"task {title}: {r.status_code} {r.text[:120]}")
    return r.json()["id"]


def attach(s, tid, name, data):
    r = s.post(B + f"/api/tasks/{tid}/attachments", files={"file": (name, data, "text/plain")})
    check(r.ok, f"attachment {name}: {r.status_code} {r.text[:120]}")


def comment(s, tid, text):
    r = s.post(B + f"/api/tasks/{tid}/comments", json={"body": text})
    check(r.ok, f"comment on {tid}: {r.status_code} {r.text[:120]}")
    return r.json().get("id")


SPEC = requests.get(V + "/openapi.json").json()
GETS = {p for p, ops in SPEC.get("paths", {}).items() if "get" in ops}
check(len(GETS) > 50, f"the spec lists the GET routes ({len(GETS)})")
# plus every GET route of /api/v1 in the server's code (also the ones the spec does not list)
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kalmido")
ROUTE_RE = re.compile(r'@app\.(get|route)\("/api/v1(/[^"]+)"(?:\s*,\s*methods=\[([^\]]*)\])?')
for root, _, files in os.walk(SRC):
    for fn in files:
        if fn.endswith(".py"):
            for kind, path, methods in ROUTE_RE.findall(open(os.path.join(root, fn), encoding="utf-8").read()):
                if kind == "get" or not methods or "GET" in methods:
                    GETS.add(re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", path))
GETS = sorted(GETS)
check(len(GETS) > 100, f"GET routes from the spec and the code ({len(GETS)})")


def scan(h, ids, extra=()):
    """{marker: [url ...]} of every marker found in an answer of a GET route of the agent API (all ids for every path
    parameter, at most 40 combinations a path), the agent's events and a few search / filter queries."""
    found, seen = {}, 0
    for p in GETS:
        names = re.findall(r"{(\w+)}", p)
        combos = itertools.islice(itertools.product(ids, repeat=len(names)), 40) if names else [()]
        for vals in combos:
            url = V + p
            for n, v in zip(names, vals):
                url = url.replace("{" + n + "}", str(v))
            qs = [""] if names else ["", "?q=ZQX", "?search=ZQX", "?query=ZQX"] + [f"?list_id={x}" for x in ids[:6]]
            for q in qs:
                r = requests.get(url + q, headers=h, timeout=30)
                seen += 1
                check(r.status_code != 429, f"no rate limit in the scan: {url + q}")
                body = r.content.upper()
                for m in MARKS:
                    if m.encode() in body:
                        found.setdefault(m, []).append(f"{p}{q} {r.status_code}")
    for url in (V + "/agent/events?since=0&limit=500", *extra):
        r = requests.get(url, headers=h, timeout=30)
        for m in MARKS:
            if m.encode() in r.content.upper():
                found.setdefault(m, []).append(url.replace(V, "") + " (events)")
    print(f"scan: {seen} answers, found {sorted(found)}", flush=True)
    return found


# ---------------------------------------------------------------- the gear (personal agent of a person without organisation)
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": AGENT_SCOPES})
check(r.status_code in (200, 201), f"a personal agent {r.status_code} {r.text[:120]}")
FA, FH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
j = lock(F, FA).json()
check(j["data_lock"]["areas"]["mail"] is True and j["data_lock"]["areas"]["contracts"] is False, f"defaults: private e-mails locked {j}")
check(set(j["always"]) >= {"journal", "mood", "health", "budget"}, f"the fixed areas {j['always']}")
check(lock(O, FA).status_code == 404 and lock(O, FA, "patch", json={"lists": []}).status_code == 404, "another person: 404")
check(lock(F, FA, "patch", json={"areas": {"health": False}}).status_code == 400, "health cannot be opened (400)")
check(lock(F, FA, "patch", json={"areas": {"journal": False}}).status_code == 400, "the journal cannot be opened (400)")
for bad in ({"areas": {"mail": "no"}}, {"areas": {"nope": True}}, {"lists": ["x"]}, {"tags": [""]}, {"tags": ["x" * 51]}, {"nope": 1}):
    check(lock(F, FA, "patch", json=bad).status_code == 400, f"invalid {bad} -> 400")
ag = requests.get(V + "/agent", headers=FH).json()
dl = ag.get("data_lock") or {}
check("mail" in dl.get("areas", []) and "journal" in dl.get("areas", []) and dl.get("list_ids") == [] and dl.get("tags_count") == 0,
      f"GET /api/v1/agent data_lock (defaults) {dl}")

# ---------------------------------------------------------------- data with the markers
P_OPEN = F.post(B + "/api/lists", json={"name": "Open work"}).json()["id"]
P_LOCK = F.post(B + "/api/lists", json={"name": "ZQXPROJ secret project"}).json()["id"]
P_CON = F.post(B + "/api/lists", json={"name": "ZQXCONTR my contracts"}).json()["id"]
dbx("UPDATE lists SET life='contracts' WHERE id=?", (P_CON,))
for lid in (P_OPEN, P_LOCK, P_CON):
    share(F, lid, FA)
T_OK = task(F, P_OPEN, "Plain visible task")
T_PROJ = task(F, P_LOCK, "ZQXPROJ the plan", due="2026-11-02")
T_MAIL = task(F, P_OPEN, "ZQXMAIL a private mail", due="2026-11-03")
dbx("UPDATE tasks SET tt_id=? WHERE id=?", ("mail:<zqx-1@example.com>", T_MAIL))
T_MSUB = task(F, P_OPEN, "ZQXMAIL subtask", parent_id=T_MAIL)
T_TAG = task(F, P_OPEN, "ZQXTAG tagged", tags=["Privat"])
T_CON = task(F, P_CON, "ZQXCONTR insurance", due="2026-11-04")
for tid, m in ((T_PROJ, "ZQXPROJ"), (T_MAIL, "ZQXMAIL"), (T_TAG, "ZQXTAG"), (T_CON, "ZQXCONTR")):
    attach(F, tid, m.lower() + ".txt", (m + " file content").encode())
CIDS = [comment(F, T_TAG, "ZQXTAG a comment"), comment(F, T_PROJ, "ZQXPROJ a comment")]
r = lock(F, FA, "patch", json={"lists": [P_LOCK], "tags": ["privat"], "areas": {"contracts": True}})
check(r.status_code == 200, f"lock saved {r.status_code} {r.text[:200]}")
j = r.json()["data_lock"]
check(j["lists"] == [{"id": P_LOCK, "name": "ZQXPROJ secret project"}] and j["tags"] == ["privat"] and j["areas"]["contracts"],
      f"the lock after a reload {j}")
check(lock(F, FA, "patch", json={"lists": [999999]}).status_code == 400, "a project the owner does not see: 400")
ag = requests.get(V + "/agent", headers=FH).json()
dl = ag.get("data_lock") or {}
check(dl.get("list_ids") == [P_LOCK] and dl.get("tags_count") == 1 and "contracts" in dl.get("areas", []), f"data_lock for the agent {dl}")
check("privat" not in str(dl).lower() and "ZQX" not in str(dl), "no tag or project name in data_lock")
# events after the lock: an assignment and a mention on every locked task (must never reach the agent)
for tid in (T_PROJ, T_MAIL, T_TAG, T_CON):
    F.patch(B + f"/api/tasks/{tid}", json={"assignee_id": FA})
    comment(F, tid, "@fridabot ZQX look")
F.patch(B + f"/api/tasks/{T_OK}", json={"assignee_id": FA})
ev = requests.get(V + "/agent/events?since=0&limit=500", headers=FH).json().get("data", [])
check(any(e["event"] == "data_lock_changed" for e in ev), "event data_lock_changed")
check(any(e["event"] == "assigned" and (e["data"].get("task") or {}).get("id") == T_OK for e in ev), "the visible task's event arrives")

IDS = [P_OPEN, P_LOCK, P_CON, T_OK, T_PROJ, T_MAIL, T_MSUB, T_TAG, T_CON] + [x for x in CIDS if x]
IDS += [r[0] for r in dbx("SELECT id FROM attachments WHERE task_id IN (?,?,?,?)", (T_PROJ, T_MAIL, T_TAG, T_CON))]
found = scan(FH, IDS)
check(not found, f"NOTHING locked in any agent answer: {found}")
r = requests.get(V + f"/tasks/{T_OK}", headers=FH)
check(r.status_code == 200, f"the plain task stays visible {r.status_code}")
for tid in (T_PROJ, T_MAIL, T_MSUB, T_TAG, T_CON):
    check(requests.get(V + f"/tasks/{tid}", headers=FH).status_code == 404, f"locked task {tid}: GET 404")
    check(requests.patch(V + f"/tasks/{tid}", headers=FH, json={"title": "x"}).status_code == 404, f"locked task {tid}: PATCH 404")
    r = requests.post(V + f"/tasks/{tid}/comments", headers=FH, json={"text": "x"})
    check(r.status_code in (400, 404) and "ZQX" not in r.text, f"locked task {tid}: no comment {r.status_code}")
for lid in (P_LOCK, P_CON):
    r = requests.post(V + "/tasks", headers=FH, json={"title": "x", "list_id": lid})
    check(r.status_code in (404, 400) and "ZQX" not in r.text, f"a new task in locked list {lid}: {r.status_code}")
check(F.get(B + f"/api/tasks/{T_PROJ}").ok, "the owner still sees everything in the app")

# ---------------------------------------------------------------- counter-check: opened -> every marker found again
r = lock(F, FA, "patch", json={"lists": [], "tags": [], "areas": {"mail": False, "contracts": False}})
check(r.status_code == 200, f"lock opened {r.status_code}")
comment(F, T_MAIL, "@fridabot ZQXMAIL now visible")
found = scan(FH, IDS)
for m in MARKS:
    check(m in found, f"counter-check: without the lock the scan finds {m}")
check(any("events" in x for x in found.get("ZQXMAIL", [])), f"counter-check: the event of the opened mail task arrives {found.get('ZQXMAIL')}")

# ---------------------------------------------------------------- a team agent (instance admin), a project of the admin
r = A.post(B + "/api/admin/agents", json={"username": "teambot", "display_name": "Team", "scopes": AGENT_SCOPES})
check(r.status_code in (200, 201), f"a team agent {r.status_code} {r.text[:100]}")
TA, TH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
check(lock(F, TA).status_code == 404, "a person without admin rights: 404 on a team agent")
L_T = A.post(B + "/api/lists", json={"name": "ZQXPROJ team project"}).json()["id"]
share(A, L_T, TA)
T_T = task(A, L_T, "ZQXPROJ org task")
check(lock(A, TA, "patch", json={"lists": [L_T]}).status_code == 200, "the admin locks a project of the team agent")
found = scan(TH, [L_T, T_T])
check(not found, f"team agent: nothing of the locked project {found}")
check(lock(A, TA, "patch", json={"lists": []}).status_code == 200, "the admin opens it")
found = scan(TH, [L_T, T_T])
check("ZQXPROJ" in found, "team agent counter-check: the opened project is visible again")
sys.exit(done("p2235_b_datalock"))
