#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.546.0 B (#4287): a finalised invoice stays as it is on every write path. Invented companies and figures only.
freelancer-matrix: office
 - the routes come from the server's own route table (app.url_map inside the test container, tests/routes_ast.py when the
   container cannot be asked): every POST / PUT / PATCH / DELETE below /api/office/docs/<id> is called against a finalised
   invoice, one or more bodies each, as the office admin. ROUTES names every such route with its verdict and the reason:
     "refused"  the route never takes a finalised invoice: 4xx for every body
     "allowed"  the route may answer 2xx (a payment, the status sent / paid, a new document made from it, a mail ...); what
                it changes are marks outside the frozen document (MARKS)
   A route without an entry is red (a new write route needs a decision), an entry without a route too (stale). No route
   answers 5xx.
 - after every call the state is the same: the head row of office_docs without MARKS (number, date, totals, the frozen
   sender / recipient / tax snapshot, pdf_sha256 / xml_sha256 ...), every row of office_doc_items and office_doc_parts, and
   the stored PDF (GET .../pdf, its SHA-256 = pdf_sha256). There is no database trigger on these tables (decided
   04.11.2026), so the rule hangs on the routes only - this suite is the guard. A control: the same state of a draft
   changes with a PATCH (the comparison is not blind).
 - the editor's undo (office/undo.py): steps recorded on the draft, then finalised -> undo / all / redo 409, nothing moves
 - the agent way (office/agentdocs.py): the write routes below /api/v1/office/(docs|offers)/<id> from the route table
   (AGENT_ROUTES, same rules) against the agent's own quotation once a person finalised it, and against the invoice
 - each for an organisation's admin and for a person without an organisation (the personal office)
 The imported finalised invoice (409 on PATCH / DELETE) is checked in tests/p2137_a_api_test.py.
usage: p2546_b_locked_test.py <datadir>      (P2546B_NOSTART=1 / KMT_NOSTART=1: a running server)"""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, check, done, fresh, setup  # noqa: E402

O = "/api/office"
D = O + "/docs"
TEST_IBAN = "DE02120300000000202051"
KEY = base64.b64encode(os.urandom(32)).decode()

# head columns a finalised invoice may still change, with the reason; everything else of the row is frozen
MARKS = {
    "status": "sent / paid / cancelled (by a credit note) are the invoice's state, not its content (ledger.py)",
    "updated_at": "the time of the last mark",
    "sent_at": "set once when it is sent",
    "paid_at": "set by the payments",
    "datev_sent_at": "the copy to the DATEV inbox went out",
    "cashflow": "the share in the own cash flow plan, never printed",
    "list_id": "the project it belongs to inside Kalmido, never printed",
    "reminder_fee_state": "a reminder's fee waived / paid (the document stays, invoices.py fd_fee_post)",
}

KS = {"project_title": "Changed", "intro": "Changed", "closing": "Changed", "number": "HACK-1", "date": "2026-01-02",
      "discount_pct": 50, "currency": "USD", "vat_mode": "novat", "title": "Changed", "text": "Changed",
      "items": [{"title": "Changed", "qty": 9, "rate": 9}], "status": "draft"}  # every field a write route might take

# "METHOD path" (placeholders as {}) -> (verdict, reason, bodies); bodies None = [KS]
ROUTES = {
    "PATCH /api/office/docs/{}": ("refused", "the head is frozen (ofx_need_editable)", [KS, {"einvoice_format": "xrechnung"}, {"client_id": None}]),
    "PUT /api/office/docs/{}/items": ("refused", "the positions are frozen", [KS, {"items": []}]),
    "POST /api/office/docs/{}/number": ("refused", "the number is frozen", [KS, {}]),
    "POST /api/office/docs/{}/finalize": ("refused", "finalised once; again = 409, nothing written anew", [{}]),
    "POST /api/office/docs/{}/unlock": ("refused", "an invoice is never taken back (only a quotation never sent)", [{}]),
    "POST /api/office/docs/{}/status": ("allowed", "sent / paid only, never back to draft (odoc_set_status); the status is a mark",
                                        [{"status": "draft"}, {"status": "accepted"}, {"status": "sent"}, {"status": "paid"}, {"status": "sent"}]),
    "POST /api/office/docs/{}/payments": ("allowed", "a payment is its own row (office_payments), the invoice stays",
                                          [{"date": "2026-05-20", "amount": 10, "method": "transfer"}]),
    "DELETE /api/office/docs/{}/payments/{}": ("allowed", "taking a payment back removes only that row", None),
    "POST /api/office/docs/{}/credit": ("allowed", "a credit note is a new document (draft) bound to the invoice", [{}]),
    "POST /api/office/docs/{}/duplicate": ("allowed", "a copy is a new draft (= a new version)", [{}]),
    "POST /api/office/docs/{}/delivery": ("allowed", "a delivery note draft is a new document", [{}]),
    "POST /api/office/docs/{}/invoice": ("refused", "an invoice is made from a quotation only", [{}]),
    "POST /api/office/docs/{}/send": ("allowed", "the mail sends the stored files; the status sent is a mark (no mail server here: 409)",
                                      [{"to": "rechnung@example.com", "subject": "Changed", "text": "Changed"}]),
    "POST /api/office/docs/{}/datev": ("allowed", "the DATEV copy sends the stored files; datev_sent_at is a mark (no mail server here: 409)", [{}]),
    "POST /api/office/docs/{}/fee": ("refused", "only a reminder's fee", [{"state": "waived"}]),
    "POST /api/office/docs/{}/project": ("allowed", "the project inside Kalmido (list_id) is a mark, never printed", [{"list_id": None}]),
    "POST /api/office/docs/{}/cashflow": ("refused", "the cash flow share is planning of quotations (an invoice: 400); on a finalised quotation it "
                                                    "may change, never printed (MARKS)", [{"cashflow": "no"}]),
    "POST /api/office/docs/{}/time-release": ("allowed", "frees the time entries of a cancelled invoice (their own rows; before: 409)", [{}]),
    "PUT /api/office/docs/{}/pay-online": ("allowed", "the pay link of a finalised invoice is frozen in the sender; this only answers or refuses",
                                           [{"on": False}, {"on": True}]),
    "POST /api/office/docs/{}/signoff": ("refused", "the customer's approval is for quotations", [{}]),
    "POST /api/office/docs/{}/parts": ("refused", "a part changes the positions", [KS, {"title": "Changed"}]),
    "PATCH /api/office/docs/{}/parts/{}": ("refused", "a part changes the positions", [KS]),
    "PUT /api/office/docs/{}/parts/{}/items": ("refused", "a part's positions are positions", [KS]),
    "DELETE /api/office/docs/{}/parts/{}": ("refused", "a part changes the positions", None),
    "POST /api/office/docs/{}/peppol": ("allowed", "sends the stored UBL through the access point (needs a connection: refused here)", [{}]),
    "POST /api/office/docs/{}/peppol/lookup": ("allowed", "looks the receiver up, writes nothing of the invoice", [{}]),
    "POST /api/office/docs/{}/peppol/refresh": ("allowed", "the delivery state of a sending (its own row)", [{}]),
    "POST /api/office/docs/{}/peppol/undelivered": ("allowed", "marks a sending undelivered (its own row)", [{}]),
    "DELETE /api/office/docs/{}": ("refused", "a finalised invoice is never deleted (GoBD), a credit note cancels it", None),
}
AGENT_ROUTES = {
    "PATCH /api/v1/office/offers/{}": ("refused", "an agent changes only its own drafts (agentdocs.py v1_office_offer_patch)",
                                       [{"title": "Changed", "intro": "Changed", "items": [{"text": "Changed", "qty": 9, "unit": "flat", "price": 9}]},
                                        {"cashflow": "no"}]),
    "POST /api/v1/office/offers/{}/invoice": ("allowed", "an invoice draft made from the finalised, accepted quotation is a new document", [{}]),
}
LAST = ("DELETE /api/office/docs/{}",)  # run at the very end


def norm(rule):
    return re.sub(r"<[^>]+>", "{}", rule)


def route_table():
    """-> ({"METHOD path"}, source): the write routes of the server below the document paths."""
    py = ("import app\nfor r in app.app.url_map.iter_rules():\n"
          "    print(r.rule, ','.join(sorted(r.methods - {'HEAD', 'OPTIONS', 'GET'})))")
    out = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", py],
                         capture_output=True, text=True).stdout
    found, src = set(), "app.url_map"
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) == 2:
            found |= {f"{m} {norm(parts[0])}" for m in parts[1].split(",") if m}
    if not found:  # the container cannot be asked: the parser's list of the same source
        from routes_ast import app_routes
        found, src = {r for r in app_routes(os.path.join(N, ".."))[0] if not r.startswith(("GET ", "DAV "))}, "routes_ast"
    return found, src


ALL, SRC = route_table()
print(f"routes from {SRC}", flush=True)
OURS = {r for r in ALL if re.match(r"^(POST|PUT|PATCH|DELETE) /api/office/docs/\{\}(/|$)", r)}
AGENTS = {r for r in ALL if re.match(r"^(POST|PUT|PATCH|DELETE) /api/v1/office/(docs|offers)/\{\}(/|$)", r)}
check(len(OURS) >= 20, f"the route table ({SRC}) names the document write routes ({len(OURS)})")
for r in sorted(OURS - set(ROUTES)):
    check(False, f"a write route without a decision in ROUTES (refused / allowed + reason): {r}")
for r in sorted(set(ROUTES) - OURS):
    check(False, f"ROUTES names a route the server does not have (stale): {r}")
for r in sorted(AGENTS - set(AGENT_ROUTES)):
    check(False, f"an agent write route without a decision in AGENT_ROUTES: {r}")
for r in sorted(set(AGENT_ROUTES) - AGENTS):
    check(False, f"AGENT_ROUTES names a route the server does not have (stale): {r}")
check(all(v[0] in ("refused", "allowed") and len(v[1]) > 10 for v in list(ROUTES.values()) + list(AGENT_ROUTES.values())),
      "every entry has a verdict and a reason")

# ---------------------------------------------------------------- setup
fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SECRET_KEY": KEY, "KALMIDO_ORGCRYPT_DELAY": "0"}, prefix="P2546B")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs,time", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, F = freelancer(B, A)
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})


def state(S, did):
    """The frozen part of document did: head without MARKS, positions, parts, the stored PDF's checksum."""
    head = kt.dbx("SELECT * FROM office_docs WHERE id=?", (did,))
    items = kt.dbx("SELECT * FROM office_doc_items WHERE doc_id=? ORDER BY id", (did,))
    parts = kt.dbx("SELECT * FROM office_doc_parts WHERE doc_id=? ORDER BY id", (did,))
    pdf = S.get(B + f"{D}/{did}/pdf")
    return {"head": {k: v for k, v in dict(head[0]).items() if k not in MARKS} if head else None,
            "items": [dict(x) for x in items], "parts": [dict(x) for x in parts],
            "pdf": hashlib.sha256(pdf.content).hexdigest() if pdf.ok else f"http {pdf.status_code}"}


def diff(a, b):
    if a["head"] is None or b["head"] is None:
        return "the document is gone"
    out = [k for k in sorted(set(a["head"]) | set(b["head"])) if a["head"].get(k) != b["head"].get(k)]
    out += [k for k in ("items", "parts", "pdf") if a[k] != b[k]]
    return ", ".join(out)


def fill(route, did, extra):
    """The URL of route (placeholders: the document first, then the extra ids in order)."""
    ids = iter([did] + extra)
    return B + re.sub(r"\{\}", lambda _m: str(next(ids, 999999)), route.split(" ", 1)[1])


def call(S, route, did, extra, body, headers=None):
    m, url = route.split(" ", 1)[0], fill(route, did, extra)
    kw = {"headers": headers} if headers else {}
    return (requests if headers else S).request(m, url, **({"json": body} if m != "DELETE" else {}), **kw)


def matrix(who, S, did, table, routes, extra_ids, headers=None):
    """Every route of routes (sorted, LAST at the end) with every body against did: the frozen state stays."""
    before, codes = state(S, did), {}
    for route in sorted(routes, key=lambda r: (r in LAST, r)):
        verdict, _why, bodies = table[route]
        for body in bodies or [KS]:
            r = call(S, route, did, extra_ids.get(route, []), body, headers)
            codes.setdefault(route, []).append(r.status_code)
            tag = f"{who}: {route} {json.dumps(body)[:60]}"
            check(r.status_code < 500, f"{tag}: no server error ({r.status_code} {r.text[:160]})")
            if verdict == "refused":
                check(400 <= r.status_code < 500, f"{tag}: refused ({r.status_code} {r.text[:160]})")
            after = state(S, did)
            check(after == before, f"{tag}: the finalised document is unchanged ({r.status_code}; changed: {diff(before, after)})")
            before = after if after["head"] is not None else before
    return codes


def succeeded(who, codes, routes):
    """The allowed routes that must really have done their work here (not only refused), so the matrix sees the success path."""
    for route in routes:
        check(any(200 <= x < 300 for x in codes.get(route, [])), f"{who}: {route} succeeded at least once ({codes.get(route)})")


for who, S in (("org admin", A), ("freelancer", F)):
    r = S.put(B + O + "/settings", json={"lang": "de", "currency": "EUR",
                                         "company_fields": {"name": "Beispiel Studio GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt",
                                                            "country": "DE", "email": "kontakt@example.com", "tax_number": "12/345/67890",
                                                            "vat_id": "DE999999999", "iban": TEST_IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
    check(r.ok, f"{who}: office settings " + r.text[:160])
    r = S.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktplatz 2", "zip": "54321", "city": "Beispielort", "country": "DE",
                                         "vat_id": "DE987654321", "email_invoice": "rechnung@example.com"})
    check(r.status_code == 201, f"{who}: a client " + r.text[:160])
    CL = r.json().get("id")

    def invoice(title, S=S, CL=CL):
        r = S.post(B + D, json={"kind": "invoice", "project_title": title, "client_id": CL, "service_from": "2026-05-01", "service_to": "2026-05-31",
                                "date": "2026-05-08", "einvoice_format": "zugferd",
                                "items": [{"title": "Kamera", "qty": 2, "unit": "day", "rate": 500}, {"title": "Buch", "qty": 10, "unit": "piece", "rate": 12.5, "tax": "reduced"}]})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    # ---- the control: the comparison sees a change of a draft
    I0 = invoice("Kontrolle")
    s0 = state(S, I0)
    S.patch(B + f"{D}/{I0}", json={"project_title": "Kontrolle 2"})
    s1 = state(S, I0)
    check(s0 != s1 and "project_title" in diff(s0, s1), f"{who}: control - a draft's change is seen ({diff(s0, s1)})")

    # ---- the matrix against a finalised invoice
    INV = invoice("Imagefilm Hafen")
    r = S.post(B + f"{D}/{INV}/finalize")
    check(r.ok and r.json().get("number"), f"{who}: the invoice is finalised " + r.text[:160])
    st = state(S, INV)
    check(st["head"]["pdf_sha256"] and st["pdf"] == st["head"]["pdf_sha256"], f"{who}: the stored PDF is the one pdf_sha256 names")
    check(len(st["items"]) == 2 and st["head"]["locked_at"], f"{who}: two frozen positions")
    r = S.post(B + f"{D}/{INV}/payments", json={"date": "2026-05-15", "amount": 1, "method": "transfer"})
    pays = S.get(B + f"{D}/{INV}/payments").json().get("payments") or []
    extra = {"DELETE /api/office/docs/{}/payments/{}": [pays[0]["id"]] if pays else []}
    check(bool(pays), f"{who}: a payment to take back in the matrix " + r.text[:120])
    codes = matrix(who, S, INV, ROUTES, OURS, extra)
    succeeded(who, codes, ("POST /api/office/docs/{}/status", "POST /api/office/docs/{}/payments", "DELETE /api/office/docs/{}/payments/{}",
                           "POST /api/office/docs/{}/credit", "POST /api/office/docs/{}/duplicate", "POST /api/office/docs/{}/delivery",
                           "POST /api/office/docs/{}/project", "PUT /api/office/docs/{}/pay-online"))
    # cancelled by its credit note (the credit note the matrix made, finalised): the status is a mark, the routes once more
    crs = [x for x in kt.dbx("SELECT id FROM office_docs WHERE kind='credit' AND cancels_id=? ORDER BY id", (INV,))]
    r = S.post(B + f"{D}/{crs[0]['id']}/finalize") if crs else None
    check(r is not None and r.ok, f"{who}: the credit note of the matrix is finalised " + (r.text[:160] if r is not None else "(none)"))
    check(kt.dbx("SELECT status FROM office_docs WHERE id=?", (INV,))[0]["status"] == "cancelled", f"{who}: the invoice is cancelled by it")
    pays = S.get(B + f"{D}/{INV}/payments").json().get("payments") or []
    codes = matrix(f"{who} (cancelled)", S, INV, ROUTES, OURS, {"DELETE /api/office/docs/{}/payments/{}": [pays[0]["id"]] if pays else []})
    succeeded(f"{who} (cancelled)", codes, ("POST /api/office/docs/{}/time-release",))

    # ---- undo (office/undo.py): steps on the draft, then finalised -> 409, nothing moves
    I2 = invoice("Rueckgaengig")
    tok = "%032x" % (0x4287 + len(who))
    U = {"X-Kalmido-Undo": tok}
    check(S.patch(B + f"{D}/{I2}", json={"project_title": "Schritt eins"}, headers=U).ok, f"{who}: undo step 1")
    check(S.put(B + f"{D}/{I2}/items", json={"items": [{"title": "Schnitt", "qty": 1, "unit": "day", "rate": 700}]}, headers=U).ok, f"{who}: undo step 2")
    r = S.post(B + f"/api/office/undo/doc/{I2}", json={"sess": tok, "op": "undo"})
    check(r.ok, f"{who}: one step undone while a draft (so a redo exists) {r.status_code} {r.text[:160]}")
    check(S.post(B + f"{D}/{I2}/finalize").ok, f"{who}: then finalised")
    before = state(S, I2)
    for op in ("undo", "all", "redo", "redoall"):
        r = S.post(B + f"/api/office/undo/doc/{I2}", json={"sess": tok, "op": op})
        after = state(S, I2)
        check(r.status_code == 409 and after == before, f"{who}: undo {op} on the finalised invoice: 409, unchanged ({r.status_code}; {diff(before, after)})")

    # ---- the agent way: its own quotation, finalised by the person; and the invoice
    r = S.post(B + "/api/my/agents", json={"username": f"p2546bot{len(who)}", "display_name": "P2546 Bot", "scopes": ["read", "office"]})
    check(r.status_code == 201, f"{who}: an own agent " + r.text[:160])
    if r.status_code != 201:
        continue
    AG, AH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"], "X-Requested-With": "kalmido"}
    check(S.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok and S.put(B + O + "/settings", json={"agents_read": 1}).ok,
          f"{who}: the agent may make drafts")
    r = requests.post(B + "/api/v1/office/offers", headers=AH, json={"title": "Angebot vom Agenten", "client_id": CL,
                                                                      "items": [{"text": "Schnitt", "qty": 1, "unit": "flat", "price": 300}]})
    check(r.status_code == 201, f"{who}: the agent's quotation draft " + r.text[:160])
    Q = (r.json().get("doc") or {}).get("id") if r.status_code == 201 else None
    if Q:
        r = requests.patch(B + f"/api/v1/office/offers/{Q}", headers=AH, json={"title": "Noch ein Entwurf"})
        check(r.ok, f"{who}: the agent changes its draft (control) {r.status_code}")
        check(S.post(B + f"{D}/{Q}/finalize").ok, f"{who}: the person finalises the agent's quotation")
        for st_ in ("sent", "accepted"):  # so that an invoice may be made from it
            r = S.post(B + f"{D}/{Q}/status", json={"status": st_})
            check(r.ok, f"{who}: the quotation is {st_} {r.status_code} {r.text[:120]}")
        codes = matrix(f"{who} agent on its finalised quotation", S, Q, AGENT_ROUTES, AGENTS, {}, headers=AH)
        succeeded(f"{who} agent", codes, ("POST /api/v1/office/offers/{}/invoice",))
    before = state(S, INV)
    for route in sorted(AGENTS):
        r = call(S, route, INV, [], (AGENT_ROUTES[route][2] or [{}])[0], AH)
        after = state(S, INV)
        check(400 <= r.status_code < 500 and after == before, f"{who}: agent {route} on the finalised invoice: refused, unchanged ({r.status_code}; {diff(before, after)})")

sys.exit(done("p2546_b_locked"))
