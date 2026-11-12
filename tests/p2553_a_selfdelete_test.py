#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.553.0 (#1413): a person deletes their own account (admin/selfdelete.py). Own container with the SMTP stub
(tests/stub_mail.py). A person without an organisation throughout (freelancer-matrix: own):
 - the dialog's numbers (GET /api/account/delete): without own projects, then with a shared and a private one
 - asking needs a choice per project and the password; the shared project goes to a member, the private one along
 - meanwhile: the account is locked (session ended, the sign-in answers only "deleting", its API token and its agent are
   refused), the member keeps using the shared project, a mail with the cancel link went out
 - the cancel link lifts all of it (sign-in, token, agent back); asked again, the reminder one day before carries a new
   link; the sign-in with the password cancels too; an admin who enables the account again ends the deletion
 - the final run (delete_at set into the past, no waiting): the project went to the member, the other one is gone, the
   attachment files are gone from the disk, the last mail says so
 - refused: the last admin of an organisation, the only server admin
Invented names only.
usage: p2553_a_selfdelete_test.py <datadir>"""
import base64
import email
import hashlib
import hmac
import email.policy
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402
from kt import B, CT, DATA, check, dbx, sess, until  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
SMTP = {"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
        "KALMIDO_MAIL_FROM": "kalmido@example.test", "KALMIDO_INSTANCE_MODE": "workspaces"}
PW = "password123"


def write(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    c.execute(q, args)
    c.commit()
    c.close()


def totp(secret, step):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    o = mac[-1] & 15
    return str((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


def mails():
    out = []
    try:
        for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8"):
            m = json.loads(x)
            msg = email.message_from_string(m["raw"], policy=email.policy.default)
            body = msg.get_body(("plain",))
            out.append({"to": [t.lower() for t in m["to"]], "subject": str(msg["subject"] or ""), "text": body.get_content() if body else ""})
    except OSError:
        pass
    return out


def mail_to(addr, part, n=1, wait=15):
    return until(lambda: (lambda ms: ms if len(ms) >= n else None)([m for m in mails() if addr in m["to"] and part in m["subject"]]), wait)


def cancel_token(m):
    x = re.search(r"#delete-cancel=([\w.-]+)", m["text"])
    return x.group(1) if x else ""


if kt.fresh(env=SMTP, prefix="P2553A"):
    os.makedirs(os.path.join(DATA, "mail"), exist_ok=True)
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
    time.sleep(1)
A = kt.setup()
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
FID, Fr = freelancer(B, A, "frida")
BOB, Bo = freelancer(B, A, "bob")

# ---------------------------------------------------------------- the dialog without own projects
j = Fr.get(B + "/api/account/delete").json()
check(j.get("can") is True and j.get("lists") == [] and j.get("days") == 7 and j.get("confirm") == "password",
      f"the dialog of a person without projects: may go, no projects, 7 days, the password confirms {j}")
check("shared" in (j.get("purge") or {}), f"the dialog names what is handed on (purge.shared, as the admin's) {j.get('purge')}")
check(A.get(B + "/api/account/delete").json().get("can") is False, "the only server admin may not delete themself")
r = A.post(B + "/api/account/delete", json={"password": PW, "lists": {}})
check(r.status_code == 409 and "server admin" in r.json().get("error", ""), f"the only server admin is refused ({r.status_code} {r.text[:150]})")

# ---------------------------------------------------------------- the last admin of an organisation
CID = A.post(B + "/api/users", json={"username": "carla", "display_name": "Carla", "password": PW, "email": "carla@example.com", "orgs": []}).json()["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Garden Studio", "admin_id": CID}).json()["id"]
Ca = sess("carla")
j = Ca.get(B + "/api/account/delete").json()
check(j.get("can") is False and "Garden Studio" in j.get("reason", ""), f"the last admin of an organisation: refused with its name {j}")
r = Ca.post(B + "/api/account/delete", json={"password": PW, "lists": {}})
check(r.status_code == 409 and not dbx("SELECT delete_at FROM users WHERE id=?", (CID,))[0][0], f"... and asking changes nothing ({r.status_code})")

# ---------------------------------------------------------------- review N2: an app code confirms once
TID = A.post(B + "/api/users", json={"username": "tina", "display_name": "Tina", "password": PW, "email": "tina@example.com", "orgs": []}).json()["id"]
Ti = sess("tina")
r = Ti.post(B + "/api/me/2fa/totp", json={"password": PW})
SEC = (r.json().get("secret") or "").replace(" ", "")
step0 = int(time.time() // 30)
check(bool(SEC) and Ti.post(B + "/api/me/2fa/totp/confirm", json={"code": totp(SEC, step0)}).ok, "setup: tina has the authenticator app")
TL = Ti.post(B + "/api/lists", json={"name": "Tina's list"}).json()["id"]
check(Ti.post(B + "/api/account/delete", json={"password": PW}).json().get("code_needed") is True, "with the app: the code is asked for")
CODE = totp(SEC, step0 + 1)
r = Ti.post(B + "/api/account/delete", json={"password": PW, "code": CODE, "lists": {}})
check(r.status_code == 409, f"the right code, but no choice for her project: refused ({r.status_code})")
r = Ti.post(B + "/api/account/delete", json={"password": PW, "code": CODE, "lists": {str(TL): {"delete": True}}})
check(r.status_code == 403 and not dbx("SELECT delete_at FROM users WHERE id=?", (TID,))[0][0], f"the same code a second time: refused ({r.status_code})")

# ---------------------------------------------------------------- own projects: one shared with bob, one private
L1 = Fr.post(B + "/api/lists", json={"name": "Garden plan"}).json()["id"]
L2 = Fr.post(B + "/api/lists", json={"name": "Private notes"}).json()["id"]
dbx("UPDATE users SET email_proved=lower(COALESCE(email, '')) WHERE email_proved=''")  # 2.1001.0 (#5669): a list / folder shared by address binds only a proved address (a mailed link / OIDC); the accounts here proved theirs
r = Fr.put(B + f"/api/lists/{L1}/members", json={"email": "bob@example.com", "role": "edit"})  # people without an organisation: by e-mail
check(r.ok and dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (L1, BOB)), f"setup: bob in the garden plan {r.status_code} {r.text[:200]}")
T1 = Fr.post(B + "/api/tasks", json={"title": "Plant tulips", "list_id": L1}).json()["id"]
T2 = Fr.post(B + "/api/tasks", json={"title": "Diary", "list_id": L2}).json()["id"]
check(Fr.post(B + f"/api/tasks/{T2}/attachments", files={"file": ("diary.txt", b"dear diary\n" * 30, "text/plain")}).ok, "setup: an attachment in the private project")
ATT = dbx("SELECT path FROM attachments WHERE task_id=?", (T2,))[0][0]
check(os.path.exists(os.path.join(DATA, "attachments", ATT)), "setup: its file is on the disk")
ag = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read"]})
check(ag.status_code in (200, 201), f"setup: her own agent {ag.status_code} {ag.text[:150]}")
AGID = ag.json().get("id")
AGTOK = Fr.post(B + f"/api/my/agents/{AGID}/token").json().get("token") or "none"
tk = Fr.post(B + "/api/me/tokens", json={"name": "cli", "scopes": ["read", "write"]})
check(tk.status_code == 201, f"setup: her API token {tk.status_code} {tk.text[:150]}")
TOK = tk.json().get("token") or "none"


def api(tok):
    return requests.get(B + "/api/v1/me", headers={"Authorization": "Bearer " + tok})


check(api(TOK).ok and api(AGTOK).ok, "setup: her token and her agent's token work")

j = Fr.get(B + "/api/account/delete").json()
by = {x["id"]: x for x in j["lists"]}
check(set(by) == {L1, L2}, f"the dialog names both projects {list(by)}")
check([h["id"] for h in by[L1]["heirs"]] == [BOB] and by[L2]["heirs"] == [] and by[L1]["shared"] == 1,
      f"the shared one can go to bob, the private one to nobody {by}")

r = Fr.post(B + "/api/account/delete", json={"password": PW, "lists": {str(L2): {"delete": True}}})
check(r.status_code == 409 and r.json().get("lists") == [L1], f"a shared project without a choice: refused, never deleted quietly ({r.status_code} {r.text[:120]})")
r = Fr.post(B + "/api/account/delete", json={"password": PW, "lists": {str(L1): {"to": CID}, str(L2): {"delete": True}}})
check(r.status_code == 409, f"only a member of the project takes it over ({r.status_code})")
r = Fr.post(B + "/api/account/delete", json={"password": "wrong-pass", "lists": {str(L1): {"to": BOB}, str(L2): {"delete": True}}})
check(r.status_code == 403, f"the wrong password: refused ({r.status_code})")
CHOICE = {str(L1): {"to": BOB}, str(L2): {"delete": True}}
r = Fr.post(B + "/api/account/delete", json={"password": PW, "lists": CHOICE})
check(r.ok and r.json().get("delete_at"), f"asked for the deletion {r.status_code} {r.text[:200]}")

# ---------------------------------------------------------------- locked meanwhile
check(Fr.get(B + "/api/state").status_code == 401, "her session ended")
s = requests.Session()
s.headers.update({"X-Requested-With": "kalmido"})
r = s.post(B + "/api/auth/login", json={"username": "frida", "password": PW})
check(r.status_code == 403 and r.json().get("deleting") is True and s.get(B + "/api/state").status_code == 401,
      f"the sign-in offers only the cancelling, no session ({r.status_code} {r.text[:120]})")
r = s.post(B + "/api/auth/login", json={"username": "frida", "password": "wrong-pass"})
check(r.status_code == 401 and not r.json().get("deleting"), "a wrong password learns nothing about the deletion")
check(api(TOK).status_code == 401, "her API token is refused")
check(api(AGTOK).status_code in (401, 403) and dbx("SELECT enabled FROM agents WHERE user_id=?", (AGID,))[0][0] == 0, "her agent is paused, its token refused")
check(Bo.post(B + "/api/tasks", json={"title": "Water the roses", "list_id": L1}).ok, "bob keeps writing in the shared project")
check(Bo.get(B + f"/api/tasks/{T1}").ok, "... and reads her tasks there")
m = mail_to("frida@example.com", "will be deleted")
check(bool(m) and cancel_token(m[0]) and "backup" in m[0]["text"].lower(), f"the mail with the cancel link and the backups' line {m[:1]}")

# ---------------------------------------------------------------- the cancel link lifts everything
check(s.post(B + "/api/auth/delete-cancel", json={"token": "999.nope"}).status_code == 403, "a wrong link does nothing")
# review N1: an endless number in the link is a wrong link (403), never a server error
check(s.post(B + "/api/auth/delete-cancel", json={"token": "9" * 40 + ".nope"}).status_code == 403, "a too long number: 403, no 500")
r = s.post(B + "/api/auth/delete-cancel", json={"token": cancel_token(m[0])})
check(r.ok, f"the cancel link {r.status_code} {r.text[:120]}")
check(dbx("SELECT disabled, delete_at, delete_plan FROM users WHERE id=?", (FID,))[0] == (0, None, ""), "unlocked, nothing planned")
Fr = login(B, "frida")
check(Fr.get(B + "/api/state").ok, "she signs in again")
check(api(TOK).ok and api(AGTOK).ok, "her token and her agent's token work again")
check(bool(mail_to("frida@example.com", "was cancelled")), "a mail says the deletion was cancelled")
check(s.post(B + "/api/auth/delete-cancel", json={"token": cancel_token(m[0])}).status_code == 403, "the link works once")

# ---------------------------------------------------------------- the reminder, the cancelling by the password
r = Fr.post(B + "/api/account/delete", json={"password": PW, "lists": CHOICE})
check(r.ok, "asked again")
write("UPDATE users SET delete_at=to_char((now() AT TIME ZONE 'UTC') + interval '12 hours', 'YYYY-MM-DD\"T\"HH24:MI:SS\"+00:00\"') WHERE id=?", (FID,))
m2 = mail_to("frida@example.com", "deleted tomorrow")
check(bool(m2) and cancel_token(m2[0]) and cancel_token(m2[0]) != cancel_token(m[0]), "the reminder one day before carries a new cancel link")
check(bool(until(lambda: json.loads(dbx("SELECT delete_plan FROM users WHERE id=?", (FID,))[0][0] or "{}").get("reminded"), 10)), "the reminder is noted once")
r = s.post(B + "/api/auth/delete-cancel", json={"username": "frida", "password": PW})
check(r.ok and not dbx("SELECT delete_at FROM users WHERE id=?", (FID,))[0][0], f"the sign-in's password cancels as well ({r.status_code})")

# an admin who enables the account again ends the deletion too
Fr = login(B, "frida")
check(Fr.post(B + "/api/account/delete", json={"password": PW, "lists": CHOICE}).ok, "asked a third time")
check(A.patch(B + f"/api/users/{FID}", json={"disabled": False}).ok, "the admin enables her again")
check(bool(until(lambda: not dbx("SELECT delete_at FROM users WHERE id=?", (FID,))[0][0], 15)), "the next tick lifts the deletion")

# ---------------------------------------------------------------- the final run (no waiting: delete_at in the past)
Fr = login(B, "frida")
check(Fr.post(B + "/api/account/delete", json={"password": PW, "lists": CHOICE}).ok, "asked for the last time")
# 2.553.0 (#1413, review M2): a record to keep that came after the request (a receipt in the project deleted along) passed no
# export or waiver - the final run waits (notes the try) instead of deleting it
write("INSERT INTO budget_entries(list_id, day, created_at, updated_at) VALUES(?, '2026-11-05', '2026-11-05T00:00:00+00:00', '2026-11-05T00:00:00+00:00')", (L2,))
BE = dbx("SELECT id FROM budget_entries WHERE list_id=?", (L2,))[0][0]
write("INSERT INTO budget_files(entry_id, list_id, name, path, created_at) VALUES(?, ?, 'r.pdf', 'x/r.pdf', '2026-11-05T00:00:00+00:00')", (BE, L2))
write("UPDATE users SET delete_at='2000-01-01T00:00:00+00:00' WHERE id=?", (FID,))
tried = until(lambda: '"tried"' in (dbx("SELECT delete_plan FROM users WHERE id=?", (FID,)) or [("",)])[0][0], 30)
check(bool(tried) and dbx("SELECT 1 FROM lists WHERE id=?", (L2,)), "a receipt after the request: the final run waits, nothing deleted")
write("DELETE FROM budget_entries WHERE id=?", (BE,))
write("UPDATE users SET delete_plan=replace(delete_plan, '\"tried\"', '\"tried_old\"') WHERE id=?", (FID,))
gone = until(lambda: not dbx("SELECT 1 FROM users WHERE id=?", (FID,)), 30)
check(bool(gone), "the watchdog deleted the account " + str(dbx("SELECT delete_plan FROM users WHERE id=?", (FID,))))
check(dbx("SELECT owner_id FROM lists WHERE id=?", (L1,)) == [(BOB,)], "the shared project went to bob")
check(not dbx("SELECT 1 FROM lists WHERE id=?", (L2,)) and not dbx("SELECT 1 FROM tasks WHERE id=?", (T2,)), "the private project went with its tasks")
check(bool(until(lambda: not os.path.exists(os.path.join(DATA, "attachments", ATT)), 10)), "its attachment file is gone from the disk")
check(Bo.get(B + f"/api/tasks/{T1}").ok, "bob still has her task in the project")
check(bool(mail_to("frida@example.com", "was deleted")), "the last mail confirms the deletion")
check(not dbx("SELECT 1 FROM users WHERE id=?", (AGID,)), "her agent went with her")
sys.exit(kt.done("p2553_a_selfdelete"))
