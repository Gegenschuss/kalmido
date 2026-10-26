#!/usr/bin/env python3
"""2.299.0 D (#3193): the fixed check of a receipt at the receipt and in the receipts list of the bookkeeping. Invented
companies, people and figures only (texts made here, @example.com). freelancer-matrix: files, office  tenant-matrix: document
 - a person without an organisation (private documents, her personal office): a complete invoice has no hints; one whose
   figures do not add up and without a tax id carries checks (calc_sum warn, taxid "Missing") with the sentence in her
   language (German: comma, "Bitte prüfen"), stored as codes (doc_meta.rchk, no content)
 - the receipts list: row "hints", the number of receipts with hints, the filter hints=1; Hide hints (one undo step: show)
   takes it out of the list; a new, different hint (the category becomes entertainment) shows again; a receipt not checked
   yet (rchk empty) is checked by the next list request (hints_pending 0)
 - rights: another person 404, an unknown action 400, an agent reads the hints through the API v1 (shared document) but gets
   403 on hide; an organisation's document: a person of another organisation 404, a member without office rights 403 on the
   list; a letter has no checks
usage: p2299_d_api_test.py <datadir>   (P2299D_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import base64
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
import requests  # noqa: E402
from kt import B, check, sess, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
RL = "/api/office/books/receipts"
P = {"from": "2026-01-01", "to": "2026-12-31"}
FEAT = "cal,comments,collab,office,clients,docs,files"

FULL = """Muster Werkstatt GmbH
Industrieweg 12
12345 Beispielstadt
USt-IdNr.: DE273645199

Rechnung an:
Beispiel Agentur
Hauptstraße 7
54321 Musterdorf

Rechnungsnummer: RE-2026-501
Rechnungsdatum: 12.10.2026

Pos  Menge  Leistung                 Preis
1    4 h    Wartung Druckmaschine    320,00 EUR
2    1 Stk  Ersatzteil Walze          80,00 EUR

Nettobetrag                          400,00 EUR
zzgl. 19 % MwSt                       76,00 EUR
Gesamtbetrag                         476,00 EUR
"""
BAD = (FULL.replace("USt-IdNr.: DE273645199\n", "").replace("RE-2026-501", "RE-2026-502")
       .replace("Gesamtbetrag                         476,00", "Gesamtbetrag                         496,00"))


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def upload(s, name, text, ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, text.encode(), "text/plain")})
    assert r.ok, r.text
    j = r.json()
    return (j.get("ids") or [x["id"] for x in j.get("docs") or j.get("items") or []])[0]


def done(s, nid):
    def f():
        r = s.get(B + f"/api/docs/{nid}")
        return r.json() if r.ok and r.json()["state"] in ("done", "failed") else None
    return until(f, 60)


def codes(d):
    return [x["code"] for x in ((d or {}).get("checks") or {}).get("items") or []]


def receipt(s, nid, category="Material", amount=None):
    if amount:  # the list counts a receipt with an amount and a day only
        assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": "2026-10-12"}).ok
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": category, "vat_pct": "19", "keep": True})
    assert r.ok, r.text


def lst(s, **q):
    r = s.get(B + RL, params={**P, **q})
    assert r.ok, (r.status_code, r.text[:300])
    return r.json()


def row(j, nid):
    return next((x for x in j["rows"] if x["node_id"] == nid), None)


def ck(s, nid, act):
    return s.post(B + f"/api/docs/{nid}/checks", json={"do": act})


kt.fresh(env={"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2299D")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
for u, n in (("carol", "Carol Other"), ("bob", "Bob Member")):
    assert A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"}).ok
Ca, Bo = sess("carol"), sess("bob")
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
for s in (A, Ca, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
FID, Fr = freelancer(B, A)  # freelancer-matrix: files, office (private documents, the personal office's receipts)

# ---- schema: three new columns, nothing renamed
cols = {r[0] for r in kt.dbx("SELECT column_name FROM information_schema.columns WHERE table_name='doc_meta' AND column_name LIKE 'rchk%'")}
check(cols == {"rchk", "rchk_at", "rchk_ok"}, f"doc_meta.rchk / rchk_at / rchk_ok added ({cols})")

# ---- the freelancer: a complete invoice, one that does not add up
D1 = upload(Fr, "rechnung-ok.txt", FULL)
D2 = upload(Fr, "rechnung-falsch.txt", BAD)
d1, d2 = done(Fr, D1), done(Fr, D2)
check(d1 and d1["state"] == "done" and d1.get("extracted"), f"recognised {d1 and d1['state']}")
check(d1 and d1.get("checks") is None, f"a complete invoice: no hints {d1 and d1.get('checks')}")
c2 = (d2 or {}).get("checks") or {}
check({"calc_sum", "taxid"} <= set(codes(d2)) and c2.get("hidden") is False, f"figures + tax id: hints {codes(d2)}")
x = next((i for i in c2.get("items") or [] if i["code"] == "calc_sum"), {})
check(x.get("level") == "warn" and x.get("text") == "Please check: net 400.00 + VAT 76.00 gives 476.00, the receipt says 496.00", f"the sentence {x}")
x = next((i for i in c2.get("items") or [] if i["code"] == "taxid"), {})
check(x.get("level") == "warn" and x.get("text", "").startswith("Missing:"), f"no tax id, no label: Missing {x}")
check(set(c2["items"][0]) == {"code", "level", "text"} and c2["items"][0]["level"] == "warn", "items: code, level, text; warnings first")
Fr.patch(B + "/api/settings", json={"lang": "de"})
x = next((i for i in (Fr.get(B + f"/api/docs/{D2}").json().get("checks") or {}).get("items") or [] if i["code"] == "calc_sum"), {})
check(x.get("text") == "Bitte prüfen: Netto 400,00 + Steuer 76,00 ergibt 476,00, auf dem Beleg steht 496,00", f"German: comma + Bitte prüfen {x}")
Fr.patch(B + "/api/settings", json={"lang": "en"})
raw = kt.dbx("SELECT rchk, rchk_at FROM doc_meta WHERE node_id=?", (D2,))[0]
check("calc_sum" in raw[0].split(",") and raw[1], f"stored after the recognition run: codes + state {raw}")
check(kt.dbx("SELECT rchk FROM doc_meta WHERE node_id=?", (D1,))[0][0] == ".", "stored: nothing to say = '.'")

# ---- the receipts list of the personal office
receipt(Fr, D1, amount="476.00")
receipt(Fr, D2, amount="496.00")
j = lst(Fr)
check(row(j, D2) and row(j, D2)["hints"] >= 2 and row(j, D1) and row(j, D1)["hints"] == 0, f"rows: hints {j['rows']}")
check(j.get("hints") == 1 and j.get("hints_pending") == 0, f"one receipt with hints, none pending {j.get('hints')} {j.get('hints_pending')}")
j = lst(Fr, hints="1")
check([x["node_id"] for x in j["rows"]] == [D2] and j["total"]["count"] == 1, f"filter: only with hints {[x['node_id'] for x in j['rows']]}")

# hide (one undo step: show)
check(ck(Fr, D2, "nonsense").status_code == 400, "an unknown action: 400")
r = ck(Fr, D2, "hide")
check(r.ok and (r.json()["doc"].get("checks") or {}).get("hidden") is True, f"hidden {r.status_code} {r.text[:200]}")
j = lst(Fr, hints="1")
check(j["rows"] == [] and j["hints"] == 0, f"hidden: out of the list {j['rows']}")
r = ck(Fr, D2, "show")
check(r.ok and r.json()["doc"]["checks"]["hidden"] is False and lst(Fr)["hints"] == 1, "show: back in the list")
ck(Fr, D2, "hide")
# a new, different hint shows again: the category becomes entertainment (the meal details)
receipt(Fr, D2, "Bewirtung")
d2 = Fr.get(B + f"/api/docs/{D2}").json()
check("meal" in codes(d2) and d2["checks"]["hidden"] is False, f"a new hint: shown again {codes(d2)}")
j = lst(Fr)
check(row(j, D2)["hints"] == 1 and j["hints"] == 1, f"the list counts the new hint only {row(j, D2)}")

# a receipt not checked yet (as before 2.299): the next list request checks it
dbw("UPDATE doc_meta SET rchk='', rchk_at='', rchk_ok='' WHERE node_id=?", (D2,))
j = lst(Fr)
raw = kt.dbx("SELECT rchk FROM doc_meta WHERE node_id=?", (D2,))[0][0]
check("calc_sum" in raw and row(j, D2)["hints"] >= 3 and j["hints_pending"] == 0, f"checked by the list {raw} {row(j, D2)}")

# ---- rights
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
check(ck(Ca, D2, "hide").status_code == 404 and Ca.get(B + f"/api/docs/{D2}").status_code == 404, "another person: 404")
r = A.post(B + "/api/admin/agents", json={"username": "fridabot", "display_name": "Fridabot"})
assert r.status_code == 201, r.text
AG, tok = r.json()["id"], r.json().get("token") or ""
dbw("DELETE FROM org_members WHERE user_id=?", (AG,))
dbw("UPDATE agents SET org_id=NULL, owner_id=? WHERE user_id=?", (FID, AG))
check(Fr.post(B + f"/api/files/nodes/{D2}/shares", json={"agent_id": AG, "role": "edit"}).ok, "setup: shared with the agent")
AGS = requests.Session()  # an agent's token, no browser header
AGS.headers.update({"Authorization": "Bearer " + tok})
r = AGS.get(B + f"/api/v1/documents/{D2}")
check(r.ok and "calc_sum" in codes(r.json()), f"the agent reads the hints (API v1) {r.status_code} {r.text[:200]}")
r = AGS.post(B + f"/api/docs/{D2}/checks", json={"do": "hide"})
check(r.status_code == 403, f"the agent cannot hide them (403) {r.status_code} {r.text[:120]}")
spec = A.get(B + "/api/v1/openapi.json")
check(spec.ok and "checks" in spec.json()["components"]["schemas"]["Document"]["properties"], "OpenAPI: Document.checks")

# an organisation's document
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
D3 = upload(A, "rechnung-org.txt", BAD.replace("RE-2026-502", "RE-2026-503"), ws=f"org:{ORG}")
d3 = done(A, D3)
check("calc_sum" in codes(d3), f"org document: hints {codes(d3)}")
check(ck(Ca, D3, "hide").status_code == 404, "another organisation: 404")
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(Bo.get(B + RL, params=P).status_code == 403, "a member without office rights: the list 403")
receipt(A, D3, amount="496.00")
check(row(lst(A), D3) and row(lst(A), D3)["hints"] >= 2, "org admin: the list shows the hints")

# a letter: nothing
D4 = upload(Fr, "brief.txt", "Liebe Frau Beispiel,\nanbei der Plan fuer 2027.\nViele Gruesse\n")
d4 = done(Fr, D4)
check(d4 and d4.get("checks") is None and kt.dbx("SELECT rchk FROM doc_meta WHERE node_id=?", (D4,))[0][0] == ".", f"a letter: no checks {d4 and d4.get('checks')}")

sys.exit(kt.done("p2299_d_api"))
