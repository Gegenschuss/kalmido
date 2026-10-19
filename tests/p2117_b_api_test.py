#!/usr/bin/env python3
"""2.117.0 API tests, part B: samples of the document templates (#2283) and PDF files of a framework contract (#2285).
Own container (start.sh, org encryption on). Invented companies, people and figures only.
tenant-matrix: office
freelancer-matrix: office
 - #2283: the samples list = the three contract samples + seven letters (cover letter, payment reminder, dunning letter,
   notice of termination, power of attorney, handover record, credit note cover letter) in German / English (the office's
   document language, ?lang= the other); each only uses known variables; "use sample" makes an own template in the current
   area (a fresh organisation and the personal office of a person without organisation); the preview of a document from
   a letter sample fills the client / company / today; legal samples are marked
 - #2285: upload (only PDF, magic %PDF-, size limit), list, open (the same bytes, a download), date change, replace (the old
   one into the trash), remove + restore (undo), the paper clip count in the contracts list, the file sealed at rest
   (0600); deleting the contract puts its files into the trash; the purge after 30 days removes row and file
 - rights: an organisation member with the office reads but cannot write (403); a member without the office module 403;
   an agent 403; another organisation 404 (its contract and file ids); a person without organisation (personal office)
   uses everything
usage: p2117_b_api_test.py <datadir>      (P2117B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import re
import subprocess
import sys
import time

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
TP = O + "/doc-templates"
GD = O + "/gen-docs"
VARS = {"client.name", "client.address", "client.contact", "project.title", "offer.number", "offer.date", "offer.total",
        "company.name", "company.address", "today"}
LETTERS = ["letter", "reminder", "dunning", "termination", "authority", "handover", "credit"]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def pdf(tag):
    return (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n% " + tag.encode()
            + b"\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def up(s, cid, data, name="Vertrag.pdf", **form):
    return s.post(B + f"{O}/contracts/{cid}/files", files={"file": (name, data, "application/pdf")}, data=form)


if os.environ.get("P2117B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("eve", "Eve Nooffice")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Ev = sess("bob"), sess("carol"), sess("eve")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Ev.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,clients,docs", "tour": "done"})  # no office
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
for em in ("bob@example.com", "eve@example.com"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": em, "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ev, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Beispiel Studio GmbH", "street": "Musterweg 1",
                                                                                   "zip": "12345", "city": "Musterstadt", "country": "DE"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Kundenweg 5", "zip": "20000", "city": "Beispielstadt", "country": "DE",
                                       "contact": "Erika Beispiel"}).json()["id"]

# ================================================================ #2283: samples
st = A.get(B + TP + "/starters").json()
keys = [x["key"] for x in st["starters"]]
check(keys == ["contract", "confirmation", "nda"] + LETTERS, f"#2283: ten samples in order {keys}")
check(st["lang"] == "de" and all(x["lang"] == "de" and x["name"] and x["body"] for x in st["starters"]), "#2283: German in a German office")
names = {x["key"]: x["name"] for x in st["starters"]}
check(names["reminder"] == "Zahlungserinnerung" and names["dunning"] == "Mahnung" and names["authority"] == "Vollmacht"
      and names["handover"] == "Übergabeprotokoll" and names["credit"] == "Gutschrift-Anschreiben" and names["termination"] == "Kündigung",
      f"#2283: German names {names}")
ste = A.get(B + TP + "/starters?lang=en").json()
check(ste["lang"] == "en" and {x["key"]: x["name"] for x in ste["starters"]}["handover"] == "Handover record", "#2283: English samples")
for s_ in st["starters"] + ste["starters"]:
    used = set(re.findall(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}", s_["body"]))
    check(used and used <= VARS, f"#2283: {s_['key']}/{s_['lang']} uses known variables only {used - VARS}")
    check(s_["body"].startswith("# "), f"#2283: {s_['key']}/{s_['lang']} starts with its heading")
leg = {x["key"]: x["legal"] for x in st["starters"]}
check(leg["dunning"] and leg["termination"] and leg["authority"] and leg["contract"] and not leg["letter"] and not leg["reminder"],
      f"#2283: legal samples marked {leg}")
check(st["note"], "#2283: the note: sample text, no legal advice")
r = A.post(B + TP, json={"starter": "reminder"})
check(r.status_code == 201 and r.json()["name"] == "Zahlungserinnerung" and r.json()["kind"] == "other" and r.json()["sign"] == 0
      and r.json()["lang"] == "de", "#2283: use sample: an own template " + r.text[:200])
TR = r.json()["id"]
check(A.patch(B + f"{TP}/{TR}", json={"name": "Erinnerung kurz", "body": "# Erinnerung\n\nHallo {{client.name}}"}).ok, "#2283: the template is freely editable")
check(len([x for x in A.get(B + TP + "/starters").json()["starters"] if x["key"] == "reminder"]) == 1, "#2283: the sample itself stays unchanged")
r = A.post(B + TP, json={"starter": "handover", "lang": "en"})
check(r.status_code == 201 and r.json()["name"] == "Handover record" and r.json()["sign"] == 1, "#2283: handover (signable) in English")
TH = r.json()["id"]
check(A.post(B + TP, json={"starter": "film_release"}).status_code == 400, "#2283: an unknown sample 400")
check(A.post(B + TP, json={"starter": ["letter"]}).status_code == 400, "#2283: a sample key not a string 400")
r = A.post(B + GD, json={"template_id": TH, "client_id": CL})
check(r.status_code == 201, "#2283: a document from the handover sample " + r.text[:200])
GH = r.json()["id"]
pv = A.post(B + GD + "/preview", json={"gen_doc_id": GH}).json()
txt = pv.get("text") or ""
check("Kunde Eins GmbH" in txt and "Beispiel Studio GmbH" in txt and "Erika Beispiel" in txt and "{{client.name}}" not in txt,
      "#2283: the preview fills client / company / contact " + txt[:300])
check(A.get(B + f"{GD}/{GH}/pdf").content[:5] == b"%PDF-", "#2283: the draft's PDF")
for s in (Bo, Ev):
    check(s.get(B + TP + "/starters").status_code == 403 and s.post(B + TP, json={"starter": "letter"}).status_code == 403,
          "#2283: member / member without office: no samples")
check(requests.get(B + TP + "/starters", headers=AGH).status_code == 403, "#2283: agent 403")
# a fresh organisation (its admin had no template before)
r = Ca.post(B + TP, json={"starter": "letter", "lang": "en"})
check(r.status_code == 201 and r.json()["name"] == "Cover letter" and Ca.get(B + TP).json()["templates"][0]["id"] == r.json()["id"],
      "#2283: a fresh organisation takes over a sample")
check(A.get(B + f"{TP}").json()["templates"] and all(t["id"] != r.json()["id"] for t in A.get(B + TP).json()["templates"]),
      "#2283: the other organisation does not see it")

# ================================================================ #2285: PDF files of a framework contract
C1 = A.post(B + O + "/contracts", json={"name": "Rahmenvertrag Kunde Eins", "client_id": CL}).json()["id"]
C2 = Ca.post(B + O + "/contracts", json={"name": "Fremdvertrag"}).json()["id"]
F = O + f"/contracts/{C1}/files"
check(A.get(B + F).json()["items"] == [], "#2285: no files yet")
P1, P2, P3 = pdf("vertrag"), pdf("nachtrag"), pdf("neu")
r = up(A, C1, P1, "Vertrag unterschrieben.pdf")
check(r.status_code == 201 and r.json()["name"] == "Vertrag unterschrieben.pdf" and r.json()["size"] == len(P1)
      and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r.json()["date"]), "#2285: upload " + r.text[:200])
F1 = r.json()["id"]
r = up(A, C1, P2, "Nachtrag 1", date="2026-03-01")
check(r.status_code == 201 and r.json()["name"] == "Nachtrag 1.pdf" and r.json()["date"] == "2026-03-01", "#2285: an addendum with its date " + r.text[:200])
F2 = r.json()["id"]
check(up(A, C1, b"GIF89a not a pdf", "bild.pdf").status_code == 400, "#2285: not a PDF (magic) 400")
check(up(A, C1, b"%PDF-" + b"x" * (1024 * 1024 + 10)).status_code in (400, 413), "#2285: larger than the limit refused")
check(up(A, C1, P1, date="2026-13-40").status_code == 400, "#2285: bad date 400")
check(A.post(B + F, data={"date": "2026-01-01"}).status_code == 400, "#2285: no file 400")
items = A.get(B + F).json()["items"]
check([x["id"] for x in items] == [F2, F1], f"#2285: list sorted by date {items}")
r = A.get(B + f"{F}/{F1}")
cd = r.headers.get("Content-Disposition", "")
check(r.ok and r.content == P1 and r.headers.get("Content-Type", "").startswith("application/pdf") and cd.startswith("attachment; filename*=UTF-8''")
      and '"' not in cd, f"#2285: open = the same bytes, a download {cd!r}")
fn = sql("SELECT file FROM office_contract_files WHERE id=?", (F1,))[0][0]
p = os.path.join(DATA, "office", str(ORG), fn)
try:
    raw = open(p, "rb").read()
    check(not raw.startswith(b"%PDF-") and b"vertrag" not in raw, "#2285: the file is sealed at rest")
    check(oct(os.stat(p).st_mode & 0o777) == "0o600", "#2285: file 0600")
except PermissionError:
    print("note: the office folder is not readable from the runner, sealing not checked here")
lst = A.get(B + O + "/contracts").json()["items"]
check([x.get("files") for x in lst if x["id"] == C1] == [2], f"#2285: the contracts list counts the files {lst}")
# date change, replace, remove + restore
r = A.patch(B + f"{F}/{F1}", json={"date": "2026-02-15"})
check(r.ok and r.json()["date"] == "2026-02-15", "#2285: the date changed")
check(A.patch(B + f"{F}/{F1}", json={"date": "gestern"}).status_code == 400, "#2285: a bad date 400")
r = up(A, C1, P3, "Vertrag neu.pdf", replace=str(F1))
check(r.status_code == 201 and r.json()["replaced"] == F1 and r.json()["date"] == "2026-02-15", "#2285: replace keeps the date " + r.text[:200])
F3 = r.json()["id"]
check(sorted(x["id"] for x in A.get(B + F).json()["items"]) == sorted([F2, F3]) and A.get(B + f"{F}/{F1}").status_code == 404,
      "#2285: the replaced one is gone from the list")
check(A.post(B + f"{F}/{F1}/restore").ok and A.get(B + f"{F}/{F1}").content == P1, "#2285: undo of replace: the old one is back")
check(A.delete(B + f"{F}/{F1}").ok and A.get(B + f"{F}/{F1}").status_code == 404, "#2285: remove")
check(A.post(B + f"{F}/{F1}/restore").ok and len(A.get(B + F).json()["items"]) == 3, "#2285: restore (undo)")
check(A.delete(B + f"{F}/{F1}").ok, "#2285: removed again")
check(A.post(B + f"{F}/999999/restore").status_code == 404, "#2285: restore of an unknown file 404")
# rights
check(Bo.get(B + F).ok and Bo.get(B + f"{F}/{F2}").content == P2, "#2285: a member of the office reads the files")
check(up(Bo, C1, P1).status_code == 403 and Bo.delete(B + f"{F}/{F2}").status_code == 403
      and Bo.patch(B + f"{F}/{F2}", json={"date": "2026-01-01"}).status_code == 403 and Bo.post(B + f"{F}/{F1}/restore").status_code == 403,
      "#2285: a member cannot write")
check(Ev.get(B + F).status_code == 403 and Ev.get(B + f"{F}/{F2}").status_code == 403, "#2285: a member without the office module 403")
check(requests.get(B + F, headers=AGH).status_code == 403 and requests.get(B + f"{F}/{F2}", headers=AGH).status_code == 403,
      "#2285: agent 403")
# tenant-matrix: office -- another organisation's contract / file = 404
check(Ca.get(B + F).status_code == 404 and Ca.get(B + f"{F}/{F2}").status_code == 404 and up(Ca, C1, P1).status_code == 404
      and Ca.delete(B + f"{F}/{F2}").status_code == 404, "#2285: another organisation 404")
check(A.get(B + O + f"/contracts/{C2}/files").status_code == 404 and up(A, C2, P1).status_code == 404, "#2285: the other organisation's contract 404")
r = up(Ca, C2, pdf("fremd"))
check(r.status_code == 201, "#2285: carol attaches to her own contract")
check(A.get(B + O + f"/contracts/{C1}/files/{r.json()['id']}").status_code == 404, "#2285: a file id of another contract 404")
# deleting the contract: the files go into the trash, the purge removes row and file
check(A.delete(B + O + f"/contracts/{C1}").json().get("result") == "deleted", "#2285: contract deleted")
rows = sql("SELECT id, deleted_at FROM office_contract_files WHERE contract_id=?", (C1,))
check(len(rows) == 3 and all(x[1] for x in rows), f"#2285: its files are in the trash {rows}")
check(A.get(B + F).status_code == 404, "#2285: the deleted contract's files 404")
sql("UPDATE office_contract_files SET deleted_at='2020-01-01T00:00:00Z' WHERE contract_id=?", (C1,), write=True)
A.get(B + O + "/contracts")
check(sql("SELECT COUNT(*) FROM office_contract_files WHERE contract_id=?", (C1,))[0][0] == 0, "#2285: purged after the trash period")
try:
    check(not os.path.exists(p), "#2285: the stored file is deleted for good")
except PermissionError:
    pass
check(sql("SELECT COUNT(*) FROM office_contract_files WHERE contract_id=?", (C2,))[0][0] == 1, "#2285: the other organisation's file stays")

# ================================================================ a person without organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
st = Fr.get(B + TP + "/starters").json()
check(len(st["starters"]) == 10, "freelancer: the samples in the personal office")
r = Fr.post(B + TP, json={"starter": "credit"})
check(r.status_code == 201 and r.json()["kind"] == "other", "freelancer: use sample " + r.text[:200])
check([t["id"] for t in Fr.get(B + TP).json()["templates"]] == [r.json()["id"]], "freelancer: only the own template")
CF = Fr.post(B + O + "/contracts", json={"name": "Rahmenvertrag privat"}).json()["id"]
r = up(Fr, CF, pdf("privat"), "privat.pdf")
check(r.status_code == 201, "freelancer: upload " + r.text[:200])
FF = r.json()["id"]
FFU = O + f"/contracts/{CF}/files"
check(Fr.get(B + FFU).json()["items"][0]["id"] == FF and Fr.get(B + f"{FFU}/{FF}").content == pdf("privat"), "freelancer: list and open")
check(Fr.patch(B + f"{FFU}/{FF}", json={"date": "2026-05-05"}).ok, "freelancer: date")
r = up(Fr, CF, pdf("privat2"), replace=str(FF))
check(r.status_code == 201, "freelancer: replace")
check(Fr.delete(B + f"{FFU}/{r.json()['id']}").ok and Fr.post(B + f"{FFU}/{r.json()['id']}/restore").ok, "freelancer: remove + restore")
check(A.get(B + FFU).status_code == 404 and A.get(B + f"{FFU}/{FF}").status_code == 404, "freelancer: the organisation's admin does not reach it")
check(Fr.get(B + O + f"/contracts/{C2}/files").status_code == 404, "freelancer: an organisation's contract 404")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
