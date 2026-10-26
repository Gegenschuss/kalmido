#!/usr/bin/env python3
"""2.237.0 B (#2864) API tests: the month lock / finalisation (#2471) on the ways around it. Own container (start.sh),
invented companies and people only (@example.com / .example), the PDFs are made here.
 - a new version of a receipt file: the upload of the same name (POST /api/files/upload, replace) and API v1
   (POST /api/v1/files/<id>/versions) -> 409 in a locked month (the current version stays), a new version in an open one
 - bulk restore (POST /api/files/restore): a receipt of a locked month in the batch -> 409 for the whole batch (all stays in
   the trash); open months: restored as before
 - splitting a stack (POST /api/docs/<id>/split): a receipt of a locked month -> 409, nothing in the trash; undo
   (POST /api/docs/<id>/unsplit): a part that became a receipt of a locked month -> 409, nothing moved; open: as before
 - test phase deletion of a finalised invoice: an office group with manage (copy of tpl:finance) 403 now; the admin in an
   open month deletes as before; an invoice dated in a locked month or with a payment in one -> 409, nothing deleted
 - a person without an organisation (freelancer-matrix: files, office): every way locked / open in the own personal office
usage: p2237_b_periodlock_test.py <datadir>      (a fresh container; P2237B_NOSTART=1 = the server already runs)"""
import base64
import os
import sys
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from kt import B, DATA, check, sess, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(env={"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": base64.b64encode(os.urandom(32)).decode()}, prefix="P2237B")
FEAT = "cal,comments,collab,clients,office,docs,files,time"
O, D, R = "/api/office", "/api/office/docs", "/api/office/rights"
TODAY = kt.today()
TD = TODAY.isoformat()
M = ((TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)).isoformat()[:7]  # the month before: the one locked below
ML = f"{M[5:7]}/{M[:4]}"
OLD = f"{M}-08"
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "de",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051",
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}
CLIENT = {"name": "Example Client AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Koeln", "country": "DE",
          "email_invoice": "billing@client.example", "payment_terms_days": 14}


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        cur = c.execute(q, args)
        return cur.fetchall() if q.lstrip().upper().startswith(("SELECT", "WITH")) else None
    finally:
        c.close()


def pdf(*texts):
    """A PDF with one page per text (hand-written, no library)."""
    n = len(texts)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % (4 + 2 * i) for i in range(n)) + b"] /Count %d >>" % n,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, t in enumerate(texts):
        stream = f"BT /F1 12 Tf 40 700 Td ({t}) Tj ET".encode()
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R /Resources << /Font << /F1 3 0 R >> >> >>" % (5 + 2 * i))
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def doc(s, nid):
    r = s.get(B + f"/api/docs/{nid}")
    return r.json() if r.ok else None


def up(s, name, data, ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, data, "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    until(lambda: (doc(s, nid) or {}).get("state") in ("done", "failed"), 180)
    return nid


def receipt(s, nid, day):
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": "11.90", "date": day})
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Software", "vat_pct": "19", "keep": True})
    assert r.ok, r.text
    return nid


def node(nid):
    return sql("SELECT parent_id, cur_version, deleted_at, name FROM fs_nodes WHERE id=?", (nid,))[0]


def same_name_upload(s, nid):
    n = node(nid)
    form = {"parent_id": str(n[0])} if n[0] else {"space": "private"}
    return s.post(B + "/api/files/upload", data=form, files={"file": (n[3], pdf("Neue Fassung"), "application/pdf")})


def v1_version(s, nid):
    """API v1 with a personal token of the session's person (files:write)."""
    if not hasattr(s, "tok"):
        r = s.post(B + "/api/me/tokens", json={"name": "p2237b", "scopes": ["read", "write"]})
        assert r.status_code == 201, r.text
        s.tok = r.json()["token"]
    return requests.post(B + f"/api/v1/files/{nid}/versions", headers={"Authorization": "Bearer " + s.tok}, json={"content_base64": base64.b64encode(pdf("API Fassung")).decode(),
                                                               "mime": "application/pdf"})


def setup_office(s):
    check(s.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"}).ok, "office settings")
    r = s.post(B + "/api/clients", json=CLIENT)
    check(r.status_code in (200, 201), "a client " + r.text[:200])
    return r.json().get("id")


def invoice(s, cl, title):
    r = s.post(B + D, json={"kind": "invoice", "project_title": title, "client_id": cl, "service_from": TD, "service_to": TD})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    assert s.put(B + f"{D}/{did}/items", json={"items": [{"title": "Schnitt", "qty": 1, "rate": 500}]}).ok
    r = s.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    return did, s.get(B + f"{D}/{did}").json().get("number") or ""


def delete(s, did, num):
    return s.delete(B + f"{D}/{did}?confirm_number=" + requests.utils.quote(num))


def gone(did):
    return not sql("SELECT 1 FROM office_docs WHERE id=?", (did,))


def lock(s, who):
    r = s.post(B + O + "/periods/lock", json={"through": M, "confirm": ML})
    check(r.ok, f"{who}: lock {M} {r.status_code} {r.text[:160]}")


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "fina", "display_name": "Fina Finance", "password": "password123",
                                   "email": "fina@example.com"})
assert r.ok, r.text
FINA = r.json()["id"]
Fi = sess("fina")
for s in (A, Fi):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT, "workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A, "fred", features=FEAT)  # freelancer-matrix: files (receipt versions, bulk restore, split), office (test phase delete)
Fr.patch(B + "/api/settings", json={"workspace": "private"})

# ---------------------------------------------------------------- data before the lock (the freelancer's private documents)
RV = receipt(Fr, up(Fr, "beleg-alt.pdf", pdf("Beleg alt")), OLD)  # locked month: no new version
RO = receipt(Fr, up(Fr, "beleg-neu.pdf", pdf("Beleg neu")), TD)  # open month
RB = receipt(Fr, up(Fr, "beleg-papierkorb.pdf", pdf("Beleg Papierkorb")), TD)
RX = receipt(Fr, up(Fr, "beleg-zweiter.pdf", pdf("Beleg zweiter")), TD)
S1 = receipt(Fr, up(Fr, "stapel-alt.pdf", pdf("Seite eins", "Seite zwei")), OLD)  # a stack that is a receipt of the locked month
S2 = up(Fr, "stapel-neu.pdf", pdf("Seite eins neu", "Seite zwei neu"))
check((doc(Fr, S1) or {}).get("pages") == 2 and (doc(Fr, S2) or {}).get("pages") == 2, "the stacks have two pages")
for x in (RB, RX):
    check(Fr.delete(B + f"/api/files/nodes/{x}").ok, f"open receipt {x} into the trash")
CLF = setup_office(Fr)
lock(Fr, "freelancer")

# ================================================================ 1. a new version of a receipt file
v0 = node(RV)[1]
r = same_name_upload(Fr, RV)
check(r.status_code == 409 and ML in r.text, f"upload of the same name onto a receipt of the locked month: 409 ({r.status_code} {r.text[:160]})")
check(node(RV)[1] == v0, "the locked receipt keeps its current version (upload)")
r = v1_version(Fr, RV)
check(r.status_code == 409, f"API v1 new version of a receipt of the locked month: 409 ({r.status_code} {r.text[:160]})")
check(node(RV)[1] == v0, "the locked receipt keeps its current version (API v1)")
v1 = node(RO)[1]
r = same_name_upload(Fr, RO)
check(r.ok and node(RO)[1] == v1 + 1, f"open month: the upload of the same name is a new version ({r.status_code} {node(RO)[1]})")
r = v1_version(Fr, RO)
check(r.status_code == 201 and node(RO)[1] == v1 + 2, f"open month: API v1 new version ({r.status_code} {r.text[:120]})")

# ================================================================ 2. bulk restore
sql("UPDATE doc_meta SET doc_date=? WHERE node_id=?", (OLD, RB))  # the trashed receipt belongs to the locked month now
r = Fr.post(B + "/api/files/restore", json={"ids": [RX, RB]})
check(r.status_code == 409 and ML in r.text, f"bulk restore with a receipt of the locked month: 409 ({r.status_code} {r.text[:160]})")
check(node(RB)[2] is not None and node(RX)[2] is not None, "all or nothing: both stay in the trash")
sql("UPDATE doc_meta SET doc_date=? WHERE node_id=?", (TD, RB))
r = Fr.post(B + "/api/files/restore", json={"ids": [RX, RB]})
check(r.ok and node(RB)[2] is None and node(RX)[2] is None, f"open month: bulk restore as before ({r.status_code} {r.text[:120]})")

# ================================================================ 3. split / unsplit
r = Fr.post(B + f"/api/docs/{S1}/split", json={"parts": [[1], [2]]})
check(r.status_code == 409 and ML in r.text, f"split of a receipt of the locked month: 409 ({r.status_code} {r.text[:160]})")
check(node(S1)[2] is None, "the locked stack stays (not in the trash)")
r = Fr.post(B + f"/api/docs/{S2}/split", json={"parts": [[1], [2]]})
P = r.json().get("ids") or [] if r.status_code == 201 else []
check(len(P) == 2 and node(S2)[2] is not None, f"open month: the stack is split as before ({r.status_code} {r.text[:160]})")
if len(P) == 2:
    until(lambda: (doc(Fr, P[0]) or {}).get("state") in ("done", "failed"), 180)
    receipt(Fr, P[0], TD)
    sql("UPDATE doc_meta SET doc_date=? WHERE node_id=?", (OLD, P[0]))  # the part became a receipt of the locked month
    r = Fr.post(B + f"/api/docs/{S2}/unsplit")
    check(r.status_code == 409 and ML in r.text, f"undo with a part of the locked month: 409 ({r.status_code} {r.text[:160]})")
    check(node(P[0])[2] is None and node(P[1])[2] is None and node(S2)[2] is not None, "nothing moved: the parts stay, the stack in the trash")
    sql("UPDATE doc_meta SET doc_date=? WHERE node_id=?", (TD, P[0]))
    r = Fr.post(B + f"/api/docs/{S2}/unsplit")
    check(r.ok and node(S2)[2] is None and node(P[0])[2] is not None and node(P[1])[2] is not None,
          f"open month: undo as before ({r.status_code} {r.text[:120]})")

# ================================================================ 4. test phase deletion of a finalised invoice
# the freelancer (admin of the personal office)
FI1, FN1 = invoice(Fr, CLF, "Offen")
r = delete(Fr, FI1, FN1)
check(r.ok and gone(FI1), f"freelancer, open month: the invoice goes as before ({r.status_code} {r.text[:160]})")
FI2, FN2 = invoice(Fr, CLF, "Gesperrt")
sql("UPDATE office_docs SET date=? WHERE id=?", (OLD, FI2))
r = delete(Fr, FI2, FN2)
check(r.status_code == 409 and ML in r.text and not gone(FI2), f"freelancer: an invoice of the locked month stays (409) ({r.status_code} {r.text[:160]})")

# the organisation: Fina in a copy of the finance template (manage on quotes & invoices)
CL = setup_office(A)
r = A.post(B + R + "/groups", json={"from": "tpl:finance", "name": "Controlling"})
check(r.ok, "a group copied from finance " + r.text[:160])
GF = r.json().get("id")
check(A.put(B + f"{R}/people/{FINA}", json={"groups": [f"g:{GF}"]}).ok, "Fina into the finance group")
I1, N1 = invoice(A, CL, "Gruppe")
r = delete(Fi, I1, N1)
check(r.status_code == 403 and not gone(I1), f"office group with manage: the test phase deletion 403 ({r.status_code} {r.text[:160]})")
r = delete(A, I1, N1)
check(r.ok and gone(I1), f"the admin, open month: the invoice goes as before ({r.status_code} {r.text[:160]})")
I2, N2 = invoice(A, CL, "Gesperrt")
I3, N3 = invoice(A, CL, "Zahlung gesperrt")
r = A.post(B + f"{D}/{I3}/payments", json={"date": TD, "amount": "100.00"})
check(r.status_code in (200, 201), "a payment " + r.text[:160])
sql("UPDATE office_docs SET date=? WHERE id=?", (OLD, I2))
lock(A, "organisation")
sql("UPDATE office_payments SET date=? WHERE doc_id=?", (OLD, I3))  # a payment booked in the locked month
r = delete(A, I2, N2)
check(r.status_code == 409 and ML in r.text and not gone(I2), f"admin: an invoice of the locked month stays (409) ({r.status_code} {r.text[:160]})")
r = delete(A, I3, N3)
check(r.status_code == 409 and ML in r.text and not gone(I3), f"admin: an invoice with a payment of the locked month stays (409) ({r.status_code} {r.text[:160]})")
check(sql("SELECT count(*) FROM office_payments WHERE doc_id=?", (I3,))[0][0] == 1, "its payment stays")

sys.exit(kt.done("p2237_b_periodlock"))
