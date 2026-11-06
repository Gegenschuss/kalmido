#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.581.0 A (#4826): "Check passphrase" of the backups -- POST /api/admin/backups/passphrase-check {passphrase} -> {ok}
(admin/backup.py backups_passphrase_check). Own container (admin alerts on), restarted once with KALMIDO_BACKUP_PASSPHRASE.
Invented names only. The instance admin runs the server without any organisation (a self-operator: the freelancer case).
freelancer-matrix: admin
 - no passphrase set yet: 409 code no_passphrase
 - the step-up: without the password 403 need password (no try counted), with it the check runs; then the session holds it
 - the stored passphrase: matches -> {ok: true}, another one -> {ok: false}; the answer has only the key ok
 - bad input (no string, empty) 400
 - KALMIDO_BACKUP_PASSPHRASE set (restart): it wins over the stored one (env matches, the stored one no longer)
 - the 6th try within 15 minutes of one account: 429
 - a person without admin rights (an account without an organisation, tests/freelancer_fixture.py): 403
 - no leak: neither the answers, nor the admin log (admin_alerts: "checked the backup passphrase: it matches / it does not
   match"), nor the server log hold the typed or the stored passphrase or a piece of it
usage: p2581_a_passcheck_test.py <datadir>"""
import os
import secrets
import subprocess
import sys

os.environ["KALMIDO_ADMIN_ALERTS"] = "1"  # start.sh passes it to the container
import kt  # noqa: E402
from kt import B, check, until  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402

ENV = {"KALMIDO_BACKUPS": "1", "KALMIDO_ADMIN_ALERT_WINDOW": "3"}
kt.fresh(env=ENV, prefix="P2581AP")
A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
check((A.get(B + "/api/state").json()["me"].get("workspaces") or []) == [], "setup: the admin is in no organisation (self-operator)")
FID, Fr = freelancer(B, A)  # freelancer-matrix: admin (a person without an organisation and without admin rights)
PC = "/api/admin/backups/passphrase-check"
STORED = "stored-" + secrets.token_hex(8)
ENVPW = "envpass-" + secrets.token_hex(8)
WRONG = "wrong-" + secrets.token_hex(8)
SEEN = []  # every answer's text (the leak check at the end)


def pc(s, pw, password=None):
    b = {"passphrase": pw}
    if password:
        b["password"] = password
    r = s.post(B + PC, json=b)
    SEEN.append(r.text)
    return r


def alerts():
    return [r[0] for r in kt.dbx("SELECT message FROM admin_alerts WHERE key LIKE 'bk-passcheck:%' ORDER BY id")]


# ---- not an admin: 403 (before anything else)
r = pc(Fr, STORED, kt.PASSWORD)
check(r.status_code == 403, f"a person without admin rights: 403 ({r.status_code} {r.text[:120]})")

# ---- the step-up first: without the password 403 need, no try counted
r = pc(A, WRONG)
check(r.status_code == 403 and r.json().get("need") == "password", f"without the step-up: 403 need password ({r.status_code} {r.text[:160]})")

# ---- no passphrase yet (try 1)
r = pc(A, WRONG, kt.PASSWORD)
check(r.status_code == 409 and r.json().get("code") == "no_passphrase", f"no passphrase set: 409 no_passphrase ({r.status_code} {r.text[:160]})")
check(A.patch(B + "/api/admin/backups", json={"passphrase": STORED}).ok, "setup: the stored passphrase")
check(A.get(B + "/api/admin/backups").json().get("passphrase_set") is True, "setup: passphrase_set")

# ---- bad input (no try counted; the step-up holds for the session now). 2.581.0 (#4826, review): a lone surrogate is a 400, not a 500
for bad in ('{"passphrase": 5}', '{"passphrase": ""}', '{"passphrase": "\\ud800x"}'):
    r = A.post(B + PC, data=bad, headers={"Content-Type": "application/json"})
    check(r.status_code == 400, f"bad input 400 {bad} ({r.status_code})")
# ---- matches / does not match (tries 2, 3)
r = pc(A, STORED)
check(r.ok and r.json() == {"ok": True}, f"the stored passphrase matches ({r.status_code} {r.text[:160]})")
r = pc(A, WRONG)
check(r.ok and r.json() == {"ok": False}, f"another one does not match ({r.status_code} {r.text[:160]})")
al = until(lambda: alerts() if len(alerts()) >= 2 else None, 20) or alerts()
check(len(al) == 2 and "it matches" in al[0] and "does not match" in al[1] and all("alice" in m for m in al),
      f"the admin log names both checks: {al}")

# ---- tries 4, 5, then the 6th within the window: 429
for _ in range(2):
    r = pc(A, WRONG)
    check(r.ok, f"try 4/5 still answered ({r.status_code})")
r = pc(A, STORED)
check(r.status_code == 429, f"the 6th try: 429 ({r.status_code} {r.text[:160]})")

# ---- restart with KALMIDO_BACKUP_PASSPHRASE: it wins over the stored one (a new admin session: the same account's limit holds,
# so a second admin checks)
LOG1 = subprocess.run(["docker", "logs", kt.CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout  # before the restart
kt.fresh(env={**ENV, "KALMIDO_BACKUP_PASSPHRASE": ENVPW}, prefix="P2581AP", keep=True)
r = A.post(B + "/api/users", json={"username": "dora", "display_name": "Dora", "password": kt.PASSWORD, "email": "dora@example.com",
                                   "orgs": [], "is_admin": True})
check(r.ok, f"setup: dora, a second admin {r.status_code} {r.text[:120]}")
Do = login(B, "dora")
r = pc(Do, ENVPW, kt.PASSWORD)
check(r.ok and r.json() == {"ok": True}, f"KALMIDO_BACKUP_PASSPHRASE matches ({r.status_code} {r.text[:160]})")
r = pc(Do, STORED)
check(r.ok and r.json() == {"ok": False}, f"the stored one no longer matches while the env is set ({r.status_code} {r.text[:160]})")
r = pc(A, ENVPW)
check(r.status_code in (403, 429), f"alice's limit (or her step-up after the restart) still refuses ({r.status_code})")

# ---- no leak: answers, admin log, server log
log = LOG1 + subprocess.run(["docker", "logs", kt.CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
check("passphrase-check" in log or len(log) > 1000, "the server log was read")
al = alerts()
for name, v in (("stored", STORED), ("env", ENVPW), ("typed", WRONG)):
    piece = v.split("-")[1]
    check(not any(piece in t for t in SEEN), f"no answer holds the {name} passphrase")
    check(not any(piece in m for m in al), f"the admin log does not hold the {name} passphrase")
    check(piece not in log, f"the server log does not hold the {name} passphrase")

sys.exit(kt.done("p2581_a_passcheck"))
