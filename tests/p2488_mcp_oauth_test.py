#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.488.0 (#3363): the hosted MCP access - /mcp with OAuth 2.1 (agents/mcpremote.py), against a test client.
freelancer-matrix: agents (the person without an organisation connects her own agent: consent, token, tools, revoke)
tenant-matrix: agent (another person neither sees nor revokes her access, nor picks her agent; the agent sees only what is shared with it)
 - admin switch "Hosted MCP access" off (default): /mcp, /oauth/* and the metadata answer 404; switching on asks for the password
 - metadata (RFC 9728 / 8414), /mcp without a token: 401 with WWW-Authenticate resource_metadata
 - dynamic client registration: only https or http on localhost / 127.0.0.1, no fragment; a limit per address
 - authorize: unknown client / redirect URI never redirected; PKCE S256 required (plain, missing -> error to the client with
   state); not signed in -> the sign-in with the way back; the consent page: client, host, only the person's own agents
   (an instance admin also team agents), sealed form bound to the person, cross-site refused, frame-ancestors 'none'
 - token: wrong verifier, other client, other redirect URI, a code twice (revokes the access made with it); hashes only
 - /mcp: initialize, tools/list after the agent's scopes, tools/call with the agent's rights (a project not shared with it
   stays invisible), GET / DELETE 405, a foreign Origin 403, a notification 202
 - refresh rotation (old access + old refresh dead; the old refresh again revokes the access), Settings > Agents lists and
   revokes, /oauth/revoke, a new personal agent from the consent page
usage: p2488_mcp_oauth_test.py <datadir>      (KMT_NOSTART=1 / P2488MO_NOSTART=1: a running server)"""
import base64
import hashlib
import html
import re
import secrets
import sys
import urllib.parse

import requests
from kt import B, PASSWORD, check, dbx, done, fresh, setup
from freelancer_fixture import freelancer

fresh(prefix="P2488MO")
A = setup()
CB = "http://127.0.0.1:9/cb"
CB2 = "https://app.example/cb"


def j(r):
    try:
        return r.json()
    except ValueError:
        return {}


def pkce():
    v = secrets.token_urlsafe(48)
    return v, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


# ---------------------------------------------------------------- the switch, off by default
for p in ("/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource", "/oauth/authorize?client_id=x", "/mcp"):
    r = requests.get(B + p, allow_redirects=False)
    check(r.status_code == 404, f"off: GET {p} 404 ({r.status_code})")
r = requests.post(B + "/oauth/register", json={"redirect_uris": [CB]})
check(r.status_code == 404, f"off: POST /oauth/register 404 ({r.status_code})")
r = requests.post(B + "/oauth/token", data={"grant_type": "authorization_code"})
check(r.status_code == 404, f"off: POST /oauth/token 404 ({r.status_code})")
r = requests.post(B + "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
check(r.status_code == 404, f"off: POST /mcp 404 ({r.status_code})")
check(A.get(B + "/api/about").json().get("mcp_remote") is False, "about: mcp_remote false for the admin")

r = A.patch(B + "/api/admin/settings", json={"mcp_remote": True})
check(r.status_code in (401, 403) and j(r).get("password_needed"), f"switching on asks for the password ({r.status_code} {r.text[:120]})")
r = A.patch(B + "/api/admin/settings", json={"mcp_remote": True, "password": PASSWORD})
check(r.ok and r.json().get("mcp_remote") is True, f"switched on with the password ({r.status_code} {r.text[:120]})")
check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok, "personal agents allowed")

# ---------------------------------------------------------------- metadata, 401
pr = requests.get(B + "/.well-known/oauth-protected-resource")
check(pr.ok and pr.json()["resource"].endswith("/mcp") and pr.json()["authorization_servers"], f"resource metadata {pr.text[:200]}")
check(requests.get(B + "/.well-known/oauth-protected-resource/mcp").ok, "resource metadata at the path form too")
asm = requests.get(B + "/.well-known/oauth-authorization-server").json()
check(asm.get("code_challenge_methods_supported") == ["S256"] and asm.get("token_endpoint_auth_methods_supported") == ["none"]
      and asm["authorization_endpoint"].endswith("/oauth/authorize") and asm["token_endpoint"].endswith("/oauth/token")
      and asm["registration_endpoint"].endswith("/oauth/register") and asm["issuer"] == pr.json()["authorization_servers"][0],
      f"authorization server metadata {asm}")
r = requests.post(B + "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
wa = r.headers.get("WWW-Authenticate", "")
check(r.status_code == 401 and 'resource_metadata="' in wa and "/.well-known/oauth-protected-resource" in wa, f"/mcp without a token: 401 {wa}")
r = requests.post(B + "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={"Authorization": "Bearer abk_nothing"})
check(r.status_code == 401 and 'error="invalid_token"' in r.headers.get("WWW-Authenticate", ""), "/mcp with a wrong token: invalid_token")

# ---------------------------------------------------------------- registration
for bad in (["http://evil.example/cb"], ["javascript:alert(1)"], ["https://app.example/cb#x"], [], ["https://u:p@app.example/cb"],
            ["ftp://app.example/cb"], "https://app.example/cb"):
    r = requests.post(B + "/oauth/register", json={"redirect_uris": bad, "client_name": "Bad"})
    check(r.status_code == 400 and j(r).get("error") == "invalid_redirect_uri", f"register refuses {bad!r} ({r.status_code})")
r = requests.post(B + "/oauth/register", json={"redirect_uris": [CB], "grant_types": ["client_credentials"]})
check(r.status_code == 400 and j(r).get("error") == "invalid_client_metadata", "register refuses other grant types")
r = requests.post(B + "/oauth/register", json={"redirect_uris": [CB, CB2], "client_name": "Test Connector",
                                               "token_endpoint_auth_method": "none"})
check(r.status_code == 201 and r.json()["client_id"].startswith("kmc_") and r.json()["token_endpoint_auth_method"] == "none"
      and r.headers.get("Cache-Control") == "no-store", f"registered {r.status_code} {r.text[:200]}")
CID = r.json()["client_id"]
CID2 = requests.post(B + "/oauth/register", json={"redirect_uris": [CB], "client_name": "Other"}).json()["client_id"]

# ---------------------------------------------------------------- the person without an organisation and her agent
FID, Fr = freelancer(B, A)
ag = Fr.post(B + "/api/my/agents", json={"username": "frida-mcp", "display_name": "Frida MCP"})
check(ag.status_code == 201, f"her agent {ag.status_code} {ag.text[:120]}")
AID = ag.json()["id"]
L1 = Fr.post(B + "/api/lists", json={"name": "Shared with the bot"}).json()["id"]
L2 = Fr.post(B + "/api/lists", json={"name": "Private only"}).json()["id"]
check(Fr.put(B + f"/api/lists/{L1}/members", json={"user_id": AID, "role": "edit"}).ok, "L1 shared with her agent")
team = A.post(B + "/api/admin/agents", json={"username": "teambot", "display_name": "Team Bot"})
check(team.ok, f"a team agent {team.status_code} {team.text[:120]}")
TEAM = team.json().get("id")
aown = A.post(B + "/api/my/agents", json={"username": "alice-own", "display_name": "Alice Own"})
AOWN = aown.json().get("id")


def authz_url(cid=CID, redirect=CB, ch=None, method="S256", state="st-123", **extra):
    q = {"response_type": "code", "client_id": cid, "redirect_uri": redirect, "code_challenge": ch or pkce()[1],
         "code_challenge_method": method, "state": state, **extra}
    return B + "/oauth/authorize?" + urllib.parse.urlencode({k: v for k, v in q.items() if v is not None})


def page(s, url):
    r = s.get(url, allow_redirects=False)
    m = re.search(r'name="t" value="([^"]+)"', r.text)
    return r, html.unescape(m.group(1)) if m else ""


def consent(s=Fr, agent=AID, ch=None, cid=CID, redirect=CB, **form):
    """-> the redirect after "Connect" (the Location header)."""
    _, t = page(s, authz_url(cid=cid, redirect=redirect, ch=ch))
    r = s.post(B + "/oauth/authorize", data={"t": t, "decision": "allow", "agent": str(agent), **form}, allow_redirects=False)
    return r


def code_of(loc):
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(loc).query)
    return (q.get("code") or [""])[0], (q.get("state") or [""])[0]


def token(**f):
    return requests.post(B + "/oauth/token", data=f)


def mcp(tok, msg, **kw):
    return requests.post(B + "/mcp", json=msg, headers={"Authorization": "Bearer " + tok, **kw.pop("headers", {})}, **kw)


def full(agent=AID, s=Fr):
    v, ch = pkce()
    code, _ = code_of(consent(s, agent, ch).headers.get("Location", ""))
    r = token(grant_type="authorization_code", code=code, redirect_uri=CB, client_id=CID, code_verifier=v)
    return r.json() if r.ok else {}


# ---------------------------------------------------------------- authorize
r = requests.get(authz_url(cid="kmc_unknown"), allow_redirects=False)
check(r.status_code == 400 and "Location" not in r.headers, "unknown client: an error page, never a redirect")
r = Fr.get(authz_url(redirect="https://evil.example/cb"), allow_redirects=False)
check(r.status_code == 400 and "Location" not in r.headers, "a redirect URI that is not registered: an error page, no redirect")
r = Fr.get(authz_url(redirect=CB + "/x"), allow_redirects=False)
check(r.status_code == 400 and "Location" not in r.headers, "redirect URIs are compared exactly")
for meth, ch in (("plain", "a" * 43), ("", None), ("S256", "short")):
    r = Fr.get(authz_url(method=meth or None, ch=ch if ch else ("" if meth == "" else None)), allow_redirects=False)
    loc = r.headers.get("Location", "")
    check(r.status_code == 302 and loc.startswith(CB) and "error=invalid_request" in loc and "state=st-123" in loc,
          f"PKCE {meth or 'missing'} refused to the client with state ({r.status_code} {loc})")
r = Fr.get(authz_url(response_type="token"), allow_redirects=False)
check("error=unsupported_response_type" in r.headers.get("Location", ""), "response_type token refused")
r = requests.get(authz_url(), allow_redirects=False)
loc = r.headers.get("Location", "")
check(r.status_code == 303 and loc.startswith("/?oauth=") and urllib.parse.unquote(loc[len("/?oauth="):]).startswith("?response_type=code"),
      f"not signed in: to the sign-in with the way back ({r.status_code} {loc[:80]})")

r, T_FR = page(Fr, authz_url())
csp = r.headers.get("Content-Security-Policy", "")
check(r.status_code == 200 and "Test Connector" in r.text and "127.0.0.1:9" in r.text and "Frida MCP" in r.text and T_FR,
      f"the consent page names client, host and her agent ({r.status_code})")
check("frame-ancestors 'none'" in csp and "form-action 'self' http://127.0.0.1:9" in csp and r.headers.get("X-Frame-Options") == "DENY",
      f"consent page: no framing, the form only here / to the client ({csp})")
check("Team Bot" not in r.text and "Alice Own" not in r.text, "her page lists only her own agents")
ra, T_A = page(A, authz_url())
check("Team Bot" in ra.text and "Alice Own" in ra.text and "Frida MCP" not in ra.text, "the instance admin also sees the team agents, not her agent")
r = Fr.post(B + "/oauth/authorize", data={"t": T_A, "decision": "allow", "agent": str(AID)}, allow_redirects=False)
check(r.status_code == 400 and "Location" not in r.headers, "the sealed form of another person is refused")
r = Fr.post(B + "/oauth/authorize", data={"t": T_FR + "x", "decision": "allow", "agent": str(AID)}, allow_redirects=False)
check(r.status_code == 400 and "Location" not in r.headers, "a changed form value is refused")
r = Fr.post(B + "/oauth/authorize", data={"t": T_FR, "decision": "allow", "agent": str(AID)}, headers={"Sec-Fetch-Site": "cross-site"},
            allow_redirects=False)
check(r.status_code == 403, "a cross-site form post is refused")
r = Fr.post(B + "/oauth/authorize", data={"t": T_FR, "decision": "allow", "agent": str(AID)}, headers={"Origin": "https://evil.example"},
            allow_redirects=False)
check(r.status_code == 403, "a foreign Origin is refused")
r = Fr.post(B + "/oauth/authorize", data={"t": T_FR, "decision": "allow", "agent": str(TEAM)}, allow_redirects=False)
check(r.status_code == 400 and "Location" not in r.headers, "a team agent is not hers to give")
r = Fr.post(B + "/oauth/authorize", data={"t": T_FR, "decision": "allow", "agent": str(AOWN)}, allow_redirects=False)
check(r.status_code == 400 and "Location" not in r.headers, "another person's agent is not hers to give")
r = Fr.post(B + "/oauth/authorize", data={"t": T_FR, "decision": "deny"}, allow_redirects=False)
loc = r.headers.get("Location", "")
check(r.status_code == 303 and loc.startswith(CB) and "error=access_denied" in loc and "state=st-123" in loc, f"deny: access_denied + state {loc}")
r = requests.post(B + "/oauth/authorize", data={"t": T_FR, "decision": "allow", "agent": str(AID)}, allow_redirects=False)
check(r.status_code == 401, "posting the form without a session is refused")

# ---------------------------------------------------------------- token: the failures
v1, ch1 = pkce()
c1, st = code_of(consent(Fr, AID, ch1).headers.get("Location", ""))
check(c1 and st == "st-123", "allow: code + state back to the client")
check(asm.get("authorization_response_iss_parameter_supported") is True, "RFC 9207: the issuer comes with the code (announced)")
r = token(grant_type="authorization_code", code=c1, redirect_uri=CB, client_id=CID, code_verifier=pkce()[0])
check(r.status_code == 400 and j(r).get("error") == "invalid_grant", "a wrong verifier: invalid_grant")
r = token(grant_type="authorization_code", code=c1, redirect_uri=CB, client_id=CID, code_verifier=v1)
check(r.status_code == 400 and j(r).get("error") == "invalid_grant", "the code is spent after one try")
v2, ch2 = pkce()
c2, _ = code_of(consent(Fr, AID, ch2).headers.get("Location", ""))
r = token(grant_type="authorization_code", code=c2, redirect_uri=CB, client_id=CID2, code_verifier=v2)
check(r.status_code == 400 and j(r).get("error") == "invalid_grant", "the code of another client: invalid_grant")
v3, ch3 = pkce()
c3, _ = code_of(consent(Fr, AID, ch3).headers.get("Location", ""))
r = token(grant_type="authorization_code", code=c3, redirect_uri=CB2, client_id=CID, code_verifier=v3)
check(r.status_code == 400 and j(r).get("error") == "invalid_grant", "another redirect URI than at the consent: invalid_grant")
r = token(grant_type="authorization_code", code="nothing", client_id="kmc_unknown", code_verifier=v3)
check(r.status_code == 401 and j(r).get("error") == "invalid_client", "an unknown client: invalid_client")
r = token(grant_type="password", client_id=CID)
check(j(r).get("error") == "unsupported_grant_type", "only code and refresh_token")
v4, ch4 = pkce()
c4, _ = code_of(consent(Fr, AID, ch4).headers.get("Location", ""))
dbx("UPDATE oauth_codes SET expires_at='2000-01-01T00:00:00Z' WHERE used_at IS NULL")
r = token(grant_type="authorization_code", code=c4, redirect_uri=CB, client_id=CID, code_verifier=v4)
check(r.status_code == 400 and j(r).get("error") == "invalid_grant", "an expired code: invalid_grant")

# ---------------------------------------------------------------- token: the good way, a code twice
v5, ch5 = pkce()
c5, _ = code_of(consent(Fr, AID, ch5).headers.get("Location", ""))
r = token(grant_type="authorization_code", code=c5, redirect_uri=CB, client_id=CID, code_verifier=v5)
t5 = j(r)
check(r.ok and t5.get("access_token", "").startswith("abk_") and t5.get("refresh_token", "").startswith("kmr_") and t5.get("expires_in") == 3600
      and t5.get("token_type") == "Bearer" and r.headers.get("Cache-Control") == "no-store", f"code -> tokens {r.status_code} {r.text[:200]}")
h5 = hashlib.sha256(t5.get("access_token", "").encode()).hexdigest()
row = dbx("SELECT user_id, expires_at, name FROM api_tokens WHERE token_hash=?", (h5,))
check(row and row[0][0] == AID and row[0][1] and row[0][2].startswith("MCP: Test Connector"), f"the access token is an API token of her agent with an expiry {row}")
check(not dbx("SELECT 1 FROM api_tokens WHERE token_hash=? OR prefix=?", (t5.get("access_token", ""), t5.get("refresh_token", "")[:12])),
      "no token is stored in plain text")
check(dbx("SELECT 1 FROM oauth_grants WHERE refresh_hash=?", (hashlib.sha256(t5.get("refresh_token", "").encode()).hexdigest(),)),
      "the refresh token only as SHA-256")
check(mcp(t5["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "ping"}).ok, "the access token works on /mcp")
r = token(grant_type="authorization_code", code=c5, redirect_uri=CB, client_id=CID, code_verifier=v5)
check(r.status_code == 400 and j(r).get("error") == "invalid_grant", "the same code twice: invalid_grant")
r = mcp(t5["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "ping"})
check(r.status_code == 401, f"... and the access made with it ends ({r.status_code})")

# ---------------------------------------------------------------- /mcp with the agent's rights
tk = full()
AT, RT = tk.get("access_token", ""), tk.get("refresh_token", "")
r = mcp(AT, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                                              "clientInfo": {"name": "t", "version": "1"}}})
check(r.ok and r.json()["result"]["protocolVersion"] == "2025-06-18" and r.json()["result"]["serverInfo"]["name"] == "kalmido",
      f"initialize {r.status_code} {r.text[:200]}")
r = mcp(AT, {"jsonrpc": "2.0", "method": "notifications/initialized"})
check(r.status_code == 202, f"a notification: 202 ({r.status_code})")
names = {t["name"] for t in mcp(AT, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]}
check("list_lists" in names and "create_task" in names and "delete_task" not in names and "empty_trash" not in names,
      f"tools/list after the agent's scopes (default: no delete) {len(names)}")
r = mcp(AT, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_lists", "arguments": {}}})
txt = r.text
check(r.ok and not r.json()["result"]["isError"] and "Shared with the bot" in txt and "Private only" not in txt,
      f"tools/call list_lists: the shared project, never the other {txt[:300]}")
r = mcp(AT, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "create_task", "arguments": {"title": "From MCP", "list_id": L1}}})
check(r.ok and not r.json()["result"]["isError"], f"tools/call create_task in the shared project {r.text[:200]}")
check(dbx("SELECT 1 FROM tasks WHERE list_id=? AND title='From MCP' AND created_by=?", (L1, AID)), "the task is the agent's")
r = mcp(AT, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "create_task", "arguments": {"title": "Sneak", "list_id": L2}}})
check(r.ok and r.json()["result"]["isError"] and not dbx("SELECT 1 FROM tasks WHERE title='Sneak'"), "not into the project that is not shared")
r = mcp(AT, {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "delete_task", "arguments": {"task_id": 1}}})
check(r.ok and r.json()["result"]["isError"] and "scope" in r.text, "a tool outside the scopes: refused")
r = requests.get(B + "/mcp", headers={"Authorization": "Bearer " + AT})
check(r.status_code == 405 and r.headers.get("Allow") == "POST", f"GET /mcp: 405 ({r.status_code})")
r = requests.delete(B + "/mcp", headers={"Authorization": "Bearer " + AT})
check(r.status_code == 405, f"DELETE /mcp: 405 ({r.status_code})")
r = mcp(AT, {"jsonrpc": "2.0", "id": 7, "method": "ping"}, headers={"Origin": "https://evil.example"})
check(r.status_code == 403, f"a foreign Origin: 403 ({r.status_code})")

# ---------------------------------------------------------------- refresh rotation
r = token(grant_type="refresh_token", refresh_token=RT, client_id=CID)
t6 = j(r)
check(r.ok and t6.get("refresh_token") not in ("", None, RT) and t6.get("access_token") not in ("", None, AT), "refresh: new tokens")
check(mcp(AT, {"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401, "the old access token is dead")
check(mcp(t6.get("access_token", ""), {"jsonrpc": "2.0", "id": 1, "method": "ping"}).ok, "the new one works")
r = token(grant_type="refresh_token", refresh_token=t6.get("refresh_token", ""), client_id=CID2)
check(r.status_code == 400, "refresh with another client: refused")
r = token(grant_type="refresh_token", refresh_token=RT, client_id=CID)
check(r.status_code == 400 and j(r).get("error") == "invalid_grant", "the old refresh token again: invalid_grant")
check(mcp(t6.get("access_token", ""), {"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401, "... and the whole access ends")
r = token(grant_type="refresh_token", refresh_token=t6.get("refresh_token", ""), client_id=CID)
check(r.status_code == 400, "... its newest refresh token too")

# ---------------------------------------------------------------- Settings > Agents: list and revoke; /oauth/revoke
tk = full()
check(mcp(tk.get("access_token", ""), {"jsonrpc": "2.0", "id": 1, "method": "ping"}).ok, "a new access")
gl = Fr.get(B + "/api/my/mcp-grants").json()
gs = [x for x in gl["grants"] if x["agent"]["id"] == AID]
check(gl["on"] and gl["url"].endswith("/mcp") and len(gs) == 1 and gs[0]["client"] == "Test Connector" and gs[0]["created_at"]
      and gs[0]["last_used_at"] and gs[0]["redirect_host"] == "127.0.0.1:9", f"Settings > Agents lists the access {gl}")
check(not [x for x in A.get(B + "/api/my/mcp-grants").json()["grants"] if x["agent"]["id"] == AID], "another person does not see it")
check(A.delete(B + f"/api/my/mcp-grants/{gs[0]['id']}").status_code == 404, "... nor revoke it")
check(Fr.delete(B + f"/api/my/mcp-grants/{gs[0]['id']}").ok, "she revokes it")
check(mcp(tk.get("access_token", ""), {"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401, "revoked: the access token is dead at once")
check(token(grant_type="refresh_token", refresh_token=tk.get("refresh_token", ""), client_id=CID).status_code == 400, "... and the refresh token")
tk = full()
r = requests.post(B + "/oauth/revoke", data={"token": tk.get("refresh_token", ""), "client_id": CID})
check(r.status_code == 200, "RFC 7009 revoke: 200")
check(mcp(tk.get("access_token", ""), {"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401, "revoked by the client: access token dead")

# ---------------------------------------------------------------- a new personal agent from the consent page
v7, ch7 = pkce()
r = consent(Fr, "new", ch7, username="frida-conn", display_name="Frida Conn")
c7, _ = code_of(r.headers.get("Location", ""))
na = dbx("SELECT a.user_id FROM agents a JOIN users u ON u.id=a.user_id WHERE u.username='frida-conn' AND a.owner_id=?", (FID,))
check(r.status_code == 303 and c7 and na, f"a new personal agent of hers from the consent page ({r.status_code})")
r = token(grant_type="authorization_code", code=c7, redirect_uri=CB, client_id=CID, code_verifier=v7)
check(r.ok and dbx("SELECT 1 FROM api_tokens WHERE user_id=? AND name LIKE 'MCP:%'", (na[0][0] if na else 0,)), "its token")
r = consent(Fr, "new", pkce()[1], username="frida-conn", display_name="Again")
check(r.status_code == 400 and "Location" not in r.headers, "a taken user name: the page again with the problem")

# ---------------------------------------------------------------- the instance admin connects a team agent
tk = full(TEAM, A)
check(tk.get("access_token") and mcp(tk["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "ping"}).ok, "the admin connects a team agent")

# ---------------------------------------------------------------- the registration limit, switched off again
n429 = 0
for i in range(25):
    if requests.post(B + "/oauth/register", json={"redirect_uris": [CB], "client_name": f"n{i}"}).status_code == 429:
        n429 += 1
check(n429 > 0, f"registrations per address are limited ({n429} refused)")
check(A.patch(B + "/api/admin/settings", json={"mcp_remote": False}).ok, "switched off")
check(requests.post(B + "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={"Authorization": "Bearer " + tk.get("access_token", "")}).status_code == 404,
      "off: /mcp 404 also with a valid token")
check(requests.get(B + "/.well-known/oauth-authorization-server").status_code == 404, "off: the metadata 404")

sys.exit(done("p2488_mcp_oauth"))
