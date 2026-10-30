#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.360.2 D (#2561): privacy remains.
 1 a deleted person's months stay with the organisation, without the person (hours noted, nobody can decide them); the
   private ones go; the foreign key of an older database is changed once
 2 approval records of deleted video reviews: visible and deletable for office admins / the creator, by law kept ones not,
   private ones leave with the account
 3 the account export holds private file content, the booking page, polls, forms with entries and holiday allowances
 4 privacy link, contact and imprint on public pages
 5 one export log row per person, list and day
 6 one way, once: old approval log entries lose e-mail, address and device, sealed ones too; unreadable ones stay
freelancer-matrix: privacy (account export, orphaned approvals, public pages)
usage: p23602_d_api_test.py <datadir>"""
import base64
import io
import json
import os
import subprocess
import sys
import zipfile

import requests

from kt import B, CT, DATA, check, dbx, done, fresh, sess, setup, su_get, until
from freelancer_fixture import freelancer

KEY = base64.b64encode(os.urandom(32)).decode()
fresh({"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY})
A = setup()
assert A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "collab_all": True, "time_all": True, "modules": ["comments", "time"]}).ok
ME = A.get(B + "/api/state").json()["me"]
ORG, AL = ME["workspaces"][0]["id"], ME["id"]
T = "2026-10-01T10:00:00+00:00"


def user(name, orgs):
    r = A.post(B + "/api/users", json={"orgs": orgs, "username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com"})
    assert r.ok, r.text
    return r.json()["id"]


def in_app(code):
    """Runs code in the app container (the sealing needs the server's key); the output's last line."""
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app\n" + code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    return r.stdout.strip().splitlines()[-1]


def export_of(s):
    assert s.post(B + "/api/account/export").status_code == 202
    until(lambda: s.get(B + "/api/account/export").json().get("state") != "running", 120)
    r = su_get(s, B + "/api/account/export/file")
    assert r.ok, r.text[:200]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return z, json.loads(z.read("manifest.json")), {n[5:-5]: json.loads(z.read(n)) for n in z.namelist() if n.startswith("data/")}


def sig(org, by, title, state="open", signed=None, name=None):
    tok = os.urandom(8).hex()
    return dbx("""INSERT INTO office_signoffs(org_id,kind,title,token_hash,token,state,signed_at,signer_name,created_by,created_at)
                  VALUES(?,'video',?,?,?,?,?,?,?,?) RETURNING id""", (org, title, tok, tok, state, signed, name, by, T))[0][0]


# ================================================================== 1 timesheets
BOB, CAROL = user("bob", [ORG]), user("carol", [ORG])
FID, Fr = freelancer(B, A)
OL = A.post(B + "/api/lists", json={"name": "Org work", "org_id": ORG}).json()["id"]
assert dbx("SELECT org_id FROM lists WHERE id=?", (OL,))[0][0] == ORG
dbx("""INSERT INTO time_entries(user_id,list_id,start,"end",seconds,created_at,updated_at) VALUES(?,?,'2026-05-10T08:00:00+00:00','2026-05-10T10:00:00+00:00',7200,?,?) RETURNING id""", (BOB, OL, T, T))
for month, state, org, by in (("2026-05", "approved", ORG, AL), ("2026-06", "closed", ORG, None), ("2026-07", "closed", None, None)):
    dbx("""INSERT INTO time_sheets(org_id,user_id,month,state,decided_by,decided_at,log,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) RETURNING id""",
        (org, BOB, month, state, by, T if by else None, json.dumps([{"at": T, "by": BOB, "action": "close"}]), T, T))
check(A.get(B + f"/api/users/{BOB}/delete-info").json()["purge"].get("sheets_kept") == 2, "delete-info counts the organisation's months only")
r = A.delete(B + f"/api/users/{BOB}")
check(r.ok, "bob deleted " + r.text[:200])
rows = dbx("SELECT month, state, user_id, decided_by, log FROM time_sheets WHERE org_id=? ORDER BY month", (ORG,))
check([(x[0], x[1], x[2], x[3]) for x in rows] == [("2026-05", "approved", None, AL), ("2026-06", "closed", None, None)],
      f"the organisation's months stay with their decision, without the person {rows}")
check(str(BOB) not in str(dbx("SELECT user_id FROM time_sheets")) and not dbx("SELECT 1 FROM time_sheets WHERE org_id IS NULL AND user_id IS NULL"),
      "the private month went with the account")
check(all(x.get("by") != BOB for x in json.loads(rows[0][4])), "the person's id left the history")
rv = A.get(B + "/api/time/sheets", params={"month": "2026-05"}).json().get("review") or []
check([(x["user_id"], x["state"], x["seconds"], x["name"]) for x in rv] == [(None, "approved", 7200, "Deleted user")],
      f"the admin sees the month with its noted hours {rv}")
rv = A.get(B + "/api/time/sheets", params={"month": "2026-09"}).json().get("review") or []
check(rv == [], f"a deleted person's closed month does not wait in every month {rv}")
check(A.post(B + "/api/time/sheets/decide", json={"user_id": None, "month": "2026-06", "action": "approve"}).status_code == 404, "nobody decides it")
# the organisation goes: the months nobody holds go along (no row without person and organisation)
O2 = A.post(B + "/api/admin/orgs", json={"name": "Second", "admin_id": AL})
check(O2.ok, "a second organisation " + O2.text[:160])
oid2 = O2.json().get("id")
dbx("INSERT INTO time_sheets(org_id,user_id,month,state,created_at,updated_at) VALUES(?,NULL,'2026-01','closed',?,?) RETURNING id", (oid2, T, T))
r = A.delete(B + f"/api/admin/orgs/{oid2}?confirm=1")
check(r.ok and not dbx("SELECT 1 FROM time_sheets WHERE month='2026-01'"), f"an organisation's end takes the kept months {r.status_code} {r.text[:160]}")

# ================================================================== 2 orphaned approvals
Ca = sess("carol")
OP, DONE, OLD = sig(ORG, CAROL, "Open cut"), sig(ORG, CAROL, "Signed cut", "accepted", "2026-03-01T10:00:00+00:00", "Dana Customer"), sig(ORG, CAROL, "Old cut", "accepted", "2015-03-01T10:00:00+00:00")
MINE, SEAL = sig(None, FID, "My cut", "accepted", T, "Eva Customer"), sig(None, FID, "Sealed cut", "accepted", T, "kenc1:AAAA")
got = A.get(B + "/api/videos/signoffs/orphaned")
ids = {x["id"]: x for x in got.json().get("signoffs", [])}
check(got.ok and set(ids) == {OP, DONE, OLD}, f"the office admin sees the organisation's records {got.text[:200]}")
check(ids[DONE]["signer_name"] == "Dana Customer" and ids[DONE]["kept_until"] == "2032-12-31" and ids[OP]["kept_until"] is None, f"kept by law: named {ids[DONE]}")
check(not Ca.get(B + "/api/videos/signoffs/orphaned").json()["signoffs"], "a member sees none (and no other person's)")
check(Ca.delete(B + f"/api/videos/signoffs/orphaned/{OP}").status_code == 404, "a member deletes none")
check(A.delete(B + f"/api/videos/signoffs/orphaned/{DONE}").status_code == 409, "a signed record stays inside its legal period")
check(A.delete(B + f"/api/videos/signoffs/orphaned/{OP}").ok and A.delete(B + f"/api/videos/signoffs/orphaned/{OLD}").ok, "open / past the period: deleted")
check(dbx("SELECT 1 FROM office_doc_log WHERE org_id=? AND action='signoff_delete'", (ORG,)), "the deletion is in the office log")
F = {x["id"]: x for x in Fr.get(B + "/api/videos/signoffs/orphaned").json()["signoffs"]}
check(set(F) == {MINE, SEAL} and F[MINE]["signer_name"] == "Eva Customer" and F[MINE]["kept_until"] is None and F[SEAL]["signer_name"] is None,
      f"a person without an organisation sees their private records; an unreadable name is left out {F}")
check(A.delete(B + f"/api/videos/signoffs/orphaned/{MINE}").status_code == 404, "another person's private record: 404")
check(Fr.delete(B + f"/api/videos/signoffs/orphaned/{MINE}").ok and not dbx("SELECT 1 FROM office_signoffs WHERE id=?", (MINE,)), "the creator deletes it")
GONE, Gs = freelancer(B, A, "gert")
GS = sig(None, GONE, "Left behind")
r = A.delete(B + f"/api/users/{GONE}")
check(r.ok and not dbx("SELECT 1 FROM office_signoffs WHERE id=?", (GS,)), "a private record leaves with the account")

# ================================================================== 3 account export
r = Fr.post(B + "/api/files/upload", data={"space": "private"}, files={"file": ("note.txt", b"my private content", "text/plain")})
assert r.status_code == 201, r.text
NID = r.json()["items"][0]["id"]
PL = Fr.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
FM = Fr.post(B + f"/api/lists/{PL}/forms", json={"title": "Contact form", "access": "public"}).json()
TID = Fr.post(B + "/api/tasks", json={"list_id": PL, "title": "From the form"}).json()["id"]
dbx("INSERT INTO form_entries(task_id,form_id,sender,email,answers,created_at) VALUES(?,?,'Fay','fay@example.com','{}',?) RETURNING task_id", (TID, FM["id"], T))
dbx("INSERT INTO appt_pages(user_id,slug,created_at,updated_at) VALUES(?,'frida-p',?,?) RETURNING user_id", (FID, T, T))
ty = dbx("INSERT INTO appt_types(user_id,name,created_at,updated_at) VALUES(?,'Call',?,?) RETURNING id", (FID, T, T))[0][0]
dbx("""INSERT INTO appt_bookings(user_id,type_id,start,"end",name,email,ip,confirm_hash,created_at) VALUES(?,?,?,?,'Gina','gina@example.com','192.0.2.7','hash-x',?) RETURNING id""", (FID, ty, T, T, T))
po = dbx("INSERT INTO sched_polls(user_id,title,token,token_hash,created_at,updated_at) VALUES(?,'When?','tk','th',?,?) RETURNING id", (FID, T, T))[0][0]
dbx("INSERT INTO sched_poll_votes(poll_id,name,email,answers,edit_hash,ip_hash,created_at,updated_at) VALUES(?,'Hans','hans@example.com','{}','eh','ih',?,?) RETURNING id", (po, T, T))
Z, MAN, D = export_of(Fr)
check(Z.read(f"files/private_files/{NID}-note.txt") == b"my private content", "the private file's content is in the file")
check(next(x for x in D["private_files"] if x["id"] == NID).get("file"), "its row points to it")
check(D["appt_pages"] and D["appt_types"] and D["appt_bookings"][0]["name"] == "Gina", f"booking page and bookings {D.get('appt_bookings')}")
text = json.dumps(D)
check("192.0.2.7" not in text and "hash-x" not in text and "hans@example.com" not in text and '"tk"' not in text and '"eh"' not in text,
      "no network address, voter's address, link or hash")
check(D["polls"][0]["title"] == "When?" and D["poll_votes"][0]["name"] == "Hans", "polls with votes")
check(D["forms"][0]["title"] == "Contact form" and D["form_entries"][0]["email"] == "fay@example.com", "forms with entries (the owner's)")
check(not any("booking pages" in x for x in MAN["not_included"]) and not any("content of your private" in x for x in MAN["not_included"]), "the manifest no longer says they are missing")
dbx("INSERT INTO hub_leave_quota(org_id,user_id,year,days,carry,updated_at) VALUES(?,?,2026,28,2,?) RETURNING id", (ORG, AL, T))
_, _, DA = export_of(A)
check([(x["org_id"], x["year"], x["days"]) for x in DA["leave_quota"]] == [(ORG, 2026, 28)], f"the holiday allowance {DA.get('leave_quota')}")
check(not DA["polls"] and not DA["appt_bookings"] and not DA["form_entries"], "nobody else's polls, bookings, entries")

# ================================================================== 5 export log (before 4: A's lists from above)
logn = lambda: dbx("SELECT COUNT(*) FROM org_list_log WHERE action='export' AND list_id=?", (OL,))[0][0]  # noqa: E731
check(A.get(B + "/api/export.json").ok and A.get(B + "/api/export.json").ok and logn() == 1, f"one row per person, list and day however often {logn()}")
dbx("UPDATE org_list_log SET created_at='2026-01-01T10:00:00+00:00' WHERE action='export' AND list_id=? RETURNING id", (OL,))
A.get(B + "/api/export.json")
check(logn() == 2, f"another day: a new row {logn()}")

# ================================================================== 4 public pages
TOK = FM.get("token") or FM.get("url", "").rsplit("/", 1)[-1]
page = lambda: requests.get(B + "/f/" + TOK).text  # noqa: E731
check("<footer>" in page() and "mailto:" not in page() and "privacy.example" not in page(), "nothing set: no link")
r = A.patch(B + "/api/admin/settings", json={"privacy_url": "https://privacy.example/p", "imprint_url": "https://privacy.example/i", "privacy_email": "dpo@example.com"})
check(r.ok, "admin sets the contact " + r.text)
h = page()
check('href="https://privacy.example/p"' in h and 'href="mailto:dpo@example.com"' in h and 'href="https://privacy.example/i"' in h, "form: link, contact, imprint")
h = requests.get(B + "/s/q/nope").text
check("mailto:dpo@example.com" in h, "the page of an approval link too (also when it is gone)")
check(A.patch(B + "/api/admin/settings", json={"privacy_email": "not an address"}).status_code == 400, "a bad address: 400")
check(A.get(B + "/api/about").json().get("privacy_email") == "dpo@example.com", "the admin reads it back")
check(set(sess().get(B + "/api/auth/info").json()["legal"]) == {"privacy_url", "imprint_url"}, "the login page's data stay as they were")

# ================================================================== 6 + the upgrade of an older database (1)
PLAIN = {"signoff": 1, "state": "accepted", "name": "Ina", "email": "ina@example.com", "ip": "192.0.2.9", "user_agent": "UA", "reason": "fine", "doc_hash": "abc"}
sealed = in_app(f"""
from kalmido.core.db import connect
from kalmido.core.orgcrypt import oc_enc
from kalmido.core.pg import system_ctx
c = connect()
with system_ctx(c):
    v = oc_enc(c, {ORG}, "office_doc_log.detail", {json.dumps(json.dumps(PLAIN))})
    c.commit()
print(v)
""")
assert sealed.startswith("kenc1:"), sealed
log = lambda act, d: dbx("INSERT INTO office_doc_log(org_id,at,action,target,detail) VALUES(?,?,?,'doc',?) RETURNING id", (ORG, T, act, d))[0][0]  # noqa: E731
L1, L2, L3, L4 = log("signoff_accepted", json.dumps(PLAIN)), log("signoff_declined", sealed), log("signoff_accepted", "kenc1:AAAA"), log("doc_mail", json.dumps({"email": "keep@example.com"}))
dbx("DELETE FROM settings WHERE key IN ('migr_siglog2360','migr_upg2360') RETURNING key")
dbx("DELETE FROM time_sheets WHERE user_id IS NULL RETURNING id")
dbx("ALTER TABLE time_sheets DROP CONSTRAINT IF EXISTS time_sheets_user_id_fkey RETURNING 1".replace(" RETURNING 1", ""))
dbx("ALTER TABLE time_sheets ALTER COLUMN user_id SET NOT NULL, ADD CONSTRAINT time_sheets_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE")
fresh({"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, keep=True)
d1 = json.loads(dbx("SELECT detail FROM office_doc_log WHERE id=?", (L1,))[0][0])
check(not set(d1) & {"email", "ip", "user_agent"} and d1["name"] == "Ina" and d1["reason"] == "fine" and d1["doc_hash"] == "abc", f"plain entry: the three keys gone, the rest stays {d1}")
raw = dbx("SELECT detail FROM office_doc_log WHERE id=?", (L2,))[0][0]
check(raw.startswith("kenc1:") and raw != sealed, "a sealed entry is sealed again")
d2 = json.loads(in_app(f"""
from kalmido.core.db import connect
from kalmido.core.orgcrypt import oc_dec
from kalmido.core.pg import system_ctx
c = connect()
with system_ctx(c):
    print(oc_dec(c, {ORG}, "office_doc_log.detail", {raw!r}))
"""))
check(not set(d2) & {"email", "ip", "user_agent"} and d2["name"] == "Ina", f"sealed entry: opened, shortened {d2}")
check(dbx("SELECT detail FROM office_doc_log WHERE id=?", (L3,))[0][0] == "kenc1:AAAA", "an entry that cannot be opened stays")
check("keep@example.com" in dbx("SELECT detail FROM office_doc_log WHERE id=?", (L4,))[0][0], "other entries are not touched")
logs = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
check("1 sealed one(s) without a key left" in logs.stdout + logs.stderr, "the start counts the entries it could not open")
r = dbx("SELECT is_nullable FROM information_schema.columns WHERE table_name='time_sheets' AND column_name='user_id'")
k = dbx("SELECT confdeltype FROM pg_constraint WHERE conname='time_sheets_user_id_fkey'")
check(r[0][0] == "YES" and k[0][0] == "n", f"an older database gets the changed key once {r} {k}")
check(sess("alice").get(B + "/api/state").ok, "the app runs after the one-shots")
sys.exit(done("p23602_d_api_test"))
