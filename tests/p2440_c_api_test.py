#!/usr/bin/env python3
"""2.44.0 API tests, part C (#1517 set up an agent on a computer with one command), own container (start.sh). Invented names only.
 - POST /api/my/agents/{id}/setup-code (own agent) and /api/admin/agents/{id}/setup-code (admin): os mac | windows | linux,
   folder; a code lives 15 minutes, only its hash is stored; somebody else's agent = 404, a member without admin = 403
 - POST /api/agent-setup/redeem (no login, the code is the credential): gives a working agent token, the computer's name /
   folder / os stay on the token; a second redeem, an expired or a wrong code = 400; a used code never works again
 - several computers per agent (one token each), GET .../machines with connected / last contact; PUT /api/v1/agent/status
   {host} renames the computer of the token in use; an unknown field is still refused
 - DELETE .../machines/{tid} and POST /api/agent-setup/remove (the token itself) revoke exactly one computer
 - /agent-setup.sh and /agent-setup.ps1 are served without a login
 - redeem is rate limited per address (429 after 10 failures) -- last, since it locks this address for 15 minutes
usage: p2440_c_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def redeem(code, **kw):
    return requests.post(B + "/api/agent-setup/redeem", headers=H, json={"code": code, **kw})


def tokh(tok):
    return {"Authorization": "Bearer " + tok}


if not os.environ.get("P2440_C_NOSTART"):  # (a quick local run against a running server sets it)
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
r = Bo.post(B + "/api/my/agents", json={"username": "bobs-helper", "display_name": "Helper"})
check(r.ok, "bob creates a personal agent " + r.text[:200])
AID = r.json()["id"]

# ---- issue
r = Bo.post(B + f"/api/my/agents/{AID}/setup-code", json={"os": "mac", "folder": "~/projects/site"})
check(r.ok and r.json()["code"].startswith("ks_") and r.json()["ttl_min"] == 15 and r.json()["os"] == "mac", "owner gets a code " + r.text[:200])
CODE = r.json()["code"]
row = dbx.connect(DATA).execute("SELECT * FROM agent_setup_codes WHERE agent_id=?", (AID,)).fetchone()
check(row and CODE not in str(dict(row)) and len(row["code_hash"]) >= 40, "only the hash of the code is stored")
check(Bo.post(B + f"/api/my/agents/{AID}/setup-code", json={"os": "amiga", "folder": "x"}).status_code == 400, "unknown os = 400")
check(Bo.post(B + f"/api/my/agents/{AID}/setup-code", json={"os": "linux", "folder": "a\nb"}).status_code == 400, "control characters in the folder = 400")
check(Ca.post(B + f"/api/my/agents/{AID}/setup-code", json={"os": "mac", "folder": "x"}).status_code == 404, "somebody else's agent: 404")
check(Ca.post(B + f"/api/admin/agents/{AID}/setup-code", json={"os": "mac", "folder": "x"}).status_code == 403, "no admin: 403 on the admin route")
check(requests.post(B + f"/api/my/agents/{AID}/setup-code", headers=H, json={"os": "mac"}).status_code == 401, "no login: 401")
r = A.post(B + f"/api/admin/agents/{AID}/setup-code", json={"os": "windows", "folder": "C:\\work\\site"})
check(r.ok, "an admin may issue a code for any agent " + r.text[:200])
CODE_W = r.json()["code"]

# ---- redeem
r = redeem(CODE, host="studio-mac", folder="/Users/demo/projects/site", os="mac")
check(r.ok and r.json()["token"].startswith("abk_") and r.json()["agent"]["id"] == AID and r.json()["starter_base"], "redeem gives the token " + r.text[:100])
TOK = r.json()["token"]
check(requests.get(V + "/agent", headers=tokh(TOK)).ok, "the token works for the agent API")
r2 = redeem(CODE)
check(r2.status_code == 400 and "expired" in r2.json()["error"], "a second redeem of the same code = 400")
check(redeem("ks_" + "x" * 24).status_code == 400, "a wrong code = 400")
check(redeem("").status_code == 400, "no code = 400")
r = Bo.post(B + f"/api/my/agents/{AID}/setup-code", json={"os": "linux", "folder": "/srv/x"})
OLD = r.json()["code"]
dbx.connect(DATA).execute("UPDATE agent_setup_codes SET expires_at=? WHERE code_hash=(SELECT code_hash FROM agent_setup_codes ORDER BY id DESC LIMIT 1)",
                          ("2020-01-01T00:00:00+00:00",))
check(redeem(OLD).status_code == 400, "an expired code = 400")
r = redeem(CODE_W, host="office-pc")
check(r.ok, "a second computer for the same agent " + r.text[:100])
TOK_W = r.json()["token"]
check(requests.get(V + "/agent", headers=tokh(TOK)).ok, "the first computer keeps working")

ms = Bo.get(B + f"/api/my/agents/{AID}/machines").json()["machines"]
mac = next((m for m in ms if m["host"] == "studio-mac"), None)
win = next((m for m in ms if m["host"] == "office-pc"), None)
check(mac and mac["os"] == "mac" and mac["folder"] == "/Users/demo/projects/site" and mac["connected"], f"machine with os / folder / connected: {mac}")
check(win and win["os"] == "windows" and win["folder"] == "C:\\work\\site", f"the folder of the code when the script sends none: {win}")
check(Ca.get(B + f"/api/my/agents/{AID}/machines").status_code == 404, "somebody else cannot list the computers")
check(A.get(B + f"/api/admin/agents/{AID}/machines").ok, "an admin lists them")
check(all("token" not in m and "token_hash" not in m for m in ms), "no token / hash in the list")

# ---- the starter reports its host
r = requests.put(V + "/agent/status", headers=tokh(TOK), json={"status": "idle", "host": "studio-mac-2"})
check(r.ok, "PUT status with host " + r.text[:200])
ms = Bo.get(B + f"/api/my/agents/{AID}/machines").json()["machines"]
check(any(m["host"] == "studio-mac-2" for m in ms) and any(m["host"] == "office-pc" for m in ms), "the host of the token in use is renamed, the other stays")
check(requests.put(V + "/agent/status", headers=tokh(TOK), json={"status": "idle", "host": "x" * 81}).status_code == 400, "host too long = 400")
check(requests.put(V + "/agent/status", headers=tokh(TOK), json={"status": "idle", "hostname": "y"}).status_code == 400, "an unknown field is still refused")
r = requests.put(V + "/agent/status", headers=tokh(TOK), json={"status": "error", "text": "agent command not found on studio-mac: claude"})
check(r.ok and r.json()["status"] == "error", "an error status from the starter")

# ---- remove
wid = next(m["id"] for m in ms if m["host"] == "office-pc")
check(Ca.delete(B + f"/api/my/agents/{AID}/machines/{wid}").status_code == 404, "somebody else cannot remove a computer")
r = Bo.delete(B + f"/api/my/agents/{AID}/machines/{wid}")
check(r.ok and all(m["id"] != wid for m in r.json()["machines"]), "Remove computer")
check(requests.get(V + "/agent", headers=tokh(TOK_W)).status_code == 401, "its token stops at once")
check(requests.get(V + "/agent", headers=tokh(TOK)).ok, "the other computer keeps working")
check(Bo.delete(B + f"/api/my/agents/{AID}/machines/{wid}").status_code == 404, "removing twice = 404")
check(requests.post(B + "/api/agent-setup/remove", headers={**H, **tokh(TOK)}).ok, "the setup script's --uninstall revokes its own token")
check(requests.get(V + "/agent", headers=tokh(TOK)).status_code == 401, "... gone")

# ---- the scripts
for p, needle in (("/agent-setup.sh", "kalmido-setup-step: redeem"), ("/agent-setup.ps1", "kalmido-setup-step: redeem")):
    r = requests.get(B + p)
    check(r.ok and needle in r.text and r.headers.get("Content-Type", "").startswith("text/plain"), f"{p} served without a login")

# ---- rate limit (last: it locks this address for the login window)
codes = [redeem("ks_wrong%02d" % i).status_code for i in range(12)]
check(codes[0] == 400 and codes[-1] == 429, f"redeem is rate limited: {codes}")
r = Bo.post(B + f"/api/my/agents/{AID}/setup-code", json={"os": "mac", "folder": "/x"})
check(redeem(r.json()["code"]).status_code == 429, "while locked even a valid code waits")

print(f"p2440_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
