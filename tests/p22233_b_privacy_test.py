#!/usr/bin/env python3
"""2.223.3 B (#2878 #2880 #2879): data protection -- clients go with their account / organisation, a client only
finalised documents keep can be deleted or anonymised; the organisation export holds only the lists the exporting
admin sees in the app and no deleted rows. Own container (start.sh, mode workspaces, server key). Invented accounts only.
 - #2880: a member's organisation list shared with nobody is not in the admin's export (nor its task, comment or file);
   a shared one and the admin's own unshared one are
 - #2879: a task in the trash, a deleted absence and a deleted booking are not in the export, the live ones are; a client
   in the trash is not in the retention export
 - #2878: a client with only a draft or a trial document goes to the trash (not archived); one with a finalised invoice
   is archived, "anonymize" empties its name / e-mail / contact persons and leaves the invoice as it was; a finalised
   document without its recipient copy (older) -> 409; another organisation 404, a member who did not create it 403
 - #2878: deleting an account without organisation removes its private clients and their contact persons; with a kept
   invoice the client moves into the retired office, anonymised; deleting an organisation leaves no client with its creator
freelancer-matrix: office
usage: p22233_b_privacy_test.py <datadir>      (P22233B_NOSTART=1: a running server on KALMIDO_TEST_PORT)
"""
import base64
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import date, datetime, timezone

import dbx as dbxm
from freelancer_fixture import freelancer, org_join

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # noqa: E402
FEAT = "cal,comments,collab,office,clients,docs,files,dispo"
O = "/api/office"
D = O + "/docs"
TODAY = date.today().isoformat()
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # an UPDATE without rows to read
            return []
    finally:
        c.close()


def box(code):
    """Runs python code inside the app container; returns its output."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.commit()\nc.close()"],
                         capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def export(oid, uid):
    """The organisation export of oid as admin uid (admin/orgexport.py ox_build, the ZIP before its encryption) -> {name: rows}
    of the JSON entries + "_files": the file entries."""
    out = box(f"""import io, json, zipfile
from kalmido.admin.orgexport import ox_build
from kalmido.core.pg import system_ctx
b = io.BytesIO()
with system_ctx(c):
    ox_build(c, {int(oid)}, b, by={{"id": {int(uid)}, "name": "Admin"}})
z = zipfile.ZipFile(b)
d = {{n: json.loads(z.read(n)) for n in z.namelist() if n.endswith(".json") and n != "manifest.json"}}
d["_files"] = [n for n in z.namelist() if n.startswith("files/")]
d["_manifest"] = json.loads(z.read("manifest.json"))
print("OXJSON" + json.dumps(d, default=str))""")
    line = next((x for x in out.splitlines() if x.startswith("OXJSON")), None)
    assert line, out[-3000:]
    return json.loads(line[6:])


def ids(x, name):
    return {r["id"] for r in x.get(name, [])}


def invoice(s, client, final=True):
    r = s.post(B + D, json={"kind": "invoice", "client_id": client, "service_from": TODAY, "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if final:
        r = s.post(B + f"{D}/{did}/finalize")
        assert r.ok, r.text
    return did


def client(s, name, **kw):
    r = s.post(B + "/api/clients", json={"name": name, "email": name.split()[0].lower() + "@example.com", "street": "Kundenweg 2",
                                         "zip": "20095", "city": "Hamburg", "country": "DE", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


if os.environ.get("P22233B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
    assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
U = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    U[u] = r.json()["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Nordlicht Test", "admin_id": ALICE}).json()["id"]
for u in ("bob", "carol"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
    org_join(B, u, ORG)
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Fremde KG", "admin_id": U["dave"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG), (Da, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})

# ================================================================== #2880 + #2879: the organisation export
SECRET = Bo.post(B + "/api/lists", json={"name": "Bobs ungeteilte Liste", "org_id": ORG}).json()["id"]
ST = Bo.post(B + "/api/tasks", json={"title": "Geheimaufgabe Bob", "list_id": SECRET}).json()["id"]
Bo.post(B + f"/api/tasks/{ST}/comments", json={"body": "Kommentar nur fuer Bob"})
r = Bo.post(B + f"/api/tasks/{ST}/attachments", files=[("file", ("bob-only.txt", b"only bob", "text/plain"))])
check(r.ok, "setup: a file on bob's unshared list " + r.text[:120])
SHARED = Bo.post(B + "/api/lists", json={"name": "Bobs geteilte Liste", "org_id": ORG}).json()["id"]
r = Bo.put(B + f"/api/lists/{SHARED}/members", json={"user_id": U["carol"], "role": "edit"})
check(r.ok, "setup: bob shares a list with carol " + r.text[:120])
SHT = Bo.post(B + "/api/tasks", json={"title": "Geteilte Aufgabe", "list_id": SHARED}).json()["id"]
OWN = A.post(B + "/api/lists", json={"name": "Alices eigene Liste", "org_id": ORG}).json()["id"]
OT = A.post(B + "/api/tasks", json={"title": "Alices Aufgabe", "list_id": OWN}).json()["id"]
GONE = A.post(B + "/api/tasks", json={"title": "Aufgabe im Papierkorb", "list_id": OWN}).json()["id"]
check(A.delete(B + f"/api/tasks/{GONE}").ok, "setup: a task into the trash")
check(sql("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (SHARED, U["carol"])) and not sql(
    "SELECT 1 FROM list_members WHERE list_id=? AND user_id!=?", (SECRET, U["bob"])), "setup: one list shared with carol, one with nobody")
NW = now()
for kind, note, gone in (("sick", "Grippe erfunden", NW), ("vacation", "Urlaub erfunden", None)):
    sql("INSERT INTO hub_absences(org_id, user_id, kind, start_date, end_date, note, created_by, created_at, deleted_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (ORG, U["bob"], kind, TODAY, TODAY, note, U["bob"], NW, gone))
for title, gone in (("Buchung geloescht", NW), ("Buchung aktiv", None)):
    sql("INSERT INTO hub_bookings(org_id, title, start, \"end\", resource_kind, resource_id, created_by, created_at, updated_at, deleted_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)", (ORG, title, TODAY, TODAY, "person", U["bob"], U["bob"], NW, NW, gone))

x = export(ORG, ALICE)
lists, tasks = ids(x, "lists.json"), ids(x, "tasks.json")
check(SECRET not in lists and ST not in tasks, f"#2880: bob's unshared list and its task are not in the admin's export {sorted(lists)}")
check(SHARED in lists and SHT in tasks and OWN in lists and OT in tasks, "#2880: the shared list and the admin's own list are in it")
text = json.dumps(x)
check("Kommentar nur fuer Bob" not in text and not any("bob-only" in f for f in x["_files"]), "#2880: nor its comment and file")
check(any("share" in n and "nobody" in n for n in x["_manifest"].get("not_included", [])), "#2880: the manifest names the rule")
check(GONE not in tasks, "#2879: a task in the trash is not in the export")
ab = {r["note"]: r for r in x.get("hub/absences.json", [])}
bk = {r["title"] for r in x.get("hub/bookings.json", [])}
check("Grippe erfunden" not in ab and "Urlaub erfunden" in ab, f"#2879: a deleted absence is not in the export, the live one is {sorted(ab)}")
check("Buchung geloescht" not in bk and "Buchung aktiv" in bk, f"#2879: a deleted booking is not in the export, the live one is {sorted(bk)}")
xb = export(ORG, U["bob"])  # bob as the exporter (the rule follows the person): his own list is in it
check(SECRET in ids(xb, "lists.json"), "#2880: the list's owner exports it with the rest")

# ================================================================== #2878: deleting / anonymising a client (freelancer)
FID, Fr = freelancer(B, A)
assert Fr.put(B + O + "/settings", json={"company_fields": COMPANY}).ok
K1 = client(Fr, "Entwurf Kunde")
D1 = invoice(Fr, K1, final=False)
r = Fr.delete(B + f"/api/clients/{K1}")
check(r.ok and r.json().get("trashed") and not r.json().get("archived") and sql("SELECT archived FROM clients WHERE id=? AND deleted_at IS NOT NULL", (K1,)) == [(0,)],
      "#2878: a client with only a draft goes to the trash " + r.text[:200])
check(sql("SELECT 1 FROM office_docs WHERE id=?", (D1,)), "#2878: the draft stays")
K2 = client(Fr, "Probe Kunde")
D2 = invoice(Fr, K2)
sql("UPDATE office_docs SET trial=1 WHERE id=?", (D2,))
r = Fr.delete(B + f"/api/clients/{K2}")
check(r.ok and r.json().get("trashed"), "#2878: a client with only a trial document goes to the trash " + r.text[:200])
K3 = client(Fr, "Beleg Kunde", contacts=[{"name": "Erika Beispiel", "email": "erika@example.com"}])
D3 = invoice(Fr, K3)
before = sql("SELECT recipient, recipient_snapshot, number, locked_at FROM office_docs WHERE id=?", (D3,))
rd0 = Fr.get(B + f"{D}/{D3}/render").json()
u = Fr.get(B + f"/api/clients/usage?ids={K3}").json()
check(u.get("in_use") == 1, f"#2878: usage counts the client as kept {u}")
r = Fr.delete(B + f"/api/clients/{K3}")
check(r.ok and r.json().get("archived") is True and sql("SELECT archived, deleted_at FROM clients WHERE id=?", (K3,)) == [(1, None)],
      "#2878: a client with a finalised invoice is archived " + r.text[:200])
r = Ca.post(B + f"/api/clients/{K3}/anonymize")
check(r.status_code == 404, f"#2878: another person (another space) 404 {r.status_code}")
r = Fr.post(B + f"/api/clients/{K3}/anonymize")
row = sql("SELECT name, email, street, city, archived FROM clients WHERE id=?", (K3,))
check(r.ok and r.json().get("anonymized") and row == [("Deleted client", "", "", "", 1)], f"#2878: anonymised {row} " + r.text[:160])
check(not sql("SELECT 1 FROM office_client_contacts WHERE client_id=?", (K3,)), "#2878: its contact persons are gone")
check(sql("SELECT recipient, recipient_snapshot, number, locked_at FROM office_docs WHERE id=?", (D3,)) == before, "#2878: the invoice is unchanged")
rd1 = Fr.get(B + f"{D}/{D3}/render").json()
check(rd1.get("recipient") == rd0.get("recipient") and "Beleg Kunde" in json.dumps(rd1.get("recipient")), "#2878: it still prints the address of its copy")
K4 = client(Fr, "Alt Kunde")
D4 = invoice(Fr, K4)
sql("UPDATE office_docs SET recipient_snapshot=NULL WHERE id=?", (D4,))
r = Fr.post(B + f"/api/clients/{K4}/anonymize")
check(r.status_code == 409 and sql("SELECT name FROM clients WHERE id=?", (K4,)) == [("Alt Kunde",)], f"#2878: an older document reads it live -> 409 {r.status_code}")

# an organisation's client: a member who did not create it 403, its creator anonymises it
assert A.put(B + O + "/settings", json={"company_fields": COMPANY}).ok
OC = client(A, "Org Kunde AG")
invoice(A, OC)
r = Bo.post(B + f"/api/clients/{OC}/anonymize")
check(r.status_code == 403, f"#2878: a member who did not create it 403 {r.status_code}")
r = Da.post(B + f"/api/clients/{OC}/anonymize")
check(r.status_code == 404, f"#2878: the admin of another organisation 404 {r.status_code}")
check(A.post(B + f"/api/clients/{OC}/anonymize").ok, "#2878: its creator anonymises it")

# ================================================================== #2879: the retention export without the clients' trash
r = Fr.get(B + "/api/retention/me/export.zip")
csv = ""
if r.ok and r.content[:2] == b"PK":
    z = zipfile.ZipFile(io.BytesIO(r.content))
    csv = z.read("invoices/clients.csv").decode("utf-8", "replace") if "invoices/clients.csv" in z.namelist() else ""
check(r.ok and "Entwurf Kunde" not in csv and "Alt Kunde" in csv, f"#2879: the retention export's clients leave the trash out {r.status_code} {csv[:300]!r}")

# ================================================================== #2878: the account deletion (no organisation)
CID, Cr = freelancer(B, A, "carl")
P1 = client(Cr, "Carls Privatkunde", contacts=[{"name": "Paul Beispiel"}])
r = A.delete(B + f"/api/users/{CID}")
check(r.ok and not sql("SELECT 1 FROM users WHERE id=?", (CID,)), "#2878: carl's account is deleted " + r.text[:200])
check(not sql("SELECT 1 FROM clients WHERE created_by=?", (CID,)) and not sql("SELECT 1 FROM office_client_contacts WHERE client_id=?", (P1,)),
      "#2878: his private clients and their contact persons are gone")
# with a finalised invoice (self-hosting retires the personal office): the client goes into it, anonymised
HID, Hr = freelancer(B, A, "hanna")
assert Hr.put(B + O + "/settings", json={"company_fields": COMPANY}).ok
P2 = client(Hr, "Hannas Kunde", contacts=[{"name": "Ida Beispiel"}])
invoice(Hr, P2)
PO = sql("SELECT id FROM orgs WHERE personal_of=?", (HID,))[0][0]
r = A.delete(B + f"/api/users/{HID}")
if r.status_code == 409 and (r.json() or {}).get("code") == "retention":
    r = A.delete(B + f"/api/users/{HID}", params={"retention": "waived"})
row = sql("SELECT c.org_id, c.name, c.email FROM clients c JOIN orgs o ON o.id=c.org_id WHERE c.id=? AND o.retired_at IS NOT NULL", (P2,))
check(r.ok and (not sql("SELECT 1 FROM clients WHERE id=?", (P2,)) or row == [(PO, "Deleted client", "")]), f"#2878: a kept client is in the retired office, anonymised {row} " + r.text[:200])
check(not sql("SELECT 1 FROM clients WHERE org_id IS NULL AND created_by=?", (HID,)), "#2878: no private client of hanna is left")

# ================================================================== #2878: the organisation deletion
DEL = A.post(B + "/api/admin/orgs", json={"name": "Dritte KG", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{DEL}/members", json={"email": "bob@example.com", "role": "member"}).ok
org_join(B, "bob", DEL)
Bo.patch(B + "/api/settings", json={"workspace": f"org:{DEL}"})
DC = client(Bo, "Kunde der Dritten KG")
check(sql("SELECT org_id FROM clients WHERE id=?", (DC,)) == [(DEL,)], "setup: the client belongs to the organisation")
# 2.223.3 (#2878, review): a client of it that a logbook entry of ANOTHER organisation keeps moves there instead of going
DC2 = client(Bo, "Kunde mit fremder Fahrt")
DRV = sql("INSERT INTO office_drives(org_id, day, client_id, created_at, updated_at) VALUES(?,?,?,?,?) RETURNING id",
          (ORG, "2026-10-01", DC2, "2026-10-01T10:00:00Z", "2026-10-01T10:00:00Z"))[0][0]
r = A.delete(B + f"/api/admin/orgs/{DEL}", params={"confirm": "1"})
check(sql("SELECT org_id FROM clients WHERE id=?", (DC2,)) == [(ORG,)] and sql("SELECT client_id FROM office_drives WHERE id=?", (DRV,)) == [(DC2,)],
      "#2878: a client another organisation's logbook keeps moves there, the entry keeps it")
check(r.ok and not sql("SELECT 1 FROM orgs WHERE id=?", (DEL,)), "#2878: the organisation is deleted " + r.text[:200])
check(not sql("SELECT 1 FROM clients WHERE id=?", (DC,)), "#2878: its client went with it (not bob's private client now)")
Bo.patch(B + "/api/settings", json={"workspace": "private"})
check("Kunde der Dritten KG" not in json.dumps(Bo.get(B + "/api/clients").json()), "#2878: bob sees no such client")

print(f"p22233_b_privacy: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
