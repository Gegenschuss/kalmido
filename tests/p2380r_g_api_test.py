#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.380 G API tests (security part of the 2.380 rest package). Invented names only, addresses @example.com.
 - #2289: the inbound webhook takes its token as the header X-Kalmido-Hook-Token on POST /api/hooks/in (no cookie, no CSRF
   header); a missing / wrong header 404; the path token stays valid; create and rotate show endpoint + token + header once
 - #3391: a NEW personal webhook never delivers events of an organisation's list (also not a shared one), an old one (from
   before 2.380: org_grace_until set by the migration) until its last day; the first event after it ends the grace for good
   and gives the owner ONE News item (whorgcut); the list of webhooks names the organisations (org_hits, admin flag) and the
   last day (org_until); private lists reach every personal webhook as before; an organisation admin sets the same webhook
   up as one of the organisation; a person without an organisation: org_hits empty, private events as before
 - #3390: the redeem answer of the agent setup carries starter_sha256 = mcp/starter_sha256.txt (made by tools/starter_sha.py,
   in the image), for a person without an organisation too; the file matches the starter files (tools/starter_sha.py --check)
 - #3389: the allowed internal hosts per purpose (13 purposes): the start's one-shot copied the old list into every purpose,
   a purpose without an entry falls back to the old list; PATCH allow_hosts_by_purpose changes only the purposes named
   (unknown purpose / a URL 400, non-admins 403, never shown to them); the old field cal_allow_hosts sets every purpose;
   a host allowed for calendars only does not open webhooks (and the other way round)
usage: p2380r_g_api_test.py <datadir>      (KMT_NOSTART=1 / P2380RG_NOSTART=1: a running server)"""
import os
import subprocess
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, H, check, dbx, done, fresh, sess, until

fresh(prefix="P2380RG")
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Org", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
FID, F = freelancer(B, A)  # a person without an organisation


def local(u):
    """The public URL the server answers with -> the test server's address."""
    return B + u[u.index("/api/"):]


# ================================================================ #2289: the hook token as a header
L = F.post(B + "/api/lists", json={"name": "Automations", "kind": "project", "org_id": None}).json()["id"]
r = F.post(B + f"/api/lists/{L}/hooks-in", json={"name": "Home Assistant"})
HK = r.json()
check(r.status_code == 201 and HK.get("token", "").startswith("khi_") and HK.get("header") == "X-Kalmido-Hook-Token"
      and HK.get("endpoint", "").endswith("/api/hooks/in") and HK.get("url", "").endswith("/api/hooks/in/" + HK.get("token", "-")),
      f"#2289: create shows endpoint, token and header once (and the path URL): {r.status_code} {r.text[:200]}")
EP, TOK = local(HK["endpoint"]), HK["token"]
r = requests.post(EP, headers={"X-Kalmido-Hook-Token": TOK}, json={"title": "Washing machine done"})
check(r.status_code == 201 and r.json().get("id"), f"#2289: the header variant creates a task without cookie / CSRF: {r.status_code} {r.text[:200]}")
if r.status_code == 201:
    t = F.get(B + f"/api/tasks/{r.json()['id']}").json()
    check(t.get("list_id") == L and t.get("title") == "Washing machine done", f"#2289: the task is in the webhook's list: {t}")
check(requests.post(EP, json={"title": "x"}).status_code == 404, "#2289: no header: 404")
check(requests.post(EP, headers={"X-Kalmido-Hook-Token": "khi_wrong"}, json={"title": "x"}).status_code == 404, "#2289: a wrong header: 404")
check(requests.post(EP, headers={"X-Kalmido-Hook-Token": "x" * 300}, json={"title": "x"}).status_code == 404, "#2289: a far too long header: 404")
r = requests.post(local(HK["url"]), json={"title": "Path still works"})
check(r.status_code == 201, f"#2289: the path token stays valid: {r.status_code} {r.text[:160]}")
r = F.post(B + f"/api/hooks-in/{HK['id']}/rotate")
check(r.ok and r.json().get("token", TOK) != TOK and r.json().get("header") == "X-Kalmido-Hook-Token", f"#2289: rotate shows the new token once: {r.text[:160]}")
NEW = r.json().get("token", "")
check(requests.post(EP, headers={"X-Kalmido-Hook-Token": TOK}, json={"title": "x"}).status_code == 404, "#2289: the rotated token stops in the header too")
check(requests.post(EP, headers={"X-Kalmido-Hook-Token": NEW}, json={"title": "Rotated"}).status_code == 201, "#2289: the new token works in the header")
check("token" not in F.get(B + f"/api/lists/{L}/hooks-in").json()["hooks"][0], "#2289: the list never shows the token again")

# ================================================================ #3391: personal webhooks and organisation lists
HOOK = "https://hooks.example.invalid/hook"
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": [ORG]})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
OL = A.post(B + "/api/lists", json={"name": "Org board", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{OL}/members", json={"user_id": BOB, "role": "edit"}).ok, "#3391 setup: bob in the organisation's list")
PL = Bo.post(B + "/api/lists", json={"name": "Bob private", "org_id": None}).json()["id"]
W0 = Bo.post(B + "/api/me/webhooks", json={"name": "old", "url": HOOK + "/old", "events": ["task.created"]}).json()["id"]
W1 = Bo.post(B + "/api/me/webhooks", json={"name": "new", "url": HOOK + "/new", "events": ["task.created"]}).json()["id"]
check(dbx("SELECT org_grace_until FROM webhooks WHERE id=?", (W1,))[0][0] == "", "#3391: a new personal webhook has no grace period")
dbx("UPDATE webhooks SET org_grace_until='2099-12-31' WHERE id=?", (W0,))  # what the migration gives the webhooks from before 2.380
check(len(dbx("SELECT id FROM kalmido_migrations WHERE id IN ('webhooks.org_grace_until', 'webhooks.org_grace_until#2')")) == 2,
      "#3391: both migration steps (column + the grace of the existing webhooks) ran")


def queued(title):
    """webhook ids with a queued delivery of the task (the test address never answers: the rows stay for the retries)."""
    return {r[0] for r in dbx("SELECT webhook_id FROM webhook_queue WHERE payload LIKE ?", (f"%{title}%",))}


A.post(B + "/api/tasks", json={"list_id": OL, "title": "Org task one"})
Bo.post(B + "/api/tasks", json={"list_id": PL, "title": "Private task one"})
q = until(lambda: queued("Private task one") >= {W0, W1} and queued("Private task one"), 15)
check({W0, W1} <= (q or set()), f"#3391: a private list reaches every personal webhook: {q}")
q = queued("Org task one")
check(W0 in q and W1 not in q, f"#3391: the organisation's list only at the old webhook (grace), never at the new one: {q}")
hs = {h["id"]: h for h in Bo.get(B + "/api/me/webhooks").json()["hooks"]}
check([o["id"] for o in hs[W1].get("org_hits", [])] == [ORG] and hs[W1]["org_hits"][0]["admin"] is False and hs[W1].get("org_until") == "",
      f"#3391: the new webhook names the organisation (bob no admin), no last day: {hs[W1].get('org_hits')} {hs[W1].get('org_until')}")
check(hs[W0].get("org_until") == "2099-12-31", f"#3391: the old webhook shows its last day: {hs[W0].get('org_until')}")
dbx("UPDATE webhooks SET org_grace_until='2020-01-01' WHERE id=?", (W0,))  # the grace is over
# review: an organisation list bob does not reach neither ends the grace nor makes a News item (no foreign names)
OL2 = A.post(B + "/api/lists", json={"name": "Not for bob", "org_id": ORG}).json()["id"]
A.post(B + "/api/tasks", json={"list_id": OL2, "title": "Foreign org task"})
Bo.post(B + "/api/tasks", json={"list_id": PL, "title": "Private task between"})
until(lambda: queued("Private task between"), 15)
check(dbx("SELECT org_grace_until FROM webhooks WHERE id=?", (W0,))[0][0] == "2020-01-01"
      and not [x for x in Bo.get(B + "/api/news").json()["items"] if x["kind"] == "whorgcut"],
      "#3391 review: an event of a list the owner does not reach leaves the grace and makes no News item")
A.post(B + "/api/tasks", json={"list_id": OL, "title": "Org task two"})
A.post(B + "/api/tasks", json={"list_id": OL, "title": "Org task three"})
Bo.post(B + "/api/tasks", json={"list_id": PL, "title": "Private task two"})
until(lambda: queued("Private task two"), 15)
check(not queued("Org task two") & {W0, W1} and not queued("Org task three") & {W0, W1}, "#3391: after the last day no personal webhook gets the organisation's list")
check(dbx("SELECT org_grace_until FROM webhooks WHERE id=?", (W0,))[0][0] == "", "#3391: the first event after the last day ends the grace for good")
nw = [x for x in Bo.get(B + "/api/news").json()["items"] if x["kind"] == "whorgcut"]
check(len(nw) == 1 and nw[0]["data"].get("org_id") == ORG and nw[0]["data"].get("webhook") == "old",
      f"#3391: one News item for the owner (not one per event): {nw}")
check(not [x for x in A.get(B + "/api/news").json()["items"] if x["kind"] == "whorgcut"], "#3391: nobody else gets it")
check(Bo.get(B + "/api/me/webhooks").json()["hooks"][0].get("org_until") == "", "#3391: no last day shown any more")
AW = A.post(B + "/api/me/webhooks", json={"name": "alice", "url": HOOK + "/alice", "events": ["task.created", "task.completed"]}).json()
check([(o["id"], o["admin"]) for o in AW.get("org_hits", [])] == [(ORG, True)], f"#3391: alice is admin of the organisation: {AW.get('org_hits')}")
r = A.post(B + f"/api/orgs/{ORG}/webhooks", json={"name": AW["name"], "url": AW["url"], "events": AW["events"]})
check(r.status_code == 201 and r.json().get("secret"), f"#3391: 'Set up as organisation webhook' = the same fields as an organisation webhook: {r.status_code}")
OW = r.json().get("id")
A.post(B + "/api/tasks", json={"list_id": OL, "title": "Org task four"})
q = until(lambda: queued("Org task four"), 15)
check(OW in (q or set()) and AW["id"] not in (q or set()), f"#3391: the organisation's webhook gets it, the personal one not: {q}")
check(Bo.post(B + f"/api/orgs/{ORG}/webhooks", json={"name": "x", "url": HOOK, "events": ["task.created"]}).status_code == 403,
      "#3391: a member is no admin: no organisation webhook")
# a person without an organisation: nothing changes
FW = F.post(B + "/api/me/webhooks", json={"name": "frida", "url": HOOK + "/frida", "events": ["task.created"]}).json()
check(FW.get("org_hits") == [] and FW.get("org_until") == "", f"#3391 freelancer: no organisation hits: {FW.get('org_hits')}")
F.post(B + "/api/tasks", json={"list_id": L, "title": "Frida private task"})
q = until(lambda: queued("Frida private task"), 15)
check(FW.get("id") in (q or set()), f"#3391 freelancer: the private task reaches the personal webhook: {q}")

# ================================================================ #3390: checksums of the starter files in the redeem answer
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "mcp", "starter_sha256.txt"), encoding="utf-8") as f:
    WANT = {ln.split()[1]: ln.split()[0] for ln in f if ln.strip() and not ln.startswith("#")}
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "starter_sha.py"), "--check"], capture_output=True, text=True)
check(r.returncode == 0, f"#3390: mcp/starter_sha256.txt matches the starter files: {r.stdout} {r.stderr}")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read"]})
check(r.ok, f"#3390 setup: a personal agent of a person without an organisation: {r.status_code} {r.text[:160]}")
if r.ok:
    rc = F.post(B + f"/api/my/agents/{r.json()['id']}/setup-code", json={"os": "linux", "folder": "/work/x"})
    check(rc.ok, f"#3390 setup: a setup code {rc.text[:160]}")
    rr = requests.post(B + "/api/agent-setup/redeem", headers=H, json={"code": rc.json().get("code", ""), "host": "box", "folder": "/work/x", "os": "linux"})
    got = rr.json().get("starter_sha256")
    check(rr.ok and got == WANT and "agent_run.py" in got and "starter_files.txt" in got,
          f"#3390: the redeem answer sends the checksums of this version: {rr.status_code} {str(got)[:200]}")

# ================================================================ #3389: allowed internal hosts per purpose
PURPOSES = {"calendar", "carddav", "webhooks", "mail", "git", "newsletter", "ntfy", "peppol", "feeds", "oidc", "paperless", "karakeep", "servers"}


def by():
    return A.get(B + "/api/about").json().get("allow_hosts_by_purpose") or {}


check(dbx("SELECT value FROM settings WHERE key='migr_allow2380'")[0][0] == "1", "#3389: the one-shot copy ran at the start")
check(set(by()) == PURPOSES and all(v == "" for v in by().values()), f"#3389: every purpose, empty on a fresh server: {by()}")
r = A.patch(B + "/api/admin/settings", json={"cal_allow_hosts": "10.9.8.6:8443"})
check(r.ok and set(r.json()["allow_hosts_by_purpose"].values()) == {"10.9.8.6:8443"}, f"#3389: the old field sets every purpose: {r.text[:200]}")
dbx("UPDATE settings SET value=? WHERE key='allow_hosts_by_purpose'", ('{"calendar": "10.9.8.5"}',))  # a purpose missing in the setting
b0 = by()
check(b0.get("calendar") == "10.9.8.5" and b0.get("webhooks") == "10.9.8.6:8443", f"#3389: a purpose without an entry = the old list (what the copy gives): {b0}")
r = A.patch(B + "/api/admin/settings", json={"allow_hosts_by_purpose": {"calendar": "10.9.8.8:8443", "webhooks": "10.9.8.7:8443 10.9.8.7:8443"}})
b1 = r.json().get("allow_hosts_by_purpose") or {}
check(r.ok and b1.get("calendar") == "10.9.8.8:8443" and b1.get("webhooks") == "10.9.8.7:8443" and b1.get("git") == "10.9.8.6:8443",
      f"#3389: only the purposes named change, normalised: {r.text[:300]}")
check(A.patch(B + "/api/admin/settings", json={"allow_hosts_by_purpose": {"printer": "x.lan"}}).status_code == 400, "#3389: an unknown purpose 400")
check(A.patch(B + "/api/admin/settings", json={"allow_hosts_by_purpose": {"git": "http://x.lan/"}}).status_code == 400, "#3389: a URL instead of a host 400")
check(A.patch(B + "/api/admin/settings", json={"allow_hosts_by_purpose": ["git"]}).status_code == 400, "#3389: not an object 400")
check(by().get("git") == "10.9.8.6:8443", "#3389: a refused change changes nothing")
check(Bo.patch(B + "/api/admin/settings", json={"allow_hosts_by_purpose": {"git": "x.lan"}}).status_code == 403, "#3389: only admins")
check("allow_hosts_by_purpose" not in Bo.get(B + "/api/about").json(), "#3389: non-admins never see the lists")
r = Bo.post(B + "/api/me/webhooks", json={"name": "cal host", "url": "http://10.9.8.8:8443/hook", "events": ["task.created"]})
check(r.status_code == 400, f"#3389: a host allowed for calendars only does not open webhooks: {r.status_code} {r.text[:120]}")
r = Bo.post(B + "/api/me/webhooks", json={"name": "wh host", "url": "http://10.9.8.7:8443/hook", "events": ["task.created"]})
check(r.status_code == 201, f"#3389: the host allowed for webhooks: {r.status_code} {r.text[:120]}")
r = F.post(B + "/api/me/webhooks", json={"name": "wh host", "url": "http://10.9.8.7:8443/hook", "events": ["task.created"]})
check(r.status_code == 201, f"#3389 freelancer: the same list for a person without an organisation: {r.status_code} {r.text[:120]}")

sys.exit(done("p2380r_g_api"))
