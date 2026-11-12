#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1033.0 (#5790): a person proves the own e-mail address (Settings > Account > E-mail address, "Confirm address"). Own
container (start.sh with the SMTP stub of tests/stub_mail.py, workspaces). Invented people and addresses only.
freelancer-matrix: own
 - GET /api/me/email: the own address, not proved yet (an admin typed it in), mail sending on
 - an organisation admin invites the unproved address (#5775: a silent row, nothing for the person) - in an ordinary
   organisation and in a company of its own whose admin may not see the person (#3570)
 - POST /api/me/email/proof: a mail to the address with a one-time link (#mailproof/<token>); the token is not in the database
 - the link opened by another account (signed in as somebody else): 404, nothing proved for either, the link still works
 - a wrong token: 404; the right one: proved (users.email_proved), the silent invitation of the ordinary organisation woke
   (GET /api/orgs joins, News item orgjoin, the person can accept it), the one of the company of its own stays silent
 - the link a second time: 404; "Confirm address" once proved: proved, no new mail
 - GET /api/me/mail names the own address again (it was swallowed by a comment since 2.49.0) and email_proved
 - the address changed after the mail was sent: 409, nothing proved (the link proves the old address only)
 - all of it as a person without an organisation (P4)
usage: p21033_a_mailproof_api_test.py <datadir>"""
import email
import email.policy
import json
import os
import re
import shutil
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
import kt  # noqa: E402
from kt import B, CT, DATA, check, dbx, done, sess, until  # noqa: E402

MAILENV = {"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
           "KALMIDO_MAIL_FROM": "kalmido@example.test", "KALMIDO_INSTANCE_MODE": "workspaces"}
kt.fresh(MAILENV)
os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
until(lambda: subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 1025), 1)"],
                             capture_output=True).returncode == 0, 20)


def wr(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def proofs(to):
    """The proof mails to address `to` (the SMTP stub's out.jsonl) -> [token], oldest first."""
    p, out = os.path.join(DATA, "mail", "out.jsonl"), []
    if os.path.exists(p):
        for ln in open(p):
            if not ln.strip():
                continue
            m = email.message_from_string(json.loads(ln)["raw"], policy=email.policy.default)
            if to in str(m["To"] or "") and "Confirm your e-mail address" in str(m["Subject"] or ""):
                t = m.get_body(("plain",)).get_content()
                out.append((re.search(r"#mailproof/([A-Za-z0-9_-]{20,100})", t) or [None, None])[1])
    return out


def proved(uid):
    return dbx("SELECT email_proved FROM users WHERE id=?", (uid,))[0][0]


def news_kinds(s):
    return [x["kind"] for x in s.get(B + "/api/news?limit=50").json().get("items", [])]


A = kt.setup()
ids = {}
for u in ("bob", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, ERIN = ids["bob"], ids["erin"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB}).json()["id"]
SELF = A.post(B + "/api/admin/orgs", json={"name": "Erin Studio", "admin_id": ERIN}).json()["id"]
wr("DELETE FROM org_members WHERE NOT ((org_id=? AND user_id=?) OR (org_id=? AND user_id=?))", (ORG, BOB, SELF, ERIN))
wr("UPDATE orgs SET self_made=? WHERE id=?", (ERIN, SELF))  # a company of Erin's own (#3570): she reaches only people she may see
FID, Fr = freelancer(B, A, "fiona")   # the person without an organisation who proves her address
CID, Cr = freelancer(B, A, "cleo")    # another one: opens Fiona's link, later changes her own address
Bo, Er = sess("bob"), sess("erin")

# ---- the own address, not proved (the admin typed it in)
j = Fr.get(B + "/api/me/email").json()
check(j == {"email": "fiona@example.com", "proved": False, "mail_out": True}, "GET /api/me/email: the own address, not proved " + json.dumps(j))
check(not proved(FID), "the admin's address is not proved")
m = Fr.get(B + "/api/me/mail").json()
check(m.get("email") == "fiona@example.com" and m.get("email_proved") is False, "GET /api/me/mail names the address again, not proved " + json.dumps(m)[:300])

# ---- invitations to the unproved address stay silent (#5775)
r = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "fiona@example.com"})
check(r.ok, "Bob invites Fiona's address " + r.text[:200])
r = Er.post(B + f"/api/orgs/{SELF}/invites", json={"email": "fiona@example.com"})
check(r.ok, "Erin invites Fiona's address into her company of her own " + r.text[:200])
check(dbx("SELECT org_id, silent, email FROM org_joins WHERE user_id=? ORDER BY org_id", (FID,)) == [(ORG, 1, "fiona@example.com"), (SELF, 1, "fiona@example.com")],
      "two silent rows with the typed address")
check(Fr.get(B + "/api/orgs").json().get("joins") == [] and "orgjoin" not in news_kinds(Fr), "nothing for Fiona yet")

# ---- the proof mail
r = Fr.post(B + "/api/me/email/proof")
check(r.ok and r.json().get("sent") is True and r.json().get("email") == "fiona@example.com", "POST /api/me/email/proof sends the mail " + r.text[:200])
toks = until(lambda: proofs("fiona@example.com"), 20)
check(len(toks) == 1 and toks[0], "one proof mail with the link to fiona@example.com")
TOK = toks[0] if toks else "x" * 43
check(not dbx("SELECT 1 FROM eph_state WHERE v LIKE ? OR k=?", ("%" + TOK + "%", TOK)), "the token itself is stored nowhere")
check(not proved(FID), "sending proves nothing")

# ---- another account opens the link: nothing for either
r = Cr.post(B + "/api/me/email/proof/confirm", json={"token": TOK})
check(r.status_code == 404 and not proved(FID) and not proved(CID), "the link opened signed in as Cleo: 404, nothing proved " + r.text[:200])
r = Fr.post(B + "/api/me/email/proof/confirm", json={"token": "A" * 43})
check(r.status_code == 404 and not proved(FID), "a wrong token: 404")
r = Fr.post(B + "/api/me/email/proof/confirm", json={"token": 5})
check(r.status_code == 404, "a token that is no text: 404")

# ---- Fiona opens it: proved, the ordinary organisation's invitation wakes, the company of its own stays silent
r = Fr.post(B + "/api/me/email/proof/confirm", json={"token": TOK})
check(r.ok and r.json().get("proved") is True and r.json().get("invitations") == 1, "Fiona's own link proves her address, one invitation woke " + r.text[:200])
check(proved(FID) == "fiona@example.com", "users.email_proved is set")
check(Fr.get(B + "/api/me/email").json().get("proved") is True and Fr.get(B + "/api/me/mail").json().get("email_proved") is True, "both settings say proved")
joins = Fr.get(B + "/api/orgs").json().get("joins") or []
check([x["org_id"] for x in joins] == [ORG] and joins[0]["by"] == "Bob", "the invitation of Alpha is open for Fiona now, in Bob's name " + json.dumps(joins)[:300])
check("orgjoin" in news_kinds(Fr), "a News item for the invitation")
check(dbx("SELECT org_id, silent FROM org_joins WHERE user_id=? ORDER BY org_id", (FID,)) == [(ORG, 0), (SELF, 1)],
      "the company of its own keeps its row silent (#3570: its admin may not see Fiona)")
check(Fr.post(B + f"/api/orgs/{SELF}/join").status_code == 404, "... and Fiona cannot accept that one")
check(Fr.post(B + f"/api/orgs/{ORG}/join").ok and dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (ORG, FID)), "Fiona accepts Alpha")
r = Fr.post(B + "/api/me/email/proof/confirm", json={"token": TOK})
check(r.status_code == 404, "the link works once")
n0 = len(proofs("fiona@example.com"))
r = Fr.post(B + "/api/me/email/proof")
check(r.ok and r.json().get("proved") is True and "sent" not in r.json(), "Confirm address when proved: nothing to send " + r.text[:200])
check(len(proofs("fiona@example.com")) == n0, "no second mail")

# ---- the address changed after the mail: the link proves the old one only
r = Cr.post(B + "/api/me/email/proof")
check(r.ok and r.json().get("sent") is True, "Cleo asks for a proof mail")
ct = until(lambda: proofs("cleo@example.com"), 20)
r = A.patch(B + f"/api/users/{CID}", json={"email": "cleo.new@example.com"})
check(r.ok, "the admin changes Cleo's address")
r = Cr.post(B + "/api/me/email/proof/confirm", json={"token": ct[-1] if ct else "y" * 43})
check(r.status_code == 409 and not proved(CID), "the old address's link after the change: 409, nothing proved " + r.text[:200])
check(Cr.get(B + "/api/me/email").json() == {"email": "cleo.new@example.com", "proved": False, "mail_out": True}, "Cleo's new address is not proved")

done("p21033_a_mailproof_api")
