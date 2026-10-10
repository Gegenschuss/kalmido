#!/usr/bin/env python3
"""2.36.2 API tests (package A, #1142): the organisation boundary through the central access layer.
 - former members (an organisation admin removes them, the instance admin sets the members anew, they leave themselves) see
   nothing of the organisation afterwards: lists, tasks, comments, attachments, calendars, address books, contacts, search,
   withdrawing an approval (404); a membership row left behind does not bring access back (second floor in the roles)
 - a person in two organisations sees both in "All workspaces" and loses only the one they leave
 - unassign: no News / agent event for somebody who cannot see the task any more; reaction event to an agent the same way
 - an agent token limited to lists: calendar / contact / export / search routes show nothing outside its lists
 - the layer itself (core/access.py acx_lists_sql) run directly against the database, so the check stays usable for 2.37
 - the nightly boundary check takes memberships across the boundary out and reports counts / ids only
 - route scan: every route with an <int:...> id answers a person outside with a refusal, never content
tenant-matrix: lists, tasks, comments, attachments, calendars, events, address books, contacts, search, approvals, agents
usage: p2362_a_api_test.py <datadir>      (a fresh container; the suite restarts it itself with other settings)"""
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CONTAINER = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]
MARK = "Qx9Alpha"  # in every name of the first organisation's objects
FEAT = "cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments,events,contacts,clients,workload,forms"
TS = "2026-10-01T00:00:00+00:00"


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
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def restart(extra, **env):
    e = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + extra, **env)
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def layer_lists(uid, write=False):
    """The list ids of account uid straight from the access layer (core/access.py acx_lists_sql), inside the container."""
    code = ("import json, sqlite3, os\nfrom kalmido.core.access import acx_lists_sql\n"
            "c = sqlite3.connect(os.environ['TASKS_DB'])\n"
            f"print(json.dumps(sorted(r[0] for r in c.execute('SELECT id FROM lists WHERE id IN ' + acx_lists_sql(write={write}, req=False), ({uid}, {uid})))))")
    p = subprocess.run(["docker", "exec", CONTAINER, "python", "-c", code], capture_output=True, text=True, timeout=60)
    try:
        return set(json.loads(p.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        print("layer_lists:", p.stdout[-300:], p.stderr[-600:], flush=True)
        return None


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin", "frank", "gina", "zed"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN, FRANK, GINA, ZED = (ids[k] for k in ("bob", "carol", "dave", "erin", "frank", "gina", "zed"))
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "calendar", "contacts", "export"],
                                         "username": "alphabot", "display_name": "Alpha bot"})
AGA, AGAH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
A.patch(B + f"/api/admin/agents/{AGA}", json={"org_id": ORG})

restart("-e KALMIDO_INSTANCE_MODE=workspaces")
S = {u: sess(u) for u in ("alice", "bob", "carol", "dave", "erin", "frank", "gina", "zed")}
A = S["alice"]
for s in S.values():
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "all"})
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
# Alpha: alice (admin), bob, dave, erin, frank, gina; Beta: carol (admin), erin (in both); zed: no organisation
check(A.patch(B + f"/api/admin/orgs/{ORG}", json={"admins": [1]}).ok, "setup: alice administers Alpha")
for u in (CAROL, ZED):
    r = A.delete(B + f"/api/orgs/{ORG}/members/{u}")
    check(r.ok, f"setup: {u} out of Alpha ({r.status_code} {r.text[:200]})")
A.patch(B + f"/api/admin/orgs/{BETA}", json={"members": [CAROL, ERIN], "admins": [CAROL]})
check({r[0] for r in dbx("SELECT user_id FROM org_members WHERE org_id=?", (ORG,))} >= {1, BOB, DAVE, ERIN, FRANK, GINA}, "setup: Alpha members")

# ---- Alpha's objects (alice), shared with bob, dave, erin, frank
LA = A.post(B + "/api/lists", json={"name": f"{MARK} list", "org_id": ORG}).json()["id"]
for u in (BOB, DAVE, ERIN, FRANK):
    check(A.put(B + f"/api/lists/{LA}/members", json={"user_id": u, "role": "edit"}).ok, f"setup: share {u}")
TA = A.post(B + "/api/tasks", json={"title": f"{MARK} task", "list_id": LA}).json()["id"]
A.post(B + f"/api/tasks/{TA}/comments", json={"body": f"{MARK} comment"})
AA = None
r = A.post(B + f"/api/tasks/{TA}/attachments", files={"file": (f"{MARK}.txt", b"secret\n", "text/plain")})
if r.ok:
    AA = dbx("SELECT id FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (TA,))[0][0]
KA = A.post(B + "/api/evcals", json={"name": f"{MARK} cal"}).json()
check(KA.get("org_id") == ORG, "setup: the calendar is Alpha's " + str(KA))
KA = KA["id"]
EA = A.post(B + "/api/events", json={"title": f"{MARK} event", "start": "2026-10-21T10:00", "end": "2026-10-21T11:00", "cal_id": KA}).json()["id"]
BA = A.post(B + "/api/books", json={"name": f"{MARK} book"}).json()["id"]
CTA = A.post(B + "/api/contacts", json={"book_id": BA, "given": MARK, "family": "Contact"}).json()["id"]
for u in (BOB, DAVE, ERIN, FRANK):
    A.put(B + f"/api/evcals/{KA}/members", json={"user_id": u, "role": "view"})
    A.put(B + f"/api/books/{BA}/members", json={"user_id": u, "role": "view"})
# an approval asked by dave (so dave could withdraw it while a member)
A.put(B + f"/api/lists/{LA}/members", json={"user_id": DAVE, "role": "admin"})
TAP = S["dave"].post(B + "/api/tasks", json={"title": f"{MARK} approval", "list_id": LA}).json()["id"]
r = S["dave"].post(B + f"/api/tasks/{TAP}/approval", json={"action": "request", "approver_id": 1})
check(r.ok, "setup: dave asks alice for an approval " + r.text[:120])

# ---- Beta's objects (carol), shared with erin
LB = S["carol"].post(B + "/api/lists", json={"name": "Beta list", "org_id": BETA}).json()["id"]
check(S["carol"].put(B + f"/api/lists/{LB}/members", json={"user_id": ERIN, "role": "edit"}).ok, "setup: Beta list shared with erin")
TB = S["carol"].post(B + "/api/tasks", json={"title": "Beta task", "list_id": LB}).json()["id"]


def lists_of(s):
    return {x["id"] for x in s.get(B + "/api/state").json()["lists"]}


def sees_nothing(u, what):
    s = S[u]
    st = s.get(B + "/api/state")
    check(st.ok and LA not in {x["id"] for x in st.json()["lists"]} and MARK not in st.text, f"{what}: the list is gone from the state")
    check(s.get(B + f"/api/tasks/{TA}").status_code == 404, f"{what}: task 404")
    check(s.get(B + f"/api/tasks/{TA}/timeline").status_code == 404, f"{what}: comments 404")
    if AA:
        check(s.get(B + f"/api/attachments/{AA}").status_code == 404, f"{what}: attachment 404")
    r = s.get(B + "/api/evcals")
    check(r.ok and MARK not in r.text, f"{what}: calendar gone")
    r = s.get(B + "/api/events", params={"from": "2026-10-01", "to": "2026-11-01"})
    check(MARK not in r.text, f"{what}: event gone ({r.status_code})")
    r = s.get(B + "/api/books")
    check(r.ok and MARK not in r.text, f"{what}: address book gone")
    check(s.get(B + f"/api/contacts/{CTA}").status_code == 404, f"{what}: contact 404")
    r = s.get(B + "/api/search/messages", params={"q": MARK})
    check(MARK not in r.text, f"{what}: search shows nothing ({r.status_code})")
    check(s.get(B + "/api/export.json").ok and MARK not in s.get(B + "/api/export.json").text, f"{what}: own export without Alpha content")
    check(s.post(B + f"/api/comments/0/decide", json={"decision": "approve"}).status_code == 404, f"{what}: unknown comment 404")


# ================================================================== before: they see it
for u in ("bob", "dave", "erin", "frank"):
    check(LA in lists_of(S[u]), f"before: {u} sees the Alpha list")
check(layer_lists(DAVE) is not None and LA in layer_lists(DAVE), "layer: dave's list scope has the Alpha list")

# ================================================================== double member: both in "All workspaces"
st = S["erin"].get(B + "/api/state").json()
check({LA, LB} <= {x["id"] for x in st["lists"]}, "double member: both organisations' lists in one answer")

# ================================================================== path 1: an organisation admin removes dave
r = A.delete(B + f"/api/orgs/{ORG}/members/{DAVE}")
check(r.ok, f"path 1: alice removes dave ({r.status_code} {r.text[:200]})")
sees_nothing("dave", "path 1 (removed by the organisation admin)")
r = S["dave"].post(B + f"/api/tasks/{TAP}/approval", json={"action": "cancel"})
check(r.status_code == 404 and MARK not in r.text, f"path 1: withdrawing the approval is 404 ({r.status_code})")
check(dbx("SELECT approval FROM tasks WHERE id=?", (TAP,))[0][0] == "pending", "path 1: the approval stays")
check(LA not in (layer_lists(DAVE) or {LA}), "layer: dave's list scope no longer has the Alpha list")

# a membership row left behind (as an older version could leave it) gives no access back: second floor
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,'edit','edit',0,?) ON CONFLICT DO NOTHING", (LA, DAVE, TS), write=True)
dbx("INSERT INTO ev_cal_members(cal_id,user_id,role,added_at) VALUES(?,?,'view',?) ON CONFLICT DO NOTHING", (KA, DAVE, TS), write=True)
dbx("INSERT INTO book_members(book_id,user_id,role,added_at) VALUES(?,?,'view',?) ON CONFLICT DO NOTHING", (BA, DAVE, TS), write=True)
sees_nothing("dave", "left-behind rows")
check(LA not in (layer_lists(DAVE) or {LA}) and LA not in (layer_lists(DAVE, True) or {LA}), "layer: left-behind row not in the scope (read / write)")
r = S["dave"].post(B + f"/api/tasks/{TAP}/approval", json={"action": "cancel"})
check(r.status_code == 404, f"left-behind rows: withdrawing the approval is 404 ({r.status_code})")
check(S["dave"].patch(B + f"/api/tasks/{TA}", json={"title": "x"}).status_code == 404, "left-behind rows: no change (404)")

# ================================================================== path 2: the instance admin sets Alpha's members anew (without bob)
mem = [r[0] for r in dbx("SELECT user_id FROM org_members WHERE org_id=?", (ORG,)) if r[0] != BOB]
r = A.patch(B + f"/api/admin/orgs/{ORG}", json={"members": mem})
check(r.ok, "path 2: the instance admin sets the members " + r.text[:100])
check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (LA, BOB)), "path 2: bob left the list (like org_leave)")
check(not dbx("SELECT 1 FROM ev_cal_members WHERE cal_id=? AND user_id=?", (KA, BOB)), "path 2: bob left the calendar")
sees_nothing("bob", "path 2 (members set by the instance admin)")

# ================================================================== path 3: frank leaves himself
check(S["frank"].delete(B + f"/api/orgs/{ORG}/members/{FRANK}").ok, "path 3: frank leaves Alpha")
sees_nothing("frank", "path 3 (left himself)")

# ================================================================== double member leaves Beta: keeps Alpha
check(S["erin"].delete(B + f"/api/orgs/{BETA}/members/{ERIN}").ok, "double member: erin leaves Beta")
ls = lists_of(S["erin"])
check(LA in ls and LB not in ls, "double member: Alpha stays, Beta is gone")
check(S["erin"].get(B + f"/api/tasks/{TB}").status_code == 404 and S["erin"].get(B + f"/api/tasks/{TA}").ok, "double member: task of Beta 404, of Alpha 200")
check(layer_lists(ERIN) is not None and LA in layer_lists(ERIN) and LB not in layer_lists(ERIN), "layer: erin's scope = Alpha only")

# ================================================================== unassign: no News / agent event for somebody who cannot see the task
LP = A.post(B + "/api/lists", json={"name": f"{MARK} part", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{LP}/members", json={"user_id": GINA, "role": "participant"}).ok, "setup: gina is a participant")
check(A.put(B + f"/api/lists/{LP}/members", json={"user_id": AGA, "role": "participant"}).ok, "setup: the agent is a participant")
TP = A.post(B + "/api/tasks", json={"title": f"{MARK} part task", "list_id": LP, "assignee_id": GINA}).json()["id"]
check(S["gina"].get(B + f"/api/tasks/{TP}").ok, "participant sees her assigned task")
n0 = dbx("SELECT COUNT(*) FROM notifications WHERE user_id=? AND task_id=?", (GINA, TP))[0][0]
check(A.patch(B + f"/api/tasks/{TP}", json={"assignee_id": None}).ok, "unassign gina")
time.sleep(0.5)
check(S["gina"].get(B + f"/api/tasks/{TP}").status_code == 404, "after unassign: the participant no longer sees the task")
check(dbx("SELECT COUNT(*) FROM notifications WHERE user_id=? AND task_id=?", (GINA, TP))[0][0] == n0, "unassign: no News entry for somebody who cannot see the task")
TQ = A.post(B + "/api/tasks", json={"title": f"{MARK} agent task", "list_id": LP, "assignee_id": AGA}).json()["id"]
e0 = dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=? AND event='unassigned'", (AGA,))[0][0]
check(A.patch(B + f"/api/tasks/{TQ}", json={"assignee_id": None}).ok, "unassign the agent")
ev = dbx("SELECT payload FROM agent_events WHERE agent_id=? AND event='unassigned' ORDER BY id", (AGA,))[e0:]
check(len(ev) == 1 and MARK not in ev[0][0] and '"visible": false' in ev[0][0].replace('"visible":false', '"visible": false'),
      "unassign: the agent that cannot see the task any more gets only the ids " + str(ev)[:300])

# ================================================================== reaction event to an agent that cannot see the task
LR = A.post(B + "/api/lists", json={"name": f"{MARK} gate", "org_id": ORG}).json()["id"]
TR = A.post(B + "/api/tasks", json={"title": f"{MARK} gate task", "list_id": LR}).json()["id"]
dbx("INSERT INTO comments(task_id,user_id,body,created_at,suggestion) VALUES(?,?,?,?,?)",
    (TR, AGA, "please integrate", TS, json.dumps({"kind": "integrate", "state": "open"})), write=True)
KG = dbx("SELECT id FROM comments WHERE task_id=? ORDER BY id DESC LIMIT 1", (TR,))[0][0]
e0 = dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=? AND event='reaction'", (AGA,))[0][0]
r = A.post(B + f"/api/comments/{KG}/decide", json={"decision": "approve"})
check(r.status_code in (200, 409), "reaction: alice decides " + r.text[:120])
check(dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=? AND event='reaction'", (AGA,))[0][0] == e0,
      "reaction: no event to an agent that is not in the list")

# ================================================================== an agent token limited to lists
LT = A.post(B + "/api/lists", json={"name": "Token list", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{LT}/members", json={"user_id": AGA, "role": "edit"})
A.put(B + f"/api/lists/{LA}/members", json={"user_id": AGA, "role": "edit"})
A.put(B + f"/api/evcals/{KA}/members", json={"user_id": AGA, "role": "view"})
A.put(B + f"/api/books/{BA}/members", json={"user_id": AGA, "role": "view"})
A.post(B + f"/api/tasks/{TA}/contacts", json={"contact_id": CTA, "kind": "about"})
check(MARK in requests.get(V + "/lists", headers=AGAH).text, "token: unlimited, the agent sees the Alpha list")
dbx("UPDATE api_tokens SET list_ids=? WHERE user_id=?", (str(LT), AGA), write=True)
r = requests.get(V + "/lists", headers=AGAH)
check(r.ok and f"{MARK} list" not in r.text, "token: limited, lists only the allowed one")
check(requests.get(V + f"/tasks/{TA}", headers=AGAH).status_code == 404, "token: limited, task outside 404")
for p in ("/search?q=" + MARK + "%20task", "/events?from=2026-10-01&to=2026-11-01", "/contacts?book_id=" + str(BA), f"/contacts/{CTA}"):
    r = requests.get(V + p, headers=AGAH)
    check(f"{MARK} task" not in r.text, f"token: limited, {p.split('?')[0]} shows no task outside its lists ({r.status_code})")
check(requests.get(V + "/export", headers=AGAH).status_code in (403, 404), "token: limited, no export")
dbx("UPDATE api_tokens SET list_ids='' WHERE user_id=?", (AGA,), write=True)

# ================================================================== route scan: every <int:id> route refuses a person outside
srcs = sorted(glob.glob(os.path.join(ROOT, "kalmido", "**", "*.py"), recursive=True)) + [os.path.join(ROOT, "app.py")]
RX = re.compile(r'@app\.(get|post|put|patch|delete)\("([^"]*<int:[^"]*)"')
routes = sorted({(m.group(1).upper(), m.group(2)) for p in srcs if os.path.exists(p) for m in RX.finditer(open(p, encoding="utf-8").read())})
check(len(routes) > 200, f"route scan: routes found ({len(routes)})")
# ids that exist and belong to alice / Alpha (lists, tasks, comments, calendars, events, books, contacts ...): the first rows
FOREIGN = {"lid": LA, "tid": TA, "cid": CTA, "eid": EA, "bid": BA, "aid": AA or 1}
Z = S["zed"]
tok = Z.post(B + "/api/me/tokens", json={"name": "scan", "scopes": ["read", "tasks:write", "comments", "calendar", "contacts", "export"]})
ZH = {"Authorization": "Bearer " + tok.json().get("token", "")} if tok.ok else None
# routes whose answer is not about a stored object (public pages with their own token, admin / instance routes answering 403 for
# everybody but admins, the caller's own resources looked up by position): a refusal other than 404 is fine there
OK_403 = ("/api/admin/", "/api/v1/admin/", "/api/orgs/", "/api/office/")
bad = []
for meth, path in routes:
    if path.startswith(("/pub/", "/dav", "/.well-known", "/api/hooks/", "/f/", "/forms/")):
        continue
    url = re.sub(r"<int:(\w+)>", lambda m: str(FOREIGN.get(m.group(1), FOREIGN.get(m.group(1)[:3], TA))), path)
    url = re.sub(r"<(?:string:|path:)?(\w+)>", "1", url)
    if path.startswith("/api/v1/"):
        if not ZH:
            continue
        r = requests.request(meth, B + url, headers=ZH, json={}, timeout=20)
    else:
        r = Z.request(meth, B + url, json={}, timeout=20)
    leak = MARK in r.text
    ok = r.status_code == 404 or (r.status_code in (400, 401, 403, 405, 409, 410, 413, 415, 422, 429) and not leak)
    if r.status_code == 403 and not path.startswith(OK_403) and meth == "GET":
        ok = False  # a GET of a stored object answers 404 (its existence is not revealed)
    if not ok or leak or r.status_code >= 500 or 200 <= r.status_code < 300 and leak:
        bad.append(f"{meth} {path} -> {r.status_code} {r.text[:80]!r}")
    elif 200 <= r.status_code < 300:
        bad.append(f"{meth} {path} -> {r.status_code} (answer to a person outside) {r.text[:60]!r}")
# refused before any lookup, without content: agent-only endpoint (role check) and token scope checks
SCAN_EXCEPT = {"GET /api/v1/agent/jobs/<int:jid>", "GET /api/v1/attachments/<int:aid>", "GET /api/v1/attachments/<int:aid>/text",
               "GET /api/v1/lists/<int:lid>/files/<file_id>"}
bad = [b for b in bad if " ".join(b.split(" ")[:2]) not in SCAN_EXCEPT]
check(not bad, f"route scan: every id route refuses a person outside ({len(bad)} of {len(routes)}):\n  " + "\n  ".join(bad[:80]))
check(S["alice"].get(B + f"/api/tasks/{TA}").ok and MARK in S["alice"].get(B + f"/api/tasks/{TA}").text, "route scan: alice's data is untouched")

# ================================================================== the nightly check repairs memberships across the boundary
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,'edit','edit',0,?) ON CONFLICT DO NOTHING", (LA, ZED, TS), write=True)
dbx("INSERT INTO ev_cal_members(cal_id,user_id,role,added_at) VALUES(?,?,'view',?) ON CONFLICT DO NOTHING", (KA, ZED, TS), write=True)
check(LA not in lists_of(Z), "left-behind row for zed: still no access")
restart("-e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_TENANT_CHECK=always", KALMIDO_ADMIN_ALERTS="1")
A = sess("alice")
items = []
for _ in range(30):
    items = [i for i in A.get(B + "/api/admin/alerts").json()["items"] if i["kind"] == "security" and "removed" in i["message"].lower()]
    if items:
        break
    time.sleep(0.5)
check(len(items) == 1 and MARK not in items[0]["message"], "repair: one security alert with counts only " + str([i["message"] for i in items]))
check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id IN (?,?)", (LA, DAVE, ZED)), "repair: the rows across the boundary are gone (lists)")
check(not dbx("SELECT 1 FROM ev_cal_members WHERE cal_id=? AND user_id IN (?,?)", (KA, DAVE, ZED)), "repair: (calendars)")
check(not dbx("SELECT 1 FROM book_members WHERE book_id=? AND user_id=?", (BA, DAVE)), "repair: (address books)")
check(dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (LA, ERIN)), "repair: members of the organisation stay")
check(A.get(B + "/api/admin/orgs").json()["boundary"]["violations"] == 0, "repair: the boundary is clean")

print(f"\n{OKS[0]} checks passed, {len(FAILS)} failed")
if FAILS:
    sys.exit(1)
print("ALL P2362 A API CHECKS PASSED")
