#!/usr/bin/env python3
"""2.144.0 API tests, part D (#797 the hosting operator's interface, #2158 supporter licence prices), own container.
Invented people only (example.com).
tenant-matrix: operator
freelancer-matrix: personal
 - #797 off by default: without KALMIDO_OPERATOR_TOKEN_FILE every /api/operator/... route answers 404, with or without a token
 - with a token file: no / a wrong token = 401; the admin's session cookie, a personal access token and a person without an
   organisation get 401; the right token gets the numbers: version, people, organisations, active people, storage, backups
 - the answers carry no person or content: no user names, display names, e-mail addresses, list / task titles, the notice's text
 - the first admin: POST /api/operator/setup-code gives a one-time code for the setup page (only while no account exists, 409 after)
 - PUT /api/operator/notice sets / clears the maintenance notice (no push), a wrong level is refused
 - the token never appears in the server's log; too many wrong tokens from one address are blocked (429)
 - #2158: /api/about names the prices (person 25, server 100, EUR); no buy link by default, KALMIDO_SUPPORT_URL=default = the
   purchase page; a hosted server carries none of the supporter fields
usage: p2144_d_api_test.py <datadir>      (P2144D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import secrets
import shutil
import subprocess
import sys

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CONTAINER = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]
NOSTART = os.environ.get("P2144D_NOSTART") == "1"


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


def op(method, path, tok=None, **kw):
    hd = {"Authorization": "Bearer " + tok} if tok else {}
    return requests.request(method, B + "/api/operator/" + path, headers=hd, timeout=30, **kw)


# the token file lives next to the data dir (start.sh wipes the data dir itself) and is mounted read-only
OPDIR = os.path.abspath(DATA.rstrip("/")) + "-op"
TOKEN = secrets.token_urlsafe(40)
BASE = os.environ.get("EXTRA", "")
OPENV = f" -v {OPDIR}:/run/kop:ro -e KALMIDO_OPERATOR_TOKEN_FILE=/run/kop/token"


def start(extra="", keep=False, **env):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True,
                       env=dict(os.environ, EXTRA=BASE + extra, **({"KEEP": "1"} if keep else {}), **env))
    assert r.returncode == 0, r.stdout + r.stderr


def walk_keys(x, out):
    if isinstance(x, dict):
        for k, v in x.items():
            out.add(k)
            walk_keys(v, out)
    elif isinstance(x, list):
        for v in x:
            walk_keys(v, out)
    return out


if NOSTART:  # a running server cannot be restarted with the token: only the "off" part
    check(op("GET", "status").status_code == 404, "off: status 404")
    print(f"p2144_d_api: {OKS[0]} ok, {len(FAILS)} failed")
    sys.exit(1 if FAILS else 0)

# ---------------------------------------------------------------- #797 off by default
start()
for m, p in (("GET", "status"), ("POST", "setup-code"), ("PUT", "notice")):
    check(op(m, p).status_code == 404, f"off: {m} {p} without a token 404")
    check(op(m, p, TOKEN).status_code == 404, f"off: {m} {p} with a token 404")
r = requests.get(B + "/api/does-not-exist-2144")
check(op("GET", "status").status_code == r.status_code, "off: looks exactly like a route that does not exist")

# ---------------------------------------------------------------- on: a token file, the setup code check active
shutil.rmtree(OPDIR, ignore_errors=True)
os.makedirs(OPDIR)
with open(os.path.join(OPDIR, "token"), "w") as f:
    f.write(TOKEN + "\n")
os.chmod(OPDIR, 0o755)
os.chmod(os.path.join(OPDIR, "token"), 0o644)
start(OPENV, KALMIDO_SETUP_CODE="")
check(op("GET", "status").status_code == 401, "on: no token 401")
check(op("GET", "status", "x" * 40).status_code == 401, "on: a wrong token 401")
check(op("GET", "status", TOKEN[:-1]).status_code == 401, "on: the token minus one character 401")
check(op("GET", "status", TOKEN + "x" * 600).status_code == 401, "on: an overlong token 401")
r = requests.get(B + "/api/operator/status", headers={"Authorization": "Basic " + TOKEN})
check(r.status_code == 401, "on: the token as another scheme 401")
r = op("GET", "status", TOKEN)
check(r.ok, f"on: status with the token {r.status_code} {r.text[:200]}")
j0 = r.json() if r.ok else {}
check(j0.get("setup_done") is False and j0.get("people", {}).get("total") == 0, f"a fresh instance: no account yet {j0.get('people')}")
check(isinstance(j0.get("version"), str) and j0.get("ok") is True, "status: version + ok")

# ---- the first admin: a one-time setup code for the setup page
r = op("POST", "setup-code", TOKEN)
check(r.ok and isinstance(r.json().get("setup_code"), str), f"setup code {r.status_code} {r.text[:200]}")
CODE = r.json().get("setup_code", "") if r.ok else ""
s0 = requests.Session()
s0.headers.update(H)
r = s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123", "setup_code": "zzzz-zzzz-zzzz"})
check(r.status_code == 403, f"a wrong setup code is refused {r.status_code}")
r = s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123", "setup_code": CODE})
check(r.ok, f"the operator's setup code creates the first admin {r.status_code} {r.text[:200]}")
r = op("POST", "setup-code", TOKEN)
check(r.status_code == 409 and r.json().get("code") == "setup_done", f"after the setup: no code any more {r.status_code}")

# ---- content the operator must never see
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "bobsecret", "display_name": "Bobby Hiddenname", "password": "password123",
                                   "email": "bob.hidden@example.com"})
assert r.ok, r.text
Bo = sess("bobsecret")
r = A.post(B + "/api/admin/orgs", json={"name": "Orgname Confidential"})
check(r.ok, f"an organisation {r.status_code} {r.text[:200]}")
L = A.post(B + "/api/lists", json={"name": "Listname Topsecret"}).json()["id"]
A.post(B + "/api/tasks", json={"title": "Tasktitle Classified", "list_id": L, "notes": "Notes Private"})
A.put(B + "/api/admin/announcement", json={"text": "Admintext Hidden", "level": "info"})
FID, Fr = freelancer(B, A, "frieda")
r = op("GET", "status", TOKEN)
check(r.ok, "status with content on the server")
j = r.json() if r.ok else {}
raw = r.text.lower()
for word in ("alice", "bobsecret", "hiddenname", "example.com", "orgname", "confidential", "listname", "tasktitle", "notes private",
             "admintext", "frieda", "password", TOKEN.lower()):
    check(word not in raw, f"status: no content ({word})")
keys = walk_keys(j, set())
for k in ("title", "name", "email", "username", "display_name", "text", "notes", "token", "setup_code"):
    check(k not in keys, f"status: no field {k}")
pe = j.get("people", {})
check(pe.get("total") == 3 and pe.get("disabled") == 0, f"people counted {pe}")
check(pe.get("active_30d", 0) >= 2 and pe.get("active_7d", 0) >= 2, f"active people counted {pe}")
check(j.get("organisations", 0) >= 1, f"organisations counted {j.get('organisations')}")
check(j.get("setup_done") is True, "setup done")
st = j.get("storage", {})
check(isinstance(st.get("files_bytes"), int) and isinstance(st.get("db_bytes"), int) and st.get("db_bytes") > 0, f"storage {st}")
check(isinstance(j.get("backup"), dict) and "on" in j["backup"], "backup state")
check(j.get("notice") == {"level": "info", "active": True, "starts_at": "", "ends_at": ""} or
      (j.get("notice") or {}).get("level") == "info", f"the notice: level only {j.get('notice')}")

# ---- nobody but the token: the admin's cookie, a personal access token, a person without an organisation
check(A.get(B + "/api/operator/status").status_code == 401, "the instance admin's session: 401")
check(A.post(B + "/api/operator/setup-code").status_code == 401, "the instance admin's session: setup code 401")
check(A.put(B + "/api/operator/notice", json={"text": "x", "level": "maintenance"}).status_code == 401, "the instance admin's session: notice 401")
r = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "write"]})
if r.ok:
    pat = r.json()["token"]
    check(op("GET", "status", pat).status_code == 401, "a personal access token: 401")
check(Fr.get(B + "/api/operator/status").status_code == 401, "a person without an organisation: 401")
check(Bo.get(B + "/api/operator/status").status_code == 401, "a member: 401")
check(A.get(B + "/api/operator/status", headers={"Authorization": "Bearer " + TOKEN}).ok,
      "the token works with or without a session (the token is the credential)")

# ---- the maintenance notice (no push), cleared again
r = op("PUT", "notice", TOKEN, json={"text": "Maintenance tonight", "level": "maintenance", "minutes": 30, "push": True})
check(r.ok and (r.json().get("notice") or {}).get("level") == "maintenance", f"maintenance notice set {r.status_code} {r.text[:200]}")
check("Maintenance tonight" not in r.text, "the answer does not repeat the text")
n = (r.json().get("notice") or {}) if r.ok else {}
check(n.get("active") is True and n.get("ends_at"), f"active with an end {n}")
check(op("GET", "status", TOKEN).json().get("notice", {}).get("level") == "maintenance", "status shows the maintenance level")
check(op("PUT", "notice", TOKEN, json={"text": "x", "level": "panic"}).status_code == 400, "a wrong level 400")
check(op("PUT", "notice", TOKEN, json={"text": "x" * 600}).status_code == 400, "an overlong text 400")
r = op("PUT", "notice", TOKEN, json={"text": ""})
check(r.ok and r.json().get("notice") is None, f"an empty text clears the notice {r.text[:200]}")
check(op("GET", "status", TOKEN).json().get("notice") is None, "cleared")

# ---- #2158 the prices; no buy link by default
j = A.get(B + "/api/about").json()
check(j.get("support_prices") == {"currency": "EUR", "person": 25, "server": 100}, f"about: the prices {j.get('support_prices')}")
check(j.get("support_url") == "", f"about: no buy link by default {j.get('support_url')!r}")
check(Fr.get(B + "/api/about").json().get("support_prices", {}).get("person") == 25, "a person without an organisation sees the prices")

# ---- the token never in the log
lg = subprocess.run(["docker", "logs", CONTAINER], capture_output=True, text=True)
logtext = lg.stdout + lg.stderr
check("operator interface on" in logtext, "the log says the interface is on")
check("operator: status from" in logtext, "operator calls are logged")
check(TOKEN not in logtext and TOKEN[:16] not in logtext, "the token is never logged")

# ---- too many wrong tokens from one address: blocked (also the right one, for a while)
codes = [op("GET", "status", "w" * 40).status_code for _ in range(22)]
check(codes[-1] == 429, f"too many wrong tokens: 429 ({codes[-3:]})")
check(op("GET", "status", TOKEN).status_code == 429, "blocked for a while, the right token too")

# ---- a too short token file: off (404)
with open(os.path.join(OPDIR, "token"), "w") as f:
    f.write("short\n")
start(OPENV, keep=True, KALMIDO_SUPPORT_URL="default")
check(op("GET", "status", "short").status_code == 404, "a too short token: the interface stays off")
A = sess("alice")
check(A.get(B + "/api/about").json().get("support_url") == "https://kalmido.com/support.html", "KALMIDO_SUPPORT_URL=default: the purchase page")

# ---- hosted: no supporter fields (the prices neither)
start(f" -e KALMIDO_HOSTED=1 -e KALMIDO_SECRET_KEY={'A' * 43}=", keep=True)
A = sess("alice")
j = A.get(B + "/api/about").json()
check(not any(k in j for k in ("support_prices", "support_url", "supporter")), f"hosted: no supporter fields ({sorted(j)[:8]})")

shutil.rmtree(OPDIR, ignore_errors=True)
print(f"p2144_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
