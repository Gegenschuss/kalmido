#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.485.0 B (#3939) API tests, own container: the hosting operator's console handles one customer's account -- lock,
unlock, storage quota and delete -- without content (the routes of admin/operator.py, after p2144_d_api_test.py).
Invented people only (example.com).
tenant-matrix: operator
freelancer-matrix: operator (a person without an organisation is found, locked, unlocked and deleted like everybody else)
 - off by default: every new route answers 404; on: no / a wrong token 401, the instance admin's session cookie 401
 - POST /api/operator/accounts/find {email} -> the account by number (unknown address / an agent's: 404); GET by number
 - the answers carry no name, display name, e-mail address or title -- only numbers, states and days
 - PUT {disabled: true} ends the sessions and the sign-in fails; {disabled: false} -> the sign-in works again; the last
   active admin cannot be locked (409); is_admin / other fields are refused (400)
 - PUT {storage_quota_mb} sets / resets (null) the own quota; out of range 400; PUT /api/operator/quota-default
 - DELETE ?confirm=<id>: without / with a wrong confirm 400; own projects 409 code projects with the number; a server admin
   409 code admin; an agent 404; without projects the account is gone (404 afterwards), the log names it by number only
 - the e-mail address used for find never appears in the server log
usage: p2485_b_api_test.py <datadir>"""
import os
import secrets
import shutil
import subprocess
import sys

import requests

import kt
from kt import B, CT, check, sess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else kt.DATA
OPDIR = os.path.abspath(DATA.rstrip("/")) + "-op"
TOKEN = secrets.token_urlsafe(40)
OPENV = f" -v {OPDIR}:/run/kop:ro -e KALMIDO_OPERATOR_TOKEN_FILE=/run/kop/token"
BASE = os.environ.get("EXTRA", "")


def op(method, path, tok=None, **kw):
    hd = {"Authorization": "Bearer " + tok} if tok else {}
    return requests.request(method, B + "/api/operator/" + path, headers=hd, timeout=60, **kw)


def start(extra="", keep=False):
    env = dict(os.environ, EXTRA=(BASE + extra).strip())
    if keep:
        env["KEEP"] = "1"
    else:
        env.pop("KEEP", None)
    r = subprocess.run(["bash", os.path.join(os.path.dirname(os.path.abspath(__file__)), "start.sh"), DATA],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr


def no_content(r, words, what):
    raw = r.text.lower()
    for w in words:
        check(w.lower() not in raw, f"{what}: no content ({w})")
    for k in ('"name"', '"email"', '"username"', '"display_name"', '"title"'):
        check(k not in raw, f"{what}: no field {k}")


def can_login(user):
    s = requests.Session()
    s.headers.update(kt.H)
    return s.post(B + "/api/auth/login", json={"username": user, "password": kt.PASSWORD}).ok


ROUTES = (("POST", "accounts/find"), ("GET", "accounts/2"), ("PUT", "accounts/2"), ("DELETE", "accounts/2?confirm=2"),
          ("PUT", "quota-default"))

# ---------------------------------------------------------------- off by default
start()
for m, p in ROUTES:
    check(op(m, p, json={}).status_code == 404, f"off: {m} {p} without a token 404")
    check(op(m, p, TOKEN, json={}).status_code == 404, f"off: {m} {p} with a token 404")

# ---------------------------------------------------------------- on
shutil.rmtree(OPDIR, ignore_errors=True)
os.makedirs(OPDIR)
with open(os.path.join(OPDIR, "token"), "w") as f:
    f.write(TOKEN + "\n")
os.chmod(OPDIR, 0o755)
os.chmod(os.path.join(OPDIR, "token"), 0o644)
start(OPENV)
A = kt.setup()
AID = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"username": "bobsecret", "display_name": "Bobby Hiddenname", "password": kt.PASSWORD,
                                   "email": "bob.hidden@example.com"})
assert r.ok, r.text
BID = r.json()["id"]
Bo = sess("bobsecret")
L = Bo.post(B + "/api/lists", json={"name": "Listname Topsecret"}).json()["id"]
Bo.post(B + "/api/tasks", json={"title": "Tasktitle Classified", "list_id": L})
r = A.post(B + "/api/users", json={"username": "carlquiet", "display_name": "Carl Quietname", "password": kt.PASSWORD,
                                   "email": "carl.quiet@example.com"})
assert r.ok, r.text
CID = r.json()["id"]
FID, Fr = freelancer(B, A, "frieda")
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "robotagent", "display_name": "Robot Agentname"})
check(ag.status_code == 201, f"an agent {ag.status_code} {ag.text[:200]}")
GID = ag.json().get("id") if ag.ok else 0
WORDS = ("alice", "bobsecret", "hiddenname", "example.com", "listname", "tasktitle", "carlquiet", "quietname", "frieda",
         "robotagent", "agentname", TOKEN)

# ---- nobody but the token
for m, p in ROUTES:
    check(op(m, p, json={}).status_code == 401, f"on: {m} {p} without a token 401")
    check(op(m, p, "x" * 40, json={}).status_code == 401, f"on: {m} {p} with a wrong token 401")
    check(A.request(m, B + "/api/operator/" + p, json={}).status_code == 401, f"on: {m} {p} with the admin's session 401")
check(Fr.post(B + "/api/operator/accounts/find", json={"email": "frieda@example.com"}).status_code == 401,
      "a person without an organisation: 401")
for p in ("accounts/x", "accounts/0", "accounts/2/x", "accounts", "accounts/"):
    check(op("GET", p, TOKEN).status_code in (401, 403, 404, 405), f"foreign path /api/operator/{p} not served")

# ---- find + get: numbers only
r = op("POST", "accounts/find", TOKEN, json={"email": "Bob.Hidden@Example.com"})
check(r.ok and r.json()["account"]["id"] == BID, f"find by address (any case) {r.status_code} {r.text[:200]}")
no_content(r, WORDS, "find")
acc = r.json().get("account", {}) if r.ok else {}
check(acc.get("disabled") is False and acc.get("is_admin") is False and acc.get("projects") == 1, f"find: the states {acc}")
check(len(acc.get("created", "")) == 10 and len(acc.get("last_active", "")) == 10, f"find: days only {acc}")
st = acc.get("storage", {})
check(isinstance(st.get("files_bytes"), int) and st.get("quota_mb") is None and isinstance(st.get("effective_mb"), int),
      f"find: storage {st}")
check(op("POST", "accounts/find", TOKEN, json={"email": "nobody@example.com"}).status_code == 404, "an unknown address 404")
check(op("POST", "accounts/find", TOKEN, json={"email": ""}).status_code == 400, "an empty address 400")
check(op("POST", "accounts/find", TOKEN, json={"email": "x" * 300}).status_code == 400, "an overlong address 400")
check(op("POST", "accounts/find", TOKEN, json=["a"]).status_code == 400, "not an object 400")
r = op("GET", f"accounts/{AID}", TOKEN)
check(r.ok and r.json()["account"]["is_admin"] is True, f"get the admin {r.status_code}")
no_content(r, WORDS, "get")
check(op("GET", f"accounts/{GID}", TOKEN).status_code == 404, "an agent: 404")
check(op("GET", "accounts/999999", TOKEN).status_code == 404, "an unknown number: 404")

# ---- lock / unlock
r = op("PUT", f"accounts/{BID}", TOKEN, json={"disabled": True})
check(r.ok and r.json()["account"]["disabled"] is True, f"locked {r.status_code} {r.text[:200]}")
no_content(r, WORDS, "put")
check(Bo.get(B + "/api/state").status_code == 401, "locking ended the session")
check(not can_login("bobsecret"), "a locked account cannot sign in")
r = op("PUT", f"accounts/{BID}", TOKEN, json={"disabled": False})
check(r.ok and r.json()["account"]["disabled"] is False, f"unlocked {r.status_code}")
check(can_login("bobsecret"), "unlocked: the sign-in works again")
check(op("PUT", f"accounts/{AID}", TOKEN, json={"disabled": True}).status_code == 409, "the last active admin: 409")
check(can_login("alice"), "the admin stays unlocked")
check(op("PUT", f"accounts/{BID}", TOKEN, json={"is_admin": True}).status_code == 400, "the admin right: 400")
check(op("PUT", f"accounts/{BID}", TOKEN, json={"display_name": "x"}).status_code == 400, "another field: 400")
check(op("PUT", f"accounts/{BID}", TOKEN, json={"disabled": "yes"}).status_code == 400, "disabled not a bool: 400")
check(op("PUT", f"accounts/{GID}", TOKEN, json={"disabled": True}).status_code == 404, "an agent cannot be locked here: 404")
check(op("GET", f"accounts/{BID}", TOKEN).json()["account"]["is_admin"] is False, "still no admin")

# ---- quota
r = op("PUT", f"accounts/{BID}", TOKEN, json={"storage_quota_mb": 500})
check(r.ok and r.json()["account"]["storage"]["quota_mb"] == 500 and r.json()["account"]["storage"]["effective_mb"] == 500,
      f"own quota set {r.text[:200]}")
for bad in (-1, 10_000_001, "5", True, 1.5):
    check(op("PUT", f"accounts/{BID}", TOKEN, json={"storage_quota_mb": bad}).status_code == 400, f"quota {bad!r}: 400")
r = op("PUT", f"accounts/{BID}", TOKEN, json={"storage_quota_mb": None})
check(r.ok and r.json()["account"]["storage"]["quota_mb"] is None, f"own quota reset {r.text[:200]}")
r = op("PUT", "quota-default", TOKEN, json={"storage_quota_mb": 250})
check(r.ok and r.json().get("storage_quota_mb") == 250 and r.json().get("effective_mb") == 250, f"default quota {r.text[:200]}")
check(op("GET", f"accounts/{BID}", TOKEN).json()["account"]["storage"]["effective_mb"] == 250, "the default applies")
check(op("PUT", "quota-default", TOKEN, json={"storage_quota_mb": -3}).status_code == 400, "default quota out of range: 400")
check(op("PUT", "quota-default", TOKEN, json={}).status_code == 400, "default quota missing: 400")
r = op("PUT", "quota-default", TOKEN, json={"storage_quota_mb": None})
check(r.ok and r.json().get("storage_quota_mb") is None, f"default quota reset {r.text[:200]}")

# ---- delete
check(op("DELETE", f"accounts/{CID}", TOKEN).status_code == 400, "delete without confirm: 400")
check(op("DELETE", f"accounts/{CID}?confirm={BID}", TOKEN).status_code == 400, "delete with another number: 400")
r = op("DELETE", f"accounts/{BID}?confirm={BID}", TOKEN)
check(r.status_code == 409 and r.json().get("code") == "projects" and r.json().get("projects") == 1,
      f"own projects: 409 with the number {r.status_code} {r.text[:200]}")
no_content(r, WORDS, "delete refused")
check(can_login("bobsecret"), "refused: the account stays")
r = op("DELETE", f"accounts/{AID}?confirm={AID}", TOKEN)
check(r.status_code == 409 and r.json().get("code") == "admin", f"a server admin: 409 {r.status_code}")
check(op("DELETE", f"accounts/{GID}?confirm={GID}", TOKEN).status_code == 404, "an agent: 404")
r = op("DELETE", f"accounts/{CID}?confirm={CID}", TOKEN)
check(r.ok and r.json().get("deleted") == CID, f"deleted without projects {r.status_code} {r.text[:200]}")
no_content(r, WORDS, "delete")
check(op("GET", f"accounts/{CID}", TOKEN).status_code == 404, "deleted: gone")
check(not can_login("carlquiet"), "deleted: no sign-in")
check(op("DELETE", f"accounts/{CID}?confirm={CID}", TOKEN).status_code == 404, "deleted twice: 404")
check(A.get(B + "/api/state").ok, "the app's admin keeps working")

# ---- freelancer-matrix: operator -- a person without an organisation, like everybody else
r = op("POST", "accounts/find", TOKEN, json={"email": "frieda@example.com"})
check(r.ok and r.json()["account"]["id"] == FID and r.json()["account"]["orgs"] == 0, f"freelancer: found {r.text[:200]}")
no_content(r, WORDS, "freelancer find")
r = op("PUT", f"accounts/{FID}", TOKEN, json={"disabled": True})
check(r.ok and Fr.get(B + "/api/state").status_code == 401 and not can_login("frieda"), "freelancer: locked, signed out")
check(op("PUT", f"accounts/{FID}", TOKEN, json={"disabled": False}).ok and can_login("frieda"), "freelancer: unlocked")
r = op("DELETE", f"accounts/{FID}?confirm={FID}", TOKEN)
check(r.ok, f"freelancer: deleted {r.status_code} {r.text[:200]}")
check(op("GET", f"accounts/{FID}", TOKEN).status_code == 404 and not can_login("frieda"), "freelancer: gone")

# ---- the app's own deletion still works (the shared core, accounts/users.user_delete_run)
r = A.delete(B + f"/api/users/{BID}")
check(r.status_code == 409, f"app: projects still block {r.status_code}")
r = A.delete(B + f"/api/users/{BID}?lists=delete&confirm=bobsecret")
check(r.ok and r.json().get("lists") == 1, f"app: deleted with its projects {r.status_code} {r.text[:200]}")

# ---- the log: actions by number, never the address or the token
lg = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
text = lg.stdout + lg.stderr
check(f"operator: account-delete #{CID}" in text, "the deletion is logged by number")
oplines = [ln for ln in text.splitlines() if "operator" in ln]
check(not any("@" in ln for ln in oplines), "the operator's log lines name no address")
for w in ("nobody@example.com", TOKEN, TOKEN[:16]):  # an address only the console used (the others get security mails)
    check(w.lower() not in text.lower(), f"never in the log: {w[:12]}...")

shutil.rmtree(OPDIR, ignore_errors=True)
sys.exit(kt.done("p2485_b_api"))
