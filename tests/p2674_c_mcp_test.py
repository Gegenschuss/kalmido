#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.674.0 C (#4028): the rest of the review of 2.488.0 on the hosted MCP access (agents/mcpremote.py), against a test client.
freelancer-matrix: agents (a person without an organisation connects her own agent; the 90-day end and the clean-up apply to her)
 - F10: an /mcp body without Content-Length (Transfer-Encoding: chunked) is read in pieces up to the limit (mcpr_body): a small
   one works, a large one is 413, and the server never reads more than the limit from the stream
 - F11: with PUBLIC_URL set the issuer and the accepted Origin come from it only, never from the Host header; the admin's
   about says whether PUBLIC_URL is set (Administration > Agents warns without it)
 - F12: an access ends 90 days after it was made (refresh refused, access revoked; no token outlives that day); the consent
   page writes a line into the agent's log (agent_audit: 201 = agent made there, 200 = an existing one); Administration >
   Agents lists the apps of team agents (who, when, last used, end) and revokes them, nobody else sees or revokes them
 - F13: revoked / run-out accesses and the revoked_creds rows of tokens ended 30 days ago are cleaned up (lgc_expired), rows
   without an end stay; a backup restored after the clean-up brings no working access back (review F2 of 2.488.0)
usage: p2674_c_mcp_test.py <datadir>      (KMT_NOSTART=1 / P2674C_NOSTART=1: a running server)"""
import base64
import hashlib
import html
import json
import re
import secrets
import subprocess
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from kt import B, CT, PASSWORD, check, dbx, done, fresh, sess, setup
from freelancer_fixture import freelancer, login

KEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (32 bytes, base64), kept over the restarts
PUB = "https://kalmido.example"
fresh(env={"KALMIDO_SECRET_KEY": KEY}, prefix="P2674C")
A = setup()
CB = "http://127.0.0.1:9/cb"


def in_app(code):
    """A few lines inside the container with the server's modules -> the last JSON line."""
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app, json\n" + code],
                       capture_output=True, text=True, timeout=300)
    for line in reversed((r.stdout or "").strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    print("container python:", r.returncode, (r.stdout or "")[-800:], (r.stderr or "")[-1500:], flush=True)
    return {}


def sha(v):
    return hashlib.sha256(v.encode()).hexdigest()


def j(r):
    try:
        return r.json()
    except ValueError:
        return {}


def pkce():
    v = secrets.token_urlsafe(48)
    return v, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def ts(days=0, hours=0):
    return (datetime.now(timezone.utc) + timedelta(days=days, hours=hours)).isoformat(timespec="seconds")


def pt(v):
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


check(A.get(B + "/api/about").json().get("public_url_set") is False, "F11: about: PUBLIC_URL not set (the admin pane warns)")
r = A.patch(B + "/api/admin/settings", json={"mcp_remote": True, "password": PASSWORD})
check(r.ok and r.json().get("mcp_remote") is True, f"the hosted MCP access switched on ({r.status_code})")
check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok, "personal agents allowed")
CID = requests.post(B + "/oauth/register", json={"redirect_uris": [CB], "client_name": "Test Connector"}).json()["client_id"]
FID, Fr = freelancer(B, A)
ag = Fr.post(B + "/api/my/agents", json={"username": "frida-mcp", "display_name": "Frida MCP"})
check(ag.status_code == 201, f"her agent {ag.status_code}")
AID = ag.json()["id"]
TEAM = A.post(B + "/api/admin/agents", json={"username": "teambot", "display_name": "Team Bot"}).json().get("id")


def authz_url(ch):
    q = {"response_type": "code", "client_id": CID, "redirect_uri": CB, "code_challenge": ch, "code_challenge_method": "S256", "state": "s1"}
    return B + "/oauth/authorize?" + urllib.parse.urlencode(q)


def consent(s, agent, ch, headers=None, **form):
    r = s.get(authz_url(ch), allow_redirects=False)
    m = re.search(r'name="t" value="([^"]+)"', r.text)
    return s.post(B + "/oauth/authorize", data={"t": html.unescape(m.group(1)) if m else "", "decision": "allow", "agent": str(agent), **form},
                  headers=headers or {}, allow_redirects=False)


def code_of(r):
    return (urllib.parse.parse_qs(urllib.parse.urlsplit(r.headers.get("Location", "")).query).get("code") or [""])[0]


def token(**f):
    return requests.post(B + "/oauth/token", data=f)


def full(agent=AID, s=None, **form):
    v, ch = pkce()
    r = token(grant_type="authorization_code", code=code_of(consent(s or Fr, agent, ch, **form)), redirect_uri=CB, client_id=CID, code_verifier=v)
    return r.json() if r.ok else {}


def refresh(tk):
    return token(grant_type="refresh_token", refresh_token=tk.get("refresh_token", ""), client_id=CID)


def grant_of(tk):
    g = dbx("SELECT id FROM oauth_grants WHERE refresh_hash=?", (sha(tk.get("refresh_token", "-")),))
    return g[0][0] if g else 0


def mcp(tok, body=None, **kw):
    h = {"Authorization": "Bearer " + tok, "Content-Type": "application/json", **kw.pop("headers", {})}
    return requests.post(B + "/mcp", data=body if body is not None else json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}), headers=h, **kw)


TK = full()
check(TK.get("access_token") and mcp(TK["access_token"]).ok, "setup: her access works")

# ================================================================ F10: chunked bodies
PING = json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"}).encode()
r = mcp(TK["access_token"], iter([PING[:10], PING[10:]]))  # a generator: requests sends Transfer-Encoding: chunked
check(r.status_code == 200 and j(r).get("id") == 9, f"F10: a small chunked body works ({r.status_code} {r.text[:120]})")
r = mcp(TK["access_token"], (b" " * 65536 for _ in range(20)))
check(r.status_code == 413, f"F10: a chunked body over the limit: 413 ({r.status_code})")
out = in_app(r"""
import io
from kalmido.core.config import app as fl
from kalmido.agents import mcpremote as mr
class Big(io.RawIOBase):
    n = 0
    def readable(self): return True
    def readinto(self, b):
        if Big.n >= 50_000_000: return 0
        k = len(b); b[:k] = b"x" * k; Big.n += k; return k
with fl.test_request_context("/mcp", method="POST", input_stream=io.BufferedReader(Big()), headers={"Transfer-Encoding": "chunked"},
                             environ_overrides={"wsgi.input_terminated": True}):
    raw = mr.mcpr_body()
print(json.dumps({"len": len(raw), "read": Big.n, "max": mr.MCPR_MAX_BODY}))
""")
check(out.get("len") == out.get("max", 0) + 1 and 0 < out.get("read", 10 ** 9) <= out.get("max", 0) + 200_000,
      f"F10: from a 50 MB chunked stream only the limit + 1 byte is read ({out})")

# ================================================================ F12: the agent's log for the consent page
na = full("new", Fr, username="frida-conn", display_name="Conn")
NA = (dbx("SELECT user_id FROM agents WHERE owner_id=? AND user_id<>?", (FID, AID)) or [(0,)])[0][0]
check(na.get("access_token") and NA, "F12: a new personal agent from the consent page")
rows = dbx("SELECT method, route, status, scope FROM agent_audit WHERE agent_id=? AND route='/oauth/authorize'", (NA,))
check(rows == [("POST", "/oauth/authorize", 201, "mcp")], f"F12: the agent made on the consent page is in its log ({rows})")
check(("POST", "/oauth/authorize", 200, "mcp") in dbx("SELECT method, route, status, scope FROM agent_audit WHERE agent_id=?", (AID,)),
      "F12: giving an existing agent to an app is in its log too")
r = A.get(B + f"/api/admin/agents/{NA}/audit")
check(r.ok and any(x.get("route") == "/oauth/authorize" for x in (j(r).get("data") or j(r).get("rows") or [])),
      f"F12: the admin reads it in the agent's log ({r.status_code} {r.text[:200]})")

# ================================================================ F12: 90 days at most
tk = full()
G = grant_of(tk)
dbx("UPDATE oauth_grants SET created_at=? WHERE id=?", (ts(-90, 2), G))  # made 90 days less 2 hours ago
r = refresh(tk)
tk2 = j(r)
row = dbx("SELECT refresh_expires_at FROM oauth_grants WHERE id=?", (G,))
check(r.ok and tk2.get("expires_in", 9999) <= 3600 and row and pt(row[0][0]) <= datetime.now(timezone.utc) + timedelta(hours=2, minutes=1),
      f"F12: near the end the new refresh token ends with the access, not 30 days later ({r.status_code} {row})")
dbx("UPDATE oauth_grants SET created_at=? WHERE id=?", (ts(-91), G))
r = refresh(tk2)
check(r.status_code == 400 and j(r).get("error") == "invalid_grant" and "90 days" in j(r).get("error_description", ""),
      f"F12: 90 days after the access was made the refresh is refused ({r.status_code} {r.text[:160]})")
check(dbx("SELECT revoked_at FROM oauth_grants WHERE id=?", (G,))[0][0] is not None, "F12: and the access is revoked")
check(not any(g["id"] == G for g in Fr.get(B + "/api/my/mcp-grants").json()["grants"]), "F12: it left her list")

# ================================================================ F12: Administration > Agents, the apps of team agents
tt = full(TEAM, A)
GT = grant_of(tt)
check(tt.get("access_token") and GT, "F12: the admin connects the team agent")
r = A.get(B + "/api/admin/mcp-grants")
L = {x["id"]: x for x in j(r).get("grants", [])}
x = L.get(GT, {})
check(r.ok and x.get("agent", {}).get("id") == TEAM and x.get("given_by", {}).get("name") == "Alice Admin" and x.get("client") == "Test Connector"
      and x.get("created_at") and x.get("last_used_at") and x.get("ends_at") and x.get("redirect_host") == "127.0.0.1:9",
      f"F12: the admin's list names agent, app, who, when, last use and end ({x})")
check(grant_of(TK) not in L, "F12: a personal agent's access is not in the admin's list (its owner manages it)")
check(Fr.get(B + "/api/admin/mcp-grants").status_code == 403, "F12: a person who is no admin: 403")
check(Fr.delete(B + f"/api/admin/mcp-grants/{GT}").status_code == 403, "F12: a person who is no admin cannot revoke it")
check(requests.get(B + "/api/admin/mcp-grants", headers={"Authorization": "Bearer " + tt["access_token"]}).status_code in (401, 403),
      "F12: never with the access token itself")
check(A.delete(B + f"/api/admin/mcp-grants/{grant_of(TK)}").status_code == 404, "F12: the admin cannot revoke her personal agent's access here")
check(A.delete(B + f"/api/admin/mcp-grants/{GT}").ok, "F12: the admin revokes the team agent's access")
check(refresh(tt).status_code == 400 and mcp(tt["access_token"]).status_code == 401, "F12: the app's tokens stop at once")
check(GT not in {x["id"] for x in A.get(B + "/api/admin/mcp-grants").json()["grants"]}, "F12: gone from the list")

# ================================================================ F13: the clean-up
tk = full()
G1 = grant_of(tk)
old_at = tk["access_token"]
r = refresh(tk)
tk = j(r)
ex = dbx("SELECT exp FROM revoked_creds WHERE hash=?", (sha(old_at),))
check(r.ok and ex and ex[0][0], f"F13: the rotated access token is in revoked_creds with its end ({ex})")
Fr.delete(B + f"/api/my/mcp-grants/{G1}")
tk3 = full()
G3 = grant_of(tk3)
Fr.delete(B + f"/api/my/mcp-grants/{G3}")  # revoked now: stays
tk4 = full()
G4 = grant_of(tk4)  # open, its refresh token ran out long ago: goes
dbx("UPDATE oauth_grants SET revoked_at=? WHERE id=?", (ts(-31), G1))
dbx("UPDATE oauth_grants SET refresh_expires_at=? WHERE id=?", (ts(-31), G4))
pt_tok = Fr.post(B + "/api/me/tokens", json={"name": "no end", "scopes": ["read"]}).json()
Fr.delete(B + f"/api/me/tokens/{pt_tok.get('id')}")
dbx("INSERT INTO revoked_creds(hash, at, exp) VALUES('f13-old', ?, ?), ('f13-new', ?, ?)", (ts(-60), ts(-31), ts(-1), ts(-1)))
dbx("UPDATE revoked_creds SET at=? WHERE hash=?", (ts(-400), sha(pt_tok.get("token", "-"))))
n_open = dbx("SELECT COUNT(*) FROM oauth_grants WHERE revoked_at IS NULL AND (refresh_expires_at IS NULL OR refresh_expires_at>?)", (ts(),))[0][0]
out = in_app("""
from kalmido.core.db import connect, now_utc
from kalmido.core.pg import system_ctx
from kalmido.admin.dataretention import lgc_expired
c = connect()
with system_ctx(c):
    o = lgc_expired(c, now_utc())
    c.commit()
print(json.dumps(o))
""")
lim = in_app("from kalmido.admin.dataretention import LGC_REVOKED_DAYS as a\nfrom kalmido.agents.mcpremote import MCPR_REFRESH_DAYS as b\n"
             "print(json.dumps({'clean': a, 'refresh': b}))")
check(lim.get("clean", 0) >= lim.get("refresh", 99), f"F13: the clean-up waits at least as long as a refresh token lives ({lim})")
check(out.get("oauth_grants", 0) >= 2 and out.get("revoked_creds", 0) >= 1, f"F13: the clean-up counts what went ({out})")
left = {r[0] for r in dbx("SELECT id FROM oauth_grants WHERE id IN (?,?,?)", (G1, G3, G4))}
check(left == {G3}, f"F13: an access revoked 31 days ago and one run out 31 days ago go, one revoked today stays ({left})")
check(n_open == dbx("SELECT COUNT(*) FROM oauth_grants WHERE revoked_at IS NULL AND (refresh_expires_at IS NULL OR refresh_expires_at>?)", (ts(),))[0][0],
      "F13: no open access is touched")
hs = {r[0] for r in dbx("SELECT hash FROM revoked_creds WHERE hash IN ('f13-old', 'f13-new', ?)", (sha(pt_tok.get("token", "-")),))}
check(hs == {"f13-new", sha(pt_tok.get("token", "-"))},
      f"F13: a row of a token ended 31 days ago goes; a token ended yesterday and a token without an end stay ({hs})")
check(mcp(tk["access_token"]).status_code == 401 and refresh(tk).status_code == 400, "F13: the cleaned-up access stays dead")

# ---------------------------------------------------------------- F13 + review F2: a restore after the clean-up
# the backup holds an access as it was 31 days ago (its token ended then, its refresh token at the latest 30 days later)
# and a personal token without an end; both are revoked after the backup, the clean-up runs, the backup comes back
tb = full()
GB = grant_of(tb)
dbx("UPDATE oauth_grants SET created_at=?, refresh_expires_at=? WHERE id=?", (ts(-31), ts(-1), GB))
dbx("UPDATE api_tokens SET expires_at=? WHERE token_hash=?", (ts(-31, 1), sha(tb["access_token"])))
pk = Fr.post(B + "/api/me/tokens", json={"name": "kept revoked", "scopes": ["read"]}).json()
BK = in_app("from kalmido.admin import backup as bk\nprint(json.dumps({'name': bk.bk_create('manual')}))").get("name")
check(BK, f"F13: a backup {BK}")
Fr.delete(B + f"/api/my/mcp-grants/{GB}")
Fr.delete(B + f"/api/me/tokens/{pk.get('id')}")
dbx("UPDATE oauth_grants SET revoked_at=? WHERE id=?", (ts(-31), GB))
in_app("""
from kalmido.core.db import connect, now_utc
from kalmido.core.pg import system_ctx
from kalmido.admin.dataretention import lgc_expired
c = connect()
with system_ctx(c):
    print(json.dumps(lgc_expired(c, now_utc())))
    c.commit()
""")
check(not dbx("SELECT 1 FROM oauth_grants WHERE id=?", (GB,)) and not dbx("SELECT 1 FROM revoked_creds WHERE hash=?", (sha(tb["access_token"]),))
      and dbx("SELECT 1 FROM revoked_creds WHERE hash=?", (sha(pk.get("token", "-")),)),
      "F13: the access and its ended token's row are cleaned up, the row of the token without an end stays")
r = A.post(B + "/api/admin/backups/restore", json={"name": BK, "confirm": "RESTORE", "password": PASSWORD})
check(r.ok, f"F13: the backup restored {r.status_code} {r.text[:160]}")
A, Fr = sess("alice"), login(B, "frida")
check(refresh(tb).status_code == 400, "F13 + F2: the restored access gives no new token (its refresh token had run out)")
check(mcp(tb["access_token"]).status_code == 401, "F13 + F2: its access token from the backup is expired")
check(requests.get(B + "/api/v1/me", headers={"Authorization": "Bearer " + pk.get("token", "-")}).status_code == 401,
      "review F2 still holds: a token without an end revoked after the backup stays revoked")

# ================================================================ F11: PUBLIC_URL set - issuer and Origin from it only
fresh(env={"KALMIDO_SECRET_KEY": KEY, "PUBLIC_URL": PUB}, prefix="P2674C", keep=True)
A = sess("alice")
check(A.get(B + "/api/about").json().get("public_url_set") is True, "F11: about: PUBLIC_URL set (no warning)")
for host in (None, "evil.example"):
    asm = requests.get(B + "/.well-known/oauth-authorization-server", headers={"Host": host} if host else {}).json()
    pr = requests.get(B + "/.well-known/oauth-protected-resource", headers={"Host": host} if host else {}).json()
    check(asm.get("issuer") == PUB and asm.get("token_endpoint") == PUB + "/oauth/token" and pr.get("resource") == PUB + "/mcp",
          f"F11: issuer and resource from PUBLIC_URL (Host {host}: {asm.get('issuer')} {pr.get('resource')})")
Fr = login(B, "frida")
tk = full(AID, Fr)
check(tk.get("access_token") and mcp(tk["access_token"]).ok, "F11: an access with PUBLIC_URL set")
check(mcp(tk["access_token"], headers={"Origin": PUB}).ok, "F11: Origin = PUBLIC_URL is accepted")
r = mcp(tk["access_token"], headers={"Origin": B})
check(r.status_code == 403, f"F11: the Origin of the Host header is refused when PUBLIC_URL is set ({r.status_code})")
r = mcp(tk["access_token"], headers={"Origin": "http://evil.example", "Host": "evil.example"})
check(r.status_code == 403, f"F11: a forged Host and the same Origin are refused ({r.status_code})")
r = consent(Fr, AID, pkce()[1], headers={"Origin": B})
check(r.status_code == 403, f"F11: the consent form from the Host header's origin is refused ({r.status_code})")
r = consent(Fr, AID, pkce()[1], headers={"Origin": PUB})
check(r.status_code == 303 and code_of(r), f"F11: the consent form from PUBLIC_URL works ({r.status_code})")

raise SystemExit(done("p2674_c_mcp"))
