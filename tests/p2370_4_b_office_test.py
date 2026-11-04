#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.370.4 part B (#3089): office / clients / agent docs, the findings of the review of 2.272 (N2, M6, N11, N12, the gaps of
p2272_d). Own container (start.sh, mode workspaces). Invented accounts only (example.com); the person without an
organisation (freelancer fixture, private clients in the personal office) does every client and office step.
 - N2: the office write paths take no client from the trash (409 "The client is in the trash"): a new invoice, a client set
   on a draft, an invoice from times, a deal, a letter, a framework contract, a trip; a draft that has the client already
   stays saveable; after the restore it works again
 - the signature link of a document of a client in the trash is dead (back after the restore); the mail code of its data
   protection sheet takes in nothing (the video link: p2272_d)
 - M6: the undo of an account import puts its clients into the client trash (with their contact persons) and its address
   books into the address book trash, both restorable
 - N11: /api/clients/usage for many clients counts the same as the single clients summed up; the bulk delete archives the
   one in use and trashes the others
 - N12: the dry run of the entertainment receipts does not count a bill kept by law
 - roles in an organisation: the member who made the client deletes / restores it, another member gets 403, a read-only
   member 403, a stranger 404
freelancer-matrix: office
usage: p2370_4_b_office_test.py <datadir>      (P23704B_NOSTART=1: a running server on KALMIDO_TEST_PORT)
"""
import email.message
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, FAILS, OKS, check  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

CT = kt.CT
TRASH = "The client is in the trash"


def sql(q, args=()):
    return kt.dbx(q, args)


def one(q, args=()):
    r = sql(q, args)
    return r[0][0] if r else None


def run(q, args=()):
    """A write in the suite's database (kt.dbx only reads)."""
    import dbx as dbxm
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # an UPDATE without rows to read
            return []
    finally:
        c.close()


def box(code, env=()):
    """Runs python code inside the app container (a fresh process)."""
    cmd = ["docker", "exec"]
    for e in env:
        cmd += ["-e", e]
    out = subprocess.run(cmd + [CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.commit()\nc.close()"],
                         capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def ago(hours=0, days=0):
    return (datetime.now(timezone.utc) - timedelta(hours=hours, days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


def person(name, org, role):
    """A person in organisation org with role (created by the instance admin) -> (id, session)."""
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": kt.PASSWORD,
                                       "email": f"{name}@example.com", "orgs": [{"id": org, "role": role}] if org else []})
    assert r.ok, r.text
    if org:
        assert org_join(B, name, org), name
    s = kt.sess(name)
    assert s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"}).ok
    return r.json()["id"], s


def gone(r, what):
    check(r.status_code == 409 and TRASH in r.text, f"N2 {what}: a client in the trash -> 409 ({r.status_code} {r.text[:200]})")


def made(r, what):
    check(r.status_code in (200, 201), f"N2 {what}: with a live client it works ({r.status_code} {r.text[:200]})")
    return (r.json() or {}).get("id") if r.status_code in (200, 201) else None


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P23704B")
A = kt.setup()
FID, Fr = freelancer(B, A)
Fr.get(B + "/api/office/docs?kind=invoice")  # the personal office exists from its first use
PO = one("SELECT id FROM orgs WHERE personal_of=?", (FID,))
NOW = ago()

# ================================================================== N2: no client from the trash on the write paths
LIVE = Fr.post(B + "/api/clients", json={"name": "Live Example"}).json()["id"]
CL = Fr.post(B + "/api/clients", json={"name": "Trash Example"}).json()["id"]
D1 = Fr.post(B + "/api/office/docs", json={"kind": "invoice", "client_id": CL}).json().get("id")
check(D1, "N2 setup: a draft of the client")
r = Fr.delete(B + f"/api/clients/{CL}")
check(r.ok and r.json().get("trashed") is True, f"N2 setup: the client goes to the trash {r.text[:200]}")

made(Fr.post(B + "/api/office/docs", json={"kind": "invoice", "client_id": LIVE}), "new invoice")
gone(Fr.post(B + "/api/office/docs", json={"kind": "invoice", "client_id": CL}), "new invoice")
D2 = Fr.post(B + "/api/office/docs", json={"kind": "invoice"}).json()["id"]
gone(Fr.patch(B + f"/api/office/docs/{D2}", json={"client_id": CL}), "client set on a draft")
r = Fr.patch(B + f"/api/office/docs/{D1}", json={"client_id": CL, "project_title": "Still saveable"})
check(r.ok, f"N2: a draft that has the client already stays saveable ({r.status_code} {r.text[:200]})")
gone(Fr.post(B + "/api/office/docs/from-time", json={"client_id": CL, "from": "2020-01-01", "to": "2020-01-31"}), "invoice from times")
made(Fr.post(B + "/api/office/deals", json={"title": "Live deal", "client_id": LIVE}), "deal")
gone(Fr.post(B + "/api/office/deals", json={"title": "Trash deal", "client_id": CL}), "deal")
made(Fr.post(B + "/api/office/letters", json={"subject": "Live letter", "client_id": LIVE}), "letter")
gone(Fr.post(B + "/api/office/letters", json={"subject": "Trash letter", "client_id": CL}), "letter")
made(Fr.post(B + "/api/office/contracts", json={"name": "Live frame", "client_id": LIVE}), "framework contract")
gone(Fr.post(B + "/api/office/contracts", json={"name": "Trash frame", "client_id": CL}), "framework contract")
TRIP = {"date_from": "2026-03-12", "dest": "Example place", "items": [{"date": "2026-03-12", "category": "taxi", "amount": 25}]}
made(Fr.post(B + "/api/office/trips", json={**TRIP, "client_id": LIVE}), "trip")
gone(Fr.post(B + "/api/office/trips", json={**TRIP, "client_id": CL}), "trip")
check(Fr.post(B + f"/api/clients/{CL}/restore").ok, "N2: restore")
made(Fr.post(B + "/api/office/deals", json={"title": "Deal after the restore", "client_id": CL}), "deal after the restore")

# ================================================================== signature link and mail code of a client in the trash
GD = run("INSERT INTO office_gen_docs(org_id, client_id, title, body, body_hash, status, created_by, created_at, updated_at) "
         "VALUES(?,?,?,?,?,?,?,?,?) RETURNING id", (PO, CL, "Consent", "Text", "", "final", FID, NOW, NOW))[0][0]
SIGOK = (f"from kalmido.office.doctpl import dt_hash, dt_sig_valid\nfrom kalmido.core.pg import system_ctx\n"
         f"with system_ctx(c):\n    h = dt_hash('Text')\n    c.execute('UPDATE office_gen_docs SET body_hash=? WHERE id=?', (h, {GD}))\n"
         f"    print('sigok', dt_sig_valid(c, {{'gen_doc_id': {GD}, 'org_id': {PO}, 'doc_hash': h}}))")
s0 = box(SIGOK)
check("sigok True" in s0, f"setup: the signature link of the document is valid {s0[-300:]}")
assert Fr.delete(B + f"/api/clients/{CL}").ok
s1 = box(SIGOK)
check("sigok False" in s1, f"trash: the signature link of the client's document is dead {s1[-300:]}")
SID = run("INSERT INTO office_privacy_sheets(org_id, client_id, kind, status, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?) RETURNING id",
          (PO, CL, "consent", "sent", FID, NOW, NOW))[0][0]
CODE = "ABCDEFGHJKLM"
msg = email.message.EmailMessage()
msg["From"], msg["To"], msg["Subject"], msg["Message-ID"] = "client@example.com", "office@example.com", f"Re: Consent [DS-{CODE}]", "<p23704b@example.com>"
msg.set_content("Signed, see attachment")
msg.add_attachment(b"%PDF-1.4\n%%EOF\n", maintype="application", subtype="pdf", filename="signed.pdf")
MAIL = (f"from kalmido.office.privacy import dsb_code_hash, dsb_mail_import\nimport email\n"
        f"c.execute('UPDATE office_privacy_sheets SET code_hash=? WHERE id=?', (dsb_code_hash('{CODE}'), {SID}))\n"
        f"raw = {msg.as_bytes()!r}\nprint('mail', dsb_mail_import(c, email.message_from_bytes(raw), raw))")
m1 = box(MAIL)
row = sql("SELECT status, signed_node_id FROM office_privacy_sheets WHERE id=?", (SID,))[0]
check("mail 0" in m1 and row[0] == "sent" and row[1] is None, f"trash: the mail code of its data protection sheet signs nothing {m1[-300:]} {row}")
check(Fr.post(B + f"/api/clients/{CL}/restore").ok and "sigok True" in box(SIGOK), "restore: the signature link works again")

# ================================================================== M6: the undo of an account import -> the trashes
C5 = Fr.post(B + "/api/clients", json={"name": "Imported Echo", "contacts": [{"name": "Eva Example"}]}).json()["id"]
K5 = one("SELECT id FROM office_client_contacts WHERE client_id=?", (C5,))
BK = Fr.post(B + "/api/books", json={"name": "Imported book"}).json()["id"]
# 2.506.0 (#4299): rows born after an import stay at its undo: these are the import's, so older than it
run("UPDATE clients SET created_at=?, updated_at=? WHERE id=?", (ago(hours=2), ago(hours=2), C5))
run("UPDATE office_client_contacts SET created_at=?, updated_at=? WHERE id=?", (ago(hours=2), ago(hours=2), K5))
cr = {"oi": [["clients", C5, None], ["office_client_contacts", K5, None]], "books": [BK]}
IID = run("INSERT INTO imports(user_id, source, file_name, created, report, created_at) VALUES(?,?,?,?,?,?) RETURNING id",
          (FID, "Kalmido", "p23704b.kalmido-export", json.dumps(cr), "{}", ago(hours=1)))[0][0]
r = Fr.post(B + f"/api/imports/{IID}/undo")
check(r.ok, f"M6: the undo runs {r.status_code} {r.text[:200]}")
check(one("SELECT deleted_at FROM clients WHERE id=?", (C5,)) and one("SELECT COUNT(*) FROM office_client_contacts WHERE client_id=?", (C5,)) == 1,
      "M6: its client lies in the client trash with its contact person (was deleted for good)")
check(one("SELECT deleted_at FROM books WHERE id=?", (BK,)), "M6: its address book lies in the address book trash (was deleted for good)")
r = Fr.post(B + f"/api/clients/{C5}/restore")
check(r.ok and len(Fr.get(B + f"/api/clients/{C5}").json().get("contacts") or []) == 1, f"M6: the client comes back with its contact person {r.text[:200]}")
check(Fr.post(B + f"/api/books/{BK}/restore").ok and one("SELECT deleted_at FROM books WHERE id=?", (BK,)) is None, "M6: the address book comes back")
# review M1: a client put into the trash by hand before the undo keeps its contact person (restorable with it)
C6 = Fr.post(B + "/api/clients", json={"name": "Imported Foxtrot", "contacts": [{"name": "Fiona Example"}]}).json()["id"]
K6 = one("SELECT id FROM office_client_contacts WHERE client_id=?", (C6,))
check(Fr.delete(B + f"/api/clients/{C6}").ok and one("SELECT deleted_at FROM clients WHERE id=?", (C6,)), "M6: setup: client into the trash by hand")
IID6 = run("INSERT INTO imports(user_id, source, file_name, created, report, created_at) VALUES(?,?,?,?,?,?) RETURNING id",
           (FID, "Kalmido", "p23704b-2.kalmido-export", json.dumps({"oi": [["clients", C6, None], ["office_client_contacts", K6, None]]}), "{}",
            ago(hours=1)))[0][0]
r = Fr.post(B + f"/api/imports/{IID6}/undo")
check(r.ok and one("SELECT COUNT(*) FROM office_client_contacts WHERE id=?", (K6,)) == 1,
      f"M6: the contact person of a client already in the trash stays after the undo {r.status_code} {r.text[:200]}")

# ================================================================== N11: the numbers of many clients at once
ids = []
for i in range(3):
    cid = Fr.post(B + "/api/clients", json={"name": f"Usage Example {i}", "contacts": [{"name": f"Person {i}"}, {"name": f"Second {i}"}][:i + 1]}).json()["id"]
    lid = Fr.post(B + "/api/lists", json={"name": f"Usage project {i}"}).json()["id"]
    run("UPDATE lists SET client_id=? WHERE id=?", (cid, lid))
    ids.append(cid)
run("INSERT INTO office_privacy_sheets(org_id, client_id, kind, status, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
    (PO, ids[1], "consent", "signed", FID, NOW, NOW))
alone = [Fr.get(B + f"/api/clients/usage?ids={i}").json() for i in ids]
summed = {}
for u in alone:
    for t, n in (u.get("refs") or {}).items():
        summed[t] = summed.get(t, 0) + n
allu = Fr.get(B + "/api/clients/usage?ids=" + ",".join(map(str, ids))).json()
check(allu.get("refs") == summed and summed.get("office_client_contacts") == 5 and summed.get("lists") == 3 and summed.get("office_privacy_sheets") == 1,
      f"N11: many at once count like the single ones summed up {allu.get('refs')} {summed}")
check(allu.get("in_use") == 1 == sum(u.get("in_use", 0) for u in alone), f"N11: one is kept by its signed sheet {allu.get('in_use')}")
j = Fr.post(B + "/api/clients/bulk", json={"action": "delete", "ids": ids}).json()
check(j.get("archived") == 1 and sorted(j.get("trashed") or []) == sorted([ids[0], ids[2]]), f"N11: the bulk delete archives the one in use {j}")

# ================================================================== N12: the dry run of the entertainment receipts
OLD = ago(days=400)
M1 = run("INSERT INTO office_meals(org_id, date, status, created_by, created_at, updated_at, deleted_at) VALUES(?,?,?,?,?,?,?) RETURNING id",
         (PO, "2025-01-10", "draft", FID, OLD, OLD, OLD))[0][0]
M2 = run("INSERT INTO office_meals(org_id, date, status, approved_at, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?) RETURNING id",
         (PO, "2025-01-10", "approved", NOW, FID, OLD, NOW))[0][0]
run("INSERT INTO office_meal_log(org_id, meal_id, action, at) VALUES(?,?,?,?)", (PO, M2, "approve", NOW))
run("INSERT INTO office_meal_files(org_id, meal_id, name, file, created_by, created_at, deleted_at) VALUES(?,?,?,?,?,?,?)",
    (PO, M2, "old-bill.pdf", "p23704b-old.pdf", FID, OLD, OLD))
out = box("from kalmido.office import meals as M\nM.BW_TICK['at'] = 0\nprint('dry', M.bw_purge_tick(c))")
check("dry 1" in out, f"N12: the dry run counts the trashed meal, not the bill kept by law {out[-300:]}")
check(one("SELECT COUNT(*) FROM office_meals WHERE id IN (?,?)", (M1, M2)) == 2, "N12: the dry run deletes nothing")

# ================================================================== roles: delete / restore a client of an organisation
ORG = A.post(B + "/api/admin/orgs", json={"name": "Roles Example"}).json()["id"]
BID, Bo = person("bob", ORG, "member")
MID, Mi = person("mia", ORG, "member")
RID, Ri = person("rita", ORG, "readonly")
SID2, Sa = person("sam", None, None)
r = Bo.post(B + "/api/clients", json={"name": "Org Example", "org_id": ORG})
check(r.status_code == 201 and r.json().get("org_id") == ORG, f"roles setup: the member makes a client of the organisation {r.text[:200]}")
OC = r.json()["id"]
check(Ri.delete(B + f"/api/clients/{OC}").status_code == 403, "roles: a read-only member cannot delete (403)")
check(Mi.delete(B + f"/api/clients/{OC}").status_code == 403, "roles: another member cannot delete (403, only its maker or an admin)")
check(Sa.delete(B + f"/api/clients/{OC}").status_code == 404, "roles: a stranger does not see it (404)")
check(one("SELECT deleted_at FROM clients WHERE id=?", (OC,)) is None, "roles: still not in the trash")
r = Bo.delete(B + f"/api/clients/{OC}")
check(r.ok and r.json().get("trashed") is True, f"roles: its maker deletes it into the trash {r.text[:200]}")
check(Ri.post(B + f"/api/clients/{OC}/restore").status_code == 403, "roles: a read-only member cannot restore (403)")
check(Mi.post(B + f"/api/clients/{OC}/restore").status_code == 403, "roles: another member cannot restore (403)")
check(Sa.post(B + f"/api/clients/{OC}/restore").status_code == 404, "roles: a stranger cannot restore (404)")
check(Sa.delete(B + f"/api/clients/{OC}/purge").status_code == 404 and Ri.delete(B + f"/api/clients/{OC}/purge").status_code == 403,
      "roles: purge - stranger 404, read-only 403")
check(Bo.post(B + f"/api/clients/{OC}/restore").ok and one("SELECT deleted_at FROM clients WHERE id=?", (OC,)) is None, "roles: its maker restores it")

print(f"p2370_4_b_office: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
