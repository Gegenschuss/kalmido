#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.539.0 B (#4375): sign-in, remaining findings of audit #2482.
 - the own password change (PATCH /api/me password) ends all app passwords and API tokens when the tick is set
   (revoke_tokens true) and when the field is missing (API: the safe default); revoke_tokens false keeps them. An agent's
   tokens stay in every case
 - app passwords are created only from the web app's session: a token (even for all projects with calendar + contacts)
   gets 403; listing / revoking with a token stays
 - the mark of a known browser for the new-device mail holds the network too (IPv4 /24, IPv6 /64): another address in the
   same network is the same device, another network a new one; a mark from before (browser only) is taken over once
 - email_proved only from a link that went out by mail (sent_at): a copied invitation / reset link or a sign-in link
   (shown as link / QR code) proves no address
 (the OIDC part - an SSO account linked by user name only with auto-create on - is in tests/oidc_test.py)
freelancer-matrix: own
alice (instance admin), frida / dana (persons WITHOUT an organisation), pia / sia (made by the admin). Invented values only.
Red without the fix: the token survives the change without the field, a token creates an app password (201), the mark
stays the same in another network, email_proved is set after a copied link / a sign-in link.
usage: p2539_b_api_test.py <datadir>   (P2539B_NOSTART=1: the container runs already)"""
import hashlib
import json
import os
import sys

import requests

import dbx as dbxm
import kt
from kt import B, DATA, H, check
from freelancer_fixture import freelancer

kt.fresh(prefix="P2539B")
A = kt.setup()
V = B + "/api/v1"
FID, F = freelancer(B, A)
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"


def write(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute(q, args)
        c.commit()
    finally:
        c.close()


def tok(s, scopes=("read",)):
    r = s.post(B + "/api/me/tokens", json={"name": "t", "scopes": list(scopes)})
    assert r.ok, r.text
    return r.json()["token"]


def bear(t):
    return {"Authorization": "Bearer " + t}


def apw(s, name="Phone"):
    r = s.post(B + "/api/me/app-passwords", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def n_apw(uid):
    return kt.dbx("SELECT COUNT(*) FROM app_passwords WHERE user_id=?", (uid,))[0][0]


def works(t):
    return requests.get(V + "/me", headers=bear(t)).ok


# ================================================================ the own password change: the tick
T1 = tok(F)
apw(F)
check(works(T1) and n_apw(FID) == 1, "setup: frida has a token and an app password")
r = F.patch(B + "/api/me", json={"current_password": "password123", "password": "password234", "revoke_tokens": False})
check(r.ok, f"tick removed: the password changes {r.status_code} {r.text[:160]}")
check(works(T1) and n_apw(FID) == 1, "#4375: tick removed (revoke_tokens false): token and app password stay")
check(F.get(B + "/api/me").ok, "the own session stays")
r = F.patch(B + "/api/me", json={"current_password": "password234", "password": "password345"})
check(r.ok, f"without the field (API) {r.status_code} {r.text[:160]}")
check(not works(T1) and n_apw(FID) == 0, "#4375: without revoke_tokens (the safe default) token and app password end")
T2 = tok(F)
apw(F)
r = F.patch(B + "/api/me", json={"current_password": "password345", "password": "password456", "revoke_tokens": True})
check(r.ok and not works(T2) and n_apw(FID) == 0, "#4375: tick set (revoke_tokens true): token and app password end")
check(F.get(B + "/api/me").ok, "the own session still stays")

# an agent's tokens stay
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "robo", "display_name": "Robo"})
ATOK = ag.json().get("token") if ag.status_code == 201 else ""
check(bool(ATOK) and requests.get(V + "/lists", headers=bear(ATOK)).ok, f"setup: an agent with a token {ag.status_code} {ag.text[:160]}")
AT = tok(A)
r = A.patch(B + "/api/me", json={"current_password": "password123", "password": "password234"})
check(r.ok and not works(AT), f"alice changes her password: her own token ends {r.status_code} {r.text[:160]}")
check(requests.get(V + "/lists", headers=bear(ATOK)).ok, "#4375: the agent's token stays")
r = A.patch(B + "/api/me", json={"current_password": "password234", "password": "password123", "revoke_tokens": False})
check(r.ok, "alice's password back")

# ================================================================ app passwords only from the web app
FT = tok(F, ("read", "write", "account", "calendar", "contacts"))
r = requests.post(V + "/me/app-passwords", headers=bear(FT), json={"name": "Script"})
check(r.status_code == 403 and n_apw(FID) == 0, f"#4375: a token for all projects with calendar + contacts makes no app password {r.status_code} {r.text[:160]}")
check("web app" in r.text, f"#4375: the answer says where {r.text[:200]}")
PID = apw(F, "iPhone")
check(n_apw(FID) == 1, "the web session still creates one")
j = requests.get(V + "/me/app-passwords", headers=bear(FT)).json()
check([x["id"] for x in j.get("data", [])] == [PID], f"a token still lists them {j}")
check(requests.delete(V + f"/me/app-passwords/{PID}", headers=bear(FT)).ok and n_apw(FID) == 0, "a token still revokes one")

# ================================================================ the device mark holds the network
DID, _D = freelancer(B, A, "dana")


def marks():
    r = kt.dbx("SELECT value FROM user_settings WHERE user_id=? AND key='sec_devices'", (DID,))
    return json.loads(r[0][0]) if r else []


def mark(net):
    return hashlib.sha256((UA + "\n" + net).encode()).hexdigest()[:20]


def login(ip):
    kt.sess("dana", ip=ip, ua=UA)
    return marks()


m = login("192.0.2.10")
check(m and m[0] == mark("192.0.2.0/24"), f"#4375: the mark is browser + /24 {m}")
n = len(m)
m = login("192.0.2.99")
check(len(m) == n and m[0] == mark("192.0.2.0/24"), f"#4375: another address in the same /24: the same device {m}")
m = login("198.51.100.7")
check(len(m) == n + 1 and m[0] == mark("198.51.100.0/24") and mark("192.0.2.0/24") in m,
      f"#4375: the same browser from another network is a new device (the mail case) {m}")
m = login("2001:db8:1:2::5")
m2 = login("2001:db8:1:2:ffff::9")
check(m[0] == mark("2001:db8:1:2::/64") and m2 == m, f"#4375: IPv6 by its /64 {m2}")
old = hashlib.sha256(UA.encode()).hexdigest()[:20]
write("UPDATE user_settings SET value=? WHERE user_id=? AND key='sec_devices'", (json.dumps([old]), DID))
m = login("203.0.113.5")
check(m == [mark("203.0.113.0/24")], f"#4375: a mark from before (browser only) is taken over once, no second entry {m}")

# ================================================================ email_proved only from a mailed link
r = A.post(B + "/api/users", json={"username": "pia", "display_name": "Pia", "email": "pia@example.com"})
assert r.ok, r.text
PIA = r.json()["id"]


def proved(uid):
    return kt.dbx("SELECT COALESCE(email_proved, '') FROM users WHERE id=?", (uid,))[0][0]


def link_tok(s, uid):
    r = s.post(B + f"/api/users/{uid}/invite", json={"send": False})
    assert r.ok, r.text
    return r.json()["link"].split("#invite/")[1]


t = link_tok(A, PIA)
r = requests.post(B + "/api/auth/invite/accept", headers=H, json={"token": t, "password": "password123"})
check(r.ok and proved(PIA) == "", f"#4375: a copied invitation link (no mail) proves no address {r.status_code} {proved(PIA)!r}")
t = link_tok(A, PIA)
write("UPDATE user_invites SET sent_at=created_at WHERE user_id=?", (PIA,))  # as if the reset mail went out
r = requests.post(B + "/api/auth/invite/accept", headers=H, json={"token": t, "password": "password234"})
check(r.ok and proved(PIA) == "pia@example.com", f"#4375: a mailed reset link proves it {r.status_code} {proved(PIA)!r}")
r = A.post(B + "/api/users", json={"username": "sia", "display_name": "Sia", "email": "sia@example.com"})
assert r.ok, r.text
SIA = r.json()["id"]
r = A.post(B + f"/api/users/{SIA}/signin-link")
check(r.ok, f"setup: a sign-in link {r.status_code} {r.text[:160]}")
r = requests.post(B + "/api/auth/link", headers=H, json={"token": r.json()["link"].split("#signin/")[1]})
check(r.ok and proved(SIA) == "", f"#4375: a sign-in link (link / QR code) proves no address {r.status_code} {proved(SIA)!r}")

# review 2.539.0 (#4375): the admin changes the address after the mail went out -> the old mail proves no new address
r = A.post(B + "/api/users", json={"username": "ria", "display_name": "Ria", "email": "ria@example.com"})
assert r.ok, r.text
RIA = r.json()["id"]
t = link_tok(A, RIA)
write("UPDATE user_invites SET sent_at=created_at WHERE user_id=?", (RIA,))  # as if the invitation mail went out
r = A.patch(B + f"/api/users/{RIA}", json={"email": "other@example.com"})
check(r.ok, f"setup: the admin changes the address {r.status_code} {r.text[:160]}")
r = requests.post(B + "/api/auth/invite/accept", headers=H, json={"token": t, "password": "password345"})
check(r.ok and proved(RIA) == "", f"#4375: a link mailed to the old address proves no new one {r.status_code} {proved(RIA)!r}")

sys.exit(kt.done("p2539_b_api"))
