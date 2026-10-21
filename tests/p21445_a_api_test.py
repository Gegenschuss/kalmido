#!/usr/bin/env python3
"""2.144.5 API tests, part A: the recovery key step-up of accounts without a password asks the OIDC provider for a real
sign-in (#2387), the small points of the same review (F7 test switch, F8 HTTP Shortcuts download without any origin
header) and approval cards in comments decided only by approvers (#2001). One container (start.sh) with a fake OIDC
provider inside (stub_oidc.py) and a KALMIDO_SECRET_KEY; invented names and the test IBAN only.
#2387:
 - the step-up start sends prompt=login and max_age=0, the normal login start does not; without a session no step-up
 - an OIDC session alone is no fresh sign-in any more (403 need fresh, stepup oidc); a step-up with an old auth_time,
   without auth_time or for another account does not count (#rck-stepup-error=...), a fresh one does (the key, 200);
   ten minutes later it is gone again; a password session of an account without a password keeps the earlier rule
 - as an organisation admin and as a person without an organisation (freelancer-matrix: orgcrypt, auth): the own
   personal office (organisation id 0)
 - F7: KALMIDO_TEST_ROT_ABORT alone is ignored (the rotation runs to the end), with KALMIDO_TEST_MODE=1 it aborts
 - F8: the HTTP Shortcuts download without Sec-Fetch-Site, Origin and Referer stays 403 but says why
#2001 (freelancer-matrix: approvals): an editor who is no approver gets 403 and choice_can false; a list admin and the
assignee decide (choice_can true); a person without an organisation decides the cards of the own agent in the own list
usage: p21445_a_api_test.py <datadir>      (P21445A_NOSTART=1 = the server already runs with OIDC + KALMIDO_SECRET_KEY)"""
import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
ISS = "http://127.0.0.1:9990"
SECRET = "s3cret:/x+y"
TEST_IBAN = "DE89370400440532013000"
O = "/api/office"
V = B + "/api/v1"
FEAT = "cal,comments,collab,office,clients,time,wiki"
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def pem(k):
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def start():
    if os.environ.get("P21445A_NOSTART") == "1":
        return
    key = base64.b64encode(os.urandom(32)).decode()
    extra = [f"-e KALMIDO_OIDC_ISSUER={ISS}", "-e KALMIDO_OIDC_CLIENT_ID=kalmido-test", f"-e KALMIDO_OIDC_CLIENT_SECRET={SECRET}",
             "-e KALMIDO_OIDC_BUTTON_LABEL=TestID", "-e KALMIDO_ORGCRYPT_DELAY=0", "-e KALMIDO_SECRET_KEY=" + key]
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(extra))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    od = os.path.join(DATA, "oidc")
    shutil.rmtree(od, ignore_errors=True)
    os.makedirs(os.path.join(od, "signing"))
    open(os.path.join(od, "signing", "k1.pem"), "wb").write(pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
    open(os.path.join(od, "evil.pem"), "wb").write(pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
    json.dump({}, open(os.path.join(od, "codes.json"), "w"))
    shutil.copy(os.path.join(N, "stub_oidc.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_oidc.py"])
    time.sleep(0.8)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def cli(*args, env=()):
    e = [x for k in env for x in ("-e", k)]
    r = subprocess.run(["docker", "exec", "-i", *e, CT, "python", "-m", "kalmido.admin.orgcrypt_cli", *args],
                       capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout, r.stderr


def query(loc):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(loc).query))


def give_code(q, claims):
    p = os.path.join(DATA, "oidc", "codes.json")
    codes = json.load(open(p))
    code = secrets.token_urlsafe(16)
    codes[code] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "claims": claims, "mode": "ok", "userinfo": None, "kid": None}
    json.dump(codes, open(p, "w"))
    return code


def oidc_login(claims):
    s = sess()
    r = s.get(B + "/api/auth/oidc/start", allow_redirects=False)
    loc = r.headers.get("Location", "")
    assert r.status_code == 302 and loc.startswith(ISS + "/authorize?"), (r.status_code, loc, r.text[:200])
    q = query(loc)
    r = s.get(B + "/api/auth/oidc/callback", params={"code": give_code(q, claims), "state": q["state"]}, allow_redirects=False)
    assert r.status_code == 303 and r.headers.get("Location") == "/", (r.status_code, r.headers.get("Location"))
    return s, q


def stepup(s, org, claims, what="show"):
    """-> (authorization query, where the callback sends the browser)."""
    r = s.get(B + "/api/auth/oidc/start", params={"stepup": what, "org": org}, allow_redirects=False)
    loc = r.headers.get("Location", "")
    if not loc.startswith(ISS + "/authorize?"):
        return {}, loc
    q = query(loc)
    r = s.get(B + "/api/auth/oidc/callback", params={"code": give_code(q, claims), "state": q["state"]}, allow_redirects=False)
    return q, r.headers.get("Location", "")


def show(s, org):
    return s.post(B + f"/api/orgs/{org}/encryption/recovery", json={})


# ---------------------------------------------------------------- set-up
start()
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
assert A.patch(B + "/api/admin/settings", json={"cal_allow_hosts": "127.0.0.1:9990"}).ok
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ids = {}
for u, n, pw in (("sven", "Sven Single", None), ("ed", "Ed Editor", "password123"), ("mia", "Mia Second", "password123"),
                  ("max", "Max Manager", "password123")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, **({"password": pw, "email": f"{u}@example.com"} if pw else {})})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]

# ================================================================== #2001: approval cards only for approvers
# (before the first organisation exists: everyone sees everyone, as on a server without organisations)
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "robo", "display_name": "Robo"}).json()
AGH = {"Authorization": "Bearer " + ag.get("token", "x")}
Ed = sess("ed")
Ed.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Mi = sess("max")
Mi.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
L = A.post(B + "/api/lists", json={"name": "Release work"}).json()["id"]
for uid, role in ((ids["ed"], "edit"), (ids["max"], "admin"), (ag.get("id"), "edit")):
    r = A.put(B + f"/api/lists/{L}/members", json={"user_id": uid, "role": role})
    assert r.ok, (uid, role, r.text)
A.patch(B + f"/api/lists/{L}", json={"agent_members": True})
T = A.post(B + "/api/tasks", json={"title": "Publish the cut", "list_id": L}).json()["id"]


def card(tid, title, h=AGH):
    r = requests.post(V + f"/tasks/{tid}/comments", headers=h, json={"body": "May I?", "approval": {"title": title}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def can(s, tid, cid):
    x = [c for c in s.get(B + f"/api/tasks/{tid}/timeline").json().get("comments", []) if c["id"] == cid]
    return x[0].get("choice_can") if x else "missing"


C1 = card(T, "Publish the cut")
check(can(Ed, T, C1) is False and can(Mi, T, C1) is True and can(A, T, C1) is True, f"#2001: choice_can ed / max / alice {can(Ed, T, C1)} {can(Mi, T, C1)} {can(A, T, C1)}")
r = Ed.post(B + f"/api/comments/{C1}/choice", json={"choice_ids": ["yes"]})
check(r.status_code == 403 and "approval" in r.json().get("error", ""), f"#2001: an editor who is no approver: 403 {r.status_code} {r.text[:150]}")
check(Ed.get(B + f"/api/comments/{C1}/choice").json().get("choice_state") == "open", "#2001: the card stays open")
r = Mi.post(B + f"/api/comments/{C1}/choice", json={"choice_ids": ["yes"]})
check(r.ok and r.json().get("choice_state") == "answered" and r.json().get("choice_can") is True, f"#2001: a list admin decides {r.status_code} {r.text[:150]}")
C2 = card(T, "Send the invoice")
A.patch(B + f"/api/tasks/{T}", json={"assignee_id": ids["ed"]})
check(can(Ed, T, C2) is True, "#2001: the assignee may decide (choice_can)")
r = Ed.post(B + f"/api/comments/{C2}/choice", json={"choice_ids": ["no"]})
check(r.ok and r.json().get("choice", {}).get("ids") == ["no"], f"#2001: the assignee decides {r.status_code} {r.text[:150]}")
T2 = A.post(B + "/api/tasks", json={"title": "Plain buttons", "list_id": L}).json()["id"]
r = requests.post(V + f"/tasks/{T2}/comments", headers=AGH, json={"body": "Which one?", "choices": ["Short", "Long"]})
QC = r.json().get("id")
r = Ed.post(B + f"/api/comments/{QC}/choice", json={"choice_ids": ["Short"]})
check(r.ok and "choice_can" not in r.json(), f"#2001: plain answer buttons stay open to editors {r.status_code} {r.text[:150]}")


# ================================================================== #2387: the normal login is unchanged
r = sess().get(B + "/api/auth/oidc/start", allow_redirects=False)
q0 = query(r.headers.get("Location", ""))
check(r.status_code == 302 and q0.get("state") and "prompt" not in q0 and "max_age" not in q0, f"#2387: the normal login start has no prompt / max_age {q0}")
r = sess().get(B + "/api/auth/oidc/start", params={"stepup": "show", "org": 1}, allow_redirects=False)
check(r.status_code == 303 and r.headers.get("Location") == "/#rck-stepup-error=session", f"#2387: a step-up without a session {r.status_code} {r.headers.get('Location')}")

# ---- an organisation admin who signs in only with single sign-on
Sv, _ = oidc_login({"sub": "sub-sven", "preferred_username": "sven"})
check(Sv.get(B + "/api/me").json().get("username") == "sven", "#2387: sven is signed in through OIDC")
ORG = A.post(B + "/api/admin/orgs", json={"name": "Nordwind", "admin_id": ids["sven"]}).json()["id"]
Sv.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
r = Sv.put(B + O + "/settings", json={"company_fields": {"name": "Nordwind Studio GmbH", "iban": TEST_IBAN}})
check(r.ok, "#2387: the organisation's office with an IBAN " + r.text[:150])
st = Sv.get(B + f"/api/orgs/{ORG}/encryption").json()
check(st.get("step") == "fresh" and st.get("stepup") == "oidc" and st.get("fresh") is False, f"#2387: state: fresh, step-up via oidc, not fresh yet {st}")
r = show(Sv, ORG)
check(r.status_code == 403 and r.json().get("need") == "fresh" and r.json().get("stepup") == "oidc" and "recovery_key" not in r.json(),
      f"#2387: a new OIDC session alone does not count (the provider may skip the prompt) {r.status_code} {r.text[:200]}")
now = int(time.time())
q, loc = stepup(Sv, ORG, {"sub": "sub-sven", "preferred_username": "sven", "auth_time": now - 3600})
check(q.get("prompt") == "login" and q.get("max_age") == "0" and q.get("code_challenge_method") == "S256",
      f"#2387: the step-up asks the provider with prompt=login and max_age=0 {q}")
check(loc == "/#rck-stepup-error=old" and show(Sv, ORG).status_code == 403, f"#2387: an old auth_time is no step-up {loc}")
q, loc = stepup(Sv, ORG, {"sub": "sub-sven", "preferred_username": "sven"})
check(loc == "/#rck-stepup-error=auth_time" and show(Sv, ORG).status_code == 403, f"#2387: without auth_time no step-up, a clear error {loc}")
dbx("UPDATE users SET oidc_subject=? WHERE id=?", (ISS + "|sub-mia", ids["mia"]))
q, loc = stepup(Sv, ORG, {"sub": "sub-mia", "preferred_username": "mia", "auth_time": now})
check(loc == "/#rck-stepup-error=account" and show(Sv, ORG).status_code == 403, f"#2387: a sign-in of another account does not count {loc}")
q, loc = stepup(Sv, ORG, {"sub": "sub-sven", "preferred_username": "sven", "auth_time": int(time.time()) - 5}, "new")
check(loc == f"/#rck-stepup/{ORG}/new", f"#2387: a fresh step-up goes back to the recovery key {loc}")
check(Sv.get(B + "/api/me").json().get("username") == "sven", "#2387: the step-up keeps the session")
check(Sv.get(B + f"/api/orgs/{ORG}/encryption").json().get("fresh") is True, "#2387: state fresh after the step-up")
r = show(Sv, ORG)
check(r.ok and r.json().get("recovery_key", "").startswith("R2-"), f"#2387: after the step-up the key is shown {r.status_code} {r.text[:120]}")
dbx("UPDATE sessions SET stepup_at='2020-01-01T00:00:00Z' WHERE user_id=?", (ids["sven"],))
check(show(Sv, ORG).status_code == 403, "#2387: ten minutes after the step-up it no longer counts")
# an account without a password that signed in another way (here: the password before it was removed) keeps the earlier rule
Ms = sess("mia")
dbx("UPDATE users SET password_hash=NULL WHERE id=?", (ids["mia"],))
r = Sv.put(B + f"/api/orgs/{ORG}/members", json={"email": "mia@example.com", "role": "admin"})
assert r.ok, r.text
Ms.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
r = show(Ms, ORG)
check(r.ok and r.json().get("recovery_key", "").startswith("R2-"), f"#2387: a fresh non-OIDC sign-in still counts {r.status_code} {r.text[:120]}")

# ---- a person without an organisation (freelancer-matrix: orgcrypt, auth): the own personal office
FID, _ = freelancer(B, A, "fenna")
dbx("UPDATE users SET password_hash=NULL, oidc_subject=? WHERE id=?", (ISS + "|sub-fenna", FID))
Fo, _ = oidc_login({"sub": "sub-fenna", "preferred_username": "fenna"})
r = Fo.put(B + O + "/settings", json={"company_fields": {"name": "Fenna Film", "iban": TEST_IBAN}})
check(r.ok, "#2387 freelancer: the personal office with an IBAN " + r.text[:150])
st = Fo.get(B + "/api/orgs/0/encryption").json()
check(st.get("has_key") is True and st.get("step") == "fresh" and st.get("stepup") == "oidc", f"#2387 freelancer: state {st}")
check(show(Fo, 0).status_code == 403, "#2387 freelancer: the OIDC session alone does not count")
q, loc = stepup(Fo, 0, {"sub": "sub-fenna", "preferred_username": "fenna", "auth_time": int(time.time()) - 900})
check(loc == "/#rck-stepup-error=old" and show(Fo, 0).status_code == 403, f"#2387 freelancer: an old auth_time {loc}")
q, loc = stepup(Fo, 0, {"sub": "sub-fenna", "preferred_username": "fenna", "auth_time": int(time.time())})
check(q.get("prompt") == "login" and loc == "/#rck-stepup/0/show", f"#2387 freelancer: the step-up of the own office {loc}")
r = show(Fo, 0)
check(r.ok and r.json().get("recovery_key", "").startswith("R2-"), f"#2387 freelancer: the key of the own office {r.status_code} {r.text[:120]}")

# ================================================================== #2387 F8: the HTTP Shortcuts download
r = A.get(B + "/api/me/share/httpshortcuts.zip")
check(r.status_code == 403 and "does not say which page" in r.json().get("error", ""), f"F8: no origin header at all: 403 with the reason {r.status_code} {r.text[:200]}")
r = A.get(B + "/api/me/share/httpshortcuts.zip", headers={"Referer": "https://evil.example/page"})
check(r.status_code == 403 and "does not say" not in r.json().get("error", ""), f"F8: a foreign Referer stays a plain 403 {r.text[:120]}")
r = A.get(B + "/api/me/share/httpshortcuts.zip", headers={"Sec-Fetch-Site": "same-origin"})
check(r.ok and r.headers.get("Content-Type", "").startswith("application/zip"), f"F8: from the app's own page: the file {r.status_code}")

# ---- a person without an organisation (freelancer-matrix: approvals): the own agent in the own list
FU, Fr = freelancer(B, A, "frida")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})  # personal agents allowed
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments"]})
FA = r.json().get("id")
FH = {"Authorization": "Bearer " + Fr.post(B + f"/api/my/agents/{FA}/token").json().get("token", "")}
FL = Fr.post(B + "/api/lists", json={"name": "Studio"}).json()["id"]
check(Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "#2001 freelancer: the own agent in the own list")
FT = Fr.post(B + "/api/tasks", json={"title": "Deliver", "list_id": FL}).json()["id"]
FC = card(FT, "Deliver the files", FH)
check(can(Fr, FT, FC) is True, "#2001 freelancer: the owner of the list is an approver")
r = Fr.post(B + f"/api/comments/{FC}/choice", json={"choice_ids": ["yes"]})
check(r.ok and r.json().get("choice_state") == "answered", f"#2001 freelancer: decides the own agent's card {r.status_code} {r.text[:150]}")
check(Ed.post(B + f"/api/comments/{FC}/choice", json={"choice_ids": ["no"]}).status_code in (403, 404), "#2001 freelancer: another person cannot decide")

# ================================================================== #2387 F7: the abort switch only in a test run
rc, out, err_ = cli("rotate", "--org", str(ORG), env=("KALMIDO_TEST_ROT_ABORT=1", "KALMIDO_ORGCRYPT_ROT_SETTLE=0"))
check(rc == 0 and "is ignored" in out and "not finished" not in out, f"F7: KALMIDO_TEST_ROT_ABORT alone is ignored, the rotation finishes {rc} {out[-300:]} {err_[-200:]}")
rc, out, err_ = cli("rotate", "--org", str(ORG), env=("KALMIDO_TEST_MODE=1", "KALMIDO_TEST_ROT_ABORT=1", "KALMIDO_ORGCRYPT_ROT_SETTLE=0"))
check(rc == 1 and "not finished" in out, f"F7: in a test run the switch stops after the key switch {rc} {out[-300:]}")
rc, out, err_ = cli("rotate", "--org", str(ORG), env=("KALMIDO_ORGCRYPT_ROT_SETTLE=0",))
check(rc == 0, f"F7: the next run finishes {rc} {out[-200:]}")

print(f"p21445_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
