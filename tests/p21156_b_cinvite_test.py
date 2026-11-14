#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1156.0 part B (#4550): a person invites someone without an account by a link / QR code (accounts/cinvite.py). Own container
(start.sh): first with the SMTP sink stub_mail.py, then a second fresh one without e-mail. Invented names and example.com
addresses only; every inviting / invited person is a person without an organisation (tests/freelancer_fixture.py).
freelancer-matrix: team  (the routes /api/disc/invites... as a person without an organisation)
 - the instance switch: off while registration is not open (route 403, GET /api/disc invite_link false), on by default with
   signup_mode "open", an admin switches it on (asks for the password) / off
 - make (link + QR code, only the hash stored), list (note, runs out), take back + undo, run out, the limits (20 open, 10 a day)
 - without an account, with e-mail: name + address -> a registration to confirm (mail), connected only after the confirmation,
   a private account (no organisation, no admin), no admin approval even in mode "approval"; News "accepted your invitation"
 - used once: a second redemption is refused; an address with an account: the same answer, no account, no mail
 - signed in: connect (no registration); the own link: 409 and stays valid
 - agents, kid accounts, a disabled inviting person: no access / the link stops working
 - the daily clean-up removes old rows; the brake per client address on wrong tokens
 - without e-mail: name + password -> active at once, signed in, connected; no address is kept, the username from the name
 - the Fable review (2.1156.0 part C): F1/F2 no address without e-mail, F3 the confirmation after the inviting person was
   disabled / the switch went off waits for an admin, F4 a link taken back during a redemption / taking back under the
   accounts lock, F5 the mail names the inviting person and a name like a link is refused
usage: p21156_b_cinvite_test.py <datadir>"""
import email
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
import dbx as dbxm  # noqa: E402
from freelancer_fixture import PASSWORD, freelancer, login  # noqa: E402
from kt import B, CT, DATA, H, check, dbx, until  # noqa: E402

SMTP = {"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
        "KALMIDO_MAIL_FROM": "kalmido@example.test"}
S = B + "/api/admin/settings"


def write(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    c.execute(q, args)
    c.commit()
    c.close()


def mails():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def link_of(m, kind="invite"):
    msg = email.message_from_string(m["raw"])
    for p in msg.walk():
        if p.get_content_type() == "text/plain":
            t = re.search(r"#" + kind + r"/([A-Za-z0-9_-]{20,100})", p.get_payload(decode=True).decode())
            if t:
                return t.group(1)
    return None


IPN = [10]


def anon(ip=None):
    """A visitor without a session, from an address of its own (the brakes per client address count per address, like the
    invitation page's: a few wrong tokens from one address block it; the test container trusts X-Forwarded-For)."""
    s = requests.Session()
    s.headers.update(H)
    IPN[0] += 1
    s.headers["X-Forwarded-For"] = ip or f"198.51.100.{IPN[0]}"
    return s


def tok_of(j):
    return j["link"].rsplit("#cinv/", 1)[1]


def py_in_app(code):
    for _ in range(4):  # "import app" runs init_db next to the running server: now and then a Postgres deadlock of this helper
        r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                            "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.commit()\nc.close()"],
                           capture_output=True, text=True)
        if "deadlock detected" not in r.stderr:
            break
        time.sleep(2)
    return (r.stdout + r.stderr).strip()


def hold_accounts_lock():
    """2.1156.0 C (#4550, Fable F4): a transaction of the app in the container that holds write_lock "accounts" until a line on stdin."""
    code = ("import os, sys; os.environ['TASKS_WATCHDOG']='0'\nimport app\nfrom kalmido.core.pg import write_lock\nc=app.connect()\n"
            "write_lock(c, 'accounts')\nprint('held', flush=True)\nsys.stdin.readline()\nc.commit()\nprint('done', flush=True)")
    p = subprocess.Popen(["docker", "exec", "-i", CT, "python", "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    line = p.stdout.readline()
    return p if "held" in line else None


def lock_waiter():
    """A query waiting on an advisory lock (the request behind hold_accounts_lock)."""
    return dbx("SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE '%pg_advisory_xact_lock%' "
               "AND query NOT LIKE '%pg_stat_activity%'")


def via(items):
    """data.via of the newest connok News item ('' without one)."""
    for x in items:
        if x.get("kind") == "connok":
            d = x.get("data") or {}
            return (json.loads(d) if isinstance(d, str) else d).get("via", "")
    return ""


def uid_of(name):
    r = dbx("SELECT id FROM users WHERE username=?", (name,))
    return r[0][0] if r else None


# ================================================================= part 1: a server with e-mail
if kt.fresh(env=SMTP, prefix="P21156B"):
    os.makedirs(os.path.join(DATA, "mail"), exist_ok=True)
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
A = kt.setup()
FID, Fr = freelancer(B, A)                 # frida invites
DID, Do = freelancer(B, A, "dora")         # dora has an account already
OID, Ol = freelancer(B, A, "olga")         # olga invites, then gets disabled
KID_, Ki = freelancer(B, A, "kira")        # kira becomes a kid account
time.sleep(0.5)

# ---- rollback: only a new table
check(dbx("SELECT 1 FROM information_schema.tables WHERE table_name='conn_invites'"), "new table conn_invites")

# ---- the switch: off while registration is not open
check(Fr.get(B + "/api/disc").json().get("invite_link") is False, "switch off by default (registration off): no button")
_r = Fr.get(B + "/api/disc/invites")  # 2.1156.0 (#4550): the list answers with the switch off (on: false), making links does not
check(_r.status_code == 200 and _r.json().get("on") is False, "switch off: GET 200 with on false")
check(Fr.post(B + "/api/disc/invites", json={}).status_code == 403, "switch off: POST 403")
check(A.get(B + "/api/about").json().get("cinv_signup") is False, "Administration: the switch shows off")
r = A.patch(S, json={"signup_mode": "open", "password": PASSWORD})
check(r.ok, f"registration open ({r.text[:200]})")
check(Fr.get(B + "/api/disc").json().get("invite_link") is True, "default: on when anyone may register")
check(A.patch(S, json={"signup_mode": "approval", "password": PASSWORD}).ok, "registration with approval")
check(Fr.get(B + "/api/disc").json().get("invite_link") is False, "default: off when registration is not open")
r = A.patch(S, json={"cinv_signup": True})
check(r.status_code == 403 and r.json().get("password_needed"), f"switching it on asks for the password ({r.status_code})")
check(A.patch(S, json={"cinv_signup": "yes", "password": PASSWORD}).status_code == 400, "not a boolean: 400")
r = A.patch(S, json={"cinv_signup": True, "password": PASSWORD})
check(r.ok and r.json().get("cinv_signup") is True, f"an admin switches it on ({r.text[:200]})")
check(Fr.get(B + "/api/disc").json().get("invite_link") is True, "switched on: the button")

# ---- make, list
r = Fr.post(B + "/api/disc/invites", json={"note": "  For   Nina  "})
check(r.ok, f"frida makes a link ({r.text[:200]})")
j = r.json()
T1 = tok_of(j)
check("#cinv/" in j["link"] and len(T1) >= 40 and j["qr"].startswith("data:image/svg+xml"), "the answer: link + QR code")
check(j["item"]["note"] == "For Nina", "the note is trimmed")
row = dbx("SELECT token_hash, expires_at, created_at FROM conn_invites WHERE id=?", (j["item"]["id"],))[0]
check(row[0] == hashlib.sha256(T1.encode()).hexdigest() and T1 not in json.dumps(dbx("SELECT * FROM conn_invites")), "only the hash is stored")
days = (datetime.fromisoformat(str(row[1])) - datetime.fromisoformat(str(row[2]))).days
check(days == 14, f"it runs 14 days ({days})")
lst = Fr.get(B + "/api/disc/invites").json()
check([x["note"] for x in lst["items"]] == ["For Nina"] and "link" not in json.dumps(lst) and lst["limits"]["open"] == 20, "the list: note, no link")
check(Do.get(B + "/api/disc/invites").json()["items"] == [], "dora does not see frida's links")
check(Do.delete(B + f"/api/disc/invites/{j['item']['id']}").status_code == 404, "dora cannot take frida's link back")

# ---- without an account, with e-mail
r = anon().post(B + "/api/auth/cinv/check", json={"token": T1})
c1 = r.json()
check(r.ok and c1["name"] == "Frida" and c1["signed_in"] is False and c1["mail"] is True, f"the page: who invites ({r.text[:200]})")
check(anon().post(B + "/api/auth/cinv/accept", json={"token": T1, "name": "", "email": "nina@example.com"}).status_code == 400, "no name: 400")
check(anon().post(B + "/api/auth/cinv/check", json={"token": T1}).ok, "an invalid form does not use the link up")
# 2.1156.0 C (#4550, Fable F5): a name that looks like a link is refused like an empty one, the link stays valid
NONAME = anon().post(B + "/api/auth/cinv/accept", json={"token": T1, "name": " ", "email": "nina@example.com"}).json().get("error")
for bad in ("Visit https://evil.example", "www.evil example", "evil.com", "Prize at evil.co/win now"):
    r = anon().post(B + "/api/auth/cinv/accept", json={"token": T1, "name": bad, "email": "nina@example.com"})
    check(r.status_code == 400 and NONAME and r.json().get("error") == NONAME, f"Fable F5: name {bad!r} refused ({r.status_code})")
check(anon().post(B + "/api/auth/cinv/check", json={"token": T1}).ok, "Fable F5: ... and the link stays valid")
n0 = len(mails())
r = anon().post(B + "/api/auth/cinv/accept", json={"token": T1, "name": "Nina Example", "email": "nina@example.com", "lang": "en"})
ANSWER = (r.status_code, r.json())
check(r.ok and r.json() == {"ok": True, "mail": True}, f"registration: confirm by mail ({r.text[:200]})")
m = until(lambda: len(mails()) > n0 and mails()[-1], 15)
itok = link_of(m) if m else None
check(itok and "nina@example.com" in json.dumps(m["to"]).lower(), "the confirmation mail goes to the address")
mtext = "".join(p.get_payload(decode=True).decode() for p in email.message_from_string(m["raw"]).walk() if p.get_content_type() == "text/plain") if m else ""
check("Frida invited you to" in mtext and "you are connected" in mtext, f"Fable F5: the mail names who invited ({mtext[:300]!r})")
NINA = uid_of("nina")
check(NINA and dbx("SELECT signup, disabled FROM users WHERE id=?", (NINA,))[0][0] == "confirm", "a registration to confirm")
check(dbx("SELECT used_by FROM conn_invites WHERE token_hash=?", (hashlib.sha256(T1.encode()).hexdigest(),))[0][0] == NINA, "the link names the new account")
check(not dbx("SELECT 1 FROM conn_links WHERE (a_id=? AND b_id=?) OR (a_id=? AND b_id=?)", (FID, NINA, NINA, FID)), "not connected before the confirmation")
r = anon().post(B + "/api/auth/cinv/accept", json={"token": T1, "name": "Mallory", "email": "mallory@example.com"})
check(r.status_code == 404 and not uid_of("mallory"), "used once: a second redemption is refused")
check(anon().post(B + "/api/auth/cinv/check", json={"token": T1}).status_code == 404, "used: the page says invalid")
# the confirmation (mode "approval" is on: an invited account still needs no admin)
Ni = anon()
r = Ni.post(B + "/api/auth/invite/accept", json={"token": itok, "password": "nina-pass-123"})
check(r.ok and r.json().get("ok") is True, f"nina confirms and is signed in, no approval ({r.text[:200]})")
u = dbx("SELECT signup, disabled, is_admin, kid FROM users WHERE id=?", (NINA,))[0]
check(u[0] == "" and not u[1] and not u[2] and not u[3], f"active, no admin, no kid ({u})")
check(Ni.get(B + "/api/state").json()["me"].get("workspaces") == [], "a private account: no organisation")
cons = [x["person"]["id"] for x in Ni.get(B + "/api/disc").json()["connections"]]
check(FID in cons, "nina is connected with frida")
check(NINA in [x["person"]["id"] for x in Fr.get(B + "/api/disc").json()["connections"]], "frida sees nina under Connections")
check(via(Fr.get(B + "/api/news").json().get("items", [])) == "invite", "frida's News: accepted your invitation")
check(Fr.get(B + "/api/disc/invites").json()["items"] == [], "a used link is no longer open")


def confirm_late(inviter_s, uname, before):
    """2.1156.0 C (#4550, Fable F3): registers uname by a link of inviter_s, runs before() (the inviting person / the switch
    changes), confirms -> (answer, account id)."""
    t = tok_of(inviter_s.post(B + "/api/disc/invites", json={}).json())
    n0 = len(mails())
    r = anon().post(B + "/api/auth/cinv/accept", json={"token": t, "name": uname.title() + " Example", "email": f"{uname}@example.com", "lang": "en"})
    check(r.ok and r.json() == {"ok": True, "mail": True}, f"Fable F3: {uname} registers ({r.text[:200]})")
    m = until(lambda: len(mails()) > n0 and mails()[-1], 15)
    before()
    r = anon().post(B + "/api/auth/invite/accept", json={"token": link_of(m) if m else "", "password": f"{uname}-pass-123"})
    return r, uid_of(uname)


def waits(uid, inviter, what):
    u = dbx("SELECT signup, disabled FROM users WHERE id=?", (uid,))[0]
    check(u[0] == "pending" and u[1], f"Fable F3: {what}: the account waits for an admin ({u})")
    check(not dbx("SELECT 1 FROM conn_links WHERE (a_id=? AND b_id=?) OR (a_id=? AND b_id=?)", (inviter, uid, uid, inviter)), f"Fable F3: {what}: no connection")
    items = A.get(B + "/api/news").json().get("items", [])
    check(any(x.get("kind") == "signup" and (json.loads(x["data"]) if isinstance(x.get("data"), str) else x.get("data") or {}).get("user_id") == uid
              for x in items), f"Fable F3: {what}: the admins hear of it")


r, PAUL = confirm_late(Ol, "paul", lambda: write("UPDATE users SET disabled=true WHERE id=?", (OID,)))
check(r.ok and r.json() == {"ok": False, "pending": True}, f"Fable F3: inviting person disabled: pending ({r.text[:200]})")
waits(PAUL, OID, "inviting person disabled")
write("UPDATE users SET disabled=false WHERE id=?", (OID,))
r, RITA = confirm_late(Ol, "rita", lambda: check(A.patch(S, json={"cinv_signup": False}).ok, "Fable F3: the switch goes off"))
check(r.ok and r.json() == {"ok": False, "pending": True}, f"Fable F3: switch off: pending ({r.text[:200]})")
waits(RITA, OID, "switch off")
check(A.patch(S, json={"cinv_signup": True, "password": PASSWORD}).ok, "Fable F3: the switch on again")
check(A.post(B + f"/api/users/{RITA}/approve").ok and not dbx("SELECT disabled FROM users WHERE id=?", (RITA,))[0][0], "Fable F3: an admin approves")

# ---- an address with an account: the same answer, no account, no mail
T2 = tok_of(Fr.post(B + "/api/disc/invites", json={}).json())
n0 = len(mails())
r = anon().post(B + "/api/auth/cinv/accept", json={"token": T2, "name": "Dora Again", "email": "DORA@example.com"})
check((r.status_code, r.json()) == ANSWER, f"an address with an account: the same answer ({r.text[:200]})")
time.sleep(1.5)  # the background mail of a new address goes within a second: none may come here
check(len(mails()) == n0, "no mail to that address")
check(dbx("SELECT COUNT(*) FROM users WHERE lower(email)='dora@example.com'")[0][0] == 1, "no second account")
check(anon().post(B + "/api/auth/cinv/check", json={"token": T2}).status_code == 404, "the link is used up all the same")

# ---- take back + undo, run out
j3 = Fr.post(B + "/api/disc/invites", json={"note": "Tom"}).json()
T3, I3 = tok_of(j3), j3["item"]["id"]
check(Fr.delete(B + f"/api/disc/invites/{I3}").ok, "take back")
check(anon().post(B + "/api/auth/cinv/check", json={"token": T3}).status_code == 404, "taken back: invalid")
check(Fr.post(B + f"/api/disc/invites/{I3}/restore").ok, "undo of taking back")
check(anon().post(B + "/api/auth/cinv/check", json={"token": T3}).ok, "back: valid again")
check(Fr.delete(B + f"/api/disc/invites/{I3}").ok and Fr.delete(B + f"/api/disc/invites/{I3}").status_code == 404, "taken back once more; twice: 404")
j4 = Fr.post(B + "/api/disc/invites", json={}).json()
T4 = tok_of(j4)
write("UPDATE conn_invites SET expires_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), j4["item"]["id"]))
check(anon().post(B + "/api/auth/cinv/check", json={"token": T4}).status_code == 404, "run out: invalid")
check(Fr.post(B + f"/api/disc/invites/{j4['item']['id']}/restore").status_code == 404, "a link that ran out cannot come back")

# ---- signed in: connect, the own link
j5 = Fr.post(B + "/api/disc/invites", json={}).json()
T5 = tok_of(j5)
c5 = Do.post(B + "/api/auth/cinv/check", json={"token": T5}).json()
check(c5.get("signed_in") is True and c5.get("own") is False and c5.get("may") is True and c5.get("connected") is False, f"dora signed in: may connect, no connection yet ({c5})")
c5f = Fr.post(B + "/api/auth/cinv/check", json={"token": T5}).json()
check(c5f.get("own") is True, "frida's own link: own")
r = Fr.post(B + "/api/auth/cinv/accept", json={"token": T5})
check(r.status_code == 409, f"the own link cannot be accepted ({r.status_code})")
check(anon().post(B + "/api/auth/cinv/check", json={"token": T5}).ok, "... and stays valid")
r = Do.post(B + "/api/auth/cinv/accept", json={"token": T5})
check(r.ok and r.json().get("connected") is True, f"dora connects with the link ({r.text[:200]})")
check(FID in [x["person"]["id"] for x in Do.get(B + "/api/disc").json()["connections"]], "dora is connected with frida")
check(Do.post(B + "/api/auth/cinv/accept", json={"token": T5}).status_code == 404, "used once")

# ---- 2.1156.0 C (#4550, Fable F4): a link taken back between the look-up and its use is not used (signed in) ...
T10 = tok_of(Ol.post(B + "/api/disc/invites", json={}).json())
I10 = dbx("SELECT id FROM conn_invites WHERE token_hash=?", (hashlib.sha256(T10.encode()).hexdigest(),))[0][0]
write("UPDATE conn_invites SET revoked_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), I10))
out = py_in_app(f"""from flask import g
from kalmido.core.config import app as fl
import kalmido.accounts.cinvite as ci
def stale(c2, tok):  # the look-up saw the link while it was still open
    r = c2.execute("SELECT * FROM conn_invites WHERE token_hash=?", (ci._hash(tok),)).fetchone()
    return r, c2.execute("SELECT * FROM users WHERE id=?", (r["user_id"],)).fetchone()
ci._lookup = stale
with fl.test_request_context('/api/auth/cinv/accept', method='POST', json={{'token': {T10!r}}}):
    g.db = c
    g.pushes = []
    g.user = c.execute("SELECT * FROM users WHERE id=?", ({DID},)).fetchone()
    rv = ci.cinv_accept()
    print('status', rv[1] if isinstance(rv, tuple) else rv.status_code)""")
check("status 404" in out, f"Fable F4: a link taken back meanwhile: 404 ({out[-300:]})")
check(not dbx("SELECT 1 FROM conn_links WHERE (a_id=? AND b_id=?) OR (a_id=? AND b_id=?)", (OID, DID, DID, OID)), "Fable F4: ... no connection")
check(not dbx("SELECT used_at FROM conn_invites WHERE id=?", (I10,))[0][0], "Fable F4: ... the link is not marked used")
# ... and taking a link back waits for the accounts lock (a redemption holds it from its look-up to its use)
j11 = Ol.post(B + "/api/disc/invites", json={}).json()
hp = hold_accounts_lock()
check(hp is not None, "Fable F4: a transaction holds the accounts lock")
res = {}
th = threading.Thread(target=lambda: res.update(r=Ol.delete(B + f"/api/disc/invites/{j11['item']['id']}")))
th.start()
until(lambda: lock_waiter() or not th.is_alive(), 15)
check(th.is_alive() and lock_waiter(), "Fable F4: taking back waits for the accounts lock")
if hp:
    hp.stdin.write("go\n")
    hp.stdin.flush()
    hp.communicate(timeout=60)
th.join(30)
check(res.get("r") is not None and res["r"].ok, "Fable F4: ... and goes through after it")

# ---- agents, kids, a disabled inviting person
r = A.post(B + "/api/admin/agents", json={"username": "helperbot", "display_name": "Helper bot", "scopes": ["write"]})
AGTOK = r.json().get("token") or ""
r = requests.get(B + "/api/disc/invites", headers={**H, "Authorization": f"Bearer {AGTOK}"})
check(r.status_code in (401, 403, 404), f"an agent token has no access ({r.status_code})")
r = requests.post(B + "/api/disc/invites", headers={**H, "Authorization": f"Bearer {AGTOK}"}, json={})
check(r.status_code in (401, 403, 404), f"an agent cannot make a link ({r.status_code})")
j6 = Ki.post(B + "/api/disc/invites", json={}).json()
T6 = tok_of(j6)
write("UPDATE users SET kid=1 WHERE id=?", (KID_,))
r1, r2 = Ki.get(B + "/api/disc/invites").status_code, Ki.post(B + "/api/disc/invites", json={}).status_code
check(r1 == 404 and r2 in (403, 404), f"a kid account: no access ({r1}, {r2})")
check(anon().post(B + "/api/auth/cinv/check", json={"token": T6}).status_code == 404, "a kid's older link stops working")
c6 = Do.post(B + "/api/auth/cinv/check", json={"token": T6})
check(c6.status_code == 404, "... also for a signed-in person")
T7 = tok_of(Ol.post(B + "/api/disc/invites", json={}).json())
check(anon().post(B + "/api/auth/cinv/check", json={"token": T7}).ok, "olga's link works")
write("UPDATE users SET disabled=true WHERE id=?", (OID,))
check(anon().post(B + "/api/auth/cinv/check", json={"token": T7}).status_code == 404, "olga disabled: her link stops working")
write("UPDATE users SET disabled=false WHERE id=?", (OID,))
write("UPDATE users SET kid=0 WHERE id=?", (KID_,))
# a signed-in kid account cannot accept
T8 = tok_of(Fr.post(B + "/api/disc/invites", json={}).json())
write("UPDATE users SET kid=1 WHERE id=?", (KID_,))
check(Ki.post(B + "/api/auth/cinv/accept", json={"token": T8}).status_code == 403, "a kid account cannot accept")
write("UPDATE users SET kid=0 WHERE id=?", (KID_,))
check(anon().post(B + "/api/auth/cinv/check", json={"token": T8}).ok, "... the link stays valid")

# ---- the limits: 10 new a day, 20 open
made = dbx("SELECT COUNT(*) FROM conn_invites WHERE user_id=?", (FID,))[0][0]
for _ in range(10 - made):
    check(Fr.post(B + "/api/disc/invites", json={}).ok, "within the day's limit")
r = Fr.post(B + "/api/disc/invites", json={})
check(r.status_code == 429 and "today" in r.json().get("error", ""), f"the 11th link today: 429 ({r.text[:200]})")
old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
far = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
for i in range(20):
    write("INSERT INTO conn_invites(user_id, token_hash, note, created_at, expires_at) VALUES(?,?,?,?,?)", (DID, f"x{i}-{time.time()}", "", old, far))
r = Do.post(B + "/api/disc/invites", json={})
check(r.status_code == 429 and "open invitation links" in r.json().get("error", ""), f"20 open links: 429 ({r.text[:200]})")

# ---- the switch off again: routes 403, open links invalid
check(A.patch(S, json={"cinv_signup": False}).ok, "switching it off asks nothing")
check(Fr.post(B + "/api/disc/invites", json={}).status_code == 403 and Fr.get(B + "/api/disc/invites").json().get("on") is False and Fr.get(B + "/api/disc").json().get("invite_link") is False, "off: making 403, list on false, no button")  # 2.1156.0 (#4550): the list answers with the switch off
check(anon().post(B + "/api/auth/cinv/check", json={"token": T8}).status_code == 404, "off: an open link stops working")
check(A.patch(S, json={"cinv_signup": True, "password": PASSWORD}).ok, "on again")

# ---- the daily clean-up
gone = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
write("INSERT INTO conn_invites(user_id, token_hash, note, created_at, expires_at) VALUES(?,?,?,?,?)", (FID, "old-row", "", gone, gone))
out = py_in_app("from kalmido.accounts.cinvite import cinv_purge\nfrom kalmido.core.db import now_utc\nprint('purged', cinv_purge(c, now_utc()))")
check("purged" in out and not dbx("SELECT 1 FROM conn_invites WHERE token_hash='old-row'"), f"the clean-up removes a row run out long ago ({out[-200:]})")
check(anon().post(B + "/api/auth/cinv/check", json={"token": T8}).ok, "a fresh link stays")

# ---- the brake per client address on wrong tokens (an address of its own)
codes = [anon("203.0.113.77").post(B + "/api/auth/cinv/check", json={"token": "w" * 43}).status_code for _ in range(25)]
check(codes[0] == 404 and codes[-1] == 429, f"wrong tokens: 404, then the brake (429) ({codes[0]}, {codes[-1]})")
check(anon("203.0.113.78").post(B + "/api/auth/cinv/check", json={"token": T8}).ok, "another address is not braked")

# ================================================================= part 2: a server without e-mail
kt.fresh(prefix="P21156B")
A = kt.setup()
FID, Fr = freelancer(B, A)
DID, Do = freelancer(B, A, "dora")
check(A.patch(S, json={"cinv_signup": True, "password": PASSWORD}).ok, "no e-mail: an admin switches it on")
T1 = tok_of(Fr.post(B + "/api/disc/invites", json={}).json())
c1 = anon().post(B + "/api/auth/cinv/check", json={"token": T1}).json()
check(c1.get("mail") is False and c1.get("min_password", 0) >= 8, "no e-mail: the page asks for a password")
check(anon().post(B + "/api/auth/cinv/accept", json={"token": T1, "name": "Nina", "email": "nina@example.com"}).status_code == 400, "no password: 400")
Ni = anon()
r = Ni.post(B + "/api/auth/cinv/accept", json={"token": T1, "name": "Nina Example", "email": "nina@example.com", "password": "nina-pass-123"})
# 2.1156.0 C (#4550, Fable F1): without e-mail the username comes from the name and no address is kept (was: nina, the address)
check(r.ok and r.json().get("ok") is True and r.json().get("username") == "nina.example", f"active at once and signed in ({r.text[:200]})")
NINA = uid_of("nina.example")
check(NINA and not (dbx("SELECT email FROM users WHERE id=?", (NINA,))[0][0] or ""), "Fable F1: no unproved address on the account")
st = Ni.get(B + "/api/state").json()["me"]
check(st.get("username") == "nina.example" and st.get("workspaces") == [], "the session works; a private account")
check(FID in [x["person"]["id"] for x in Ni.get(B + "/api/disc").json()["connections"]], "connected with frida")
check(login(B, "nina.example", "nina-pass-123") is not None, "nina signs in with her password")
check(via(Fr.get(B + "/api/news").json().get("items", [])) == "invite", "frida's News: accepted your invitation")
T2 = tok_of(Fr.post(B + "/api/disc/invites", json={}).json())
Xx = anon()
r = Xx.post(B + "/api/auth/cinv/accept", json={"token": T2, "name": "Dora Again", "email": "dora@example.com", "password": "dora-pass-123"})
check(r.ok and set(r.json()) == {"ok", "user", "username"}, f"an address with an account: the same kind of answer ({r.text[:200]})")
check(dbx("SELECT COUNT(*) FROM users WHERE lower(email)='dora@example.com'")[0][0] == 1, "the address is not kept twice")
# 2.1156.0 C (#4550, Fable F2): the answer does not tell whether an address has an account: the username from the name either way
check(r.json().get("username") == "dora.again", f"Fable F2: the username from the name, not the address ({r.text[:200]})")
check(not (dbx("SELECT email FROM users WHERE username='dora.again'")[0][0] or ""), "Fable F2: no address on the new account")
T3 = tok_of(Fr.post(B + "/api/disc/invites", json={}).json())
r = anon().post(B + "/api/auth/cinv/accept", json={"token": T3, "name": "Jörg Müller", "password": "joerg-pass-123"})
check(r.ok and r.json().get("username") == "jorg.muller", f"Fable F1: no address needed; umlauts in the username ({r.text[:200]})")

sys.exit(kt.done("p21156_b_cinvite"))
