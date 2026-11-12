#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.500.0 (#4070): a support session reads and edits contents, nothing else. Own container (hosted, a server key). Invented accounts only.
freelancer-matrix: own
tenant-matrix: support
 - the consent page of an app (GET + POST /oauth/authorize) is refused, no code, no new agent; the person's own session still gets it
 - a route per way that would outlive the consent (agents, public links, invitations, webhooks, shares, keys, feeds, ...): 403 code
   support_session; the person's own session is not stopped there; a new area is refused too (positive list)
 - working links stay unread (public link, feed, external links), a PATCH does not carry a project out of the account's scope
 - contents stay editable: a project, a task, a comment; settings; signing out
 - the writes stand on the grant's log, the refused ones too, marked as the support session
usage: p2500_b_support_test.py <datadir>"""
import base64
import hashlib
import os
import re
import sys
import urllib.parse

import requests

import kt
from kt import B, FAILS, OKS, check, sess, dbx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer, login  # noqa: E402

KEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (32 bytes, base64)
CB = "https://client.example/callback"

kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_HOSTED": "1"})
assert kt.sess(None).post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
r = A.patch(B + "/api/admin/settings", json={"mcp_remote": True, "password": "password123"})
assert r.ok, r.text
FID, _Fr = freelancer(B, A)
Fr = login(B, "frida")
assert Fr.patch(B + "/api/settings", json={"lang": "en", "tour": "done"}).ok
assert Fr.post(B + "/api/support-access", json={"hours": 1}).ok
r = A.post(B + f"/api/users/{FID}/signin-link")
assert r.ok, r.text
X = kt.sess(None)
r = X.post(B + "/api/auth/link", json={"token": r.json()["link"].split("#signin/")[1]})
assert r.ok, r.text
check(kt.dbx("SELECT COUNT(*) FROM sessions WHERE user_id=? AND via='support'", (FID,)) == [(1,)], "the operator's session is a support session")

# ---------------------------------------------------------------- contents stay editable
r = X.post(B + "/api/lists", json={"name": "Help project"})
check(r.status_code in (200, 201), "support session: a new project " + r.text[:160])
LID = r.json()["id"]
r = X.post(B + "/api/tasks", json={"title": "Fixed by support", "list_id": LID})
check(r.status_code in (200, 201), "support session: a new task " + r.text[:160])
TID = r.json()["id"]
check(X.patch(B + f"/api/tasks/{TID}", json={"title": "Fixed by support, 2"}).ok, "support session: edits a task")
check(X.post(B + f"/api/tasks/{TID}/comments", json={"body": "Done"}).status_code in (200, 201), "support session: a comment")
check(X.patch(B + "/api/settings", json={"lang": "en"}).ok, "support session: ordinary settings")
check(X.patch(B + "/api/me", json={"display_name": "Frida"}).ok, "support session: the display name")

# ---------------------------------------------------------------- the ways that outlive the consent: a test per route
agents = kt.dbx("SELECT COUNT(*) FROM users WHERE kind='agent'")
OID = 999999
for meth, path, body in (
        ("put", f"/api/lists/{LID}/public-link", {"enabled": True}), ("post", f"/api/lists/{LID}/public-link/regenerate", {}),
        ("put", f"/api/lists/{LID}/members", {"email": "ops@example.com"}), ("delete", f"/api/lists/{LID}/members/{FID}", None),
        ("post", f"/api/lists/{LID}/owner", {"user_id": 1}), ("put", f"/api/lists/{LID}/agent", {"agent_id": 1}),
        ("post", f"/api/lists/{LID}/hooks-in", {}), ("post", f"/api/lists/{LID}/signoffs", {}),
        ("post", f"/api/lists/{LID}/e2e/start", {}), ("put", "/api/folders/public-links", {}), ("put", "/api/folders/people", {}),
        ("post", "/api/wiki/shares", {"email": "ops@example.com"}), ("post", "/api/sheets/1/shares", {"email": "ops@example.com"}),
        ("post", "/api/files/nodes/1/shares", {"email": "ops@example.com"}), ("post", "/api/files/nodes/1/ext-links", {}),
        ("patch", "/api/files/shares/1", {}), ("post", f"/api/orgs/{OID}/invites", {"email": "ops@example.com"}),
        ("put", f"/api/orgs/{OID}/members", {"email": "ops@example.com"}), ("post", f"/api/orgs/{OID}/webhooks", {"url": "https://ops.example/"}),
        ("post", f"/api/orgs/{OID}/channels", {"url": "https://ops.example/"}), ("post", "/api/orgs", {"name": "Ops"}),
        ("post", "/api/docs/scan-keys", {}), ("post", "/api/docs/mail", {}), ("put", "/api/e2e/keys", {}),
        ("post", "/api/feeds", {"url": "https://ops.example/rss"}), ("post", "/api/evcals/1/feed", {}), ("post", "/api/calendars", {"url": "https://ops.example/c"}),
        ("post", "/api/my/agents", {"username": "opsbot"}), ("post", "/api/my/agents/1/token", {}), ("post", "/api/agents", {"username": "opsbot"}),
        ("post", "/api/me/tokens", {"name": "ops"}), ("post", "/api/me/webhooks", {"url": "https://ops.example/"}), ("post", "/api/me/channels", {}),
        ("post", "/api/push/subscribe", {}), ("post", "/api/office/clients/1/portal-link", {}), ("post", "/api/office/rights/groups", {}),
        ("put", "/api/office/settings", {}), ("put", "/api/office/payonline", {}), ("put", "/api/office/mail-profile", {}),
        ("post", "/api/office/docs/1/send", {}), ("post", "/api/office/letters/1/send-mail", {}), ("post", "/api/files/requests", {}),
        ("delete", "/api/clients/1/purge", None), ("post", "/api/no-such-new-area", {})):
    r = getattr(X, meth)(B + path, **({"json": body} if body is not None else {}))
    check(r.status_code == 403 and (r.headers.get("content-type", "").startswith("application/json") and r.json().get("code") == "support_session"),
          f"support session: {meth.upper()} {path} -> 403 support_session, {r.status_code} {r.text[:100]}")
check(kt.dbx("SELECT COUNT(*) FROM users WHERE kind='agent'") == agents, "no agent came of it")
r = Fr.post(B + "/api/me/tokens", json={"name": "mine"})
check(r.status_code != 403, f"frida's own session is not stopped there {r.status_code}")
dbx("UPDATE users SET email_proved=lower(COALESCE(email, '')) WHERE email_proved=''")  # 2.1001.0 (#5669): a list / folder shared by address binds only a proved address (a mailed link / OIDC); the accounts here proved theirs
r = Fr.put(B + f"/api/lists/{LID}/members", json={"email": "nobody@example.com"})
check(r.json().get("code") != "support_session", "frida's own session: the project's members")

# ---------------------------------------------------------------- review: working links, the project's scope
for path in (f"/api/lists/{LID}/public-link", "/api/evcals/1/feed", "/api/files/nodes/1/ext-links", "/api/folders/public-links"):
    r = X.get(B + path)
    check(r.status_code == 403 and r.json().get("code") == "support_session", f"support session: GET {path} (a working link) 403, {r.status_code}")
check(Fr.get(B + f"/api/lists/{LID}/public-link").status_code != 403, "frida's own session reads the project's link state")
check(X.get(B + f"/api/lists/{LID}").status_code != 403 or X.get(B + "/api/state").ok, "support session: reading stays")
for key, val in (("org_id", 1), ("org_visibility", "all"), ("org_edit", True)):
    r = X.patch(B + f"/api/lists/{LID}", json={key: val})
    check(r.status_code == 403 and r.json().get("code") == "support_session", f"support session: PATCH the project's {key} 403, {r.status_code}")
check(X.patch(B + f"/api/lists/{LID}", json={"name": "Help project 2"}).ok, "support session: renames the project")
for meth, path in (("put", "/api/office/docs/1/pay-online"), ("post", "/api/files/nodes/1/move-space")):
    r = getattr(X, meth)(B + path, json={})
    check(r.status_code == 403 and r.json().get("code") == "support_session", f"support session: {meth.upper()} {path} 403, {r.status_code}")

# ---------------------------------------------------------------- the consent page of an app
cl = requests.post(B + "/oauth/register", json={"redirect_uris": [CB], "client_name": "Test Connector"}).json()
ver = "v" * 50
ch = base64.urlsafe_b64encode(hashlib.sha256(ver.encode()).digest()).rstrip(b"=").decode()
Q = "/oauth/authorize?" + urllib.parse.urlencode({"response_type": "code", "client_id": cl["client_id"], "redirect_uri": CB, "code_challenge": ch,
                                                  "code_challenge_method": "S256", "state": "s1"})
r = X.get(B + Q, allow_redirects=False)
check(r.status_code == 403 and 'name="t"' not in r.text, f"support session: the consent page 403, no form {r.status_code}")
r = Fr.get(B + Q, allow_redirects=False)
check(r.status_code == 200 and 'name="t"' in r.text, f"frida's own session: the consent page {r.status_code}")
t = re.search(r'name="t" value="([^"]+)"', r.text).group(1)
r = X.post(B + "/oauth/authorize", data={"t": t, "decision": "allow", "agent": "new", "username": "opsbot", "display_name": "Ops"}, allow_redirects=False)
check(r.status_code == 403, f"support session: POST with frida's form 403, no agent, no code {r.status_code} {r.text[:120]}")
check(kt.dbx("SELECT COUNT(*) FROM oauth_codes") == [(0,)] and kt.dbx("SELECT COUNT(*) FROM users WHERE kind='agent'") == agents, "nothing made: no code, no agent")

# ---------------------------------------------------------------- what the client sees
uses = Fr.get(B + "/api/support-access").json()["account"]["uses"]
check(any(u["method"] == "POST" and u["route"] == "/api/tasks" and u["by"] == "Support access" for u in uses), f"the log: the task of the support session {uses[:3]}")
check(any(u["route"] == "/api/lists/<int:lid>/public-link" and u["status"] == 403 and u["by"] == "Support access" for u in uses), "the log: the refused public link")
check(all(set(u) == {"at", "by", "method", "route", "status"} for u in uses), "the log holds no values")
check(X.post(B + "/api/auth/logout").ok, "support session: signs out")

print(f"p2500_b: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
