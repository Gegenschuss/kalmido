#!/usr/bin/env python3
# kalmido-suite:
"""2.985.0 part B (#4922): a silent invitation (org_joins.silent = 1, #3570) does not vanish when the invited account is
deleted. Own container (start.sh, mode workspaces, SMTP sink stub_mail.py). Invented names only (example.com).
 - frida (no organisation) has companies of her own (orgs.self_made); paula and dora have accounts frida may not see: their
   invitations are kept silent
 - paula deletes her own account (the watchdog's final run), dora's unconfirmed registration is cleaned up (signup _cleanup):
   their invitations stay in the company's list of open invitations exactly as before (address, role, time, state; no
   account id), as neutral rows without an account; an ordinary invitation goes with the account as before
 - Resend and Withdraw of a neutral row answer as for a silent one (the row starts again / is gone)
 - the address invited again - without an account (a new one is made) or with a new account of that address - stands once
   in the list: the neutral row gives way
 - review F1: the list and the neutral row keep the address typed, not the account's later one; F4: "add member" (ojn_invite)
   replaces the neutral row as well
usage: p2930_b_invite_test.py <datadir>"""
import os
import shutil
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, dbx, until  # noqa: E402

SMTP = {"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
        "KALMIDO_MAIL_FROM": "kalmido@example.test", "KALMIDO_INSTANCE_MODE": "workspaces"}
if kt.fresh(env=SMTP, prefix="P2930B"):
    os.makedirs(os.path.join(DATA, "mail"), exist_ok=True)
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
A = kt.setup()


def write(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    c.execute(q, args)
    c.commit()
    c.close()


def py_in_app(code):
    """Python inside the app container (the clean-up of unconfirmed registrations runs on a sign-up request only)."""
    for _ in range(4):  # "import app" runs init_db next to the running server: now and then a Postgres deadlock of this helper
        r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                            "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.commit()\nc.close()"],
                           capture_output=True, text=True)
        if "deadlock detected" not in r.stderr:
            break
        time.sleep(2)
    return (r.stdout + r.stderr).strip()


FID, Fr = freelancer(B, A)
PID, Pa = freelancer(B, A, "paula")
DID, _Do = freelancer(B, A, "dora")
O1, O2, O4 = (Fr.post(B + "/api/orgs", json={"name": n}).json().get("id") for n in ("Frida Studio", "Frida Labor", "Frida Atelier"))
check(O1 and O2 and O4, f"setup: frida's companies {O1} {O2} {O4}")


def invite(oid, email):
    r = Fr.post(B + f"/api/orgs/{oid}/invites", json={"email": email, "role": "member"})
    check(r.ok, f"setup: invite {email} into {oid}: {r.status_code} {r.text[:200]}")


def rows(oid, email):
    """The list's rows of an address, without the reference (sealed anew on every read)."""
    return [{k: v for k, v in x.items() if k != "ref"} for x in Fr.get(B + f"/api/orgs/{oid}/invites").json().get("invites", []) if x.get("email") == email]


def ref(oid, email):
    return next((x["ref"] for x in Fr.get(B + f"/api/orgs/{oid}/invites").json().get("invites", []) if x.get("email") == email), "x")


invite(O1, "paula@example.com")
invite(O4, "paula@example.com")
invite(O2, "dora@example.com")
check(dbx("SELECT COUNT(*) FROM org_joins WHERE user_id IN (?,?) AND silent=1", (PID, DID))[0][0] == 3, "setup: the invitations are kept silent (#3570)")
write("INSERT INTO org_joins(org_id, user_id, role, created_by, created_at) VALUES(?,?,?,?,?)", (O2, PID, "member", FID, "2026-11-10T00:00:00+00:00"))  # an ordinary one
before_p, before_d, before_p4 = rows(O1, "paula@example.com"), rows(O2, "dora@example.com"), rows(O4, "paula@example.com")
check(len(before_p) == 1 and before_p[0].get("state") == "invited" and before_p[0].get("user_id") is None, f"setup: paula's row in the list {before_p}")
check(len(before_d) == 1 and len(before_p4) == 1, f"setup: dora's and paula's second row {before_d} {before_p4}")

# ---------------------------------------------------------------- paula deletes her own account (the watchdog's final run)
r = Pa.post(B + "/api/account/delete", json={"password": kt.PASSWORD, "lists": {}})
check(r.ok, f"setup: paula asks to delete her account {r.status_code} {r.text[:200]}")
write("UPDATE users SET delete_at='2000-01-01T00:00:00+00:00' WHERE id=?", (PID,))
check(bool(until(lambda: not dbx("SELECT 1 FROM users WHERE id=?", (PID,)), 30)), "setup: the watchdog deleted paula's account")
# without #4922 the row went with the account (ON DELETE CASCADE): the list lacked it, while a new address's row stays
after = rows(O1, "paula@example.com")
check(after == before_p, f"(#4922) after her own deletion paula's silent invitation stands in the list exactly as before {after} {before_p}")
check([(x[0], x[1]) for x in dbx("SELECT user_id, silent FROM org_joins WHERE org_id=? AND email=?", (O1, "paula@example.com"))] == [(None, 1)],
      "(#4922) ... as a neutral row without an account")
check(rows(O4, "paula@example.com") == before_p4, "(#4922) ... in each company that invited her")
check(not dbx("SELECT 1 FROM org_joins WHERE org_id=? AND silent=0", (O2,)), "(#4922) the ordinary invitation went with the account as before")

# ---------------------------------------------------------------- dora's unconfirmed registration is cleaned up
write("UPDATE users SET signup='confirm' WHERE id=?", (DID,))
out = py_in_app("from kalmido.accounts.signup import _cleanup\n_cleanup(c)")
check(not dbx("SELECT 1 FROM users WHERE id=?", (DID,)), "setup: dora's unconfirmed account is cleaned up " + out[-300:])
after = rows(O2, "dora@example.com")
check(after == before_d, f"(#4922) after the clean-up dora's silent invitation stands in the list as before {after} {before_d}")

# ---------------------------------------------------------------- Resend and Withdraw answer as for a silent one
r = Fr.post(B + f"/api/orgs/{O1}/invites/{ref(O1, 'paula@example.com')}/resend", json={})
check(r.ok and r.json().get("invitation") == {"sent": True, "email": "paula@example.com"}, f"(#4922) Resend answers as for a silent one {r.status_code} {r.text[:200]}")
after = rows(O1, "paula@example.com")
check(len(after) == 1 and after[0]["state"] == "invited" and after[0]["created_at"] >= before_p[0]["created_at"], f"(#4922) ... and the row starts again {after}")
r = Fr.delete(B + f"/api/orgs/{O1}/invites/{ref(O1, 'paula@example.com')}")
check(r.ok and r.json().get("email") == "paula@example.com" and r.json().get("role") == "member", f"(#4922) Withdraw answers with the address {r.status_code} {r.text[:200]}")
check(rows(O1, "paula@example.com") == [] and not dbx("SELECT 1 FROM org_joins WHERE org_id=?", (O1,)), "(#4922) ... and the row is gone")

# ---------------------------------------------------------------- the address invited again: one row in the list
invite(O2, "dora@example.com")  # no account any more: a new one is made
after = rows(O2, "dora@example.com")
check(len(after) == 1 and after[0]["state"] == "invited", f"(#4922) dora's address invited again stands once in the list {after}")
check(not dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id IS NULL", (O2,)), "(#4922) the neutral row gave way to the new invitation")
PID2, _Pa2 = freelancer(B, A, "paula")  # a new account of paula's address
invite(O4, "paula@example.com")
after = rows(O4, "paula@example.com")
check(len(after) == 1 and after[0]["state"] == "invited", f"(#4922) paula's address with a new account invited again stands once in the list {after}")
check(not dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id IS NULL", (O4,)), "(#4922) ... the neutral row gave way here as well")

# ---------------------------------------------------------------- review F1: the address typed, never the account's later one
GID, _Ge = freelancer(B, A, "gerda")
invite(O1, "gerda@example.com")
before_g = rows(O1, "gerda@example.com")
check(len(before_g) == 1, f"setup: gerda's silent invitation in the list {before_g}")
write("UPDATE users SET email=? WHERE id=?", ("gerda.neu@example.com", GID))  # gerda changes her address
# without the fix the list followed the account: the new address showed (an account exists, and which address it has now)
check(rows(O1, "gerda@example.com") == before_g and rows(O1, "gerda.neu@example.com") == [],
      f"(#4922 F1) after gerda changes her address the list still shows the address typed {rows(O1, 'gerda.neu@example.com')}")
r = _Ge.post(B + "/api/account/delete", json={"password": kt.PASSWORD, "lists": {}})
check(r.ok, f"setup: gerda asks to delete her account {r.status_code} {r.text[:200]}")
write("UPDATE users SET delete_at='2000-01-01T00:00:00+00:00' WHERE id=?", (GID,))
check(bool(until(lambda: not dbx("SELECT 1 FROM users WHERE id=?", (GID,)), 30)), "setup: the watchdog deleted gerda's account")
check(rows(O1, "gerda@example.com") == before_g, f"(#4922 F1) after the deletion the row is the same {rows(O1, 'gerda@example.com')}")
check([x[0] for x in dbx("SELECT email FROM org_joins WHERE org_id=? AND user_id IS NULL", (O1,))] == ["gerda@example.com"],
      "(#4922 F1) the neutral row keeps the address typed, not the account's later one")

# ---------------------------------------------------------------- review F4: every way of inviting replaces the neutral row
write("UPDATE orgs SET self_made=0 WHERE id=?", (O1,))  # an ordinary organisation: PUT /members invites (ojn_invite), not silently
freelancer(B, A, "gerda")  # a new account of the address
r = Fr.put(B + f"/api/orgs/{O1}/members", json={"email": "gerda@example.com", "role": "member"})
check(r.ok, f"setup: frida adds gerda's address as a member {r.status_code} {r.text[:200]}")
after = rows(O1, "gerda@example.com")
check(len(after) == 1, f"(#4922 F4) the address invited by 'add member' stands once in the list {after}")
check(not dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id IS NULL", (O1,)), "(#4922 F4) ... the neutral row gave way")

sys.exit(kt.done("p2930_b_invite"))
