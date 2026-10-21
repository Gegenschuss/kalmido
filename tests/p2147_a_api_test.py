#!/usr/bin/env python3
"""2.147.0 API tests, part A: the country pack decides the office functions (#2459), single functions switched off (#2460),
the neutral base pack XX with its export for any tax advisor (#2461), the country of a new office and its change (#2462).
Invented companies, people and numbers only.
 - a new office asks its admin for the country once (pack_choose, suggestion by language / company country), members never;
   an office with saved settings or documents never asks (offices from before stay DE)
 - DE: every function on (DATEV, e-invoice, VAT return figures, tax dates, export, finalising rules), retention 8 / 10 years
 - features_off: only switchable functions (finalising rules 400, unknown 400), admin only (member 403, tenant-matrix: office); off = the routes
   answer 404 (DATEV booking batch, DATEV accounts, DATEV inbox, VAT return figures, tax dates GET / PUT, a new e-invoice
   XML), the send dialog gets no DATEV choice, the saved DATEV values stay; on again = everything back
 - e-invoice off: a newly finalised invoice gets no XML, the XML of one finalised before stays reachable
 - pack-switch preview: hidden / shown functions, open / finalised documents; unknown pack 404; member 403
 - XX: no DATEV / VAT return / tax dates, own VAT rates (labels "21 % VAT", new drafts calculate with them), XRechnung
   becomes ZUGFeRD (no buyer reference needed), retention editable (min 1 year); the finalised DE invoice keeps 19 %
 - back to DE: DATEV address, DATEV booking settings and switches unchanged, nothing lost
 - export (CSV / ZIP / check): booking list with invoice, payment, credit note; ZIP holds the CSV and the documents;
   member 403, agent 403, period over three years 400, function off 404
 - a person without an organisation (freelancer-matrix: office): own office asks for the country, base pack needs the company country before an
   invoice is finalised, the export works in the personal office
 - agents: GET /api/v1/office names the country pack and the functions as switched on
usage: p2147_a_api_test.py <datadir>"""
import io
import os
import subprocess
import sys
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,comments,office,clients"
O, D = "/api/office", "/api/office/docs"
FAILS, OKS = [], [0]
ALL = {"books.datev", "docs.einvoice", "books.vat_return", "books.tax_dates", "books.export_csv", "books.gobd"}


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
uid = {}
for u, n in (("bob", "Bob Member"), ("erin", "Erin Free")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
dbx("DELETE FROM org_members WHERE user_id=?", (uid["erin"],), write=True)
Bo, Er = sess("bob"), sess("erin")
for s in (A, Bo, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "office"], "org_id": ORG})
AG, AGT = r.json()["id"], r.json()["token"]
AH = {**H, "Authorization": "Bearer " + AGT}

# ---------------------------------------------------------------- #2462 a new office asks once
j = A.get(B + O + "/settings").json()
check(j.get("pack_choose") is True and j.get("pack_suggest") == "XX", f"#2462: new office, English: asked, base pack suggested ({j.get('pack_choose')}, {j.get('pack_suggest')})")
check(j["settings"]["pack"] == "DE" and j["pack"]["code"] == "DE", "#2462: until chosen the office works with DE as before")
check(Bo.get(B + O + "/settings").json().get("pack_choose") is False, "#2462: a member is never asked")
A.patch(B + "/api/settings", json={"lang": "de"})
check(A.get(B + O + "/settings").json().get("pack_suggest") == "DE", "#2462: German language -> DE suggested")
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel GmbH"}, "lang": "de", "datev_email": "inbox@example.com",
                                     "company_fields": {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg",
                                                        "country": "DE", "tax_number": "12/345/67890", "vat_id": "DE999999999",
                                                        "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"},
                                     "datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}})
check(r.ok, "setup: company settings " + r.text[:200])
check(A.get(B + O + "/settings").json().get("pack_choose") is False, "#2462: saved settings = never asked again")

# ---------------------------------------------------------------- #2459 DE: everything on
j = A.get(B + O + "/settings").json()
check(set(k for k, v in j["features"].items() if v) == ALL, f"#2459: DE offers every function, all on ({j['features']})")
check(j["pack"]["retention"]["receipts"] == 8 and j["pack"]["retention"]["books"] == 10 and j["pack"]["retention"]["editable"] is False,
      f"#2459: DE retention 8 / 10 years, fixed ({j['pack']['retention']})")
check(j["pack"]["offers"].get("books.period_lock") == "planned", "#2459: the 2.148 functions are known as planned")
check(set(j["pack"]["einvoice_formats"]) == {"zugferd", "xrechnung"}, "#2459: DE offers ZUGFeRD and XRechnung")
CL = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]


def invoice(s=A, client=None, rate=1000, extra=None):
    r = s.post(B + D, json=dict({"kind": "invoice", "client_id": client or CL, "service_from": "2026-03-01", "service_to": "2026-03-15",
                                 "items": [{"title": "Schnitt", "qty": 1, "rate": rate}]}, **(extra or {})))
    assert r.status_code == 201, r.text
    return r.json()["id"]


I1 = invoice()
r = A.post(B + f"{D}/{I1}/finalize")
check(r.ok, "DE: invoice finalised " + r.text[:200])
check((dbx("SELECT xml_sha256 FROM office_docs WHERE id=?", (I1,))[0][0] or "") != "", "DE: the finalised invoice has its e-invoice XML")
check(A.post(B + f"{D}/{I1}/payments", json={"date": "2026-03-20", "amount": "1190.00", "method": "transfer"}).ok, "DE: payment recorded")
TAX1 = A.get(B + f"{D}/{I1}").json()["totals"]["tax_lines"][0]["pct"]
check(float(TAX1) == 19, f"DE: 19 % on the invoice ({TAX1})")

# ---------------------------------------------------------------- #2460 switches
for bad, why in ((["books.gobd"], "finalising rules cannot be switched off"), (["nope"], "unknown function"), ("books.datev", "a list only")):
    check(A.put(B + O + "/settings", json={"features_off": bad}).status_code == 400, f"#2460: features_off {why} (400)")
check(Bo.put(B + O + "/settings", json={"features_off": ["books.datev"]}).status_code == 403, "#2460: a member may not switch (403)")
r = A.put(B + O + "/settings", json={"features_off": ["books.datev", "books.vat_return", "books.tax_dates"]})
check(r.ok and r.json()["features"]["books.datev"] is False and r.json()["features"]["docs.einvoice"] is True, "#2460: switched off, the answer names the functions " + r.text[:160])
P = "?from=2026-03-01&to=2026-03-31"
check(A.get(B + O + "/datev/extf" + P + "&check=1").status_code == 404, "#2460: DATEV off -> booking batch 404")
check(A.get(B + O + "/datev/accounts").status_code == 404, "#2460: DATEV off -> accounts 404")
check(A.post(B + f"{D}/{I1}/datev").status_code == 404, "#2460: DATEV off -> no copy to the DATEV inbox (404)")
ms = A.get(B + O + "/mail-status").json()
check(ms.get("datev_on") is False and ms.get("datev_email") == "", f"#2460: send dialog without DATEV ({ms})")
check(A.get(B + O + "/books/ustva?year=2026&period=q1").status_code == 404, "#2460: VAT return figures off -> 404")
check(A.get(B + O + "/tax-dates").status_code == 404 and A.put(B + O + "/tax-dates", json={"ustva": "quarter"}).status_code == 404,
      "#2460: tax dates off -> GET / PUT 404")
check(A.get(B + O + "/books?year=2026").json().get("accounts") is None, "#2460: DATEV off -> no SKR accounts in the bookkeeping")
s = A.get(B + O + "/settings").json()["settings"]
check(s["datev_email"] == "inbox@example.com" and s["datev_extf"].get("advisor_no") == "1234567", "#2460: off only hides: the DATEV values stay")
r = A.put(B + O + "/settings", json={"features_off": []})
check(r.ok and all(r.json()["features"][k] for k in ALL), "#2460: everything on again")
check(A.get(B + O + "/datev/extf" + P + "&check=1").ok, "#2460: DATEV on again -> booking batch check works")
check(A.get(B + O + "/books/ustva?year=2026&period=q1").ok and A.get(B + O + "/tax-dates").ok, "#2460: VAT return figures + tax dates back")
# e-invoice off: no XML for a new invoice, the old one keeps its file
A.put(B + O + "/settings", json={"features_off": ["docs.einvoice"]})
I2 = invoice(rate=500)
check(A.post(B + f"{D}/{I2}/finalize").ok, "#2460: finalising works with e-invoices off")
check((dbx("SELECT xml_sha256 FROM office_docs WHERE id=?", (I2,))[0][0] or "") == "", "#2460: e-invoice off -> no XML stored")
check(A.get(B + f"{D}/{I2}/xml").status_code == 404, "#2460: e-invoice off -> no XML for the new invoice (404)")
check(A.get(B + f"{D}/{I1}/xml").ok, "#2460: the XML of an invoice finalised before stays reachable")
A.put(B + O + "/settings", json={"features_off": []})

# ---------------------------------------------------------------- #2462 the warning before a change
r = A.get(B + O + "/pack-switch?code=XX")
j = r.json() if r.ok else {}
check(r.ok and {"books.datev", "books.vat_return", "books.tax_dates"} <= set(j.get("hidden") or []) and "docs.einvoice" not in (j.get("hidden") or []),
      "#2462: preview names the hidden functions " + r.text[:200])
check(j.get("locked_docs") == 2 and j.get("from") == "DE" and j.get("tax_editable") is True, f"#2462: preview counts finalised documents ({j.get('locked_docs')})")
check(A.get(B + O + "/pack-switch?code=ZZ").status_code == 404, "#2462: unknown pack 404")
check(Bo.get(B + O + "/pack-switch?code=XX").status_code == 403, "#2462: member 403")

# ---------------------------------------------------------------- #2461 the base pack
r = A.put(B + O + "/settings", json={"pack": "XX", "einvoice_format": "xrechnung"})
check(r.ok and r.json()["settings"]["pack"] == "XX", "#2461: switched to the base pack " + r.text[:160])
j = A.get(B + O + "/settings").json()
f = j["features"]
check(not f["books.datev"] and not f["books.vat_return"] and not f["books.tax_dates"] and f["docs.einvoice"] and f["books.export_csv"] and f["books.gobd"],
      f"#2461: base pack functions ({f})")
check(j["pack"]["neutral"] is True and j["pack"]["einvoice_formats"] == ["zugferd"] and j["pack"]["retention"]["editable"] is True, "#2461: base pack info " + str(j["pack"])[:200])
check(A.get(B + O + "/datev/extf" + P + "&check=1").status_code == 404, "#2461: no DATEV in the base pack")
r = A.put(B + O + "/settings", json={"tax_rates": {"standard": 21, "reduced": 9}, "retention_years": 6})
check(r.ok, "#2461: own rates + retention " + r.text[:160])
check(A.put(B + O + "/settings", json={"tax_rates": {"standard": 120}}).status_code == 400, "#2461: a rate over 100 % is refused")
j = A.get(B + O + "/settings").json()
check(j["pack"]["tax"]["standard"] == 21 and j["pack"]["tax"]["labels"]["en"]["standard"] == "21 % VAT" and j["pack"]["tax"]["labels"]["de"]["reduced"] == "9 % USt.",
      f"#2461: own rates with their labels ({j['pack']['tax'].get('labels', {}).get('en')})")
check(j["pack"]["retention"]["receipts"] == 6, f"#2461: own retention ({j['pack']['retention']})")
pk = {p["code"]: p for p in A.get(B + O + "/packs").json()["packs"]}
check("{rate}" not in str(pk["XX"]["tax"]["labels"]), "#2461: the pack list shows no {rate} placeholder")
I3 = invoice(rate=100)
check(float(A.get(B + f"{D}/{I3}").json()["totals"]["tax_lines"][0]["pct"]) == 21, "#2461: a new draft calculates with the own rate")
r = A.post(B + f"{D}/{I3}/finalize")
check(r.ok, "#2461: XRechnung setting becomes ZUGFeRD in the base pack (no buyer reference needed) " + r.text[:200])
x = A.get(B + f"{D}/{I3}/xml")
check(x.ok and b"xrechnung" not in x.content.lower(), "#2461: the base pack's XML is EN 16931 without XRechnung")
check(float(A.get(B + f"{D}/{I1}").json()["totals"]["tax_lines"][0]["pct"]) == 19, "#2461: the finalised DE invoice keeps 19 %")

# ---------------------------------------------------------------- back to DE: nothing lost
for did in (I1, I2, I3):  # into the period of the checks below (finalised today)
    dbx("UPDATE office_docs SET date='2026-03-10' WHERE id=?", (did,), write=True)
r = A.put(B + O + "/settings", json={"pack": "DE"})
j = A.get(B + O + "/settings").json()
s = j["settings"]
check(r.ok and all(j["features"][k] for k in ALL), "#2462: back to DE: every function again")
check(s["datev_email"] == "inbox@example.com" and s["datev_extf"].get("advisor_no") == "1234567" and s["datev_extf"].get("client_no") == "12345",
      "#2462: DE -> XX -> DE keeps the DATEV address and booking settings")
check(j["pack"]["tax"]["standard"] == 19 and j["pack"]["retention"]["receipts"] == 8, "#2462: DE ignores the own rates / retention of the base pack")
check(len(dbx("SELECT id FROM office_docs WHERE org_id=?", (ORG,))) == 3, "#2462: no document lost")
check(A.get(B + O + "/datev/extf" + P + "&check=1").json().get("count", 0) >= 2, "#2462: the DATEV batch sees the invoices again")

# ---------------------------------------------------------------- #2461 the export for any tax advisor
CR = A.post(B + f"{D}/{I2}/credit")
check(CR.status_code == 201, "export: a credit note " + CR.text[:120])
check(A.post(B + f"{D}/{CR.json()['id']}/finalize").ok, "export: credit note finalised")
X = O + "/books/export?from=2026-01-01&to=2026-12-31"
dbx("UPDATE office_docs SET date='2026-03-10' WHERE id=?", (CR.json()["id"],), write=True)
r = A.get(B + X + "&check=1")
check(r.ok and r.json()["documents"] == 4 and r.json()["rows"] >= 5, "export: check counts documents and rows " + r.text[:160])
r = A.get(B + X)
txt = r.content.decode("utf-8-sig") if r.ok else ""
lines = [ln for ln in txt.split("\r\n") if ln]
check(r.ok and r.headers.get("Content-Type", "").startswith("text/csv") and lines and lines[0].split(";")[0] == "Type", "export: CSV with header " + txt[:120])
check(any(";Credit note;" in ";" + ln + ";" and ";-" in ln for ln in lines) and any(ln.startswith("Payment;") for ln in lines),
      "export: credit note negative, payment row " + " | ".join(lines[:6])[:300])
check(any("1.190,00" in ln or "1190,00" in ln for ln in lines), "export: DE pack = decimal comma, semicolon")
r = A.get(B + X + "&zip=1")
names = zipfile.ZipFile(io.BytesIO(r.content)).namelist() if r.ok else []
check(r.ok and any(n.endswith(".csv") for n in names) and sum(1 for n in names if n.startswith("documents/") and n.endswith(".pdf")) == 4
      and any(n.startswith("documents/") and n.endswith(".xml") for n in names), f"export: ZIP with list, PDFs and XML ({names})")
check(Bo.get(B + X).status_code == 403, "export: member 403")
check(requests.get(B + X, headers=AH).status_code in (401, 403), "export: agent token refused")
check(A.get(B + O + "/books/export?from=2020-01-01&to=2026-12-31").status_code == 400, "export: more than three years 400")
A.put(B + O + "/settings", json={"features_off": ["books.export_csv"]})
check(A.get(B + X).status_code == 404, "export: switched off -> 404")
A.put(B + O + "/settings", json={"features_off": []})

# ---------------------------------------------------------------- agents see the functions
check(A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok and A.put(B + O + "/settings", json={"agents_read": 1}).ok,
      "agents: the area's admin lets the agent into the office (both switches)")
A.put(B + O + "/settings", json={"features_off": ["books.datev"]})
r = requests.get(B + "/api/v1/office", headers=AH)
check(r.ok and r.json().get("country_pack") == "DE" and r.json().get("features", {}).get("books.datev") is False
      and r.json()["features"].get("docs.einvoice") is True, "agents: /api/v1/office names the country pack and the switched functions " + r.text[:200])
A.put(B + O + "/settings", json={"features_off": []})

# ---------------------------------------------------------------- P4: a person without an organisation
j = Er.get(B + O + "/settings").json()
check(j.get("personal") in (1, True) and j.get("pack_choose") is True and j.get("role") == "admin",
      f"P4: the own office asks its owner for the country ({j.get('personal')}, {j.get('pack_choose')}, {j.get('role')}, {j.get('error')})")
r = Er.put(B + O + "/settings", json={"pack": "XX", "company": {"name": "Erin Design"},
                                      "company_fields": {"name": "Erin Design", "street": "Rue 1", "zip": "1000", "city": "Bruxelles",
                                                         "vat_id": "BE0999999999", "iban": "BE68539007547034"}})
check(r.ok and Er.get(B + O + "/settings").json().get("pack_choose") is False, "P4: the base pack chosen in the personal office " + r.text[:120])
keys = {x["key"] for x in Er.get(B + O + "/texts").json().get("items", []) if x.get("kind") == "rights_territory"}
check(keys == {"world", "region", "national"}, f"#2462: the first choice swaps the unchanged DE text blocks for the base pack's ({keys})")
check(Er.put(B + O + "/settings", json={"features_off": ["books.export_csv"]}).ok and Er.put(B + O + "/settings", json={"features_off": []}).ok,
      "P4: the owner switches functions of the personal office")
EC = Er.post(B + "/api/clients", json={"name": "Client SA", "street": "Avenue 2", "zip": "1050", "city": "Bruxelles", "country": "BE"}).json()["id"]
E1 = invoice(Er, EC, 300)
r = Er.post(B + f"{D}/{E1}/finalize")
check(r.status_code == 400 and "country of the company" in r.text, "P4: the base pack needs the company country before finalising " + r.text[:200])
Er.put(B + O + "/settings", json={"company_fields": {"country": "BE"}})
check(Er.post(B + f"{D}/{E1}/finalize").ok, "P4: with the country the invoice is finalised")
dbx("UPDATE office_docs SET date='2026-03-10' WHERE id=?", (E1,), write=True)
r = Er.get(B + O + "/books/export?from=2026-01-01&to=2026-12-31")
txt = r.content.decode("utf-8-sig") if r.ok else ""
check(r.ok and txt.split("\r\n")[0].split(",")[0] == "Type" and "360.00" in txt, "P4: base pack export = comma separated, decimal point " + txt[:200])
check(Er.get(B + O + "/datev/extf" + P + "&check=1").status_code == 404, "P4: no DATEV in the personal office with the base pack")

print(f"p2147_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
