#!/usr/bin/env python3
"""2.42.0 API tests, part B: keys per organisation (#828) -- the office's sensitive fields and the stored files of an
organisation are encrypted at rest with a key of the organisation (kalmido/core/orgcrypt.py); everyone who may see them
sees them in plain as before. Invented companies and the test IBAN only.
 - in the database only "kenc1:..." for the company's bank / tax fields, the free company lines, framework contract
   rates, purchase prices (cost 0 + cost_enc), the frozen sender of a finalised invoice, costs / margin of the totals and
   office log entries with such values; the API answers in plain (admin), a member still gets no purchase prices
 - files on disk start with the magic KENC1 (attachment of an organisation's list, stored invoice PDF / XML); the
   downloads are byte for byte the originals; the storage check finds no problem
   2.64.0 (#1864): a private list's file is sealed too, with the owner's account key (header = -owner id)
 - Settings > Organisation > Encryption: state, recovery key only for the organisation's admins after the password
   (wrong 403, member 403, other organisation 404, agent 403), noted in the office log without the value
 - the instance switch org_encrypt (admin only): off -> new values stay plain, encrypted ones stay readable
 - orgcrypt_cli (docker exec): status, decrypt-all (everything plain again, org_encrypt=0), encrypt-all
 - a wrong server key: a clear error (code orgcrypt, names KALMIDO_SECRET_KEY) instead of garbage; rewrap with the
   recovery key from stdin makes the data readable with the new server key
 - deleting an organisation deletes its key row and its office folder; a file of a list that left the organisation is
   resealed (2.64.0 #1864: with the owner's account key in a private list) and stays readable
 - without KALMIDO_SECRET_KEY nothing is encrypted (database and files plain), the state says so, the recovery key 409
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY and the mode workspaces.
usage: p2420_b_api_test.py <datadir>"""
import base64
import glob
import json
import os
import struct
import subprocess
import sys
import time

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
KEY2 = base64.b64encode(os.urandom(32)).decode()
TEST_IBAN = "DE89370400440532013000"
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def start(key=KEY, keep=False):
    extra = ["-e KALMIDO_INSTANCE_MODE=workspaces", "-e KALMIDO_ORGCRYPT_DELAY=0"] + (["-e KALMIDO_SECRET_KEY=" + key] if key else [])
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(extra), **({"KEEP": "1"} if keep else {}))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def cli(*args, stdin=None):
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", *args], input=stdin,
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout, r.stderr


def head(path):
    with open(path, "rb") as f:
        return f.read(6)


def space(path):
    """2.64.0 (#1864): the space id in a sealed file's header (> 0 organisation, < 0 the account -id), None when plain."""
    with open(path, "rb") as f:
        h = f.read(14)
    return struct.unpack(">q", h[6:14])[0] if h[:6] == b"KENC1\n" and len(h) == 14 else None


def wait_space(path, sid, secs=30):
    for _ in range(secs * 4):
        if space(path) == sid:
            return True
        time.sleep(0.25)
    return False


def office_files(oid):
    return sorted(p for p in glob.glob(os.path.join(DATA, "office", str(oid), "*")) if not os.path.basename(p).startswith("logo"))


def enc(v):
    return isinstance(v, str) and v.startswith("kenc1:")


def wait_migrated(oid, secs=30):
    for _ in range(secs * 4):
        if one("SELECT migrated_at FROM org_keys WHERE org_id=?", (oid,)):
            return True
        time.sleep(0.25)
    return False


start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = "cal,comments,collab,office,clients,time"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
O = "/api/office"

# ---------------------------------------------------------------- office data (invented)
FIELDS = {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
          "email": "hallo@nordlicht.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN,
          "bic": "COBADEFFXXX", "bank_name": "Beispielbank"}
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht GmbH", "bank_lines": ["IBAN DE89 3704 0044 0532 0130 00"]},
                                     "company_fields": FIELDS})
check(r.ok, "office settings with company fields " + r.text[:200])
CL = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"}).json()["id"]
SV = A.post(B + O + "/services", json={"name_de": "Schnitt", "daily_rate": 800}).json()["id"]
r = A.post(B + O + "/contracts", json={"name": "RV Beispielkunde", "client_id": CL, "rates": {str(SV): 700}})
check(r.status_code == 201 and r.json()["rates"] == {str(SV): 700.0}, "contract with a special rate (answer in plain) " + r.text[:200])
CT_ID = r.json()["id"]
D = A.post(B + O + "/docs", json={"project_title": "Imagefilm", "client_id": CL, "contract_id": CT_ID}).json()["id"]
r = A.put(B + O + f"/docs/{D}/items", json={"items": [{"kind": "service", "service_id": SV, "title": "Schnitt", "qty": 2, "rate": 700, "cost": 321.5}]})
check(r.ok, "positions with a purchase price " + r.text[:200])

# the database holds only ciphertext
co = dbx("SELECT * FROM office_company WHERE org_id=?", (ORG,))[0]
check(all(enc(co[k]) for k in ("tax_number", "vat_id", "iban", "bic", "bank_name")), "office_company: bank / tax fields encrypted")
check(co["name"] == FIELDS["name"] and co["city"] == "Hamburg", "office_company: name / address stay plain")
st = json.loads(one("SELECT data FROM office_settings WHERE org_id=?", (ORG,)))
check(enc(st.get("company")) and st.get("pack") == "DE", "office_settings: the company lines encrypted, the rest plain")
check(enc(one("SELECT rates FROM office_contracts WHERE id=?", (CT_ID,))), "office_contracts.rates encrypted")
it = dbx("SELECT cost, cost_enc FROM office_doc_items WHERE doc_id=?", (D,))[0]
check(float(it["cost"]) == 0 and enc(it["cost_enc"]), f"office_doc_items: cost 0 + cost_enc ({it['cost']})")
tot = json.loads(one("SELECT totals FROM office_docs WHERE id=?", (D,)))
check(enc(tot.get("costs")) and enc(tot.get("margin")) and tot.get("net") in (1400, "1400.00", 1400.0), f"totals: costs / margin encrypted, net plain ({tot.get('net')})")
logs = [r["detail"] for r in dbx("SELECT detail FROM office_doc_log WHERE org_id=?", (ORG,))]
check(not any(TEST_IBAN in d or "321.5" in d for d in logs), "office log: no IBAN / purchase price in plain")
check(any(enc(d) for d in logs), "office log: entries with protected values encrypted")

# ... and the API in plain
j = A.get(B + O + "/settings").json()
check(j["company_fields"]["iban"] == TEST_IBAN and j["company_fields"]["vat_id"] == "DE999999999", "API: company fields in plain")
check(j["settings"]["company"].get("bank_lines") == ["IBAN DE89 3704 0044 0532 0130 00"], "API: the free company lines in plain")
check(A.get(B + O + "/contracts").json()["items"][0]["rates"] == {str(SV): 700.0}, "API: contract rates in plain")
d = A.get(B + O + f"/docs/{D}").json()
check([x["cost"] for x in d["items"]] == [321.5] and d["totals"].get("costs") in (643, "643.00", 643.0), f"API admin: purchase price + costs ({d['totals'].get('costs')})")
d = Bo.get(B + O + f"/docs/{D}").json()
# 2.47.0 (#1649): the member gets no purchase field at all (was None)
check(all("cost" not in x and "margin" not in x for x in d["items"]) and "costs" not in d["totals"], "API member: no purchase prices (unchanged rule)")
lg = A.get(B + O + "/log").json()["log"]
check(any("321.5" in json.dumps(x["detail"]) for x in lg), "API office log: the change of the purchase price readable")

# ---------------------------------------------------------------- finalised invoice: sender + stored files
I = A.post(B + O + f"/docs/{D}/invoice", json={}).json()["id"]
A.patch(B + O + f"/docs/{I}", json={"service_from": "2026-10-01", "service_to": "2026-10-10"})
r = A.post(B + O + f"/docs/{I}/finalize")
check(r.ok, "invoice finalised " + r.text[:200])
check(enc(one("SELECT sender FROM office_docs WHERE id=?", (I,))), "office_docs.sender (frozen company with bank data) encrypted")
fs = office_files(ORG)
check(len(fs) == 2 and all(head(p) == b"KENC1\n" for p in fs), f"stored invoice PDF + XML sealed on disk {[os.path.basename(p) for p in fs]}")
pdf = A.get(B + O + f"/docs/{I}/pdf")
check(pdf.ok and pdf.content[:5] == b"%PDF-", "PDF download = the original PDF")
import hashlib
check(hashlib.sha256(pdf.content).hexdigest() == one("SELECT pdf_sha256 FROM office_docs WHERE id=?", (I,)), "PDF download: same SHA-256 as recorded at finalising")
x = A.get(B + O + f"/docs/{I}/xml")
check(x.ok and x.content.startswith(b"<?xml") and hashlib.sha256(x.content).hexdigest() == one("SELECT xml_sha256 FROM office_docs WHERE id=?", (I,)), "XML download = the original")
rd = A.get(B + O + f"/docs/{I}/render").json()
check(any("DE89" in ln for ln in rd["company"]["bank_lines"]), "print model of the finalised invoice: bank line from the encrypted snapshot")

# ---------------------------------------------------------------- attachments
L = A.post(B + "/api/lists", json={"name": "Projekt Nordlicht", "org_id": ORG}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Schnittplan", "list_id": L}).json()["id"]
BODY = b"Schnittplan Version 3\n" * 50
r = A.post(B + f"/api/tasks/{T}/attachments", files={"file": ("plan.txt", BODY, "text/plain")})
check(r.ok, "attachment upload " + r.text[:200])
AID = one("SELECT id FROM attachments WHERE task_id=?", (T,))
path = os.path.join(DATA, "attachments", one("SELECT path FROM attachments WHERE id=?", (AID,)))
check(head(path) == b"KENC1\n" and one("SELECT size FROM attachments WHERE id=?", (AID,)) == len(BODY), "attachment of an organisation's list sealed, size = the plain size")
r = A.get(B + f"/api/attachments/{AID}")
check(r.ok and r.content == BODY, "attachment download = the original")
r = A.get(B + f"/api/attachments/{AID}", headers={"Range": "bytes=0-5"})
check(r.status_code in (200, 206) and r.content == BODY[:len(r.content)], "range request on a sealed file answers the plain bytes")
tk = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "attachments:read"]}).json().get("token", "")
r = requests.get(B + f"/api/v1/attachments/{AID}/text", headers={"Authorization": "Bearer " + tk})
check(r.ok and "Schnittplan Version 3" in r.json().get("text", ""), "attachment text (API) from the sealed file " + r.text[:120])
PL = A.post(B + "/api/lists", json={"name": "Privat", "org_id": None}).json()["id"]
PT = A.post(B + "/api/tasks", json={"title": "privat", "list_id": PL}).json()["id"]
A.post(B + f"/api/tasks/{PT}/attachments", files={"file": ("p.txt", b"private file", "text/plain")})
pp = os.path.join(DATA, "attachments", one("SELECT path FROM attachments WHERE task_id=?", (PT,)))
# 2.64.0 (#1864): a private list's file is sealed with the owner's account key now (was: stays plain)
PA0 = one("SELECT id FROM attachments WHERE task_id=?", (PT,))
check(space(pp) == -ALICE and A.get(B + f"/api/attachments/{PA0}").content == b"private file",
      f"attachment of a private list sealed with the owner's account key ({space(pp)})")
sc = A.get(B + "/api/admin/storage-check").json()
check(not sc["problems"], f"storage check: sealed files count with their plain size {sc['problems']}")

# ---------------------------------------------------------------- Settings > Organisation > Encryption
st = A.get(B + f"/api/orgs/{ORG}/encryption").json()
check(st["enabled"] and st["active"] and st["has_key"] and st["key_ok"] and st["password"], f"state for the organisation admin {st}")
check(Bo.get(B + f"/api/orgs/{ORG}/encryption").status_code == 403, "state: member 403")
check(Ca.get(B + f"/api/orgs/{ORG}/encryption").status_code == 404, "state: other organisation 404")
check(requests.get(B + f"/api/orgs/{ORG}/encryption", headers=AGH).status_code in (401, 403), "state: agent refused")
check(A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "wrong-one"}).status_code == 403, "recovery key: wrong password 403")
check(Bo.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).status_code == 403, "recovery key: member 403")
check(Ca.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).status_code == 404, "recovery key: other organisation 404")
r = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"})
RK = r.json().get("recovery_key", "") if r.ok else ""
# 2.138.0 (#1972): "R2-" + 13 groups (the recovery secret that wraps the organisation key, no longer the key itself)
check(r.ok and RK.startswith("R2-") and len(RK.replace("-", "")) == 54 and RK.count("-") == 13 and r.headers.get("Cache-Control") == "no-store", "recovery key: R2- + 13 groups of base32, not cached")
lg = A.get(B + O + "/log").json()["log"]
check(any(x["action"] == "recovery_key" for x in lg) and RK not in json.dumps(lg), "recovery key: shown -> office log entry without the value")
check(one("SELECT recovery_shown_at FROM org_keys WHERE org_id=?", (ORG,)) is not None, "recovery key: recovery_shown_at noted")
check(RK.replace("-", "") not in json.dumps(dbx("SELECT * FROM office_doc_log")), "recovery key never in the office log table")

# ---------------------------------------------------------------- the instance switch
check(Bo.get(B + "/api/admin/orgcrypt").status_code == 403 and Bo.put(B + "/api/admin/orgcrypt", json={"org_encrypt": False}).status_code == 403, "switch: admin only")
r = A.put(B + "/api/admin/orgcrypt", json={"org_encrypt": False})
check(r.ok and r.json() == {"enabled": True, "org_encrypt": False}, "switch off " + r.text[:100])
A.put(B + O + "/settings", json={"company_fields": {"bic": "BYLADEM1001"}})
check(one("SELECT bic FROM office_company WHERE org_id=?", (ORG,)) == "BYLADEM1001", "switched off: a new value is stored plain")
check(enc(one("SELECT rates FROM office_contracts WHERE id=?", (CT_ID,))) and A.get(B + O + "/contracts").json()["items"][0]["rates"] == {str(SV): 700.0}
      and A.get(B + O + "/settings").json()["company_fields"]["iban"] == TEST_IBAN, "switched off: encrypted values stay and stay readable")
r = A.put(B + "/api/admin/orgcrypt", json={"org_encrypt": True})
check(r.ok and r.json()["org_encrypt"] is True, "switch on again")
for _ in range(40):
    if enc(one("SELECT bic FROM office_company WHERE org_id=?", (ORG,))):
        break
    time.sleep(0.25)
check(enc(one("SELECT bic FROM office_company WHERE org_id=?", (ORG,))), "switched on: the background pass encrypts what was stored plain")

# ---------------------------------------------------------------- command line: status, decrypt-all, encrypt-all
rc, out, err_ = cli("status")
try:
    stj = json.loads(out[out.index("{"):])
except ValueError:
    stj = {}
o1 = next((o for o in stj.get("orgs", []) if o["org"] == ORG), {})
check(rc == 0 and stj.get("server_key") is True and o1.get("fields", {}).get("plain") == 0 and o1.get("fields", {}).get("enc", 0) >= 8
      and o1.get("files", {}).get("enc", 0) >= 3 and o1.get("files", {}).get("plain") == 0, f"cli status: everything of the organisation encrypted {o1} {err_[-300:]}")
check(KEY not in out and RK not in out, "cli status: no key in the output")
rc, out, err_ = cli("decrypt-all")
check(rc == 0 and '"failed": 0' in out and "still encrypted: 0" in out, f"cli decrypt-all {out[-300:]} {err_[-300:]}")
check(one("SELECT iban FROM office_company WHERE org_id=?", (ORG,)) == TEST_IBAN and one("SELECT value FROM settings WHERE key='org_encrypt'") == "0",
      "decrypt-all: fields plain, org_encrypt=0")
it = dbx("SELECT cost, cost_enc FROM office_doc_items WHERE doc_id=?", (D,))[0]
check(float(it["cost"]) == 321.5 and it["cost_enc"] is None, "decrypt-all: purchase price back in cost, cost_enc empty")
check(not enc(one("SELECT sender FROM office_docs WHERE id=?", (I,))) and not enc(json.loads(one("SELECT totals FROM office_docs WHERE id=?", (D,))).get("costs")),
      "decrypt-all: sender + totals plain")
check(head(path) == BODY[:6] and all(head(p) in (b"%PDF-1", b"<?xml ") for p in office_files(ORG)), "decrypt-all: files plain on disk")
check(A.get(B + f"/api/attachments/{AID}").content == BODY and A.get(B + O + "/settings").json()["company_fields"]["iban"] == TEST_IBAN, "decrypt-all: API unchanged")
rc, out, err_ = cli("encrypt-all")
check(rc == 0 and enc(one("SELECT iban FROM office_company WHERE org_id=?", (ORG,))) and head(path) == b"KENC1\n"
      and one("SELECT value FROM settings WHERE key='org_encrypt'") == "1", f"cli encrypt-all {out[-200:]}")

# ---------------------------------------------------------------- 2.42.0 review: a list moved into the organisation gets sealed now
PL = A.post(B + "/api/lists", json={"name": "Private-Liste", "org_id": None}).json()["id"]
if one("SELECT org_id FROM lists WHERE id=?", (PL,)) is not None:
    A.patch(B + f"/api/lists/{PL}", json={"org_id": None})
PT = A.post(B + "/api/tasks", json={"title": "p", "list_id": PL}).json()["id"]
A.post(B + f"/api/tasks/{PT}/attachments", files={"file": ("p.txt", b"private file content", "text/plain")})
pp = os.path.join(DATA, "attachments", one("SELECT path FROM attachments WHERE task_id=?", (PT,)))
# 2.64.0 (#1864): private = sealed with the account key (was: plain)
check(one("SELECT org_id FROM lists WHERE id=?", (PL,)) is None and space(pp) == -ALICE, "private list: its file is sealed with the account key")
r = A.patch(B + f"/api/lists/{PL}", json={"org_id": ORG})
check(r.ok and one("SELECT org_id FROM lists WHERE id=?", (PL,)) == ORG, "private list moved into the organisation " + r.text[:150])
wait_space(pp, ORG)  # 2.64.0 (#1864): resealed from the account key to the organisation's key
check(space(pp) == ORG and A.get(B + f"/api/attachments/{one('SELECT id FROM attachments WHERE task_id=?', (PT,))}").content == b"private file content",
      "moved into the organisation: the file is sealed without a restart and still readable")

# ---------------------------------------------------------------- a wrong server key, then rewrap with the recovery key
start(key=KEY2, keep=True)
A = sess("alice")
r = A.get(B + O + "/settings")
check(r.status_code == 500 and r.json().get("code") == "orgcrypt" and "KALMIDO_SECRET_KEY" in r.json().get("error", "") and TEST_IBAN not in r.text,
      "wrong server key: clear error instead of garbage " + r.text[:200])
check(A.get(B + f"/api/orgs/{ORG}/encryption").json().get("key_ok") is False, "wrong server key: the state says key_ok false")
rc, out, err_ = cli("rewrap", "--org", str(ORG), "--recovery-file", "-", stdin="not a key\n")
check(rc == 2 and "not a recovery key" in out, "rewrap: a wrong recovery key is refused")
# 2.42.0 review: a typo in the recovery key (still 32 valid bytes) is tested on the organisation's data first -> exit 1, nothing changed
row0 = tuple(dbx("SELECT wrapped, kek_check FROM org_keys WHERE org_id=?", (ORG,))[0])
WRONG = RK[:3] + ("B" if RK[3] != "B" else "C") + RK[4:]  # 2.138.0 (#1972): a typo after "R2-"
rc, out, err_ = cli("rewrap", "--org", str(ORG), "--recovery-file", "-", stdin=WRONG + "\n")
check(rc == 1 and "nothing changed" in out and WRONG not in out, f"rewrap: a mistyped recovery key is refused {out[-200:]}")
check(tuple(dbx("SELECT wrapped, kek_check FROM org_keys WHERE org_id=?", (ORG,))[0]) == row0, "rewrap: a refused key leaves the key row unchanged")
rc, out, err_ = cli("rewrap", "--org", str(ORG), "--recovery-file", "-", stdin=RK + "\n")
check(rc == 0 and "stored with the current server key" in out and RK not in out, f"rewrap from stdin {out[-200:]} {err_[-200:]}")
row1 = tuple(dbx("SELECT wrapped, kek_check, wrapped_prev, kek_check_prev FROM org_keys WHERE org_id=?", (ORG,))[0])
check(row1[2] == row0[0] and row1[3] == row0[1] and row1[0] != row0[0],
      "rewrap: the replaced wrapped key is kept in wrapped_prev")
check(A.get(B + O + "/settings").json().get("company_fields", {}).get("iban") == TEST_IBAN and A.get(B + f"/api/attachments/{AID}").content == BODY,
      "after rewrap: fields and files readable with the new server key")
# 2.64.0 (#1864): the account keys are rewrapped with the earlier server key (they have no recovery key)
rc, out, err_ = cli("rewrap-accounts", "--old-key-file", "-", stdin=KEY + "\n")
check(rc == 0 and '"rewrapped": ' in out and KEY not in out and KEY not in err_, f"rewrap-accounts from stdin {out[-200:]} {err_[-200:]}")
r = A.get(B + f"/api/attachments/{PA0}")
check(r.status_code == 200 and r.content == b"private file",
      "after rewrap-accounts: a file sealed with an account key readable again")

# ---------------------------------------------------------------- deleting an organisation destroys its key
OG = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{OG}"})
A.put(B + O + "/settings", json={"company_fields": {"name": "Gamma Studio", "iban": TEST_IBAN}})
GL = A.post(B + "/api/lists", json={"name": "Gamma-Liste", "org_id": OG}).json()["id"]
GT = A.post(B + "/api/tasks", json={"title": "g", "list_id": GL}).json()["id"]
A.post(B + f"/api/tasks/{GT}/attachments", files={"file": ("g.txt", b"gamma file content", "text/plain")})
GA = one("SELECT id FROM attachments WHERE task_id=?", (GT,))
gp = os.path.join(DATA, "attachments", one("SELECT path FROM attachments WHERE id=?", (GA,)))
check(head(gp) == b"KENC1\n" and one("SELECT COUNT(*) FROM org_keys WHERE org_id=?", (OG,)) == 1, "Gamma: key made, file sealed")
r = A.patch(B + f"/api/lists/{GL}", json={"org_id": None})
check(r.ok and one("SELECT org_id FROM lists WHERE id=?", (GL,)) is None, "Gamma's list moved to private " + r.text[:150])
check(A.get(B + f"/api/attachments/{GA}").content == b"gamma file content", "moved list: the file sealed with Gamma's key stays readable")
os.makedirs(os.path.join(DATA, "office", str(OG)), exist_ok=True)
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.delete(B + f"/api/admin/orgs/{OG}")
check(r.ok, "organisation deleted " + r.text[:150])
check(one("SELECT COUNT(*) FROM org_keys WHERE org_id=?", (OG,)) == 0, "deleted organisation: its key row is gone")
check(not os.path.exists(os.path.join(DATA, "office", str(OG))), "deleted organisation: its office folder is gone")
# 2.64.0 (#1864): resealed with the owner's account key (was: plain)
check(wait_space(gp, -ALICE, 10) and A.get(B + f"/api/attachments/{GA}").content == b"gamma file content",
      f"the moved list's file was resealed (account key of the owner, private list) before ({space(gp)})")
check(A.get(B + O + "/settings").json()["company_fields"]["iban"] == TEST_IBAN, "the other organisation is untouched")

# ---------------------------------------------------------------- agents see what they saw before (no change of rights)
check(requests.get(B + "/api/office/settings", headers=AGH).status_code == 403, "agents: the office stays closed to them (unchanged)")

# ---------------------------------------------------------------- without KALMIDO_SECRET_KEY: everything as before
start(key=None)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ME = A.get(B + "/api/state").json()["me"]["id"]
O3 = A.post(B + "/api/admin/orgs", json={"name": "Delta", "admin_id": ME}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{O3}"})
A.put(B + O + "/settings", json={"company_fields": {"name": "Delta GmbH", "iban": TEST_IBAN}})
check(one("SELECT iban FROM office_company WHERE org_id=?", (O3,)) == TEST_IBAN, "without a server key: fields plain")
L3 = A.post(B + "/api/lists", json={"name": "D", "org_id": O3}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"title": "d", "list_id": L3}).json()["id"]
A.post(B + f"/api/tasks/{T3}/attachments", files={"file": ("d.txt", b"delta file", "text/plain")})
check(head(os.path.join(DATA, "attachments", one("SELECT path FROM attachments WHERE task_id=?", (T3,)))) == b"delta ", "without a server key: files plain")
st = A.get(B + f"/api/orgs/{O3}/encryption").json()
check(st["enabled"] is False and st["active"] is False and not st["has_key"], f"without a server key: the state says off {st}")
check(A.post(B + f"/api/orgs/{O3}/encryption/recovery", json={"password": "password123"}).status_code == 409, "without a server key: no recovery key (409)")
check(one("SELECT COUNT(*) FROM org_keys") == 0, "without a server key: no key rows")
# 2.64.0 (#1864): without a server key a private list's file stays plain and no account key is made
PL3 = A.post(B + "/api/lists", json={"name": "P", "org_id": None}).json()["id"]
if one("SELECT org_id FROM lists WHERE id=?", (PL3,)) is not None:
    A.patch(B + f"/api/lists/{PL3}", json={"org_id": None})
PT3 = A.post(B + "/api/tasks", json={"title": "p", "list_id": PL3}).json()["id"]
A.post(B + f"/api/tasks/{PT3}/attachments", files={"file": ("p.txt", b"plain private", "text/plain")})
p3 = os.path.join(DATA, "attachments", one("SELECT path FROM attachments WHERE task_id=?", (PT3,)))
check(head(p3) == b"plain " and one("SELECT COUNT(*) FROM user_keys") == 0, "without a server key: private files plain, no account keys")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
if FAILS:
    print("FAILED:", *FAILS, sep="\n  ")
    sys.exit(1)
