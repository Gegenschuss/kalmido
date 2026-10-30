#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.356.1 (#3343, #3344, #3345, #3346): the rest of moving office data (POST /api/office/move-space). Invented companies,
people and figures only.
freelancer-matrix: office
tenant-matrix: office
A person without an organisation moves from the personal office into an organisation (where she is the admin) and back with
the undo:
 - #3343 a client takes its deals along: a deal no longer makes the client a copy, the quotation that moves along stays
   linked, an issued quotation and a project of another workspace are unlinked, a deal in the trash stays; the undo puts it back
 - #3344 letter drafts one by one: a sent letter stays (retention), the draft loses its client and its linked document there,
   it opens in the target (sealed anew); the undo brings client and link back; somebody else's letter 404
 - #3345 a set with its devices: a device only this set uses moves, one another set of the old office uses is copied and
   the set names the copy; the undo writes the old items back and removes the copy
 - #3346 the preview of the own part of an organisation's office names the suppliers and the whole-office way
usage: p23561_move_test.py <datadir>      (P23561_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import base64
import os
import sys

import kt
from kt import B, check, until
from freelancer_fixture import freelancer

O = "/api/office"
D = O + "/docs"
MS = O + "/move-space"
KEY = base64.b64encode(os.urandom(32)).decode()


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


def client(s, name):
    r = s.post(B + "/api/clients", json={"name": name, "street": "Weg 1", "zip": "50000", "city": "Köln", "country": "DE"})
    assert r.ok, r.text
    return r.json()["id"]


def draft(s, cl, title, kind="offer"):
    r = s.post(B + D, json={"kind": kind, "client_id": cl, "project_title": title, "service_from": "2026-03-01",
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


def undo(s, mid):
    r = s.post(B + MS, json={"undo": mid})
    check(r.ok, f"undo {mid}: " + r.text[:300])
    return r


kt.fresh(env={"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P23561")
A = kt.setup()
FID, Fr = freelancer(B, A)
FID2, Fi = freelancer(B, A, "fiona")
ws(Fr, "private")
company(Fr, "Frida Film")
KAP = A.post(B + "/api/admin/orgs", json={"name": "Kappa", "admin_id": FID}).json()["id"]
ws(Fr, f"org:{KAP}")
company(Fr, "Kappa Studio")
ws(Fr, "private")
PB = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
TO = f"org:{KAP}"

# ================================================================ 1. #3343 deals move with their client
CLA = client(Fr, "Anfrage Nord GmbH")
OD = draft(Fr, CLA, "Angebot Nord")
CLB = client(Fr, "Anfrage Sued KG")
OI = draft(Fr, CLB, "Angebot Sued")
r = Fr.post(B + f"{D}/{OI}/finalize")
check(r.ok, "setup: an issued quotation " + r.text[:200])
PRJ = Fr.post(B + "/api/lists", json={"name": "Projekt Sued"}).json()["id"]


def deal(title, cl, **kw):
    r = Fr.post(B + O + "/deals", json={"title": title, "client_id": cl, "value": "1000", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


D1 = deal("Deal Nord", CLA)
check(Fr.patch(B + O + f"/deals/{D1}", json={"offer_id": OD}).ok, "setup: deal 1 has the draft quotation")
D2 = deal("Deal Sued", CLB, list_id=PRJ)
check(Fr.patch(B + O + f"/deals/{D2}", json={"offer_id": OI}).ok, "setup: deal 2 has the issued quotation")
D3 = deal("Deal im Papierkorb", CLB)
check(Fr.delete(B + O + f"/deals/{D3}").ok, "setup: deal 3 in the trash")
check(move(Fi, "clients", [CLA], TO, dry=1).status_code == 404, "deals: somebody else's client 404")
r = move(Fr, "clients", [CLA, CLB], TO, dry=1)
j = r.json()
check(r.ok and (j.get("count") or {}).get("deals") == 2, f"deals: the preview counts the two live deals {j.get('count')}")
check(any("deals move with their clients" in n for n in j.get("notes") or []), f"deals: the preview names them {j.get('notes')}")
check(any("lose their quotation or project" in n or "loses its quotation or project" in n for n in j.get("notes") or []),
      f"deals: the preview names the links that end {j.get('notes')}")
r = move(Fr, "clients", [CLA, CLB], TO)
check(r.ok and r.json().get("ok"), "deals: the move " + r.text[:300])
MID = r.json().get("move_id")
# 2.356.1 (#3343): before, the deal made its client a copy that stayed archived in the old office
check(sql("SELECT org_id, archived FROM clients WHERE id=?", (CLA,))[0] == (KAP, 0), "deals: a client with only a deal moves as a whole")
d1 = sql("SELECT org_id, client_id, offer_id FROM office_deals WHERE id=?", (D1,))[0]
check(d1 == (KAP, CLA, OD), f"deals: deal 1 moved with its client and keeps its quotation that moved along {d1}")
newb = sql("SELECT id FROM clients WHERE org_id=? AND name='Anfrage Sued KG'", (KAP,))
check(len(newb) == 1, "deals: the client with an issued quotation is created anew in the target")
d2 = sql("SELECT org_id, client_id, offer_id, list_id FROM office_deals WHERE id=?", (D2,))[0]
check(d2 == (KAP, newb[0][0] if newb else -1, None, None), f"deals: deal 2 follows the new client, its issued quotation and project end {d2}")
check(sql("SELECT org_id, client_id FROM office_deals WHERE id=?", (D3,))[0] == (PB, CLB), "deals: a deal in the trash stays")
ws(Fr, TO)
r = Fr.get(B + O + "/deals")
check(r.ok and any(x.get("id") == D1 and x.get("value") in ("1000", "1000.00") for x in r.json().get("items") or []),
      "deals: the deal opens in the organisation (sealed anew) " + r.text[:200])
ws(Fr, "private")
undo(Fr, MID)
check(sql("SELECT org_id, client_id, offer_id FROM office_deals WHERE id=?", (D1,))[0] == (PB, CLA, OD), "deals: the undo brings deal 1 back")
check(sql("SELECT org_id, client_id, offer_id, list_id FROM office_deals WHERE id=?", (D2,))[0] == (PB, CLB, OI, PRJ),
      "deals: the undo puts the client, quotation and project of deal 2 back")

# ================================================================ 2. #3344 letter drafts
CLL = client(Fr, "Brief Kunde AG")
r = Fr.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("bescheid.pdf", tiny_pdf("Bescheid Amt"), "application/pdf")})
check(r.status_code == 201, "setup: a document " + r.text[:200])
NODE = r.json()["ids"][0]
until(lambda: (lambda j: j.get("state") in ("done", "failed", "none", "skip", "") and j)(Fr.get(B + f"/api/docs/{NODE}").json()), 90)
r = Fr.post(B + O + "/letters", json={"client_id": CLL, "rcpt_name": "Amt Nord", "rcpt_address": "Amtsweg 1\n20000 Hamburg",
                                     "subject": "Widerspruch Entwurf", "body": "Sehr geehrte Damen und Herren"})
check(r.status_code == 201, "setup: a letter draft " + r.text[:200])
L1 = r.json()["id"]
r = Fr.post(B + O + f"/letters/{L1}/links", json={"node_id": NODE, "kind": "answers"})
check(r.status_code == 201, "setup: the draft answers the document " + r.text[:200])
r = Fr.post(B + O + "/letters", json={"rcpt_name": "Amt Sued", "rcpt_address": "Amtsweg 2\n20000 Hamburg", "subject": "Gesendet", "body": "Text"})
L2 = r.json()["id"]
r = Fr.post(B + O + f"/letters/{L2}/sent", json={})
check(r.ok, "setup: a sent letter " + r.text[:200])
check(move(Fi, "letters", [L1], TO, dry=1).status_code == 404, "letters: somebody else's letter 404")
r = move(Fr, "letters", [L1, L2], TO, dry=1)
j = r.json()
check(r.ok and (j.get("count") or {}).get("letters") == 1, f"letters: the preview counts the draft only {j.get('count')}")
check(any("sent letter stays" in n for n in j.get("notes") or []), f"letters: the sent letter stays (retention) {j.get('notes')}")
check(any("loses its links" in n for n in j.get("notes") or []), f"letters: the preview names the links that end {j.get('notes')}")
r = move(Fr, "letters", [L1, L2], TO)
check(r.ok and r.json().get("ok"), "letters: the move " + r.text[:300])
MID = r.json().get("move_id")
check(sql("SELECT org_id, client_id FROM office_letters WHERE id=?", (L1,))[0] == (KAP, None), "letters: the draft is in the organisation without the client")
check(sql("SELECT org_id FROM office_letters WHERE id=?", (L2,))[0][0] == PB, "letters: the sent letter stays")
check(not sql("SELECT 1 FROM office_letter_links WHERE letter_id=?", (L1,)), "letters: the link to the private document ended")
ws(Fr, TO)
r = Fr.get(B + O + f"/letters/{L1}")
check(r.ok and r.json().get("subject") == "Widerspruch Entwurf", "letters: the draft opens in the organisation (sealed anew) " + r.text[:200])
ws(Fr, "private")
undo(Fr, MID)
check(sql("SELECT org_id, client_id FROM office_letters WHERE id=?", (L1,))[0] == (PB, CLL), "letters: the undo brings the draft and its client back")
check(sql("SELECT node_id FROM office_letter_links WHERE letter_id=?", (L1,)) == [(NODE,)], "letters: the undo links the document again")
r = Fr.get(B + O + f"/letters/{L1}")
check(r.ok and r.json().get("subject") == "Widerspruch Entwurf", "letters: readable in the personal office again " + r.text[:200])

# ================================================================ 3. #3345 a set with its devices
eq = {}
for n in ("Kamera", "Stativ", "Licht"):
    r = Fr.post(B + O + "/equipment", json={"name": n, "daily_rate": 50})
    assert r.ok, r.text
    eq[n] = r.json()["id"]
r = Fr.post(B + O + "/sets", json={"name": "Dreh-Set", "items": [{"equipment_id": eq["Kamera"], "qty": 1}, {"equipment_id": eq["Stativ"], "qty": 2}]})
check(r.ok, "setup: a set " + r.text[:200])
S1 = r.json()["id"]
r = Fr.post(B + O + "/sets", json={"name": "Licht-Set", "items": [{"equipment_id": eq["Stativ"], "qty": 1}, {"equipment_id": eq["Licht"], "qty": 1}]})
S2 = r.json()["id"]
check(move(Fi, "sets", [S1], TO, dry=1).status_code == 404, "sets: somebody else's set 404")
r = move(Fr, "sets", [S1], TO, dry=1)
j = r.json()
cnt = j.get("count") or {}
check(r.ok and cnt.get("sets") == 1 and cnt.get("devices") == 2, f"sets: the preview counts the set and its two devices {cnt}")
check(any("copied into the target" in n for n in j.get("notes") or []), f"sets: the preview names the copied device {j.get('notes')}")
r = move(Fr, "sets", [S1], TO)
check(r.ok and r.json().get("ok"), "sets: the move " + r.text[:300])
MID = r.json().get("move_id")
check(sql("SELECT org_id FROM office_equipment WHERE id=?", (eq["Kamera"],))[0][0] == KAP, "sets: a device only this set uses moved with its id")
check(sql("SELECT org_id, archived FROM office_equipment WHERE id=?", (eq["Stativ"],))[0] == (PB, 0), "sets: a device of another set stays (active)")
cp = sql("SELECT id FROM office_equipment WHERE org_id=? AND name='Stativ'", (KAP,))
check(len(cp) == 1, "sets: a copy of the shared device in the target")
ws(Fr, TO)
r = Fr.get(B + O + "/sets")
s1 = next((x for x in (r.json().get("items") or r.json().get("rows") or []) if x.get("id") == S1), None) if r.ok else None
check(s1 is not None and [i.get("equipment_id") for i in s1.get("items") or []] == [eq["Kamera"], cp[0][0] if cp else -1],
      f"sets: the set names its devices in the target {s1} {r.text[:200]}")
ws(Fr, "private")
r = Fr.get(B + O + "/sets")
s2 = next((x for x in (r.json().get("items") or r.json().get("rows") or []) if x.get("id") == S2), None) if r.ok else None
check(s2 is not None and [i.get("equipment_id") for i in s2.get("items") or []] == [eq["Stativ"], eq["Licht"]], f"sets: the other set is untouched {s2}")
undo(Fr, MID)
check(sql("SELECT org_id FROM office_sets WHERE id=?", (S1,))[0][0] == PB, "sets: the undo brings the set back")
check(sql("SELECT org_id FROM office_equipment WHERE id=?", (eq["Kamera"],))[0][0] == PB, "sets: the undo brings the device back")
check(not sql("SELECT 1 FROM office_equipment WHERE org_id=? AND name='Stativ'", (KAP,)), "sets: the undo removes the copy")
r = Fr.get(B + O + "/sets")
s1 = next((x for x in (r.json().get("items") or r.json().get("rows") or []) if x.get("id") == S1), None) if r.ok else None
check(s1 is not None and [i.get("equipment_id") for i in s1.get("items") or []] == [eq["Kamera"], eq["Stativ"]], f"sets: the undo writes the old items back {s1}")

# ================================================================ 4. #3346 the own part of an organisation's office: the note
r = move(Fr, "office", [KAP], "private", dry=1)
notes = r.json().get("notes") or []
check(r.ok and any("the suppliers stay" in n for n in notes) and any("Bank accounts and suppliers move only with a whole office" in n for n in notes),
      f"office: the preview names the suppliers and the whole-office way {notes}")

sys.exit(kt.done("p23561_move"))
