#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1064.0 (#5818): a sent quotation without an answer rings the bell before and after its "valid until" (office/offerexp.py).
Invented companies, people and figures only.
freelancer-matrix: office
 - a finalised, sent quotation with "valid until" = today + 3: the watchdog's run puts ONE entry "offerexp" (state soon, 3
   days) into the bell of the person who sent it (to_me, counted in unread_me); a second run adds nothing
 - the date passed: the next run rings "gone"; the "soon" entry is gone (its date is no longer the quotation's); the list
   marks the quotation "expired", the editor's answer carries offer_exp
 - "Extend validity" (POST .../valid-until): a date in the past 400, a new date 200 on the finalised row (no new version, the
   same number), logged in the office log; the entry leaves the bell, the mark "expired" goes
 - answered = gone: a quotation declined (organisation) / accepted (person without an organisation) leaves the bell
 - the office setting offer_exp_notice off: no entry; an invoice and a draft quotation cannot be extended (409)
 - the same for a person without an organisation (her personal office, she is its admin)
usage: p5818_offer_expiry_test.py <datadir>"""
import os
import subprocess
import sys
from datetime import date, timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, setup  # noqa: E402

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
OFF = "/api/office"
D = OFF + "/docs"
FEAT = "cal,comments,collab,clients,office,docs,files,contacts"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "email": "hallo@beispiel.example", "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
           "bank_name": "Beispielbank"}
TODAY = date.today()


def day(n):
    return (TODAY + timedelta(days=n)).isoformat()


fresh({"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P5818")
A = setup()
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ALICE = A.get(B + "/api/me").json()["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"}).ok


def tick():
    code = ("import app\nfrom kalmido.core.db import connect\nfrom kalmido.office import offerexp as x\n"
            "x._OFE_LAST['at'] = -1e12\nc = connect()\nx.ofe_tick(c)\nc.close()")
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def news(s, did=None):
    j = s.get(B + "/api/news").json()
    its = [x for x in j["items"] if x["kind"] == "offerexp" and (did is None or (x.get("data") or {}).get("doc") == did)]
    return its, j.get("unread_me", 0)


def office(s, client):
    assert s.put(B + OFF + "/settings", json={"lang": "de", "company_fields": COMPANY}).ok
    r = s.post(B + "/api/clients", json={"name": client, "street": "Marktweg 5", "zip": "50667", "city": "Koeln", "country": "DE"})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def sent_offer(s, cl, title, finalise=True):
    r = s.post(B + D, json={"kind": "offer", "lang": "de", "client_id": cl, "project_title": title,
                            "items": [{"kind": "service", "title": "Dreh", "qty": 1, "unit": "day", "rate": 900, "tax": "standard"}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if finalise:
        r = s.post(B + f"{D}/{did}/finalize")
        assert r.ok, r.text
    r = s.post(B + f"{D}/{did}/status", json={"status": "sent"})
    assert r.ok and r.json().get("status") == "sent", r.text
    return did


def valid_to(did, v):
    dbx("UPDATE office_docs SET valid_until=? WHERE id=?", (v, did))


def run(s, who, cl, answer):
    # ---- soon: one entry, counted in the bell, once
    _, me0 = news(s)  # before the date is set: whichever run rings it (the server's watchdog or tick()), the bell gains one
    did = sent_offer(s, cl, "Imagefilm " + who)
    valid_to(did, day(3))
    tick()
    its, me1 = news(s, did)
    d = its[0].get("data") if its else {}
    check(len(its) == 1 and d.get("state") == "soon" and d.get("days") == 3 and d.get("until") == day(3) and its[0].get("to_me"),
          f"{who}: three days before 'valid until' the bell has one entry 'expires in 3 days' for the sender {its}")
    check(d.get("client") and d.get("number") and d.get("click") == f"#office/offers/{did}", f"{who}: the entry names quotation and client and opens it {d}")
    check(me1 == me0 + 1, f"{who}: the bell counts it once ({me0} -> {me1})")
    tick()
    check(len(news(s, did)[0]) == 1, f"{who}: a second run adds no second entry {news(s, did)[0]}")
    # ---- gone: the next step rings, the old one leaves; the list marks it, the editor carries the note
    valid_to(did, day(-1))
    tick()
    its = news(s, did)[0]
    check([x["data"].get("state") for x in its] == ["gone"], f"{who}: the day after 'valid until' the entry says 'expired', the 'soon' one is gone {its}")
    rows = s.get(B + D, params={"kind": "offer"}).json().get("docs") or []
    row = next((x for x in rows if x["id"] == did), {})
    check(row.get("expired") is True, f"{who}: the list marks the quotation 'expired' {row.get('expired')}")
    doc = s.get(B + f"{D}/{did}").json()
    check((doc.get("offer_exp") or {}).get("state") == "gone", f"{who}: the editor's answer carries the note {doc.get('offer_exp')}")
    num = doc.get("number")
    # ---- extend: a past date is refused, a new date on the finalised quotation (same number, no new version)
    r = s.post(B + f"{D}/{did}/valid-until", json={"valid_until": day(-2)})
    check(r.status_code == 400, f"{who}: a date in the past is refused {r.status_code} {r.text[:200]}")
    r = s.post(B + f"{D}/{did}/valid-until", json={"valid_until": day(20)})
    j = r.json() if r.ok else {}
    check(r.ok and j.get("valid_until") == day(20) and j.get("number") == num and j.get("locked") and j.get("status") == "sent" and not j.get("offer_exp"),
          f"{who}: 'Extend validity' sets the new date on the finalised quotation {r.status_code} {r.text[:300]}")
    check(not news(s, did)[0], f"{who}: extended -> the entry leaves the bell {news(s, did)[0]}")
    r = s.get(B + f"{D}/{did}/pdf")
    check(r.status_code == 200 and r.content[:4] == b"%PDF", f"{who}: the stored PDF is served after the extension (stored anew, its checksum fits) {r.status_code}")
    rows = s.get(B + D, params={"kind": "offer"}).json().get("docs") or []
    check(not next((x for x in rows if x["id"] == did), {}).get("expired"), f"{who}: extended -> no mark 'expired' in the list")
    log = s.get(B + OFF + "/log", params={"limit": 50}).json().get("log") or []
    check(any(x.get("action") == "valid_until" for x in log), f"{who}: the extension stands in the office log {[x.get('action') for x in log][:10]}")
    # ---- answered: the entry leaves the bell
    d2 = sent_offer(s, cl, "Werbespot " + who)
    valid_to(d2, day(2))
    tick()
    check(len(news(s, d2)[0]) == 1, f"{who}: a second quotation rings {news(s, d2)[0]}")
    r = s.post(B + f"{D}/{d2}/status", json={"status": answer})
    check(r.ok, f"{who}: status {answer} {r.text[:200]}")
    check(not news(s, d2)[0], f"{who}: {answer} -> no entry any more {news(s, d2)[0]}")
    # ---- refused: an invoice, a draft quotation
    r = s.post(B + D, json={"kind": "invoice", "lang": "de", "client_id": cl, "items": [{"title": "Schnitt", "qty": 1, "rate": 500}]})
    inv = r.json()["id"]
    r = s.post(B + f"{D}/{inv}/valid-until", json={"valid_until": day(10)})
    check(r.status_code == 409, f"{who}: an invoice has no validity to extend {r.status_code}")
    r = s.post(B + D, json={"kind": "offer", "lang": "de", "client_id": cl, "project_title": "Entwurf"})
    r = s.post(B + f"{D}/{r.json()['id']}/valid-until", json={"valid_until": day(10)})
    check(r.status_code == 409, f"{who}: a draft is changed in the editor, not extended {r.status_code}")
    # ---- the setting off: nothing rings
    r = s.put(B + OFF + "/settings", json={"offer_exp_notice": 0})
    check(r.ok and s.get(B + OFF + "/settings").json()["settings"].get("offer_exp_notice") == 0, f"{who}: the setting switches off {r.status_code}")
    d3 = sent_offer(s, cl, "Doku " + who, finalise=False)
    valid_to(d3, day(1))
    tick()
    check(not news(s, d3)[0], f"{who}: switched off -> no entry {news(s, d3)[0]}")
    s.put(B + OFF + "/settings", json={"offer_exp_notice": 1, "offer_exp_days": 5})
    check(s.get(B + OFF + "/settings").json()["settings"].get("offer_exp_days") == 5, f"{who}: the notice days are kept")
    tick()
    check(len(news(s, d3)[0]) == 1, f"{who}: switched on again -> the quotation rings {news(s, d3)[0]}")
    return did


A_DOC = run(A, "org", office(A, "Kunde Alpha GmbH"), "declined")

# ---------------------------------------------------------------- a person without an organisation
# freelancer-matrix: office
FID, Fr = freelancer(B, A)
run(Fr, "freelancer", office(Fr, "Privatkunde GmbH"), "accepted")

# ---------------------------------------------------------------- the boundary: another person cannot extend it
r = Fr.post(B + f"/api/office/docs/{A_DOC}/valid-until", json={"valid_until": day(40)})
check(r.status_code in (403, 404), f"another person: the organisation's quotation is not hers to extend {r.status_code}")
check(dbx("SELECT valid_until FROM office_docs WHERE id=?", (A_DOC,))[0][0] == day(20), "another person: the date stays as it was")

sys.exit(done("p5818_offer_expiry"))
