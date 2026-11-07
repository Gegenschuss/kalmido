#!/usr/bin/env python3
# kalmido-suite:
"""2.593.0 Teil C (#3570): the invitations of an organisation never tell an address with an account from a new one. Own
container (start.sh, mode workspaces, SMTP sink stub_mail.py). Invented names only (example.com).
 - frida (no organisation) has two companies of her own (orgs.self_made); paula has an account frida may not see, dora a
   disabled one; neu@ / neu2@ have none
 - POST /api/orgs/<id>/invites for paula's address into company 1 and for neu@ into company 2: the answers and the lists of
   open invitations are the same but for address, time and reference (same fields, state "invited", no user_id)
 - paula hears nothing (no News item, no invitation in GET /api/orgs, POST .../join 404): the invitation is kept silent
   (org_joins.silent = 1); dora's (disabled) likewise, with the same answer
 - Resend and Withdraw take the neutral reference for both and answer the same
 - PUT /api/orgs/<id>/members {email} for paula in a company of her own: the same answer, no invitation at all
 - an organisation of the server's admin (not self made): frida as its admin invites paula as before (a News item for paula)
usage: p2593_c_invite_test.py <datadir>      (P2593C_NOSTART=1: a running server, no start.sh)
freelancer-matrix: own"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check  # noqa: E402

SMTP = {"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
        "KALMIDO_MAIL_FROM": "kalmido@example.test", "KALMIDO_INSTANCE_MODE": "workspaces"}
EM = re.compile(r"[a-z0-9.+-]+@example\.com")


def norm(v):
    """The answer without what may differ: addresses, time stamps, references."""
    if isinstance(v, dict):
        return {k: ("T" if k == "created_at" else "R" if k == "ref" else norm(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [norm(x) for x in v]
    return EM.sub("E", v) if isinstance(v, str) else v


def one(sql, args=()):
    r = kt.dbx(sql, args)
    return r[0][0] if r else None


def mails():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8")]
    except OSError:
        return []


def joins_of(s):
    return s.get(B + "/api/orgs").json().get("joins") or []


def orgjoin_news(uid):
    return one("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='orgjoin'", (uid,))


if kt.fresh(env=SMTP, prefix="P2593C"):
    os.makedirs(os.path.join(DATA, "mail"), exist_ok=True)
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
    time.sleep(1)
A = kt.setup()
FID, Fr = freelancer(B, A)
PID, Pa = freelancer(B, A, "paula")
DID, _Do = freelancer(B, A, "dora")
check(A.patch(B + f"/api/users/{DID}", json={"disabled": True}).ok, "setup: dora's account is disabled")
O1, O2, O3 = (Fr.post(B + "/api/orgs", json={"name": n}).json().get("id") for n in ("Frida Studio", "Frida Labor", "Frida Werkstatt"))
check(O1 and O2 and O3, f"setup: frida's companies {O1} {O2} {O3}")


def invite(oid, email):
    r = Fr.post(B + f"/api/orgs/{oid}/invites", json={"email": email, "role": "member"})
    check(r.ok, f"invite {email} into {oid}: {r.status_code} {r.text[:200]}")
    return r.json() if r.ok else {}


def listed(oid):
    return Fr.get(B + f"/api/orgs/{oid}/invites").json()


# ---------------------------------------------------------------- the same answer and list for an account and a new address
a_acc, a_new = invite(O1, "paula@example.com"), invite(O2, "neu@example.com")
check(norm(a_acc) == norm(a_new) and a_acc.get("invites"), f"the answers are the same {a_acc} {a_new}")
l_acc, l_new = listed(O1), listed(O2)
check(norm(l_acc) == norm(l_new) and len(l_acc["invites"]) == 1, f"the lists are the same {l_acc} {l_new}")
row = l_acc["invites"][0]
check(row["state"] == "invited" and row["user_id"] is None and row["email"] == "paula@example.com", f"the row of paula {row}")
check(one("SELECT silent FROM org_joins WHERE org_id=? AND user_id=?", (O1, PID)) == 1, "paula's invitation is kept silent")
check(orgjoin_news(PID) == 0 and not joins_of(Pa), "paula hears nothing (no News item, nothing to answer in GET /api/orgs)")
check(Pa.post(B + f"/api/orgs/{O1}/join").status_code == 404 and Pa.delete(B + f"/api/orgs/{O1}/join").status_code == 404,
      "paula can neither accept nor decline it")
check(not one("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (O1, PID)), "paula is no member")

# a disabled account: the same as a new address
a_dead = invite(O3, "dora@example.com")
check(norm(a_dead) == norm(a_new) and norm(listed(O3)) == norm(l_new), f"a disabled account answers the same {a_dead}")
check(one("SELECT silent FROM org_joins WHERE org_id=? AND user_id=?", (O3, DID)) == 1, "dora's invitation is kept silent")

# ---------------------------------------------------------------- resend and withdraw by the neutral reference
r1 = Fr.post(B + f"/api/orgs/{O1}/invites/{l_acc['invites'][0]['ref']}/resend")
r2 = Fr.post(B + f"/api/orgs/{O2}/invites/{l_new['invites'][0]['ref']}/resend")
check(r1.ok and r2.ok and norm(r1.json()) == norm(r2.json()), f"resend answers the same {r1.status_code} {r1.text[:300]} {r2.text[:300]}")
check(orgjoin_news(PID) == 0, "the resend still tells paula nothing")
r1 = Fr.delete(B + f"/api/orgs/{O1}/invites/{listed(O1)['invites'][0]['ref']}")
r2 = Fr.delete(B + f"/api/orgs/{O2}/invites/{listed(O2)['invites'][0]['ref']}")
check(r1.ok and r2.ok and norm(r1.json()) == norm(r2.json()) and not r1.json()["invites"],
      f"withdraw answers the same {r1.status_code} {r1.text[:300]} {r2.text[:300]}")
check(not one("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (O1, PID)) and one("SELECT 1 FROM users WHERE id=?", (PID,)),
      "paula's silent invitation is gone, her account stays")

# ---------------------------------------------------------------- PUT members by address: dropped in a company of her own
r1 = Fr.put(B + f"/api/orgs/{O1}/members", json={"email": "paula@example.com", "role": "member"})
r2 = Fr.put(B + f"/api/orgs/{O1}/members", json={"email": "neu2@example.com", "role": "member"})
check(r1.ok and r2.ok and r1.json() == r2.json(), f"PUT members answers the same {r1.text[:200]} {r2.text[:200]}")
check(not one("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (O1, PID)) and orgjoin_news(PID) == 0,
      "PUT members invites nobody frida may not see into her company")

# ---------------------------------------------------------------- 2.593.0 (#3570) review F1-F3
# at most ORG_SELF_MAX (3) companies of her own: companies 1 and 2 are empty again, company 3 holds dora's silent invitation
O4, O5, O6, O7 = O1, O2, O3, O2
check(not listed(O1)["invites"] and not listed(O2)["invites"], "setup: companies 1 and 2 have no open invitation")
kt.dbx("UPDATE users SET email=? WHERE id=?", ("Paula@Example.com", PID))  # saved in her own spelling
kt.dbx("SELECT setval(pg_get_serial_sequence('org_joins', 'id'), 100000)")  # an invitation number of other length than an account's
invite(O4, "pAULA@example.com")
QUEUED = "SELECT COUNT(*) FROM bg_jobs WHERE kind='mail:security'"
q0 = one(QUEUED)
invite(O5, "Neu3@Example.COM")
l4, l5 = listed(O4)["invites"], listed(O5)["invites"]
# F1: the list shows the address in small letters for both kinds (not the account holder's own spelling)
check([x["email"] for x in l4] == ["paula@example.com"] and [x["email"] for x in l5] == ["neu3@example.com"]
      and l4[0]["name"] == "paula@example.com" and l5[0]["name"] == "neu3@example.com", f"review F1: the addresses alike {l4} {l5}")
# F2: the reference has the same length for an account and a new address
check(len(l4[0]["ref"]) == len(l5[0]["ref"]), f"review F2: the references are of the same length {l4[0]['ref']} {l5[0]['ref']}")
# F3: the invitation mail of the new address goes through the background queue, not within the request
N3 = one("SELECT id FROM users WHERE lower(email)='neu3@example.com'")
check(kt.until(lambda: one(QUEUED) > q0, 20), "review F3: the invitation mail of a new address is queued in the background")
check(kt.until(lambda: [m for m in mails() if "neu3@example.com" in [a.lower() for a in m.get("to") or []]], 20),
      "review F3: the queued invitation mail goes out")
check(kt.until(lambda: one("SELECT sent_at FROM user_invites WHERE user_id=?", (N3,)), 20), "review F3: the link counts as mailed")
r1 = Fr.post(B + f"/api/orgs/{O4}/invites/{l4[0]['ref']}/resend")
r2 = Fr.post(B + f"/api/orgs/{O5}/invites/{l5[0]['ref']}/resend")
check(r1.ok and r2.ok and r1.json()["invitation"]["email"] == "paula@example.com" and r2.json()["invitation"]["email"] == "neu3@example.com",
      f"review F1: Resend answers the address in small letters {r1.text[:200]} {r2.text[:200]}")
check(kt.until(lambda: one(QUEUED) > q0 + 1, 20),
      "review F3: Resend of a new address mails in the background, too")
r2 = Fr.delete(B + f"/api/orgs/{O5}/invites/{listed(O5)['invites'][0]['ref']}")
check(r2.ok and r2.json()["email"] == "neu3@example.com" and r2.json()["name"] == "neu3@example.com", f"review F1: Withdraw answers it in small letters {r2.text[:200]}")
check(one("SELECT silent FROM org_joins WHERE org_id=? AND user_id=?", (O4, PID)) == 1, "paula's invitation into company 4 is silent")

# ---------------------------------------------------------------- an organisation of the server's admin: as before
r = A.post(B + "/api/admin/orgs", json={"name": "Beispiel GmbH", "admin_id": FID})
check(r.status_code in (200, 201), f"setup: the server admin's organisation {r.status_code} {r.text[:200]}")
OA = r.json().get("id")
invite(OA, "paula@example.com")
check(one("SELECT silent FROM org_joins WHERE org_id=? AND user_id=?", (OA, PID)) == 0 and orgjoin_news(PID) == 1
      and [x["org_id"] for x in joins_of(Pa)] == [OA], "outside a company of her own paula is invited as before")

# ---------------------------------------------------------------- 2.593.0 (#3570) review F5 (b): Resend once the admin may see her
r = Pa.post(B + f"/api/orgs/{OA}/join")
check(r.ok, f"setup: paula joins the server admin's organisation (frida may see her now) {r.status_code} {r.text[:200]}")
r = Fr.post(B + f"/api/orgs/{O4}/invites/{listed(O4)['invites'][0]['ref']}/resend")
check(r.ok, f"Resend of paula's silent invitation {r.status_code} {r.text[:200]}")
check(one("SELECT silent FROM org_joins WHERE org_id=? AND user_id=?", (O4, PID)) == 0 and orgjoin_news(PID) == 2
      and O4 in [x["org_id"] for x in joins_of(Pa)], "review F5: Resend makes it an ordinary invitation paula hears of")

# ---------------------------------------------------------------- review F5 (a): a silent repeat does not open an expired ordinary one
invite(O7, "neu5@example.com")
N5 = one("SELECT id FROM users WHERE lower(email)='neu5@example.com'")
OLDJ = "2026-01-02T03:04:05+00:00"
kt.dbx("UPDATE org_joins SET created_at=? WHERE org_id=? AND user_id=?", (OLDJ, O7, N5))
check(listed(O7)["invites"][0]["state"] == "expired", "setup: the invitation of neu5 has expired")
invite(O7, "neu5@example.com")  # the address has an account now: frida may not see it -> the silent way
check(one("SELECT created_at FROM org_joins WHERE org_id=? AND user_id=?", (O7, N5)) == OLDJ
      and one("SELECT silent FROM org_joins WHERE org_id=? AND user_id=?", (O7, N5)) == 0
      and listed(O7)["invites"][0]["state"] == "expired", "review F5: the expired ordinary invitation is not opened again silently")

# ---------------------------------------------------------------- review F4: withdrawing keeps an account another company's silent invitation lies on
GID, Gi = freelancer(B, A, "gina")
OG = Gi.post(B + "/api/orgs", json={"name": "Gina Atelier"}).json().get("id")
r = Gi.post(B + f"/api/orgs/{OG}/invites", json={"email": "neu6@example.com", "role": "member"})
check(OG and r.ok, f"setup: gina invites a new address {r.status_code} {r.text[:200]}")
N6 = one("SELECT id FROM users WHERE lower(email)='neu6@example.com'")
invite(O6, "neu6@example.com")
check(one("SELECT silent FROM org_joins WHERE org_id=? AND user_id=?", (O6, N6)) == 1, "setup: frida's invitation of neu6 is silent")
r = Gi.delete(B + f"/api/orgs/{OG}/invites/{Gi.get(B + f'/api/orgs/{OG}/invites').json()['invites'][0]['ref']}")
check(r.ok, f"gina withdraws her invitation {r.status_code} {r.text[:200]}")
check(one("SELECT 1 FROM users WHERE id=?", (N6,)) and "neu6@example.com" in [x["email"] for x in listed(O6)["invites"]],
      "review F4: the account stays, frida's silent invitation does not vanish from her list")

sys.exit(kt.done("p2593_c_invite"))
