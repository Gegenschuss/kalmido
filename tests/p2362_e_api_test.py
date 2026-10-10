#!/usr/bin/env python3
"""2.36.2 API tests, part E: the foundation of Office & finance (#1021) and its tenant boundary (#1142 office part, #1146),
own container in mode workspaces (start.sh). Invented companies, people and test IBAN only.
 - finalising (POST /api/office/docs/<id>/finalize): the head (PATCH), the positions (PUT items), the number and deleting
   answer 409 afterwards; status changes and duplicating still work (the copy is an open draft without the snapshot);
   finalising twice = 409
 - snapshot: the print model of a finalised document stays the same after the company data, the logo, the colour, the
   settings or the services change (sums, company lines, labels); positions carry tax_pct / net / tax_amount as decimal text
 - numbers (P2): offer_number_at "finalize" = a draft without number, the number comes with finalising; the default
   "create" numbers at once as before
 - period of service (service_from / service_to) in the head and the print model; to before from = 400
 - office_company (structured company fields): saved through the settings, validated (IBAN check digits, country ISO-2,
   e-mail), printed instead of the free lines (free lines stay the fallback of an empty group)
 - client billing fields: create / change / validate; not in agent answers
 - office_doc_items.org_id filled on every new row; a position written without it (older version) gets it at the next start
 - office log: create, change (before / after), positions, finalise, open / PDF / render (once per 10 minutes), master data,
   settings, company, export, import; GET .../log only for the organisation's admin (403 member, 404 foreign document)
 - import: ids in the file that map to no row are left empty and listed (counts.unmapped)
 - tenant-matrix: office -- the second organisation and a private person: 404 / 400 on every new route; agent token 403
   without content on /api/office/*; an unknown master data kind is 404
usage: p2362_e_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
TEST_IBAN = "DE02120300000000202051"


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
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


FEAT = "cal,comments,collab,office,clients"
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Private")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"

# ---------------------------------------------------------------- settings, services, client (invented data)
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht GmbH", "lines": ["Hafenstraße 12", "20457 Hamburg"],
                                                 "bank_lines": ["Beispielbank", "IBAN DE02 1203 0000 0000 2020 51"]},
                                     "lang": "de", "currency": "EUR", "offer_scheme": "KVA-{yyyy}-{seq:03}", "color": "#2f5d8a"})
check(r.ok, "settings saved " + r.text[:200])
st = A.get(B + O + "/settings").json()
check(st.get("company_fields", {}).get("street") == "" and st["settings"].get("offer_number_at") == "create", "settings: empty company fields, numbers at creation by default")
S1 = A.post(B + O + "/services", json={"name_de": "Schnitt", "name_en": "Editing", "category": "Video", "daily_rate": 1000, "raw_fee": 1, "producing": 1}).json()["id"]
S2 = A.post(B + O + "/services", json={"name_de": "Nutzungsrechte Musik", "name_en": "Music licence", "category": "Buyout", "daily_rate": 100,
                                       "unit": "flat", "tax": "reduced"}).json()["id"]
r = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "address": "Marktstraße 5\n50667 Köln", "street": "Marktstraße 5", "zip": "50667",
                                     "city": "Köln", "country": "de", "vat_id": "DE 123456789", "customer_no": "K-1001", "buyer_reference": "991-12345-67",
                                     "email_invoice": "rechnung@beispielkunde.example", "payment_terms_days": 14})
check(r.status_code == 201, "client with billing fields " + r.text[:200])
CL = r.json()["id"]
cl = A.get(B + f"/api/clients/{CL}").json()
check(cl.get("billing") == {"street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE", "vat_id": "DE123456789", "customer_no": "K-1001",
                            "buyer_reference": "991-12345-67", "email_invoice": "rechnung@beispielkunde.example", "payment_terms_days": 14},
      f"client billing fields stored and normalised: {cl.get('billing')}")
check(A.patch(B + f"/api/clients/{CL}", json={"country": "Deutschland"}).status_code == 400, "client: country must be ISO-2")
check(A.patch(B + f"/api/clients/{CL}", json={"email_invoice": "nope"}).status_code == 400, "client: invoice e-mail validated")
check(A.patch(B + f"/api/clients/{CL}", json={"payment_terms_days": 400}).status_code == 400, "client: payment terms 0..365")
check(A.patch(B + f"/api/clients/{CL}", json={"payment_terms_days": 30}).json()["billing"]["payment_terms_days"] == 30, "client: payment terms changed")
for path in ("/api/v1/clients", f"/api/v1/clients/{CL}"):
    r = requests.get(B + path, headers=AGH)
    check("billing" not in r.text and "991-12345-67" not in r.text, f"agent: no billing fields in {path} ({r.status_code})")

# ---------------------------------------------------------------- company fields (P4)
r = A.put(B + O + "/settings", json={"company_fields": {"iban": "DE00 1234"}})
check(r.status_code == 400, "company: an IBAN with wrong check digits is refused")
check(A.put(B + O + "/settings", json={"company_fields": {"country": "DEU"}}).status_code == 400, "company: country ISO-2")
check(A.put(B + O + "/settings", json={"company_fields": {"email": "x"}}).status_code == 400, "company: e-mail validated")
check(A.put(B + O + "/settings", json={"company_fields": {"bic": "XYZ"}}).status_code == 400, "company: BIC validated")
r = A.put(B + O + "/settings", json={"company_fields": {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                        "country": "de", "email": "hallo@nordlicht.example", "phone": "+49 40 000000",
                                                        "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN.lower(),
                                                        "bic": "BYLADEM1001", "bank_name": "Beispielbank", "register_court": "Amtsgericht Hamburg",
                                                        "register_no": "HRB 00000", "managing_directors": "Jana Muster"}})
check(r.ok and r.json()["company_fields"]["iban"] == TEST_IBAN and r.json()["company_fields"]["country"] == "DE", "company fields saved (IBAN normalised) " + r.text[:200])
check(Bo.put(B + O + "/settings", json={"company_fields": {"street": "x"}}).status_code == 403, "company fields: admin only")
check(Bo.get(B + O + "/settings").json()["company_fields"]["street"] == "Hafenstraße 12", "company fields: members read them")

# ---------------------------------------------------------------- a quotation, printed from the fields
r = A.post(B + D, json={"project_title": "Imagefilm", "client_id": CL})
check(r.status_code == 201, "new quotation " + r.text[:200])
DOC = r.json()["id"]
check(r.json()["number"].startswith("KVA-") and r.json()["locked"] is False and r.json()["can_edit"] is True, "numbered at creation (default), open")
r = A.put(B + f"{D}/{DOC}/items", json={"items": [{"service_id": S1, "qty": 3}, {"service_id": S2, "qty": 1}]})
check(r.ok and r.json()["totals"]["net"] == 3700, "positions set: 3 x 1000 + 100 + 1 producing day x 600 = 3700 " + r.text[:80])
NET = r.json()["totals"]["net"]
GROSS = r.json()["totals"]["gross"]
rows = dbx("SELECT org_id FROM office_doc_items WHERE doc_id=?", (DOC,))
check(len(rows) == 2 and all(x[0] == ORG for x in rows), f"office_doc_items.org_id filled: {rows}")
rd = A.get(B + f"{D}/{DOC}/render").json()
co = rd["company"]
check(co["lines"] == ["Hafenstraße 12", "20457 Hamburg"] and any("DE02 1203 0000 0000 2020 51" in x for x in co["bank_lines"])
      and any("12/345/67890" in x for x in co["bank_lines"]) and any("HRB 00000" in x for x in co["register_lines"])
      and any("hallo@nordlicht.example" in x for x in co["contact_lines"]), f"print lines made from the fields: {co}")
check(rd["locked"] is False and rd["pack_version"], "render: open, with the pack version")
# period of service
check(A.patch(B + f"{D}/{DOC}", json={"service_from": "2026-11-02", "service_to": "2026-11-01"}).status_code == 400, "period of service: to before from = 400")
r = A.patch(B + f"{D}/{DOC}", json={"service_from": "2026-11-02", "service_to": "2026-11-06"})
check(r.ok and r.json()["service_from"] == "2026-11-02" and r.json()["service_to"] == "2026-11-06", "period of service saved")
meta = dict((k, v) for k, v in A.get(B + f"{D}/{DOC}/render").json()["meta"])
check(meta.get("Leistungszeitraum") == "02.11.2026 – 06.11.2026", f"period of service printed: {meta}")

# ---------------------------------------------------------------- finalise (P1)
check(Ca.post(B + f"{D}/{DOC}/finalize").status_code in (400, 404) and Da.post(B + f"{D}/{DOC}/finalize").status_code in (400, 404),
      "tenant-matrix: office -- finalise: other organisation / private person cannot")
check(requests.post(B + f"{D}/{DOC}/finalize", headers=AGH).status_code == 403, "agent: finalise 403")
r = Bo.post(B + f"{D}/{DOC}/finalize")
check(r.ok and r.json()["locked"] is True and r.json()["locked_at"] and r.json()["can_edit"] is False and r.json()["can_delete"] is False
      and r.json()["locked_by_name"] == "Bob Member", "a member finalises " + r.text[:200])
NUM = r.json()["number"]
check("sender" not in r.json() and "tax_snapshot" not in r.json(), "the snapshot columns stay on the server")
check(Bo.post(B + f"{D}/{DOC}/finalize").status_code == 409, "finalise twice: 409")
r = A.patch(B + f"{D}/{DOC}", json={"project_title": "anders"})
check(r.status_code == 409 and "finalised" in r.json().get("error", ""), "finalised: PATCH 409 with a reason " + r.text[:120])
check(A.put(B + f"{D}/{DOC}/items", json={"items": []}).status_code == 409, "finalised: PUT items 409")
check(A.post(B + f"{D}/{DOC}/number", json={"number": "X-1"}).status_code == 409 and A.post(B + f"{D}/{DOC}/number", json={}).status_code == 409, "finalised: number 409")
check(A.delete(B + f"{D}/{DOC}").status_code == 409, "finalised: delete 409 (admin)")
check(Bo.delete(B + f"{D}/{DOC}").status_code == 403, "finalised: a member still gets 403 on delete")
check(A.get(B + f"{D}/{DOC}").json()["project_title"] == "Imagefilm", "finalised: unchanged")
r = A.post(B + f"{D}/{DOC}/status", json={"status": "sent"})
check(r.ok and r.json()["status"] == "sent", "finalised quotation: status still changes")
items = dbx("SELECT tax_pct, net, tax_amount FROM office_doc_items WHERE doc_id=? ORDER BY sort", (DOC,))
check(items == [("19", "3000.00", "570.00"), ("7", "100.00", "7.00")], f"positions carry tax_pct / net / tax_amount as decimal text: {items}")
snap = dbx("SELECT pack_version, sender IS NOT NULL, recipient_snapshot IS NOT NULL, tax_snapshot IS NOT NULL FROM office_docs WHERE id=?", (DOC,))[0]
check(snap[0] and snap[1] == 1 and snap[2] == 1 and snap[3] == 1, f"snapshot columns written: {snap}")
before = A.get(B + f"{D}/{DOC}/render").json()

# change everything the print reads live
A.put(B + O + "/settings", json={"company_fields": {"street": "Neuer Weg 1", "iban": "", "tax_number": "99/999/99999"}, "color": "#aa3300",
                                 "company": {"name": "Andere GmbH"}})
A.patch(B + O + f"/services/{S1}", json={"daily_rate": 2000, "tax": "reduced"})
A.patch(B + f"/api/clients/{CL}", json={"name": "Umbenannt AG", "street": "Andere Straße 9"})
after = A.get(B + f"{D}/{DOC}/render").json()
for k in ("company", "totals", "lines", "labels", "recipient", "meta", "pack_version"):
    check(before[k] == after[k], f"snapshot: {k} unchanged after company / service / client changes")
check(after["totals"]["net"] == NET and after["totals"]["gross"] == GROSS, "snapshot: frozen sums")
r = A.get(B + f"{D}/{DOC}/pdf")
check(r.ok and r.headers.get("Content-Type", "").startswith("application/pdf") and r.content[:5] == b"%PDF-", "PDF of a finalised document")
# an open document follows the changes
r = A.post(B + D, json={"project_title": "Offen"})
OPEN = r.json()["id"]
A.put(B + f"{D}/{OPEN}/items", json={"items": [{"service_id": S1, "qty": 1}]})
ro = A.get(B + f"{D}/{OPEN}/render").json()
it0 = next(x for x in ro["lines"] if x["kind"] == "item")
check(ro["company"]["lines"][0] == "Neuer Weg 1" and ro["company"]["name"] == "Studio Nordlicht GmbH" and it0["rate"] == 2000, f"open documents use the live data: {ro['company']['lines']} {it0['rate']}")
check(not any("IBAN" in x for x in ro["company"]["bank_lines"]) and any("99/999/99999" in x for x in ro["company"]["bank_lines"]), "an emptied field drops its line")
# free lines are the fallback of a group without fields
A.put(B + O + "/settings", json={"company_fields": {k: "" for k in ("street", "zip", "city", "country")}})
ro = A.get(B + f"{D}/{OPEN}/render").json()
check(ro["company"]["lines"] == ["Hafenstraße 12", "20457 Hamburg"], f"empty address fields: the free lines print: {ro['company']['lines']}")

# ---------------------------------------------------------------- duplicate a finalised document
r = A.post(B + f"{D}/{DOC}/duplicate")
check(r.status_code == 201 and r.json()["locked"] is False and r.json()["number"] and r.json()["number"] != NUM and r.json()["status"] == "draft",
      "duplicate of a finalised document: an open draft with a new number " + r.text[:160])
DUP = r.json()["id"]
check(dbx("SELECT locked_at, sender, tax_snapshot FROM office_docs WHERE id=?", (DUP,))[0] == (None, None, None), "the copy has no snapshot")
check(dbx("SELECT COUNT(*) FROM office_doc_items WHERE doc_id=? AND org_id=? AND tax_pct IS NULL", (DUP, ORG))[0][0] == 2, "the copy's positions: own org_id, no frozen values")
check(A.patch(B + f"{D}/{DUP}", json={"project_title": "Fassung 2"}).ok, "the copy can be changed")

# ---------------------------------------------------------------- numbers at finalising (P2)
check(A.put(B + O + "/settings", json={"offer_number_at": "sometimes"}).status_code == 400, "offer_number_at validated")
check(A.put(B + O + "/settings", json={"offer_number_at": "finalize"}).ok, "quotations numbered at finalising")
r = A.post(B + D, json={"project_title": "Ohne Nummer"})
ND = r.json()["id"]
check(r.status_code == 201 and r.json()["number"] == "" and r.json()["number_at_finalize"] is True, "a draft without number " + r.text[:120])
r = A.post(B + f"{D}/{DUP}/duplicate")
check(r.status_code == 201 and r.json()["number"] == "", "duplicate in this mode: also without number")
A.delete(B + f"{D}/{r.json()['id']}")
r = A.post(B + f"{D}/{ND}/finalize")
check(r.ok and r.json()["number"].startswith("KVA-") and r.json()["locked"], f"finalising assigns the number: {r.json().get('number')}")
nums = [x["number"] for x in A.get(B + D).json()["docs"] if x["number"]]
check(len(nums) == len(set(nums)), f"numbers stay unique in the organisation: {nums}")
A.put(B + O + "/settings", json={"offer_number_at": "create"})

# ---------------------------------------------------------------- office log
check(Bo.get(B + f"{D}/{DOC}/log").status_code == 403 and Bo.get(B + O + "/log").status_code == 403, "log: members 403")
check(Ca.get(B + f"{D}/{DOC}/log").status_code in (400, 403, 404) and Da.get(B + O + "/log").status_code in (400, 403), "tenant-matrix: office -- log: others cannot")
lg = A.get(B + f"{D}/{DOC}/log").json()["log"]
acts = [x["action"] for x in lg]
for a in ("create", "items", "update", "finalize", "status", "render", "pdf"):
    check(a in acts, f"log of the document has '{a}' ({acts})")
fin = next(x for x in lg if x["action"] == "finalize")
check(fin["user_name"] == "Bob Member" and fin["detail"].get("number") == NUM and fin["detail"].get("gross") == GROSS, f"log: finalise entry {fin}")
upd = next(x for x in lg if x["action"] == "update")
check(upd["detail"]["after"].get("service_to") == "2026-11-06" and "service_to" in upd["detail"]["before"], f"log: before / after of a change {upd['detail']}")
n_open = acts.count("open")
A.get(B + f"{D}/{DOC}")
A.get(B + f"{D}/{DOC}")
check([x["action"] for x in A.get(B + f"{D}/{DOC}/log").json()["log"]].count("open") <= max(1, n_open), "log: reads of the same person are written once per 10 minutes")
check(acts.count("open") <= 1 and acts.count("render") <= 1, f"log: render read once ({acts.count('render')})")
A.get(B + O + "/export")
r = A.post(B + O + "/import", json={"kalmido_office": 1, "sets": [{"id": 5, "name": "Kamera-Set", "items": [{"equipment_id": 777, "qty": 1}]}],
                                    "contracts": [{"id": 9, "name": "Rahmenvertrag Test", "rates": {"888": 500}, "rights_time_id": 999}],
                                    "settings": {"producing_service_id": 4242}})
um = r.json().get("counts", {}).get("unmapped") or []
check(r.ok and {(x["in"], x["field"], x["id"]) for x in um} >= {("sets", "items", 777), ("contracts", "rates", 888), ("contracts", "rights_time_id", 999)},
      f"import: ids that map to nothing are reported {um} {r.text[:200]}")
sets = A.get(B + O + "/sets").json()["items"]
ct = next(x for x in A.get(B + O + "/contracts").json()["items"] if x["name"] == "Rahmenvertrag Test")
check(any(x["name"] == "Kamera-Set" and x["items"] == [] for x in sets) and ct["rates"] == {} and ct["rights_time_id"] is None, "import: unmapped ids left empty")
glog = A.get(B + O + "/log", params={"limit": 200}).json()["log"]
tg = {(x["action"], x["target"]) for x in glog}
for want in (("update", "company"), ("update", "settings"), ("create", "services"), ("update", "services"), ("export", "master_data"), ("import", "master_data")):
    check(want in tg, f"office log has {want}")
check(all(x.get("detail") is not None for x in glog), "log entries carry a detail")
check(A.get(B + f"{D}/999999/log").status_code == 404, "log of an unknown document: 404")
# a member's reads are logged too
Bo.get(B + f"{D}/{DOC}/pdf")
check(any(x["action"] == "pdf" and x["user_name"] == "Bob Member" for x in A.get(B + f"{D}/{DOC}/log").json()["log"]), "log: a member's PDF read")

# ---------------------------------------------------------------- tenant matrix + agents (#1142 office, #1146)
for path in (f"{D}/{DOC}", f"{D}/{DOC}/render", f"{D}/{DOC}/pdf", f"{D}/{DOC}/log"):
    rc, rd_ = Ca.get(B + path), Da.get(B + path)
    check(rc.status_code in (403, 404) and "Imagefilm" not in rc.text and rd_.status_code in (400, 403, 404) and "Imagefilm" not in rd_.text,
          f"tenant-matrix: office -- {path}: carol {rc.status_code}, dave {rd_.status_code}")
check(Ca.post(B + f"{D}/{DOC}/duplicate").status_code == 404 and Ca.post(B + f"{D}/{OPEN}/finalize").status_code == 404, "tenant-matrix: office -- duplicate / finalise of another organisation: 404")
for m, path in (("GET", O + "/settings"), ("GET", D), ("GET", f"{D}/{DOC}"), ("GET", O + "/services"), ("GET", O + "/log"), ("GET", O + "/export"),
                ("GET", O + "/nonsense"), ("POST", f"{D}/{DOC}/finalize")):
    r = requests.request(m, B + path, headers=AGH)
    check(r.status_code == 403 and "Imagefilm" not in r.text and "Nordlicht" not in r.text, f"agent token: {m} {path} -> 403 without content ({r.status_code})")
check(A.get(B + O + "/nonsense").status_code == 404, "unknown master data kind: 404")
Bo.patch(B + "/api/settings", json={"features": "cal,comments"})
check(Bo.get(B + O + "/nonsense").status_code == 404 and Bo.post(B + f"{D}/{OPEN}/finalize").status_code == 403, "feature off: unknown kind 404, finalise 403")
Bo.patch(B + "/api/settings", json={"features": FEAT})

# ---------------------------------------------------------------- positions of an older version get their org_id at start
dbx("INSERT INTO office_doc_items(doc_id, sort, kind, title, qty, unit, rate, tax) VALUES(?,?,?,?,?,?,?,?)", (OPEN, 5, "service", "Alt-Position", 1, "day", 50, "standard"), write=True)
check(dbx("SELECT org_id FROM office_doc_items WHERE title='Alt-Position'")[0][0] is None, "an old-style position without org_id")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=dict(env, KEEP="1"))
A = sess("alice")
check(dbx("SELECT org_id FROM office_doc_items WHERE title='Alt-Position'")[0][0] == ORG, "after the start it has its org_id")
d = A.get(B + f"{D}/{OPEN}").json()
check(any(x["title"] == "Alt-Position" for x in d["items"]), "and shows in its document")
check(A.get(B + f"{D}/{DOC}/render").json()["totals"]["net"] == NET, "the finalised document still renders its frozen sums after the restart")
# a quotation as 2.36.1 wrote it (no new columns set) renders and can be changed and deleted
dbx("INSERT INTO office_docs(org_id, kind, number, status, lang, currency, recipient, date, rights, fields, totals, created_by, created_at, updated_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (ORG, "offer", "ALT-001", "draft", "de", "EUR", '{"name": "Beispielkunde AG", "lines": []}', "2026-10-01", "{}", "[]",
                                             "{}", ALICE, "2026-10-01T10:00:00Z", "2026-10-01T10:00:00Z"), write=True)
OLD = dbx("SELECT id FROM office_docs WHERE number='ALT-001'")[0][0]
r = A.get(B + f"{D}/{OLD}/render")
check(r.ok and r.json()["locked"] is False and r.json()["number"] == "ALT-001", "a 2.36.1 quotation renders " + r.text[:120])
check(A.patch(B + f"{D}/{OLD}", json={"project_title": "weiter"}).ok and A.delete(B + f"{D}/{OLD}").ok, "and can be changed and deleted")

print(f"p2362_e_api_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
