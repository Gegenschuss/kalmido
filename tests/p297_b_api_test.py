#!/usr/bin/env python3
"""2.97.0 API tests, part B (#1951): a client's display name for pickers and lists, the address from the fixed fields, the
recipient of quotations / invoices always from the client. Own container (start.sh), invented companies and people only.
 - display_name: stored, in /api/state and /api/clients (label); without one, two clients of one workspace with the same
   name get "name (city)", "name (country)" when the cities are the same; another workspace's twin changes nothing
 - the free address: a client with only "address" gets street / postcode / city / country split from it (the text stays),
   filled fields are never overwritten; the extra address line (address_extra)
 - a draft reads its recipient from the client (name, attn., street, extra line, postcode city, the country when foreign);
   a given recipient is ignored while the draft has a client; a change at the client shows in the draft at once;
   recipient_missing without street / postcode / city; a draft without a client keeps its own recipient
 - finalising freezes the recipient: a later change at the client leaves the invoice, its print model and its XML alone;
   the invoice, its print model and the XML carry the legal name, never the display name; the XML has the extra line
 - an invoice needs the client's address (the client's name and attn. line are no address)
 - a person without an organisation (the personal office) works the same
freelancer-matrix: office
usage: p297_b_api_test.py <datadir>      (a fresh container; P297B_NOSTART=1: the container runs already)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
TEST_IBAN = "DE02120300000000202051"
FAILS, OKS = [], [0]


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


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


FEAT = "cal,comments,collab,office,clients,time"
if os.environ.get("P297B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
O = "/api/office"
D = O + "/docs"
COMPANY = {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hallo@nordlicht.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN,
           "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht GmbH"}, "lang": "de", "currency": "EUR",
                                     "company_fields": COMPANY, "payment_days": 14})
check(r.ok, "setup: office settings " + r.text[:200])


def client(s, **b):
    r = s.post(B + "/api/clients", json={"org_id": ORG, **b} if s is not Fr and s is not Ca else b)
    assert r.status_code == 201, r.text
    return r.json()


def state_cl(s):
    return {c["id"]: c for c in s.get(B + "/api/state").json().get("clients") or []}


Fr = None
# ---------------------------------------------------------------- display name and the automatic labels
F1 = client(A, name="Foo AG", street="Steinenring 1", zip="4051", city="Basel", country="CH")
F2 = client(A, name="Foo AG", street="Unter den Linden 2", zip="10117", city="Berlin", country="DE")
N1 = client(A, name="Neu GmbH", street="Hauptplatz 1", zip="2700", city="Neustadt", country="AT")
N2 = client(A, name="Neu GmbH", street="Marktplatz 1", zip="67433", city="Neustadt", country="DE")
DN = client(A, name="Foo AG", display_name="Foo Schweiz", street="Bahnhofstrasse 3", zip="8001", city="Zürich", country="CH")
check(DN["display_name"] == "Foo Schweiz" and DN["name"] == "Foo AG", f"display_name stored next to the name: {DN.get('display_name')}")
st = state_cl(A)
check(st[F1["id"]]["label"] == "Foo AG (Basel)" and st[F2["id"]]["label"] == "Foo AG (Berlin)",
      f"same name, no display name: the city appended: {st[F1['id']]['label']} / {st[F2['id']]['label']}")
check(st[N1["id"]]["label"] == "Neu GmbH (AT)" and st[N2["id"]]["label"] == "Neu GmbH (DE)",
      f"same name and city: the country appended: {st[N1['id']]['label']} / {st[N2['id']]['label']}")
check(st[DN["id"]]["label"] == "Foo Schweiz" and st[DN["id"]]["display_name"] == "Foo Schweiz", "a display name is the label")
cl = {c["id"]: c for c in A.get(B + "/api/clients").json()["clients"]}
check(cl[F1["id"]]["label"] == "Foo AG (Basel)" and cl[DN["id"]]["label"] == "Foo Schweiz" and cl[F1["id"]]["display_name"] == "",
      "GET /api/clients: label + display_name")
check(A.get(B + f"/api/clients/{DN['id']}").json()["label"] == "Foo Schweiz", "GET /api/clients/<id>: label")
# another workspace's twin does not count
CB = client(Ca, name="Foo AG", street="Weg 1", zip="80331", city="München", country="DE")
check(state_cl(Ca)[CB["id"]]["label"] == "Foo AG", "another workspace: its only Foo AG keeps the plain name")
check(CB["id"] not in state_cl(A), "tenant-matrix: office -- Beta's client is not in Alpha's state")
# a display name set later; removing it brings the automatic label back
r = A.patch(B + f"/api/clients/{F2['id']}", json={"display_name": "  Foo   Deutschland "})
check(r.ok and r.json()["display_name"] == "Foo Deutschland" and r.json()["label"] == "Foo Deutschland", f"PATCH display_name (trimmed): {r.text[:160]}")
st = state_cl(A)
check(st[F1["id"]]["label"] == "Foo AG", f"the twin with a display name no longer forces the city: {st[F1['id']]['label']}")
r = A.patch(B + f"/api/clients/{F2['id']}", json={"display_name": ""})
check(r.ok and state_cl(A)[F2["id"]]["label"] == "Foo AG (Berlin)", "display name removed: the automatic label again")
check(A.patch(B + f"/api/clients/{F2['id']}", json={"display_name": 5}).status_code == 400, "display_name must be text (400)")
check(Bo.patch(B + f"/api/clients/{F1['id']}", json={"display_name": "x"}).ok, "a member of the workspace may name the client")
A.patch(B + f"/api/clients/{F1['id']}", json={"display_name": ""})

# ---------------------------------------------------------------- the free address -> the fixed fields
r = A.post(B + "/api/clients", json={"org_id": ORG, "name": "Altkunde GmbH", "address": "Lindenweg 4\n50667 Köln"})
check(r.status_code == 201, "a client with only the free address " + r.text[:160])
AK = r.json()
b = AK.get("billing") or {}
check(b.get("street") == "Lindenweg 4" and b.get("zip") == "50667" and b.get("city") == "Köln" and b.get("country") == "DE",
      f"street / postcode / city / country split from the free address: {b}")
check(AK["address"] == "Lindenweg 4\n50667 Köln", "the free text stays in its column")
r = A.patch(B + f"/api/clients/{AK['id']}", json={"address": "Andere Straße 9\n12345 Irgendwo"})
check(r.ok and r.json()["billing"]["street"] == "Lindenweg 4" and r.json()["billing"]["city"] == "Köln", "filled fields are never overwritten")
# a row as an old version leaves it (free text only, the fields empty): the next write of "address" fills them
dbx("UPDATE clients SET street='', zip='', city='', country='', address=? WHERE id=?", ("Beispielkunde AG\nz. Hd. Max Muster\nMarktstraße 5\n50667 Köln", AK["id"]))
r = A.patch(B + f"/api/clients/{AK['id']}", json={"address": "Beispielkunde AG\nz. Hd. Max Muster\nMarktstraße 5\n50667 Köln"})
b = r.json()["billing"]
check(b["street"] == "Marktstraße 5" and b["zip"] == "50667" and b["city"] == "Köln", f"a whole address block (name, attn.) is split too: {b}")
r = A.patch(B + f"/api/clients/{AK['id']}", json={"address_extra": "Hinterhaus, 2. OG"})
check(r.ok and r.json()["billing"]["address_extra"] == "Hinterhaus, 2. OG", "the extra address line (address_extra)")

# ---------------------------------------------------------------- the recipient of a draft comes from the client
A.patch(B + f"/api/clients/{F1['id']}", json={"contacts": [{"name": "Erika Beispiel", "is_default": True}], "address_extra": "Postfach 12"})
r = A.post(B + D, json={"project_title": "Imagefilm", "client_id": F1["id"]})
check(r.status_code == 201, "a quotation with a client " + r.text[:160])
OFF = r.json()
check(OFF["recipient"]["name"] == "Foo AG" and OFF["recipient"]["lines"] == ["Foo AG", "Erika Beispiel", "Steinenring 1", "Postfach 12", "4051 Basel", "CH"],
      f"the recipient from the client (foreign: the country line): {OFF['recipient']}")
check(OFF["recipient"].get("street") == "Steinenring 1" and OFF["recipient"].get("extra") == "Postfach 12" and OFF["recipient"].get("country") == "CH",
      "the recipient carries the fixed fields")
check(OFF["recipient_missing"] is False, "recipient_missing false with a full address")
r = A.patch(B + f"{D}/{OFF['id']}", json={"recipient": {"name": "Jemand Anderes", "lines": ["Jemand Anderes", "Irgendwo 1"]}})
check(r.ok and r.json()["recipient"]["name"] == "Foo AG" and "Irgendwo 1" not in r.json()["recipient"]["lines"],
      "a given recipient is ignored while the draft has a client")
A.patch(B + f"/api/clients/{F1['id']}", json={"street": "Steinenring 7"})
d = A.get(B + f"{D}/{OFF['id']}").json()
check("Steinenring 7" in d["recipient"]["lines"] and "Steinenring 1" not in d["recipient"]["lines"], f"the draft reads the client's new street: {d['recipient']['lines']}")
rd = A.get(B + f"{D}/{OFF['id']}/render").json()
check("Steinenring 7" in rd["recipient"]["lines"], "the draft's print model too")
# the attn. line follows the contact person (none = gone)
r = A.patch(B + f"{D}/{OFF['id']}", json={"contact_id": 0})
check(r.ok and "Erika Beispiel" not in r.json()["recipient"]["lines"], "no contact person: no attn. line")
# a home client: no country line
r = A.post(B + D, json={"project_title": "Inland", "client_id": F2["id"]})
check(r.json()["recipient"]["lines"] == ["Foo AG", "Unter den Linden 2", "10117 Berlin"], f"home country: no country line: {r.json()['recipient']['lines']}")
# without an address
NA = client(A, name="Ohne Anschrift KG")
r = A.post(B + D, json={"project_title": "Lücke", "client_id": NA["id"]})
check(r.json()["recipient_missing"] is True and r.json()["recipient"]["lines"] == ["Ohne Anschrift KG"], "recipient_missing without street / postcode / city")
# a draft without a client keeps its own recipient (agents and old documents)
r = A.post(B + D, json={"project_title": "Frei", "recipient": {"name": "Freie Empfängerin", "lines": ["Freie Empfängerin", "Weg 3", "12345 Ort"]}})
check(r.status_code == 201 and r.json()["recipient"]["lines"] == ["Freie Empfängerin", "Weg 3", "12345 Ort"] and r.json()["recipient_missing"] is False,
      "without a client the given recipient stays")

# ---------------------------------------------------------------- invoices: the legal name, the snapshot, the XML
A.patch(B + f"/api/clients/{F2['id']}", json={"display_name": "Foo Deutschland", "address_extra": "Aufgang B"})
r = A.post(B + D, json={"kind": "invoice", "client_id": F2["id"], "service_from": "2030-05-01", "service_to": "2030-05-31",
                        "items": [{"title": "Beratung", "qty": 1, "rate": 100}]})
check(r.status_code == 201, "an invoice draft " + r.text[:160])
INV = r.json()
check(INV["recipient"]["name"] == "Foo AG" and "Foo Deutschland" not in INV["recipient"]["lines"], "the invoice uses the legal name, not the display name")
r = A.post(B + f"{D}/{INV['id']}/finalize")
check(r.ok and r.json()["locked"] is True, "finalised " + r.text[:200])
rd = A.get(B + f"{D}/{INV['id']}/render").json()
check(rd["recipient"]["name"] == "Foo AG" and rd["recipient"]["street"] == "Unter den Linden 2" and rd["recipient"]["extra"] == "Aufgang B",
      f"print model: legal name + fixed fields: {rd['recipient']}")
x = A.get(B + f"{D}/{INV['id']}/xml")
xml = x.content.decode("utf-8", "replace")
check(x.ok and "<ram:Name>Foo AG</ram:Name>" in xml and "Foo Deutschland" not in xml, "XML: the buyer is the legal name")
check("<ram:LineOne>Unter den Linden 2</ram:LineOne>" in xml and "<ram:LineTwo>Aufgang B</ram:LineTwo>" in xml and "<ram:CityName>Berlin</ram:CityName>" in xml,
      "XML: the fixed fields, the extra line as LineTwo")
# the client changes after finalising: the invoice stays
A.patch(B + f"/api/clients/{F2['id']}", json={"name": "Foo Neu AG", "street": "Neue Straße 1", "zip": "10115", "city": "Berlin"})
d = A.get(B + f"{D}/{INV['id']}").json()
check(d["recipient"]["name"] == "Foo AG" and "Unter den Linden 2" in d["recipient"]["lines"] and "Neue Straße 1" not in d["recipient"]["lines"],
      f"finalised: the recipient is frozen: {d['recipient']}")
rd = A.get(B + f"{D}/{INV['id']}/render").json()
check(rd["recipient"]["name"] == "Foo AG" and rd["recipient"]["street"] == "Unter den Linden 2", "finalised: the print model is frozen")
xml2 = A.get(B + f"{D}/{INV['id']}/xml").content.decode("utf-8", "replace")
check("Neue Straße 1" not in xml2 and "Unter den Linden 2" in xml2, "finalised: the XML is frozen")
r = A.post(B + D, json={"kind": "invoice", "client_id": F2["id"]})
check(r.json()["recipient"]["name"] == "Foo Neu AG" and "Neue Straße 1" in r.json()["recipient"]["lines"], "a new draft reads the changed client")
# an invoice needs the client's address
r = A.post(B + D, json={"kind": "invoice", "client_id": NA["id"], "service_from": "2030-05-01", "items": [{"title": "Beratung", "qty": 1, "rate": 50}]})
A.patch(B + f"/api/clients/{NA['id']}", json={"contacts": [{"name": "Max Muster", "is_default": True}]})
r = A.post(B + f"{D}/{r.json()['id']}/finalize")
check(r.status_code == 400 and "recipient address" in r.json().get("error", ""), "an invoice without the client's address: 400 " + r.text[:160])
check(Ca.get(B + f"{D}/{INV['id']}").status_code in (403, 404), "tenant-matrix: office -- another organisation does not read the invoice")

# ---------------------------------------------------------------- a person without an organisation (the personal office)
FID, Fr = freelancer(B, A)
check(Fr.put(B + O + "/settings", json={"company_fields": {"name": "Frida Film", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg",
                                                             "country": "DE", "tax_number": "12/345/67890", "iban": TEST_IBAN}}).ok,
      "freelancer: company fields")
P1 = client(Fr, name="Kunde Eins", street="Weg 1", zip="20095", city="Hamburg")
P2 = client(Fr, name="Kunde Eins", street="Weg 2", zip="80331", city="München")
P3 = client(Fr, name="Kunde Zwei", display_name="Zweitkunde", address="Ring 5\n50667 Köln")
st = state_cl(Fr)
check(P1["org_id"] is None and st[P1["id"]]["label"] == "Kunde Eins (Hamburg)" and st[P2["id"]]["label"] == "Kunde Eins (München)",
      f"freelancer: private clients, the same labels: {st.get(P1['id'], {}).get('label')}")
check(st[P3["id"]]["label"] == "Zweitkunde" and P3["billing"]["city"] == "Köln", "freelancer: display name + the free address split")
r = Fr.post(B + D, json={"kind": "invoice", "client_id": P3["id"], "service_from": "2030-02-01", "items": [{"title": "Shoot", "qty": 1, "rate": 900}]})
check(r.status_code == 201 and r.json()["recipient"]["lines"] == ["Kunde Zwei", "Ring 5", "50667 Köln"], f"freelancer: the recipient from the client: {r.text[:200]}")
FI = r.json()["id"]
check(Fr.post(B + f"{D}/{FI}/finalize").ok, "freelancer: finalised")
Fr.patch(B + f"/api/clients/{P3['id']}", json={"street": "Ring 9"})
check("Ring 5" in Fr.get(B + f"{D}/{FI}").json()["recipient"]["lines"], "freelancer: the finalised invoice keeps its address")
check(P1["id"] not in state_cl(A) and F1["id"] not in state_cl(Fr), "freelancer: no clients across the boundary")

print(f"p297_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
