#!/usr/bin/env python3
# kalmido-suite:
"""2.1005.0 part B (#5118, review F2 of 2.985.0): the daily clean-up (admin/dataretention.py lgc_tick -> lgc_expired ->
accounts/orginvite.py ojn_purge) deletes organisation invitations (org_joins) that ran out more than OJN_PURGE_DAYS ago
(made more than OJN_DAYS + OJN_PURGE_DAYS days ago). Own container (start.sh, mode workspaces, SMTP sink stub_mail.py).
Invented names only (example.com).
 - frida (no organisation) has companies of her own (orgs.self_made); paula and dora have accounts frida may not see: their
   invitations are kept silent (ojn_silent); paula deletes her account: her rows become neutral (ojn_neutral)
 - 2.1062.0 (#5786): every kind of row alike - silent, neutral, ordinary and the row of a new account this company made:
   past the period they go, just within it they stay (before, 2.1005.0 review F1, silent / neutral rows stayed for ever
   because the new account's row did)
 - one whose new-account link was used lately stays (still open, OJN_LIVE)
 - an open (fresh) invitation stays, an accepted one keeps its membership
 - 2.1062.0 (#5786): the never used account itself: OINV_WARN_DAYS before its day a warning mail with the date and a link;
   withdrawn (deleted) only on its day and OINV_WARN_DAYS after a delivered warning; not one without an address (no warning
   delivered), one set up meanwhile, one that belongs to another organisation, or a fresh one
usage: p21005_b_invite_purge_test.py <datadir>"""
import email
import email.policy
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, dbx, until  # noqa: E402

SMTP = {"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
        "KALMIDO_MAIL_FROM": "kalmido@example.test", "KALMIDO_INSTANCE_MODE": "workspaces"}
if kt.fresh(env=SMTP, prefix="P21005B"):
    os.makedirs(os.path.join(DATA, "mail"), exist_ok=True)
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
A = kt.setup()

OJN_DAYS, PURGE_DAYS = 14, 30  # accounts/orginvite.py OJN_DAYS, OJN_PURGE_DAYS
NOW = datetime.now(timezone.utc)
OLD = (NOW - timedelta(days=OJN_DAYS + PURGE_DAYS + 1)).isoformat(timespec="seconds")  # past the period
EDGE = (NOW - timedelta(days=OJN_DAYS + PURGE_DAYS - 1)).isoformat(timespec="seconds")  # just within it


def write(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    c.execute(q, args)
    c.commit()
    c.close()


def py_in_app(code):
    """Python inside the app container (the clean-up runs from the watchdog once a day; here forced)."""
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
GID, _Ge = freelancer(B, A, "gerda")
HID, _He = freelancer(B, A, "harald")
IID, _Ie = freelancer(B, A, "ida")
KID, Ka = freelancer(B, A, "karl")
O1, O2 = (Fr.post(B + "/api/orgs", json={"name": n}).json().get("id") for n in ("Frida Studio", "Frida Labor"))
check(O1 and O2, f"setup: frida's companies {O1} {O2}")


def invite(oid, email):
    r = Fr.post(B + f"/api/orgs/{oid}/invites", json={"email": email, "role": "member"})
    check(r.ok, f"setup: invite {email} into {oid}: {r.status_code} {r.text[:200]}")


def emails(oid):
    return sorted(x.get("email") for x in Fr.get(B + f"/api/orgs/{oid}/invites").json().get("invites", []))


def joins(oid, email):
    return dbx("SELECT 1 FROM org_joins j LEFT JOIN users u ON u.id=j.user_id WHERE j.org_id=? AND COALESCE(j.email, u.email)=?", (oid, email))


# silent rows (frida may not see paula / dora / gerda)
for oid in (O1, O2):
    invite(oid, "paula@example.com")
    invite(oid, "dora@example.com")
invite(O1, "gerda@example.com")
check(dbx("SELECT COUNT(*) FROM org_joins WHERE user_id IN (?,?,?) AND silent", (PID, DID, GID))[0][0] == 5, "setup: the invitations are kept silent")
# a new account this company makes (org_invites + org_joins, silent=0)
invite(O1, "neu@example.com")
NID = dbx("SELECT id FROM users WHERE email=?", ("neu@example.com",))[0][0]
check(bool(dbx("SELECT 1 FROM org_invites WHERE org_id=? AND user_id=?", (O1, NID))), "setup: the new account's org_invites row")
# ordinary invitations of existing accounts (silent=0), inserted as in tests/p2930_b_invite_test.py
for oid, uid in ((O1, HID), (O2, HID), (O1, IID), (O1, KID)):
    write("INSERT INTO org_joins(org_id, user_id, role, created_by, created_at) VALUES(?,?,?,?,?)", (oid, uid, "member", FID, NOW.isoformat(timespec="seconds")))

# karl accepts his (open) invitation
r = Ka.post(B + f"/api/orgs/{O1}/join", json={})
check(r.ok, f"setup: karl accepts {r.status_code} {r.text[:200]}")
check(bool(dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (O1, KID))), "setup: karl is a member")

# paula deletes her account: her silent rows become neutral rows
r = Pa.post(B + "/api/account/delete", json={"password": kt.PASSWORD, "lists": {}})
check(r.ok, f"setup: paula asks to delete her account {r.status_code} {r.text[:200]}")
write("UPDATE users SET delete_at='2000-01-01T00:00:00+00:00' WHERE id=?", (PID,))
check(bool(until(lambda: not dbx("SELECT 1 FROM users WHERE id=?", (PID,)), 30)), "setup: the watchdog deleted paula's account")
check(dbx("SELECT COUNT(*) FROM org_joins WHERE user_id IS NULL AND silent AND email=?", ("paula@example.com",))[0][0] == 2, "setup: paula's two neutral rows")

# the ages: O1 past the period, O2 just within it (neutral and silent alike)
write("UPDATE org_joins SET created_at=? WHERE org_id=? AND email=? AND user_id IS NULL", (OLD, O1, "paula@example.com"))
write("UPDATE org_joins SET created_at=? WHERE org_id=? AND email=? AND user_id IS NULL", (EDGE, O2, "paula@example.com"))
write("UPDATE org_joins SET created_at=? WHERE org_id=? AND user_id=?", (OLD, O1, DID))
write("UPDATE org_joins SET created_at=? WHERE org_id=? AND user_id=?", (EDGE, O2, DID))
write("UPDATE org_joins SET created_at=? WHERE org_id=? AND user_id=?", (OLD, O1, NID))  # the new account's row: old, goes (#5786)
write("UPDATE org_joins SET created_at=? WHERE org_id=? AND user_id=?", (OLD, O1, HID))  # ordinary, old: goes
write("UPDATE org_joins SET created_at=? WHERE org_id=? AND user_id=?", (EDGE, O2, HID))  # ordinary, just within: stays
# ida: an old ordinary row whose new-account link (made after it) was used 20 days ago: kept by the OJN_LIVE test (a used link
# itself goes 30 days after its use, lgc_expired "invites", in the same run before ojn_purge)
write("UPDATE org_joins SET created_at=? WHERE org_id=? AND user_id=?", (OLD, O1, IID))
write("DELETE FROM user_invites WHERE user_id=?", (IID,))
write("INSERT INTO user_invites(user_id, token_hash, kind, created_by, created_at, expires_at, used_at) VALUES(?,?,?,?,?,?,?)",
      (IID, "p21005b-ida", "invite", FID, OLD, EDGE, (NOW - timedelta(days=20)).isoformat(timespec="seconds")))
before1, before2 = emails(O1), emails(O2)
check("paula@example.com" in before1 and "dora@example.com" in before1 and "paula@example.com" in before2, f"setup: the lists {before1} {before2}")

out = py_in_app("from kalmido.admin.dataretention import lgc_tick\nprint('rows', lgc_tick(c, True))")
check("rows" in out and "Traceback" not in out, "the daily clean-up ran " + out[-300:])

# silent and neutral alike
# 2.1005.0 (#5118, review F1): kept like the new account's row (no account oracle)
# 2.1062.0 (#5786): past the period every kind goes alike, just within it every kind stays
check(not joins(O1, "paula@example.com"), "(#5786) a neutral row (deleted account) past the period goes")
check(not joins(O1, "dora@example.com"), "(#5786) a silent row (living account) past the period goes the same way")
check(bool(joins(O2, "paula@example.com")), "(#5118) a neutral row just within the period stays")
check(bool(joins(O2, "dora@example.com")), "(#5118) a silent row just within the period stays the same way")
after1, after2 = emails(O1), emails(O2)
check("paula@example.com" not in after1 and "dora@example.com" not in after1 and "neu@example.com" not in after1,
      f"(#5786) silent, neutral and the new account's row left the admins' list on the same day {after1}")
check("paula@example.com" in after2 and "dora@example.com" in after2, f"(#5118) both stand in the other list {after2}")
# ordinary rows
check(not dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (O1, HID)), "(#5118) an ordinary invitation past the period is deleted")
check(bool(dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (O2, HID))), "(#5118) an ordinary invitation just within it stays")
check(bool(dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (O1, IID))), "(#5118) an old invitation still open (link used lately) stays")
check(not dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (O1, NID)),
      "(#5786) the row of the new account this company made goes on the same day as the others")
# open and accepted
check(bool(dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=? AND silent", (O1, GID))) and "gerda@example.com" in after1,
      "(#5118) an open (fresh) silent invitation stays")
check(bool(dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (O1, KID))), "(#5118) an accepted invitation keeps its membership")
check(bool(dbx("SELECT 1 FROM users WHERE id IN (?,?,?)", (DID, HID, IID))) and dbx("SELECT COUNT(*) FROM users WHERE id IN (?,?,?)", (DID, HID, IID))[0][0] == 3,
      "(#5118) the accounts themselves stay")

# a second run deletes nothing more
n = dbx("SELECT COUNT(*) FROM org_joins")[0][0]
out = py_in_app("from kalmido.admin.dataretention import lgc_tick\nprint('rows', lgc_tick(c, True))")
check(dbx("SELECT COUNT(*) FROM org_joins")[0][0] == n, "(#5118) a second run changes nothing " + out[-200:])

# ================================================================ 2.1062.0 (#5786): the never used account itself
WARN_DAYS, PERIOD = 7, OJN_DAYS + PURGE_DAYS  # accounts/orginvite.py OINV_WARN_DAYS


def ago(days):
    return (NOW - timedelta(days=days)).isoformat(timespec="seconds")


def new_account(email, age_days):
    """A new account frida's company made, its invitation (account, org_invites, org_joins) age_days old."""
    invite(O1, email)
    uid = dbx("SELECT id FROM users WHERE email=?", (email,))[0][0]
    t = ago(age_days)
    write("UPDATE users SET oinv_made_at=?::timestamptz WHERE id=?", (t, uid))
    write("UPDATE org_invites SET created_at=? WHERE user_id=?", (t, uid))
    write("UPDATE org_joins SET created_at=? WHERE user_id=?", (t, uid))
    return uid


def mails_to(addr):
    return sum(1 for m in mails() if addr in m.get("to", []))


def warnings_to(addr):
    """The warning mails (#5786) to addr: the subject tells them from the invitation mail."""
    return [m for m in mails() if addr in m.get("to", [])
            and "will be removed on" in str(email.message_from_string(m["raw"], policy=email.policy.default)["Subject"])]


def mails():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8")]
    except OSError:
        return []


def alive(uid):
    return bool(dbx("SELECT 1 FROM users WHERE id=?", (uid,)))


GONE = new_account("gone@example.com", PERIOD + 1)        # its day is past: warned now, withdrawn a warning period later
SOON = new_account("soon@example.com", PERIOD - 3)        # its day in 3 days: warned now, not withdrawn before the day
FRESH = new_account("fresh@example.com", 1)               # nothing yet
KEPT = new_account("kept@example.com", PERIOD + 1)        # warned, then set up: stays
NOMAIL = new_account("noaddr@example.com", PERIOD + 1)    # no address: no warning delivered, never withdrawn
OTHER = new_account("other@example.com", PERIOD + 1)      # belongs to another organisation: stays like Withdraw refuses it
USED = new_account("used@example.com", PERIOD + 1)        # signed in once (review F2: its session and link are gone by now)
write("UPDATE users SET email=NULL WHERE id=?", (NOMAIL,))
write("INSERT INTO org_members(org_id, user_id, role) VALUES(?,?,?)", (O2, OTHER, "member"))
write("UPDATE users SET oinv_used=TRUE WHERE id=?", (USED,))  # the durable mark start_session sets (accounts/session.py)
check(dbx("SELECT COUNT(*) FROM users WHERE oinv_made_at IS NOT NULL AND id IN (?,?,?)", (GONE, SOON, FRESH))[0][0] == 3, "setup: (#5864) the mark of an account made by an invitation")
check(bool(until(lambda: all(mails_to(f"{a}@example.com") >= 1 for a in ("gone", "soon", "fresh", "kept", "other", "used")), 30)),
      "setup: the invitation mails went")

out = py_in_app("from kalmido.admin.dataretention import lgc_tick\nprint('rows', lgc_tick(c, True))")
check("rows" in out and "Traceback" not in out, "(#5786) the clean-up ran " + out[-300:])
warned = {a: len(warnings_to(f"{a}@example.com")) for a in ("gone", "soon", "fresh", "kept", "other", "used")}
check(warned["gone"] == 1 and warned["soon"] == 1 and warned["kept"] == 1, f"(#5786) a warning mail before the day {warned}")
check(warned["fresh"] == 0 and warned["other"] == 0 and warned["used"] == 0, f"(#5786) none for a fresh account, one of another organisation or one used once {warned}")
w = email.message_from_string(warnings_to("soon@example.com")[-1]["raw"], policy=email.policy.default)
w = w.get_body(preferencelist=("plain",)).get_content()
check("#invite/" in w and "kept" not in w and "soon" in w, "(#5786) the warning names the account and carries a link to set it up " + w[:300])
check(all(alive(u) for u in (GONE, SOON, FRESH, KEPT, NOMAIL, OTHER, USED)), "(#5786) nothing is withdrawn on the day of the warning")
check(dbx("SELECT oinv_warned_at IS NOT NULL FROM users WHERE id=?", (GONE,)) in ([(True,)], [(1,)]), "(#5786) the delivered warning is noted")
check(dbx("SELECT oinv_warned_at FROM users WHERE id=?", (NOMAIL,)) == [(None,)], "(#5786) no address: no warning noted")
check(not dbx("SELECT 1 FROM org_joins WHERE user_id IN (?,?)", (GONE, KEPT)), "(#5786) its invitation row went with the others of its day")

# a warning period later: the person of KEPT set the account up meanwhile (its link used)
for u in (GONE, SOON, KEPT, NOMAIL, OTHER):
    write("UPDATE users SET oinv_warned_at=oinv_warned_at - interval '8 days' WHERE id=? AND oinv_warned_at IS NOT NULL", (u,))
write("UPDATE user_invites SET used_at=? WHERE user_id=?", (NOW.isoformat(timespec="seconds"), KEPT))
out = py_in_app("from kalmido.admin.dataretention import lgc_tick\nprint('rows', lgc_tick(c, True))")
check("rows" in out and "Traceback" not in out, "(#5786) the clean-up ran again " + out[-300:])
check(not alive(GONE), "(#5786) warned, its day past: the never used account is withdrawn")
check(not dbx("SELECT 1 FROM org_invites WHERE user_id=?", (GONE,)), "(#5786) ... with its invitation")
check(alive(SOON), "(#5786) warned, but its day has not come: stays")
check(alive(KEPT), "(#5786) set up after the warning: stays")
check(alive(NOMAIL), "(#5786) without a delivered warning: never withdrawn")
check(alive(OTHER), "(#5786) a member of another organisation: stays")
check(alive(FRESH), "(#5786) a fresh one stays")
check(alive(USED), "(#5786, review F2) signed in once: stays though its session and link are gone")
check(len(warnings_to("soon@example.com")) == 1, "(#5786) one warning, not one a day")

sys.exit(kt.done("p21005_b_invite_purge"))
