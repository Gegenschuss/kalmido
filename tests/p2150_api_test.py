#!/usr/bin/env python3
"""2.15.0 API tests (#479 "the complete agent API", #632).
Scopes:
 - fine scopes per token: read only by default, each write route needs its scope (403 + required_scope), a second scope
   from the body (a batch that deletes needs delete), "write" from before 2.15 = everything but admin-read
 - EVERY operation of the OpenAPI document: a read-only token gets 403 with exactly the declared scope, a token with that
   scope never fails for the scope (documentation = enforcement)
 - PATCH /api/me/tokens/{id} (scopes, allowed_ips, name), other people's tokens 404, admin-read only for admins
 - the address restriction (allowed_ips), the admin's limit for agents / personal tokens (scope_limit), GET /v1/me
   effective_scopes, the migration (old read tokens get attachments:read once, old agents keep read + write)
 - agents: default read + tasks:write + comments, admin / owner change them (never account / admin-read), a new token keeps
   them and can expire; the audit log records the scope a request needed
Approvals (agents only): deleting a list / a field, emptying the trash, a batch of 10+ tasks, moving an own list into another
folder, folders, sharing -> 202 + a waiting job (the same request again = the same job), Approve replays it as the agent (job
done, event with the result), Reject stops it (nothing changes), only people with the right approve, a forged replay header 401
Security: batch / move never reach lists the agent does not see or may not move out of
New routes: sections, move with position, batch, skip, trash, dependencies, custom fields, templates, attachments, comment
edit / delete, folders, members, filters, News, habits, timer, time entries, export, archive + delete a list
#632: a new user's inbox is named in their language (lang, else the admin's); every default name shows localized
MCP against the real server: tools/list shows only the tools the token may use; move_task works
Starts its OWN container (start.sh). usage: p2150_api_test.py <datadir>"""
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
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
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


class Api:
    def __init__(self, tok):
        self.tok = tok
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers={**self.h, **k.pop("headers", {})}, timeout=60, **k)

    def get(self, p, **k):
        return self.req("GET", p, **k)

    def post(self, p, js=None, **k):
        return self.req("POST", p, json=js, **k)

    def patch(self, p, js=None, **k):
        return self.req("PATCH", p, json=js, **k)

    def put(self, p, js=None, **k):
        return self.req("PUT", p, json=js, **k)

    def delete(self, p, **k):
        return self.req("DELETE", p, **k)


def tok(s, scopes, **k):
    r = s.post(B + "/api/me/tokens", json={"name": "t" + str(time.monotonic_ns())[-6:], "scopes": scopes, **k})
    assert r.status_code == 201, r.text
    return r.json()


def need(r, scope):
    try:
        return r.status_code == 403 and r.json()["error"].get("required_scope") == scope
    except (ValueError, KeyError):
        return False


def events(api, since):
    r = api.get("/agent/events", params={"since": since, "limit": 500})
    assert r.ok, r.text
    return r.json()["data"], r.json()["cursor"]


# a higher per-token rate: the scope sweep below sends two requests per operation of the OpenAPI document
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True,
                   env=dict(os.environ, EXTRA=(os.environ.get("EXTRA", "") + " -e KALMIDO_API_RATE=5000").strip()))
assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {"alice": 1}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")

# ================================================================== #632: the inbox in the new person's language
inbox = lambda uid: dbx("SELECT name FROM lists WHERE owner_id=? AND is_inbox=1", (uid,))[0][0]
check(inbox(ids["bob"]) == "Inbox", f"#632: admin language en -> the new user's inbox is 'Inbox' ({inbox(ids['bob'])})")
r = A.post(B + "/api/users", json={"username": "dora", "display_name": "Dora", "password": "password123", "lang": "de"})
check(r.ok and inbox(r.json()["id"]) == "Eingang", "#632: lang de -> 'Eingang'")
check(A.post(B + "/api/users", json={"username": "erik", "password": "password123", "lang": "xx"}).status_code == 400, "#632: unknown lang 400")
st = sess("dora").get(B + "/api/state").json()
check({"Inbox", "Eingang"} <= set(st["inbox_names"]), "state: inbox_names (default names, shown localized)")
dtok = tok(sess("dora"), ["read"])["token"]
check(next(l for l in Api(dtok).get("/lists").json()["data"] if l["is_inbox"])["name"] == "Eingang", "v1: a German user's inbox name in German")
check(next(l for l in A.get(B + "/api/state").json()["lists"] if l["is_inbox"])["name"] in ("Eingang", "Inbox"), "alice's inbox has a default name")

# ================================================================== lists + tasks for the rest
L = A.post(B + "/api/lists", json={"name": "Team", "kind": "project"}).json()["id"]      # alice; bob edit, the agent edit
PRIV = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]                 # alice only
CAR = Ca.post(B + "/api/lists", json={"name": "Carol"}).json()["id"]                   # carol only
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "edit"}).ok
T = [A.post(B + "/api/tasks", json={"title": f"T{i}", "list_id": L}).json()["id"] for i in range(14)]
TP = A.post(B + "/api/tasks", json={"title": "secret", "list_id": PRIV}).json()["id"]
TC = Ca.post(B + "/api/tasks", json={"title": "carol's", "list_id": CAR}).json()["id"]
r = A.post(B + f"/api/tasks/{T[0]}/attachments", files={"file": ("a.txt", b"hello", "text/plain")})
AT = r.json()["attachments"][0]["id"]

# ================================================================== scopes: personal tokens
R = tok(A, ["read"])
check(R["scopes"] == ["read"] and R["effective_scopes"] == ["read"] and R["allowed_ips"] == [], f"default read token {R}")
ro = Api(R["token"])
check(ro.get("/lists").ok and ro.get(f"/tasks/{T[0]}").ok, "read token reads")
r = ro.post("/tasks", {"title": "x", "list_id": L})
check(need(r, "tasks:write") and r.json()["error"]["message"] == "This token is read-only", f"read token: 403 tasks:write {r.text[:200]}")
check(need(ro.get(f"/attachments/{AT}"), "attachments:read"), "read token: no file download without attachments:read")
check(ro.get(f"/tasks/{T[0]}/attachments").ok, "read token: the file names come with read")
tw = Api(tok(A, ["read", "tasks:write"])["token"])
check(tw.post("/tasks", {"title": "via tw", "list_id": L}).status_code == 201, "tasks:write creates tasks")
r = tw.post(f"/tasks/{T[0]}/comments", {"body": "x"})
check(need(r, "comments") and "Comments" in r.json()["error"]["message"], f"tasks:write cannot comment {r.text[:200]}")
check(need(tw.delete(f"/tasks/{T[13]}"), "delete"), "tasks:write cannot delete")
check(need(tw.post("/lists", {"name": "x"}), "structure"), "tasks:write cannot create lists")
check(need(tw.post("/tasks/batch", {"ids": [T[13]], "action": "delete"}), "delete") or
      tw.post("/tasks/batch", {"ids": [T[13]], "action": "delete"}).status_code == 403, "batch delete needs delete (second scope from the body)")
check(tw.post("/tasks/batch", {"ids": [T[13]], "action": "complete"}).ok, "batch complete with tasks:write")
tw.post("/tasks/batch", {"ids": [T[13]], "action": "reopen"})
W = tok(A, ["read", "write"])
check(W["scopes"] == ["read", "write"] and "delete" in W["effective_scopes"] and "admin-read" not in W["effective_scopes"], f"legacy write token: {W}")
wa = Api(W["token"])
check(wa.post("/lists", {"name": "Legacy"}).status_code == 201 and wa.get(f"/attachments/{AT}").ok, "legacy write: everything")
check(A.post(B + "/api/me/tokens", json={"name": "x", "scopes": ["read", "nope"]}).status_code == 400, "unknown scope 400")
check(Bo.post(B + "/api/me/tokens", json={"name": "x", "scopes": ["read", "admin-read"]}).status_code == 403, "admin-read only for admins")
me = ro.get("/me").json()
check(me["token"]["effective_scopes"] == ["read"] and me["token"]["scopes"] == ["read"], f"v1 /me: effective_scopes {me['token']}")
# PATCH a token
r = A.patch(B + f"/api/me/tokens/{R['id']}", json={"scopes": ["read", "comments", "attachments:read"]})
check(r.ok and r.json()["effective_scopes"] == ["read", "comments", "attachments:read"], f"PATCH token scopes {r.text[:200]}")
check(ro.get(f"/attachments/{AT}").ok and ro.post(f"/tasks/{T[0]}/comments", {"body": "now I may"}).status_code == 201, "new scopes apply at once")
check(Bo.patch(B + f"/api/me/tokens/{R['id']}", json={"scopes": ["read"]}).status_code == 404, "someone else's token 404")
check(A.patch(B + f"/api/me/tokens/{R['id']}", json={"scopes": ["read"], "colour": 1}).status_code == 400, "PATCH token: unknown field 400")
# address restriction
check(A.patch(B + f"/api/me/tokens/{R['id']}", json={"allowed_ips": "nonsense"}).status_code == 400, "allowed_ips: invalid 400")
r = A.patch(B + f"/api/me/tokens/{R['id']}", json={"allowed_ips": "10.99.99.99"})
check(r.ok and r.json()["allowed_ips"] == ["10.99.99.99/32"], f"allowed_ips stored as networks {r.text[:150]}")
r = ro.get("/lists")
check(r.status_code == 403 and "address" in r.json()["error"]["message"], f"another address: 403 {r.text[:150]}")
A.patch(B + f"/api/me/tokens/{R['id']}", json={"allowed_ips": ["0.0.0.0/0", "::/0"]})
check(ro.get("/lists").ok, "allowed everywhere: ok again")
A.patch(B + f"/api/me/tokens/{R['id']}", json={"allowed_ips": ""})

# ================================================================== the OpenAPI document = the enforcement
spec = requests.get(V + "/openapi.json").json()
ALLOWED = {"read", "tasks:write", "comments", "structure", "delete", "attachments:read", "attachments:write", "time", "export", "account",
           "admin-read", "agent"}
ops = [(m.upper(), p, op["x-kalmido-scope"]) for p, ms in spec["paths"].items() for m, op in ms.items()]
check(all(sc in ALLOWED for _, _, sc in ops), "every operation: a known scope")
for pth in ("/lists/{id}/sections", "/sections/{id}", "/lists/{id}/sections/order", "/tasks/{id}/move", "/tasks/batch", "/tasks/{id}/skip",
            "/trash", "/tasks/{id}/restore", "/tasks/{id}/dependencies", "/tasks/{id}/dependencies/{blocker_id}", "/lists/{id}/fields",
            "/fields/{id}", "/templates", "/templates/{id}", "/templates/{id}/apply", "/comments/{id}", "/folders", "/folders/rename",
            "/folders/delete", "/lists/{id}/members", "/lists/{id}/members/{user_id}", "/filters", "/filters/{id}", "/news",
            "/news/read", "/habits/{id}", "/time/timer", "/time/entries/{id}", "/export"):
    check(pth in spec["paths"], f"OpenAPI: {pth}")
check("delete" in spec["paths"]["/lists/{id}"] and "post" in spec["paths"]["/tasks/{id}/attachments"]
      and "get" in spec["paths"]["/tasks/{id}/attachments"] and "get" in spec["paths"]["/habits"], "OpenAPI: added methods kept the existing ones")
full = Api(tok(A, ["read", "write"])["token"])
bad_ro, bad_full = [], []
for m, p, sc in ops:
    if sc in ("read", "agent") or p.startswith("/admin"):
        continue
    url = re.sub(r"\{[^}]+\}", "987654", p)
    r = requests.request(m, V + url, headers=ro.h, json={} if m in ("POST", "PUT", "PATCH") else None, timeout=30)
    if not need(r, sc) and not (sc == "comments" and r.status_code != 403) and not (sc == "attachments:read" and r.status_code != 403):
        bad_ro.append((m, p, sc, r.status_code, r.text[:80]))
    r = requests.request(m, V + url, headers=full.h, json={} if m in ("POST", "PUT", "PATCH") else None, timeout=30)
    if r.status_code == 403 and (r.json().get("error") or {}).get("required_scope"):
        bad_full.append((m, p, sc, r.text[:80]))
check(not bad_ro, f"every write operation refuses a token without its scope with exactly that scope: {bad_ro[:6]}")
check(not bad_full, f"a token with the scope is never refused for the scope: {bad_full[:6]}")
check(spec["paths"]["/attachments/{id}"]["get"]["x-kalmido-scope"] == "attachments:read"
      and spec["paths"]["/tasks/{id}"]["delete"]["x-kalmido-scope"] == "delete"
      and spec["paths"]["/tasks/{id}/comments"]["post"]["x-kalmido-scope"] == "comments"
      and spec["paths"]["/agent/status"]["put"]["x-kalmido-scope"] == "agent", "OpenAPI: the scopes of some known operations")

# ================================================================== agents: default scopes, changes, token expiry
r = A.post(B + "/api/admin/agents", json={"username": "claude", "display_name": "Claude"})
AG, cl_tok = r.json()["id"], r.json()["token"]
cl = Api(cl_tok)
check(r.json()["scopes"] == ["comments", "read", "tasks:write"] and r.json()["effective_scopes"] == ["read", "tasks:write", "comments"],
      f"new agent: read + tasks:write + comments {r.json().get('scopes')}")
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok
check(cl.post("/tasks", {"title": "by agent", "list_id": L}).status_code == 201 and cl.post(f"/tasks/{T[1]}/comments", {"body": "hi"}).status_code == 201,
      "agent (default): tasks + comments")
check(need(cl.post("/lists", {"name": "x"}), "structure") and need(cl.delete(f"/tasks/{T[13]}"), "delete")
      and need(cl.get(f"/attachments/{AT}"), "attachments:read"), "agent (default): no structure, delete, files")
check(cl.put("/agent/status", {"status": "working", "text": "x"}).ok, "agent channel needs no scope")
check(A.patch(B + f"/api/admin/agents/{AG}", json={"scopes": ["read", "account"]}).status_code == 400, "agents never get account")
check(A.patch(B + f"/api/admin/agents/{AG}", json={"scopes": ["read", "admin-read"]}).status_code == 400, "agents never get admin-read")
r = A.patch(B + f"/api/admin/agents/{AG}", json={"scopes": ["read", "tasks:write", "comments", "structure", "delete", "attachments:read"]})
check(r.ok and "structure" in r.json()["effective_scopes"], f"admin widens the agent's scopes {r.text[:200]}")
check(cl.post("/lists", {"name": "Agent list"}).status_code == 201 and cl.get(f"/attachments/{AT}").ok, "the running token gets them at once")
r = A.post(B + f"/api/admin/agents/{AG}/token", json={"expires_days": 30})
cl = Api(r.json()["token"])
ag = next(a for a in A.get(B + "/api/admin/agents").json()["agents"] if a["id"] == AG)
check(ag["tokens"][0]["expires_at"] and "structure" in ag["tokens"][0]["effective_scopes"], f"new agent token: expiry + the agent's scopes {ag['tokens'][0]}")
check(cl.get("/me").json()["token"]["effective_scopes"] == ["read", "tasks:write", "comments", "structure", "delete", "attachments:read"],
      "agent /me effective_scopes")
# personal agent: its owner sets the scopes
A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2})
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot", "scopes": ["read", "tasks:write"]})
PA = r.json()["id"]
check(r.status_code == 201 and r.json()["effective_scopes"] == ["read", "tasks:write"], f"personal agent created with scopes {r.text[:200]}")
r = Bo.patch(B + f"/api/my/agents/{PA}", json={"scopes": ["read", "tasks:write", "comments", "time"], "allowed_ips": "0.0.0.0/0"})
check(r.ok and r.json()["effective_scopes"] == ["read", "tasks:write", "comments", "time"] and r.json()["allowed_ips"] == ["0.0.0.0/0"],
      "owner changes the personal agent's scopes + addresses")
check(Ca.patch(B + f"/api/my/agents/{PA}", json={"scopes": ["read"]}).status_code == 404, "someone else cannot")
check(Bo.patch(B + f"/api/my/agents/{PA}", json={"scopes": ["read", "account"]}).status_code == 400, "owner cannot give account")
# the admin's limit
p = A.put(B + "/api/admin/agent-policy", json={"scope_limit": {"agents": ["read", "tasks:write"], "tokens": ["read", "tasks:write", "comments"]}})
check(p.ok and p.json()["scope_limit"]["agents"] == ["read", "tasks:write"], f"admin limit stored {p.text[:200]}")
check(need(cl.post(f"/tasks/{T[1]}/comments", {"body": "x"}), "comments"), "agent over the limit: comments refused")
check(need(wa.post("/lists", {"name": "x"}), "structure"), "legacy write token over the limit: structure refused")
check(wa.get("/me").json()["token"]["effective_scopes"] == ["read", "tasks:write", "comments"], "limit shows in effective_scopes")
check(Bo.put(B + "/api/admin/agent-policy", json={"scope_limit": {"agents": []}}).status_code == 403, "only admins set the limit")
check(A.put(B + "/api/admin/agent-policy", json={"scope_limit": {"agents": ["read", "nope"]}}).status_code == 400, "limit: unknown scope 400")
A.put(B + "/api/admin/agent-policy", json={"scope_limit": {"agents": ["read", "tasks:write", "comments", "structure", "delete", "attachments:read",
                                                                  "attachments:write", "time", "export"],
                                                       "tokens": ["read", "tasks:write", "comments", "structure", "delete", "attachments:read",
                                                                  "attachments:write", "time", "export", "account"]}})
check(cl.post(f"/tasks/{T[1]}/comments", {"body": "back"}).status_code == 201 and wa.post("/lists", {"name": "back"}).status_code == 201,
      "limit lifted: everything back")
check(A.get(B + "/api/admin/agent-policy").json()["scope_limit"]["agents"][-1] == "export", "full limit = all")

# ================================================================== approvals
ev0 = cl.get("/agent").json()["cursor"]
AL = cl.post("/lists", {"name": "Agent scratch"}).json()["id"]
check(cl.patch(f"/lists/{AL}", {"archived": True}).ok, "agent archives its own list (no approval)")
r = cl.delete(f"/lists/{AL}")
check(r.status_code == 202 and r.json()["approval_required"] and r.json()["job"]["state"] == "waiting" and r.json()["job"]["approval"],
      f"agent deletes a list: 202 + waiting job {r.text[:200]}")
J = r.json()["job"]["id"]
check(cl.delete(f"/lists/{AL}").json()["job"]["id"] == J, "the same request again: the same job")
check(cl.patch(f"/agent/jobs/{J}", {"title": "Add a comment"}).status_code == 409 and "Agent scratch" in dbx("SELECT title FROM agent_jobs WHERE id=?", (J,))[0][0],
      "the agent cannot change the title of its waiting request")
jobs = A.get(B + "/api/agents/jobs").json()["jobs"]
jj = next(j for j in jobs if j["id"] == J)
check(jj["can_act"] and "Agent scratch" in jj["title"] and jj["approval"], f"admin sees it, may approve: {jj['title']}")
check(not any(j["id"] == J for j in Ca.get(B + "/api/agents/jobs").json()["jobs"]), "carol does not see it")
check(Ca.post(B + f"/api/agents/jobs/{J}/action", json={"action": "approve"}).status_code in (403, 404), "carol cannot approve")
check(dbx("SELECT COUNT(*) FROM lists WHERE id=?", (AL,))[0][0] == 1, "nothing happened yet")
r = A.post(B + f"/api/agents/jobs/{J}/action", json={"action": "approve"})
check(r.ok and r.json()["state"] == "done", f"approve: replayed, job done {r.text[:300]}")
check(dbx("SELECT COUNT(*) FROM lists WHERE id=?", (AL,))[0][0] == 0, "approved: the list is gone")
check(A.post(B + f"/api/agents/jobs/{J}/action", json={"action": "approve"}).status_code == 409, "approve twice: 409")
evs, _ = events(cl, ev0)
je = [e for e in evs if e["event"] == "job" and e["data"]["job"]["id"] == J]
check(je and je[-1]["data"]["result"]["status"] == 204 and je[-1]["data"]["action"] == "approve", f"agent gets the result as a job event {je[-1:]}")
# reject: a batch of 12
r = cl.post("/tasks/batch", {"ids": T[:12], "action": "complete"})
check(r.status_code == 202 and "12" in r.json()["job"]["title"], f"agent batch of 12: approval {r.text[:200]}")
J2 = r.json()["job"]["id"]
jt = dbx("SELECT user_id FROM agent_jobs WHERE id=?", (J2,))[0][0]
check(jt == 1, "a team agent's batch: the list owner approves")
check(A.post(B + f"/api/agents/jobs/{J2}/action", json={"action": "reject"}).json()["state"] == "stopped", "reject: stopped")
r = cl.patch(f"/agent/jobs/{J2}", {"state": "waiting", "title": "Please confirm: harmless"})
check(r.status_code == 409 and dbx("SELECT state, title FROM agent_jobs WHERE id=?", (J2,))[0][0] == "stopped", "the agent cannot revive or rename an approval job (409)")
check(A.post(B + f"/api/agents/jobs/{J2}/action", json={"action": "approve"}).status_code == 409, "a rejected request never runs")
check(dbx(f"SELECT COUNT(*) FROM tasks WHERE id IN ({','.join(map(str, T[:12]))}) AND status=0")[0][0] == 12, "rejected: nothing changed")
evs, _ = events(cl, ev0)
check(any(e["event"] == "job" and e["data"]["job"]["id"] == J2 and e["data"]["action"] == "reject" for e in evs), "agent hears of the rejection")
check(cl.post("/tasks/batch", {"ids": T[:3], "action": "complete"}).json()["count"] == 3, "a batch of 3: at once")
cl.post("/tasks/batch", {"ids": T[:3], "action": "reopen"})
r = cl.post("/tasks/batch", {"ids": T[:5], "action": "complete"})
check(r.status_code == 202, f"batches within 10 minutes count together (3 + 3 + 5 >= 10): approval {r.status_code}")
A.post(B + f"/api/agents/jobs/{r.json()['job']['id']}/action", json={"action": "reject"})
# a person's batch: never waits
check(full.post("/tasks/batch", {"ids": T[:12], "action": "complete"}).json()["count"] == 12, "a person's batch of 12: at once")
full.post("/tasks/batch", {"ids": T[:12], "action": "reopen"})
# the personal agent: its owner approves
pa_tok = Api(Bo.post(B + f"/api/my/agents/{PA}/token").json()["token"])
Bo.patch(B + f"/api/my/agents/{PA}", json={"scopes": ["read", "tasks:write", "structure"]})
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": PA, "role": "edit"}).status_code in (200, 403, 404)
PL = pa_tok.post("/lists", {"name": "Bot list"}).json()["id"]
pa_tok.patch(f"/lists/{PL}", {"folder": ""})
r = pa_tok.patch(f"/lists/{PL}", {"folder": "Work"})
check(r.status_code == 202 and dbx("SELECT user_id FROM agent_jobs WHERE id=?", (r.json()["job"]["id"],))[0][0] == ids["bob"],
      "personal agent moves its list into a folder: its owner approves")
r = Bo.post(B + f"/api/agents/jobs/{r.json()['job']['id']}/action", json={"action": "approve"})
check(r.ok and r.json()["state"] == "done" and dbx("SELECT folder FROM lists WHERE id=?", (PL,))[0][0] == "Work", f"owner approves: moved {r.text[:200]}")
check(pa_tok.patch(f"/lists/{PL}", {"name": "Bot list 2"}).ok, "renaming its list: no approval")
# a failing replay ends failed
r = cl.post("/tasks/batch", {"ids": T[:10], "action": "delete"})
check(r.status_code == 202, "agent batch delete of 10: approval")
J3 = r.json()["job"]["id"]
A.patch(B + f"/api/admin/agents/{AG}", json={"enabled": False})
r = A.post(B + f"/api/agents/jobs/{J3}/action", json={"action": "approve"})
check(r.ok and r.json()["state"] == "failed" and "paused" in r.json()["log"], f"agent paused meanwhile: the job fails {r.text[:300]}")
check(dbx(f"SELECT COUNT(*) FROM tasks WHERE id IN ({','.join(map(str, T[:10]))}) AND deleted_at IS NULL")[0][0] == 10, "failed: nothing deleted")
A.patch(B + f"/api/admin/agents/{AG}", json={"enabled": True})
# an agent limited to addresses: the approved request still runs (the address was checked when it was stored)
A.patch(B + f"/api/admin/agents/{AG}", json={"allowed_ips": "0.0.0.0/0"})
dbx("UPDATE api_tokens SET allowed_ips='172.16.0.0/12,0.0.0.0/0' WHERE user_id=?", (AG,))
IL = cl.post("/lists", {"name": "IP list"}).json()["id"]
cl.patch(f"/lists/{IL}", {"archived": True})
r = cl.delete(f"/lists/{IL}")
dbx("UPDATE api_tokens SET allowed_ips='203.0.113.7' WHERE user_id=?", (AG,))
r = A.post(B + f"/api/agents/jobs/{r.json()['job']['id']}/action", json={"action": "approve"})
check(r.ok and r.json()["state"] == "done", f"approval replay ignores the address restriction {r.text[:200]}")
A.patch(B + f"/api/admin/agents/{AG}", json={"allowed_ips": ""})
# forged replay
r = requests.delete(V + f"/lists/{L}", headers={"X-Kalmido-Replay": f"{J}:" + "0" * 64})
check(r.status_code == 401, f"forged replay header: 401 ({r.status_code})")
r = requests.delete(V + f"/lists/{L}", headers={**cl.h, "X-Kalmido-Replay": "1:abc"})
check(r.status_code == 401, "a replay header beside a real token: 401")
check(dbx("SELECT COUNT(*) FROM lists WHERE id=?", (L,))[0][0] == 1, "the team list is still there")
# group sharing waits
GID = A.post(B + "/api/admin/groups", json={"name": "Office", "members": [ids["bob"]]}).json()["id"]
A.patch(B + f"/api/admin/agents/{AG}", json={"scopes": ["read", "tasks:write", "comments", "structure", "delete", "attachments:read",
                                                         "attachments:write", "time", "export"]})
GL = cl.post("/lists", {"name": "Agent shares"}).json()["id"]
r = cl.put(f"/lists/{GL}/groups/{GID}", {"role": "view"})
check(r.status_code == 202, f"agent shares with a group: approval {r.status_code}")
r = cl.put(f"/lists/{GL}/members/{ids['carol']}", {"role": "view"})
check(r.status_code == 202, f"agent shares with a person: approval {r.status_code}")
r = cl.post("/folders/rename", {"old": "A", "new": "B"})
check(r.status_code == 202, "agent renames a folder: approval")
r = cl.req("DELETE", "/trash")
check(r.status_code == 202 and "trash" in r.json()["job"]["title"].lower(), "agent empties the trash: approval")
# audit log: the scope a request needed
time.sleep(1.5)
rows = A.get(B + f"/api/admin/agents/{AG}/audit", params={"limit": 200}).json()["data"]
check(any(x.get("scope") == "structure" for x in rows) and any(x.get("scope") == "agent" for x in rows), "audit rows carry the scope")

# ================================================================== security: batch / move into foreign lists
r = cl.post("/tasks/batch", {"ids": [TP, TC], "action": "update", "changes": {"title": "pwned"}})
check(r.ok and r.json()["count"] == 0 and dbx("SELECT title FROM tasks WHERE id=?", (TC,))[0][0] == "carol's", "batch: invisible tasks untouched")
r = cl.post("/tasks/batch", {"ids": [T[2]], "action": "update", "changes": {"list_id": CAR}})
check(r.json()["count"] == 0 and dbx("SELECT list_id FROM tasks WHERE id=?", (T[2],))[0][0] == L, f"batch: no move into a list it does not see {r.text[:200]}")
r = cl.post(f"/tasks/{T[2]}/move", {"list_id": CAR})
check(r.status_code in (403, 404) and dbx("SELECT list_id FROM tasks WHERE id=?", (T[2],))[0][0] == L, "move: no list it does not see")
r = cl.post(f"/tasks/{T[2]}/move", {"list_id": GL})
check(r.status_code == 403 and dbx("SELECT list_id FROM tasks WHERE id=?", (T[2],))[0][0] == L, f"move: not out of someone else's shared list {r.status_code}")
check(cl.post(f"/tasks/{TP}/move", {"position": "top"}).status_code == 404, "move: a hidden task 404")
check(cl.post(f"/tasks/{TC}/dependencies", {"blocked_by": T[1]}).status_code == 404, "dependency on a hidden task 404")
check(cl.post(f"/tasks/{T[1]}/dependencies", {"blocked_by": TC}).status_code == 404, "a hidden blocker 404")
check(cl.req("PATCH", f"/comments/{dbx('SELECT id FROM comments WHERE user_id=1 LIMIT 1')[0][0]}", json={"body": "x"}).status_code == 403,
      "someone else's comment cannot be edited")

# ================================================================== new routes (as alice, legacy token)
fa = full
# sections
r = fa.post(f"/lists/{L}/sections", {"name": "Doing"})
S1 = r.json()["id"]
S0 = fa.post(f"/lists/{L}/sections", {"name": "Todo", "before_id": S1}).json()["id"]
check([x["name"] for x in fa.get(f"/lists/{L}/sections").json()["data"]] == ["Todo", "Doing"], "sections: create, before_id")
check(fa.patch(f"/sections/{S1}", {"name": "In progress"}).json()["name"] == "In progress", "section renamed")
r = fa.put(f"/lists/{L}/sections/order", {"ids": [S1, S0]})
check([x["id"] for x in r.json()["data"]] == [S1, S0], "sections reordered")
check(fa.put(f"/lists/{L}/sections/order", {"ids": [S1]}).status_code == 400, "sections order: every section once")
# move with position
fa.post(f"/tasks/{T[3]}/move", {"section_id": S0, "position": "top"})
fa.post(f"/tasks/{T[4]}/move", {"section_id": S0, "position": "bottom"})
fa.post(f"/tasks/{T[5]}/move", {"section_id": S0, "before_id": T[4]})
order = [r[0] for r in dbx("SELECT id FROM tasks WHERE section_id=? ORDER BY sort", (S0,))]
check(order == [T[3], T[5], T[4]], f"move: top / bottom / before_id {order}")
fa.post(f"/tasks/{T[6]}/move", {"section_id": S0, "after_id": T[3]})
order = [r[0] for r in dbx("SELECT id FROM tasks WHERE section_id=? ORDER BY sort", (S0,))]
check(order == [T[3], T[6], T[5], T[4]], f"move: after_id {order}")
r = fa.post(f"/tasks/{T[6]}/move", {"list_id": PRIV, "position": "top"})
check(r.ok and r.json()["list_id"] == PRIV and r.json()["section_id"] is None, "move into another list (section cleared)")
fa.post(f"/tasks/{T[6]}/move", {"list_id": L})
check(fa.post(f"/tasks/{T[6]}/move", {"before_id": T[3], "after_id": T[4]}).status_code == 400, "move: one place only")
r = fa.post(f"/tasks/{T[7]}/move", {"parent_id": T[8]})
check(r.ok and r.json()["parent_id"] == T[8], "move under a parent")
fa.post(f"/tasks/{T[7]}/move", {"parent_id": None})
check(fa.delete(f"/sections/{S1}").json()["ok"], "section deleted (tasks stay)")
# batch
r = fa.post("/tasks/batch", {"ids": [T[9], T[10]], "action": "update", "changes": {"priority": "high", "tags": ["x"]}})
check(r.json()["count"] == 2 and fa.get(f"/tasks/{T[9]}").json()["priority"] == "high", "batch update")
check(fa.post("/tasks/batch", {"ids": [T[9]], "action": "wont_do"}).ok and fa.get(f"/tasks/{T[9]}").json()["status"] == "wont_do", "batch won't do")
check(fa.post("/tasks/batch", {"ids": [T[9]], "action": "nope"}).status_code == 400 and fa.post("/tasks/batch", {"ids": [], "action": "complete"}).status_code == 400,
      "batch: validation")
r = fa.post("/tasks/batch", {"ids": [T[9], 99999], "action": "delete"})
check(r.json()["count"] == 1 and r.json()["errors"], "batch delete + unknown id reported")
# trash
tr_ = fa.get("/trash").json()["data"]
check(any(t["id"] == T[9] and t["deleted"] for t in tr_), "trash lists it")
check(fa.post(f"/tasks/{T[9]}/restore").json()["deleted"] is False, "restore")
check(fa.post(f"/tasks/{T[9]}/restore").status_code == 409, "restore twice: 409")
fa.delete(f"/tasks/{T[9]}")
r = fa.req("DELETE", "/trash")
check(r.ok and r.json()["deleted"] >= 1 and not fa.get("/trash").json()["data"], f"empty the trash {r.text[:100]}")
# skip
RT = fa.post("/tasks", {"title": "weekly", "list_id": L, "due": "2030-01-07", "repeat": "FREQ=WEEKLY"}).json()["id"]
r = fa.post(f"/tasks/{RT}/skip")
check(r.ok and r.json()["due"] == "2030-01-14" and r.json()["next_due"] == "2030-01-14", "skip an occurrence")
check(fa.post(f"/tasks/{T[10]}/skip").status_code == 400, "skip: not repeating 400")
# dependencies
r = fa.post(f"/tasks/{T[10]}/dependencies", {"blocked_by": T[11]})
check(r.status_code == 201 and r.json()["blocked_by"][0]["id"] == T[11], "dependency added")
check(fa.get(f"/tasks/{T[11]}/dependencies").json()["blocking"][0]["id"] == T[10], "dependency seen from the blocker")
check(fa.post(f"/tasks/{T[11]}/dependencies", {"blocked_by": T[10]}).status_code == 400, "no cycle")
check(not fa.delete(f"/tasks/{T[10]}/dependencies/{T[11]}").json()["blocked_by"], "dependency removed")
# custom fields
r = fa.post(f"/lists/{L}/fields", {"name": "Effort", "type": "number"})
F = r.json()["id"]
check(r.status_code == 201 and fa.get(f"/lists/{L}/fields").json()["data"][0]["name"] == "Effort", "field created")
check(fa.patch(f"/fields/{F}", {"name": "Effort (h)"}).json()["name"] == "Effort (h)", "field renamed")
fa.patch(f"/tasks/{T[10]}", {"fields": {str(F): "3"}})
check(str(F) in fa.get(f"/tasks/{T[10]}").json()["fields"], "field value")
check(fa.delete(f"/fields/{F}").json()["values"] == 1, "field deleted with its value")
check(fa.post(f"/lists/{PRIV}/fields", {"name": "x", "type": "text"}).status_code == 409, "fields: project lists only")
# templates
r = fa.post("/templates", {"task_id": T[8], "name": "Tpl"})
TPL = r.json()["id"]
check(r.status_code == 201 and fa.get("/templates").json()["data"][0]["name"] == "Tpl", "template from a task")
check(fa.patch(f"/templates/{TPL}", {"name": "Tpl 2"}).json()["name"] == "Tpl 2", "template renamed")
r = fa.post(f"/templates/{TPL}/apply", {"list_id": L})
check(r.status_code == 201 and dbx("SELECT COUNT(*) FROM tasks WHERE title='T8' AND list_id=?", (L,))[0][0] == 2, f"template applied {r.text[:150]}")
check(fa.delete(f"/templates/{TPL}").status_code == 204 and not fa.get("/templates").json()["data"], "template deleted")
check(Api(tok(Bo, ["read", "write"])["token"]).delete(f"/templates/{TPL}").status_code == 404, "someone else's template 404")
# attachments
r = fa.req("POST", f"/tasks/{T[10]}/attachments", files=[("file", ("n.txt", b"note", "text/plain")), ("file", ("m.txt", b"more", "text/plain"))])
check(r.status_code == 201 and [x["name"] for x in r.json()["data"]] == ["n.txt", "m.txt"], f"upload two files {r.text[:150]}")
AT2 = r.json()["data"][0]["id"]
check(fa.get(f"/attachments/{AT2}").content == b"note", "uploaded file readable")
check(fa.req("POST", f"/tasks/{T[10]}/attachments", files=[("file", ("e.txt", b"", "text/plain"))]).status_code == 400, "empty file refused")
check(fa.req("POST", f"/tasks/{T[10]}/attachments", files=[("other", ("e.txt", b"x", "text/plain"))]).status_code == 400, "unknown form field")
check(need(tw.req("POST", f"/tasks/{T[10]}/attachments", files=[("file", ("n.txt", b"x"))]), "attachments:write"), "upload needs attachments:write")
check(fa.delete(f"/attachments/{AT2}").status_code == 204 and fa.get(f"/attachments/{AT2}").status_code == 404, "file removed")
# comments
C = fa.post(f"/tasks/{T[10]}/comments", {"body": "first"}).json()["id"]
check(fa.patch(f"/comments/{C}", {"body": "edited"}).json()["body"] == "edited", "comment edited")
check(Api(tok(Bo, ["read", "write"])["token"]).patch(f"/comments/{C}", {"body": "x"}).status_code == 403, "only the author edits")
check(fa.delete(f"/comments/{C}").status_code == 204, "comment deleted")
# folders
fa.patch(f"/lists/{PRIV}", {"folder": "Home"})
check(any(f["path"] == "Home" and f["lists"] == 1 for f in fa.get("/folders").json()["data"]), "folders listed")
r = fa.post("/folders/rename", {"old": "Home", "new": "Private stuff"})
check(r.ok and dbx("SELECT folder FROM lists WHERE id=?", (PRIV,))[0][0] == "Private stuff", "folder renamed (person: at once)")
check(fa.post("/folders/delete", {"name": "Private stuff"}).ok and dbx("SELECT folder FROM lists WHERE id=?", (PRIV,))[0][0] == "", "folder removed")
# members
r = fa.put(f"/lists/{PRIV}/members/{ids['carol']}", {"role": "view"})
check(r.ok and any(m["user_id"] == ids["carol"] and m["role"] == "view" for m in r.json()["data"]), "shared with carol (view)")
check(fa.get(f"/lists/{PRIV}/members").json()["data"][0]["role"] == "owner", "members: the owner first")
check(fa.delete(f"/lists/{PRIV}/members/{ids['carol']}").status_code == 204 and len(fa.get(f"/lists/{PRIV}/members").json()["data"]) == 1, "unshared")
check(fa.put(f"/lists/{PRIV}/members/{ids['carol']}", {"role": "boss"}).status_code == 400, "bad role 400")
# filters
r = fa.post("/filters", {"name": "Urgent", "rules": {"priority": [5]}})
FI = r.json()["id"]
check(r.status_code == 201 and fa.get("/filters").json()["data"][0]["rules"] == {"priority": [5]}, "filter saved")
check(fa.patch(f"/filters/{FI}", {"name": "Hot"}).json()["name"] == "Hot", "filter renamed")
check(fa.delete(f"/filters/{FI}").status_code == 204 and not fa.get("/filters").json()["data"], "filter deleted")
# News
bt = Api(tok(Bo, ["read", "write"])["token"])
A.post(B + f"/api/tasks/{T[10]}/comments", json={"body": f"<@{ids['bob']}> look"})
nw = bt.get("/news").json()
check(nw["unread"] >= 1 and nw["data"], "News listed")
check(bt.post("/news/read", {"all": True}).json()["unread"] == 0, "News read")
# habits
r = fa.post("/habits", {"name": "Walk", "goal": 1})
HB = r.json()["id"]
check(r.status_code == 201 and r.json()["name"] == "Walk", "habit created")
check(fa.patch(f"/habits/{HB}", {"name": "Run", "archived": True}).json()["archived"] is True, "habit changed")
check(fa.delete(f"/habits/{HB}").status_code == 204, "habit deleted")
# timer + entries (project list L)
r = fa.post("/time/timer", {"task_id": T[10], "note": "work"})
check(r.status_code == 201 and r.json()["timer"]["task_id"] == T[10], f"timer started {r.text[:150]}")
check(fa.get("/time/timer").json()["timer"]["running"], "timer running")
time.sleep(1.2)
r = fa.delete("/time/timer")
EID = (r.json().get("entry") or {}).get("id")
check(r.ok and EID, f"timer stopped {r.text[:150]}")
check(fa.get("/time/timer").json()["timer"] is None, "no timer")
check(fa.patch(f"/time/entries/{EID}", {"note": "changed", "minutes": 30}).json()["seconds"] == 1800, "entry changed")
check(fa.delete(f"/time/entries/{EID}").status_code == 204, "entry deleted")
# export
r = fa.get("/export")
check(r.ok and any(l["id"] == L for l in r.json()["lists"]), "export")
check(need(tw.get("/export"), "export"), "export needs its scope")
# lists: archive + delete
XL = fa.post("/lists", {"name": "Old"}).json()["id"]
check(fa.delete(f"/lists/{XL}").status_code == 409, "delete: archive first (409)")
check(fa.patch(f"/lists/{XL}", {"archived": True}).json()["archived"] is True, "archived")
check(fa.delete(f"/lists/{XL}").status_code == 204 and fa.get(f"/lists/{XL}").status_code == 404, "list deleted for good (a person: at once)")

# ================================================================== the migration (restart with the flag cleared)
OLDR = "abk_" + "o" * 43
dbx("INSERT INTO api_tokens(user_id,name,token_hash,prefix,scopes,created_at) VALUES(1,'oldread',?,'abk_o','read','2026-01-01')",
    (hashlib.sha256(OLDR.encode()).hexdigest(),))
dbx("UPDATE agents SET scopes='' WHERE user_id=?", (AG,))
dbx("UPDATE settings SET value='0' WHERE key='migr_scopes215'")
subprocess.run(["docker", "restart", CT], capture_output=True)
for _ in range(60):
    try:
        if requests.get(B + "/api/health", timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(0.5)
check(dbx("SELECT scopes FROM api_tokens WHERE name='oldread'")[0][0] == "read,attachments:read", "migration: an old read token gets attachments:read")
check(dbx("SELECT scopes FROM agents WHERE user_id=?", (AG,))[0][0] == "read,write", "migration: an old agent keeps read + write")
check(dbx("SELECT scopes FROM api_tokens WHERE id=?", (W["id"],))[0][0] == "read,write", "migration: write tokens unchanged")
check(Api(OLDR).get(f"/attachments/{AT}").ok, "the old read token still downloads files")

# ================================================================== MCP against this server
MCP = os.path.join(N, "..", "mcp", "kalmido_mcp.py")


def mcp_tools(token):
    p = subprocess.run([sys.executable, MCP], input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n",
                       capture_output=True, text=True, env=dict(os.environ, KALMIDO_URL=B, KALMIDO_TOKEN=token), timeout=60)
    return {t["name"] for t in json.loads(p.stdout.splitlines()[0])["result"]["tools"]}


def mcp_call(token, name, args):
    p = subprocess.run([sys.executable, MCP], input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                                "params": {"name": name, "arguments": args}}) + "\n",
                       capture_output=True, text=True, env=dict(os.environ, KALMIDO_URL=B, KALMIDO_TOKEN=token), timeout=60)
    return json.loads(p.stdout.splitlines()[0])["result"]


r = A.post(B + "/api/admin/agents", json={"username": "minimal"})
MIN = r.json()["token"]
t = mcp_tools(MIN)
check({"create_task", "add_comment", "move_task", "list_tasks", "get_agent", "set_status"} <= t, "MCP: the default agent's tools")
check(not t & {"create_list", "delete_task", "export_data", "upload_attachment", "start_timer", "get_attachment"}, f"MCP: no tools beyond its scopes {sorted(t & {'create_list', 'delete_task', 'export_data'})}")
t = mcp_tools(W["token"])
check({"create_list", "delete_task", "export_data"} <= t and "get_agent" not in t, "MCP: a person's full token: no agent tools")
r = mcp_call(MIN, "create_list", {"name": "x"})
check(r["isError"] and "structure" in r["content"][0]["text"], "MCP: a tool outside the scopes is refused")
r = mcp_call(W["token"], "move_task", {"task_id": T[12], "position": "top"})
check(not r["isError"] and r["structuredContent"]["id"] == T[12], f"MCP move_task {str(r)[:200]}")

print(f"p2150_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
