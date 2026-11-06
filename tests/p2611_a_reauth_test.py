#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.611.0 A (#4019): an admin without a password (OIDC / passkey) turns a switch that opens the server only with a fresh
sign-in. Invented data only; session ages are set in the database (no waiting).
 - PATCH /api/admin/settings with an opening switch (here: a kind of public link switched back on, registration private):
   a session older than REAUTH_FRESH_MIN (10) minutes -> 403 {reauth_needed, stepup, passkey}, nothing stored;
   a session signed in just now (password / passkey / sign-in link) -> goes
 - an OIDC session alone is no fresh sign-in (a live session at the provider signs in without typing): only its step-up
   (sessions.stepup_for "0:su", at most 10 minutes old) counts
 - closing switches ask nothing (also with an old session); PUT /api/admin/oidc of the admin rule asks the same
 - an admin with a password: unchanged (password_needed, then the password)
 - a person without an organisation: the switches are the server's (instance admins only); a non-admin gets 403 as before
usage: p2611_a_reauth_test.py <datadir>"""
import sys
import time

from freelancer_fixture import freelancer
from kt import B, PASSWORD, check, dbx, docker_logs_on_first_fail, done, fresh, sess, setup

fresh(prefix="P2611A")
docker_logs_on_first_fail()
A = setup()
S = "/api/admin/settings"
OLD = "2020-01-01T00:00:00+00:00"


def now_iso(ago=0):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - ago))


r = A.post(B + "/api/users", json={"username": "bea", "display_name": "Bea Admin", "password": PASSWORD, "is_admin": True})
assert r.ok, r.text
BEA = r.json()["id"]
Bs = sess("bea")  # signed in with the password, then the password goes: an account without one (as after an OIDC link)
dbx("UPDATE users SET password_hash=NULL WHERE id=?", (BEA,))


def kinds_off():
    return A.get(B + "/api/about").json().get("public_links_off")


def close():  # a closing step asks nothing (whoever does it)
    r = Bs.patch(B + S, json={"public_links_off": ["files"]})
    assert r.ok and kinds_off() == ["files"], r.text


def reopen():
    return Bs.patch(B + S, json={"public_links_off": []})


def age(created=None, via=None, stepup_at=None, stepup_for=None):
    sets = {"created_at": created, "via": via, "stepup_at": stepup_at, "stepup_for": stepup_for}
    sets = {k: v for k, v in sets.items() if v is not None}
    dbx("UPDATE sessions SET " + ", ".join(f"{k}=?" for k in sets) + " WHERE user_id=?", (*sets.values(), BEA))


# ---- an old session: refused with reauth_needed (the fix: before 2.611 this went through)
close()
age(created=OLD)
r = reopen()
j = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
check(r.status_code == 403 and j.get("reauth_needed") is True and not j.get("password_needed"),
      f"#4019: an admin without a password and an old session -> 403 reauth_needed {r.status_code} {r.text[:200]}")
check(j.get("stepup") == "" and j.get("passkey") is False, f"#4019: no OIDC link, no passkey: the client knows {j}")
check("10" in (j.get("error") or ""), f"#4019: the message names the minutes {j.get('error')!r}")
check(kinds_off() == ["files"], "#4019: nothing stored after the refusal")
r = Bs.patch(B + S, json={"signup_private": True})
check(r.status_code == 403 and r.json().get("reauth_needed") is True, f"#4019: another opening switch, the same answer {r.status_code}")
r = Bs.patch(B + S, json={"public_links_off": ["files", "lists"]})
check(r.ok, f"#4019: a closing switch asks nothing, also with an old session {r.status_code} {r.text[:120]}")
assert A.patch(B + S, json={"public_links_off": ["files"], "password": PASSWORD}).ok  # "lists" on again opens: the password admin

# ---- the OIDC admin rule asks the same (PUT /api/admin/oidc -> _oidc_admin_reauth -> oidc_reauth)
r = Bs.put(B + "/api/admin/oidc", json={"admin_domains": "corp.example"})
check(r.status_code == 403 and r.json().get("reauth_needed") is True, f"#4019: the OIDC admin rule with an old session {r.status_code} {r.text[:160]}")

# ---- a fresh sign-in counts (password / passkey / sign-in link of the last 10 minutes)
for via in ("password", "passkey", "link"):
    close()
    age(created=now_iso(60), via=via)
    r = reopen()
    check(r.ok and kinds_off() == [], f"#4019: a sign-in ({via}) a minute ago -> goes {r.status_code} {r.text[:160]}")
close()
age(created=now_iso(11 * 60), via="passkey")
check(reopen().status_code == 403, "#4019: a passkey sign-in 11 minutes ago is too old")

# ---- OIDC: a new session alone is no fresh sign-in, its step-up is
close()
age(created=now_iso(30), via="oidc")
r = reopen()
check(r.status_code == 403 and r.json().get("reauth_needed") is True, f"#4019: an OIDC session of just now without step-up -> 403 {r.status_code}")
age(stepup_at=now_iso(60), stepup_for="0:show")
check(reopen().status_code == 403, "#4019: a step-up of a recovery key (other purpose) does not count")
age(stepup_at=now_iso(11 * 60), stepup_for="0:su")
check(reopen().status_code == 403, "#4019: a step-up 11 minutes ago is too old")
age(stepup_at=now_iso(60), stepup_for="0:su")
r = reopen()
check(r.ok and kinds_off() == [], f"#4019: the OIDC step-up a minute ago -> goes {r.status_code} {r.text[:160]}")
close()
age(created=now_iso(30), via="restore", stepup_at=OLD, stepup_for="")
check(reopen().status_code == 403, "#4019: a session made by a restored backup is no fresh sign-in")
age(created=now_iso(30), via="password")
assert reopen().ok

# ---- an admin with a password: unchanged
assert A.patch(B + S, json={"public_links_off": ["files"]}).ok
r = A.patch(B + S, json={"public_links_off": []})
check(r.status_code == 403 and r.json().get("password_needed") is True and not r.json().get("reauth_needed"),
      f"#4019: an admin with a password is asked for it as before {r.status_code} {r.text[:160]}")
dbx("UPDATE sessions SET created_at=? WHERE user_id<>?", (OLD, BEA))
r = A.patch(B + S, json={"public_links_off": [], "password": PASSWORD})
check(r.ok and kinds_off() == [], f"#4019: with the password (old session) -> goes {r.status_code} {r.text[:160]}")

# ---- a person without an organisation: no instance admin, refused before any confirmation
FID, Fr = freelancer(B, A, "fenna")
dbx("UPDATE users SET password_hash=NULL WHERE id=?", (FID,))
assert A.patch(B + S, json={"public_links_off": ["files"]}).ok
r = Fr.patch(B + S, json={"public_links_off": []})
check(r.status_code == 403 and "reauth_needed" not in r.text, f"freelancer: the server's switches stay admins only {r.status_code} {r.text[:120]}")

sys.exit(done("p2611_a_reauth"))
