#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.356.0 A (#2926): the office moves completely. Invented companies, people and figures only.
freelancer-matrix: office
tenant-matrix: office
 - a person without an organisation (cash book entry with a receipt from the own documents) takes the whole personal office
   into an organisation: the receipt moves into the organisation's documents, a colleague there opens it (it stayed private
   and closed to the organisation before)
 - the way back, organisation -> personal office (POST /api/office/move-space what office): only the admin of the
   organisation's office (a member 403, an agent 403, another workspace than the own personal office 400); the preview names
   what moves and what stays; only what the person created moves (the drafts of a colleague stay), an issued invoice stays
   (retention) with a read-only copy in the personal archive, a client the organisation still uses stays active there and
   is created anew; the undo puts everything back
 - per new area of move-space (2.356.0 A): there and back, somebody else's office 404
usage: p2356_a_move_test.py <datadir>      (P2356A_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import base64
import os
import sys

import requests

import kt
from kt import B, H, check, sess, until
from freelancer_fixture import freelancer, org_join

O = "/api/office"
D = O + "/docs"
CBS = O + "/cashbooks"
MS = O + "/move-space"
KEY = base64.b64encode(os.urandom(32)).decode()
FEAT = "cal,comments,collab,office,clients,docs,files"


def sql(q, args=()):
    return kt.dbx(q, args)


def ws(s, v):
    r = s.patch(B + "/api/settings", json={"workspace": v})
    assert r.ok, r.text


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def company(s, name):
    r = s.put(B + O + "/settings", json={"company_fields": {"name": name, "street": "Teststraße 1", "zip": "20000", "city": "Hamburg",
                                                            "country": "DE", "tax_number": "12/345/67890", "iban": "DE02120300000000202051",
                                                            "bic": "BYLADEM1001"}})
    assert r.ok, r.text


def draft(s, client, title, kind="offer"):
    r = s.post(B + D, json={"kind": kind, "client_id": client, "project_title": title, "service_from": "2026-03-01",
                            "service_to": "2026-03-02", "items": [{"title": "Dreh", "qty": 1, "rate": 500}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def move(s, what, ids, to, **kw):
    r = s.post(B + MS, json={"what": what, "ids": ids, "to": to, **kw})
    if r.status_code >= 500:  # the server's traceback into the suite's log
        import subprocess
        x = subprocess.run(["docker", "logs", "--tail", "300", kt.CT], capture_output=True, text=True).stderr
        for ln in x[x.rfind("Traceback"):].splitlines()[:80]:
            if "^^^" not in ln and "site-packages" not in ln:
                print("server log: " + ln, flush=True)
    return r


kt.fresh(env={"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2356A")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], **H}

# ================================================================ 1. the cash book receipts go along into the organisation
FID, Fr = freelancer(B, A)
ws(Fr, "private")
company(Fr, "Frida Film")
r = Fr.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("kasse-beleg.pdf", tiny_pdf("Beleg Kasse"), "application/pdf")})
assert r.status_code == 201, r.text
RC = r.json()["ids"][0]
until(lambda: (lambda j: j.get("state") in ("done", "failed", "none", "skip", "") and j)(Fr.get(B + f"/api/docs/{RC}").json()), 90)
BK = Fr.get(B + CBS).json()["books"][0]["id"]
assert Fr.patch(B + f"{CBS}/{BK}", json={"opening": "100", "opening_day": "2026-01-01"}).ok
r = Fr.post(B + f"{CBS}/{BK}/entries", json={"day": "2026-03-03", "dir": "out", "amount": "11.90", "text": "Material bar", "vat_pct": "19", "node_id": RC})
check(r.status_code == 201, "personal office: a cash entry with a receipt " + r.text[:200])
CE = r.json()["id"]
CLP = Fr.post(B + "/api/clients", json={"name": "Kunde Nord GmbH", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]
draft(Fr, CLP, "Imagefilm")
KAP = A.post(B + "/api/admin/orgs", json={"name": "Kappa", "admin_id": FID}).json()["id"]
assert Fr.put(B + f"/api/orgs/{KAP}/members", json={"email": "bob@example.com", "role": "admin"}).ok and org_join(B, "bob", KAP)
ws(Fr, "private")
j = Fr.get(B + O + f"/move/check?org={KAP}").json()
check(j.get("ok") is True and any("receipt" in n and "organisation's documents" in n for n in j.get("notes") or []),
      f"preview: the receipt goes into the organisation's documents {j.get('notes')} {j.get('conflicts')}")
check(not any("only you can open" in n for n in j.get("notes") or []), "preview: no more 'only you can open it'")
r = Fr.post(B + O + "/move/org", json={"org": KAP, "confirm": True})
check(r.ok, "the transfer " + r.text[:300])
m = sql("SELECT ws FROM doc_meta WHERE node_id=?", (RC,))
n = sql("SELECT org_id FROM fs_nodes WHERE id=?", (RC,))
check(m and m[0][0] == f"o{KAP}" and n and n[0][0] == KAP, f"the receipt is a document of the organisation now {m} {n}")
r = Bo.get(B + f"/api/docs/{RC}/file")
check(r.ok and r.content[:5] == b"%PDF-", f"a colleague of the organisation opens the receipt {r.status_code}")
ws(Fr, f"org:{KAP}")
e = Fr.get(B + f"{CBS}/{BK}/entries?year=2026").json()["entries"]
x = next((x for x in e if x["id"] == CE), {})
check((x.get("node") or {}).get("id") == RC, f"the cash entry still shows its receipt {x.get('node')}")

# ================================================================ 2. the own part of an organisation's office -> personal office
# setup: Kappa has a client and drafts of Frida, a draft of Bob for Frida's client, an issued invoice of Frida, Bob's client
company(Fr, "Kappa Studio")
CLF = Fr.post(B + "/api/clients", json={"org_id": KAP, "name": "Studio Sued AG", "street": "Weg 2", "zip": "10000", "city": "Berlin", "country": "DE"}).json()["id"]
CLB = Bo.post(B + "/api/clients", json={"org_id": KAP, "name": "Bobs Kunde KG", "street": "Weg 3", "zip": "10000", "city": "Berlin", "country": "DE"}).json()["id"]
ws(Bo, f"org:{KAP}")
DF = draft(Fr, CLF, "Fridas Angebot")
DB = draft(Bo, CLF, "Bobs Angebot")
DBF = draft(Fr, CLB, "Frida fuer Bobs Kunden")
INVF = draft(Fr, CLF, "Fridas Rechnung", kind="invoice")
r = Fr.post(B + f"{D}/{INVF}/finalize")
check(r.ok, "setup: an issued invoice " + r.text[:200])
NUM = Fr.get(B + f"{D}/{INVF}").json()["number"]
TPL = Fr.post(B + O + "/doc-templates", json={"kind": "confirmation", "name": "Vorlage Frida", "body": "Hallo"})
TPL = TPL.json().get("id") if TPL.ok else None

# rights
r = move(Bo, "office", [KAP], "private", dry=1)
check(r.status_code == 200, "setup: Bob is an admin too " + r.text[:200])
assert Fr.put(B + f"/api/orgs/{KAP}/members", json={"email": "bob@example.com", "role": "member"}).ok
check(move(Bo, "office", [KAP], "private", dry=1).status_code == 403, "a member (no admin) of the organisation: 403")
check(requests.post(B + MS, headers=AGH, json={"what": "office", "ids": [KAP], "to": "private", "dry": 1}).status_code == 403, "an agent: 403")
FID2, Fi = freelancer(B, A, "fiona")
check(move(Fi, "office", [KAP], "private", dry=1).status_code == 404, "not a member of the organisation: 404")
LAM = A.post(B + "/api/admin/orgs", json={"name": "Lambda", "admin_id": FID}).json()["id"]
check(move(Fr, "office", [KAP], f"org:{LAM}", dry=1).status_code == 400, "into another organisation: 400 (only the own personal office)")
PB = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
check(move(Fr, "office", [PB], "private", dry=1).status_code in (404, 409), "the personal office itself: refused")

# preview
r = move(Fr, "office", [KAP], "private", dry=1, copy_issued=1)
j = r.json()
cnt = j.get("count") or {}
check(r.ok and not j.get("block"), "preview: movable " + r.text[:300])
# Frida's clients: the one that came with her personal office (with its quotation) and Studio Sued; her drafts: those two
# quotations + the one for Bob's client (it loses that client); Bob's draft and the issued invoice stay
check(cnt.get("clients") == 2 and cnt.get("drafts") == 3, f"preview: Frida's two clients and her three drafts {cnt}")
check(any("Only what you created" in n for n in j["notes"]), f"preview: says only the own part moves {j['notes']}")
check(any("issued document" in n for n in j["notes"]), "preview: the issued invoice stays")
check(any("Studio Sued AG" in n and "stays there" in n for n in j["notes"]), f"preview: the client used by the organisation stays there {j['notes']}")

# the move
r = move(Fr, "office", [KAP], "private", copy_issued=1)
check(r.ok and r.json().get("ok"), "the move " + r.text[:300])
MID = r.json().get("move_id")
st = {x[0]: (x[1], x[2]) for x in sql("SELECT id, org_id, number FROM office_docs WHERE id IN (?,?,?,?)", (DF, DB, DBF, INVF))}
check(st[DF][0] == PB and st[DBF][0] == PB, f"Frida's drafts are in her personal office {st}")
check(st[DB][0] == KAP, "Bob's draft stays in the organisation")
check(st[INVF][0] == KAP and st[INVF][1] == NUM, "the issued invoice stays with its number (retention)")
cl = sql("SELECT org_id, archived FROM clients WHERE id=?", (CLF,))[0]
check(cl[0] == KAP and cl[1] == 0, f"the client the organisation uses stays there, active {cl}")
check(sql("SELECT org_id FROM clients WHERE id=?", (CLB,))[0][0] == KAP, "Bob's client stays")
new = sql("SELECT id FROM clients WHERE org_id IS NULL AND created_by=? AND name='Studio Sued AG'", (FID,))
check(len(new) == 1, "the client is created anew in the personal office")
check(sql("SELECT client_id FROM office_docs WHERE id=?", (DF,))[0][0] == (new[0][0] if new else -1), "the moved draft points at the new client")
arch = sql("SELECT number, copy_of FROM office_archive WHERE org_id=? AND copy_of IS NOT NULL", (PB,))
check(len(arch) == 1 and arch[0][0] == "", f"a read-only copy of the issued invoice in the personal archive {arch}")
if TPL:
    check(sql("SELECT org_id FROM office_doc_templates WHERE id=?", (TPL,))[0][0] == PB, "the own template moved")
ws(Fr, "private")
r = Fr.get(B + f"{D}/{DF}")
check(r.ok, "the draft opens in the personal office " + r.text[:200])

# the undo
r = Fr.post(B + MS, json={"undo": MID})
check(r.ok, "the undo " + r.text[:300])
st = {x[0]: x[1] for x in sql("SELECT id, org_id FROM office_docs WHERE id IN (?,?)", (DF, DBF))}
check(st == {DF: KAP, DBF: KAP}, f"undo: the drafts are back in the organisation {st}")
check(sql("SELECT client_id FROM office_docs WHERE id=?", (DF,))[0][0] == CLF, "undo: the draft has its old client again")
check(not sql("SELECT 1 FROM office_archive WHERE org_id=? AND copy_of IS NOT NULL", (PB,)), "undo: the copy is gone")
if TPL:
    check(sql("SELECT org_id FROM office_doc_templates WHERE id=?", (TPL,))[0][0] == KAP, "undo: the template is back")
check(Fr.post(B + MS, json={"undo": MID}).status_code == 409, "a second undo: 409")

# ================================================================ 3. further areas: there (personal office -> Kappa) and back (undo)
ws(Fr, "private")
mk = {}
r = Fr.post(B + O + "/fixed-costs", json={"label": "Software Abo", "amount": "30", "vat_rate": 19, "repeat": "monthly", "start": "2026-02-01"})
mk["fixed"] = (r.json().get("id") if r.ok else None, "office_fixed_costs")
r = Fr.post(B + O + "/vehicles", json={"name": "Kombi", "plate": "HH-AB 1", "kind": "private", "odo_start": "1000"})
VID = r.json().get("id") if r.ok else None
mk["vehicles"] = (VID, "office_vehicles")
r = Fr.post(B + O + "/drives", json={"vehicle_id": VID, "day": "2026-02-10", "start_place": "Buero", "dest": "Kunde", "purpose": "Dreh", "km": 30, "kind": "business"})
DRV = r.json().get("id") if r.ok else None
check(VID and DRV, "setup: a vehicle with a drive " + r.text[:200])
r = Fr.post(B + O + "/texts", json={"kind": "rights_time", "key": "5y", "text_de": "Fuenf Jahre ab Abnahme.", "text_en": "Five years from acceptance."})
mk["texts"] = (r.json().get("id") if r.ok else None, "office_texts")
r = Fr.post(B + O + "/services", json={"name_de": "Schnitt", "daily_rate": 400})
mk["services"] = (r.json().get("id") if r.ok else None, "office_services")
r = Fr.post(B + O + "/equipment", json={"name": "Licht", "daily_rate": 80})
mk["equipment"] = (r.json().get("id") if r.ok else None, "office_equipment")
for what, (rid, t) in mk.items():
    if not rid:
        check(False, f"{what}: setup")
        continue
    check(move(Fi, what, [rid], "private", dry=1).status_code == 404, f"{what}: somebody else's office 404")
    r = move(Fr, what, [rid], f"org:{KAP}", dry=1)
    check(r.ok and not r.json().get("block") and (r.json().get("count") or {}).get("entries") == 1, f"{what}: preview " + r.text[:300])
    r = move(Fr, what, [rid], f"org:{KAP}")
    check(r.ok and r.json().get("ok"), f"{what}: the move " + r.text[:300])
    mid = r.json().get("move_id")
    check(sql(f"SELECT org_id FROM {t} WHERE id=?", (rid,))[0][0] == KAP, f"{what}: in the organisation with its id")
    if what == "vehicles":
        check(sql("SELECT org_id FROM office_drives WHERE id=?", (DRV,))[0][0] == KAP, "vehicles: the logbook went along")
        ws(Fr, f"org:{KAP}")
        dv = Fr.get(B + O + f"/drives?year=2026&vehicle_id={VID}")
        check(dv.ok and any(x.get("id") == DRV and x.get("dest") == "Kunde" for x in dv.json().get("drives") or []),
              "vehicles: the drive is readable in the organisation (sealed anew) " + dv.text[:200])
        ws(Fr, "private")
    r = Fr.post(B + MS, json={"undo": mid})
    check(r.ok, f"{what}: the undo " + r.text[:200])
    check(sql(f"SELECT org_id FROM {t} WHERE id=?", (rid,))[0][0] == PB, f"{what}: back in the personal office")
check(DRV and sql("SELECT org_id FROM office_drives WHERE id=?", (DRV,))[0][0] == PB, "vehicles: the logbook came back")
# a service an issued document of the personal office uses: copied, the original stays archived (the document is untouched)
CLX = Fr.post(B + "/api/clients", json={"name": "Kunde West", "street": "Weg 9", "zip": "40000", "city": "Essen", "country": "DE"}).json()["id"]
SV = mk["services"][0]
r = Fr.post(B + D, json={"kind": "invoice", "client_id": CLX, "service_from": "2026-03-01", "service_to": "2026-03-02",
                         "items": [{"title": "Schnitt", "qty": 1, "rate": 400, "service_id": SV}]})
INVX = r.json().get("id") if r.status_code == 201 else None
if INVX and Fr.post(B + f"{D}/{INVX}/finalize").ok and sql("SELECT 1 FROM office_doc_items WHERE doc_id=? AND service_id=?", (INVX, SV)):
    r = move(Fr, "services", [SV], f"org:{KAP}")
    check(r.ok, "a used service: the move " + r.text[:200])
    check(sql("SELECT org_id, archived FROM office_services WHERE id=?", (SV,))[0] == (PB, 1), "a used service stays archived in the old office")
    check(sql("SELECT COUNT(*) FROM office_services WHERE org_id=? AND name_de='Schnitt'", (KAP,))[0][0] == 1, "a used service: a copy in the target")
    check(sql("SELECT service_id FROM office_doc_items WHERE doc_id=?", (INVX,))[0][0] == SV, "the issued invoice is untouched")
    r = Fr.post(B + MS, json={"undo": r.json().get("move_id")})
    check(r.ok and sql("SELECT archived FROM office_services WHERE id=?", (SV,))[0][0] == 0, "a used service: the undo")
    check(sql("SELECT COUNT(*) FROM office_services WHERE org_id=? AND name_de='Schnitt'", (KAP,))[0][0] == 0, "a used service: the copy is gone")
else:
    print("note: the service link of an invoice position is not kept by this version: copy case skipped", flush=True)

# 2.356.0 (#2926, review N1): the undo of a vehicle move puts no drive into a month locked since (as on the way there)
r = move(Fr, "vehicles", [VID], f"org:{KAP}")
check(r.ok, "vehicles: moved again " + r.text[:200])
VMID = r.json().get("move_id") if r.ok else None
r = Fr.post(B + O + "/periods/lock", json={"through": "2026-02", "confirm": "02/2026"})
check(r.ok, "the personal office locks February 2026 " + r.text[:200])
r = Fr.post(B + MS, json={"undo": VMID})
check(r.status_code == 409 and sql("SELECT org_id FROM office_drives WHERE id=?", (DRV,))[0][0] == KAP,
      f"vehicles: no undo into a locked month, the logbook stays ({r.status_code} {r.text[:160]})")

sys.exit(kt.done("p2356_a_move"))
