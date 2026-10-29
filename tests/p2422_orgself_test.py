#!/usr/bin/env python3
# kalmido-suite:
"""2.422.0 API tests (#2937: a self-employed person creates a company of her own; private accounts register without an
invitation, a switch per server, default off), own container (start.sh, SMTP sink stub_mail.py). Invented names only.
 (a) frida (no organisation) creates "Frida Studio" (POST /api/orgs): 201, she is its only member and admin, the company
     is among her workspaces; a taken name = 409; at most 3 companies of her own (the 4th = 409)
 (b) the e-mail domains of such a company: not by her (403), by the server's admin yes
 (c) her personal office moves into a new company of her own (POST /api/office/move, before 2.422 only the server's
     admin; rollback test: 403 without the fix); can_move in her office settings
 (d) companies people created themselves do not make the server an organisation's server: open registration stays
     possible while only they exist; the server admin's organisation turns it off
 (e) the switch signup_private (default off): "open" refused (409) next to an organisation while off; on (asks for the
     password): open works, a registration with an organisation's e-mail domain stays a private account (never joins
     it); off again: the mode falls back to off
usage: p2422_orgself_test.py <datadir>      (P2422_NOSTART=1: a running server, no start.sh)
freelancer-matrix: own  tenant-matrix: org"""
import json
import os
import shutil
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, FAILS, OKS, check, sess, until  # noqa: E402

SMTP = {"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
        "KALMIDO_MAIL_FROM": "kalmido@example.test", "KALMIDO_INSTANCE_MODE": "workspaces"}
PW = "password123"
S = B + "/api/admin/settings"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def mails():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8")]
    except OSError:
        return []


if kt.fresh(env=SMTP, prefix="P2422"):
    os.makedirs(os.path.join(DATA, "mail"), exist_ok=True)
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
    time.sleep(1)
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
FID, Fr = freelancer(B, A)
about = lambda: A.get(B + "/api/about").json()  # noqa: E731

# ---------------------------------------------------------------- (a) a company of her own
r = Fr.post(B + "/api/orgs", json={"name": "Frida Studio"})
check(r.status_code == 201, f"(a) frida creates Frida Studio: 201 ({r.status_code} {r.text[:200]})")
OID = r.json().get("id") if r.status_code == 201 else None
mine = Fr.get(B + "/api/orgs").json().get("orgs") or []
o = next((x for x in mine if x["id"] == OID), {})
check(o and o.get("role") == "admin" and [m["id"] for m in o.get("members", [])] == [FID],
      f"(a) she is its only member and its admin ({o})")
check(sql("SELECT self_made FROM orgs WHERE id=?", (OID,)) == [(FID,)], "(a) marked as a company of her own (her id)")
check(Fr.post(B + "/api/orgs", json={"name": "frida studio"}).status_code == 409, "(a) a taken name: 409")
check(Fr.post(B + "/api/orgs", json={"name": " "}).status_code == 400, "(a) no name: 400")
for n in ("Frida Two", "Frida Three"):
    check(Fr.post(B + "/api/orgs", json={"name": n}).status_code == 201, f"(a) {n}: 201")
r = Fr.post(B + "/api/orgs", json={"name": "Frida Four"})
check(r.status_code == 409, f"(a) the 4th company of her own: 409 ({r.status_code} {r.text[:120]})")
# review: handing a company over (she steps down, somebody else is its admin) frees no place -- counted by who created it
T3 = next(x["id"] for x in Fr.get(B + "/api/orgs").json()["orgs"] if x["name"] == "Frida Three")
check(A.patch(B + f"/api/admin/orgs/{T3}", json={"members_add": [ALICE], "admins_add": [ALICE], "admins_remove": [FID]}).ok, "(a) setup: Frida Three handed to alice")
check(Fr.post(B + "/api/orgs", json={"name": "Frida Five"}).status_code == 409, "(a) handed over: still no 4th company")

# ---------------------------------------------------------------- (b) e-mail domains only by the server's admin
r = Fr.patch(B + f"/api/orgs/{OID}", json={"domains": "example.org"})
check(r.status_code == 403, f"(b) frida sets e-mail domains of her company: 403 ({r.status_code} {r.text[:120]})")
check(Fr.patch(B + f"/api/orgs/{OID}", json={"name": "Frida Studio GmbH"}).ok, "(b) she renames it")
check(A.patch(B + f"/api/admin/orgs/{OID}", json={"domains": "frida-studio.example"}).ok
      and sql("SELECT domains FROM orgs WHERE id=?", (OID,)) == [("frida-studio.example",)], "(b) the server's admin sets them")
A.patch(B + f"/api/admin/orgs/{OID}", json={"domains": ""})

# ---------------------------------------------------------------- (c) her personal office into a new company
GID, Gr = freelancer(B, A, "gina")
Gr.patch(B + "/api/settings", json={"workspace": "private"})
st = Gr.get(B + "/api/office/settings").json()
check(st.get("personal") == 1 and st.get("can_move") == 1, f"(c) gina's personal office offers the move ({ {k: st.get(k) for k in ('personal', 'can_move')} })")
r = Gr.post(B + "/api/office/move", json={"name": "Gina Works", "confirm": True})
check(r.ok and r.json().get("org_id"), f"(c) gina moves her personal office into Gina Works ({r.status_code} {r.text[:160]})")
GOID = r.json().get("org_id") if r.ok else None
check(GOID and sql("SELECT self_made, personal_of FROM orgs WHERE id=?", (GOID,)) == [(GID, None)], "(c) a company of her own, no personal office any more")

# ---------------------------------------------------------------- (d) companies of their own: no organisation's server
check(about().get("has_orgs") is False, f"(d) only companies people created themselves: has_orgs false ({about().get('has_orgs')})")
r = A.patch(S, json={"signup_mode": "open", "password": PW})
check(r.ok and about().get("signup_effective") == "open", f"(d) open registration possible ({r.status_code} {r.text[:160]})")
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Example", "domains": "alpha.example"}).json()["id"]
check(about().get("has_orgs") is True and about().get("signup_effective") == "off", "(d) the server admin's organisation: open is off")

# ---------------------------------------------------------------- (e) the switch "private accounts register without an invitation"
check(about().get("signup_private") is False, "(e) the switch is off by default")
A.patch(S, json={"signup_mode": "off"})
r = A.patch(S, json={"signup_mode": "open", "password": PW})
check(r.status_code == 409, f"(e) off: open next to an organisation refused (409, {r.status_code})")
r = A.patch(S, json={"signup_private": True})
check(r.status_code == 403 and (r.json() or {}).get("password_needed"), f"(e) switching it on asks for the password ({r.status_code} {r.text[:120]})")
check(A.patch(S, json={"signup_private": "yes", "password": PW}).status_code == 400, "(e) not a boolean: 400")
r = A.patch(S, json={"signup_private": True, "signup_mode": "open", "password": PW})
ab = about()
check(r.ok and ab.get("signup_private") is True and ab.get("signup_effective") == "open", f"(e) on: open in effect ({r.status_code} {ab.get('signup_effective')})")
R = sess()
r = R.post(B + "/api/auth/signup", json={"name": "Hanna Alpha", "email": "hanna@alpha.example"})
check(r.ok and r.json() == {"ok": True, "mail": True, "pending": False}, f"(e) a registration with the organisation's domain ({r.status_code} {r.text[:120]})")
u = until(lambda: sql("SELECT id FROM users WHERE email='hanna@alpha.example'"), 10)
check(u and not sql("SELECT 1 FROM org_members WHERE user_id=?", (u[0][0],)),
      "(e) it stays a private account: no member of Alpha Example (rollback test: before 2.422 open was impossible here)")
check(until(lambda: [m for m in mails() if "hanna@alpha.example" in [t.lower() for t in m["to"]]], 15), "(e) the confirmation mail goes out")
r = A.patch(S, json={"signup_private": False})
ab = about()
check(r.ok and ab.get("signup_private") is False and ab.get("signup_mode") == "off" and ab.get("signup_effective") == "off",
      f"(e) off again: the mode falls back to off ({ab.get('signup_mode')}/{ab.get('signup_effective')})")
check(sess().post(B + "/api/auth/signup", json={"name": "X", "email": "x@example.org"}).status_code == 404, "(e) registration closed: 404")

print(f"p2422_orgself: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
