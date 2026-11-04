#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.522.0 (#4468): a stack waiting for the decision (split_scan state open) mixes several letters, so the document's JSON
carries no recognised values, no receipt hints and no duplicate warning; taking the values over answers 409 and no agent is
offered to read it as a receipt. "No stack" (split_scan cleared) brings them all back.
freelancer-matrix: files
Two people: alice (instance admin, own private area) and frida (a person WITHOUT an organisation). Invented values only.
Red without the fix: extracted / checks / duplicate_of come back on the stack and apply answers 200.
usage: p4468_a_stack_api_test.py <datadir>   (P4468A_NOSTART=1: the container runs already)"""
import json
import sys

import kt
from kt import B, check, until
from freelancer_fixture import freelancer

kt.fresh(prefix="P4468A")
A = kt.setup()
FEAT = "docs,files,office"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
_fid, F = freelancer(B, A, features=FEAT)


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


def up(s, name, text):
    r = s.post(B + "/api/docs", data={"ws": "private"}, files=[("files", (name, tiny_pdf(text), "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()["ids"][0]


def doc(s, nid):
    r = s.get(B + f"/api/docs/{nid}")
    return r.json() if r.ok else None


def done(s, nid):
    return until(lambda: (lambda d: d if d and d["state"] in ("done", "failed") else None)(doc(s, nid)), 120)


X = {"supplier": "Stadtwerke Beispielstadt", "invoice_no": "SW-2026-4411", "net": "71.18", "vat_pct": "19", "gross": "84.71", "currency": "EUR"}
for who, s in (("alice", A), ("frida", F)):
    old = up(s, f"{who}-older.pdf", "Older letter")
    nid = up(s, f"{who}-stack.pdf", "Stack of letters")
    check(done(s, old) and done(s, nid), f"{who}: both documents processed")
    kt.dbx("UPDATE doc_meta SET extracted=?, dup_of=?, dup_ok=0 WHERE node_id=?", (json.dumps(X), old, nid))
    # control first: not a stack -> the values, the hints and the duplicate warning are there
    d0 = doc(s, nid)
    check(d0 and (d0.get("extracted") or {}).get("invoice_no") == "SW-2026-4411" and d0.get("duplicate_of"),
          f"{who}: without a stack the recognised values and the duplicate warning show ({json.dumps(d0 and {k: d0.get(k) for k in ('extracted', 'duplicate_of')})[:300]})")
    kt.dbx("UPDATE doc_meta SET split_scan=? WHERE node_id=?", (json.dumps({"state": "open"}), nid))
    d1 = doc(s, nid)
    check(d1 and (d1.get("split") or {}).get("stack") is True, f"{who}: the document is a stack waiting for the decision")
    check(d1 and d1.get("extracted") is None and d1.get("checks") is None and "duplicate_of" not in d1,
          f"{who}: a stack carries no recognised values, no hints, no duplicate warning ({json.dumps(d1 and {k: d1.get(k) for k in ('extracted', 'checks', 'duplicate_of')})[:300]})")
    check(d1 and all(k in d1 for k in ("date", "due", "asn", "amount")), f"{who}: the form fields stay in the JSON")
    r = s.post(B + f"/api/docs/{nid}/extracted", json={"do": "apply"})
    check(r.status_code == 409, f"{who}: taking the values of a stack over 409 ({r.status_code} {r.text[:120]})")
    check(not kt.dbx("SELECT 1 FROM rc_receipts WHERE node_id=?", (nid,)), f"{who}: the stack became no receipt")
    r = s.get(B + "/api/proposals/agents", params={"kind": "receipt_read", "doc_id": nid})
    check(r.ok and r.json().get("agents") == [], f"{who}: no agent offered to read the stack ({r.status_code})")
    # "No stack": everything is back
    kt.dbx("UPDATE doc_meta SET split_scan='' WHERE node_id=?", (nid,))
    d2 = doc(s, nid)
    check(d2 and (d2.get("extracted") or {}).get("gross") == "84.71" and d2.get("duplicate_of"), f"{who}: after No stack the values are back")

sys.exit(kt.done("p4468_a_stack_api"))
