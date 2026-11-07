#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.654.0 (#4823): a document moved into / shown in the office under "All workspaces" uses the office area the request has
open (header X-Kalmido-Office-Space, office/model.py office_space), like the office routes (docs/area.py ar_office).
Invented companies and figures only.
freelancer-matrix: files
 - a person with two organisations (Alpha, Beta), workspace "All": without the header nothing is the office (409 as before);
   "Move to office" with the header org:Alpha lands in Alpha's documents, the office list / sheet follow the header
   (Alpha lists it, Beta does not)
 - a foreign organisation in the header (one the person is no member of): as before (409), never that organisation
 - the general input (sort=1) is sorted by the queue without a request: as before, under "All" with two organisations
   nothing is sorted, the header of the upload does not decide it
 - a person without an organisation: her own office; a foreign organisation in the header changes nothing
usage: p2654_a_office_area_test.py <datadir>"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, FAILS, OKS, check, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

HS = "X-Kalmido-Office-Space"
FEAT = "docs,files,office"
if not kt.nostart("P2654A"):
    subprocess.run(["rm", "-rf", kt.DATA])
    kt.fresh(prefix="P2654A")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]

INVOICE = ("Beispiel Papier GmbH\nUSt-IdNr. DE123456789\n\nRechnung Nr. ER-2026-71\nDatum 05.03.2026\n\n"
           "Papier 100,00 EUR\nNetto 100,00 EUR\nUSt 19 % 19,00 EUR\nGesamt 119,00 EUR\n").encode()


def upload(s, name, sort=False, hdr=None):
    # the name in the text: the same content again would be a duplicate (dups), no new document
    form = {"ws": "private", **({"sort": "1"} if sort else {})}
    r = s.post(B + "/api/docs", data=form, files=[("files", (name, INVOICE + f"Ablage {name}\n".encode(), "text/plain"))], headers=hdr or {})
    assert r.ok and r.json().get("ids"), r.text
    return r.json()["ids"][0]


def row(nid):
    x = kt.dbx("SELECT area, area_sort, ws FROM doc_meta WHERE node_id=?", (nid,))
    return tuple(x[0]) if x else None


def settled(s, nid, secs=90):
    def one():
        if (row(nid) or ("", "pending"))[1] in ("pending", "sorting"):
            return None
        r = s.get(B + f"/api/docs/{nid}")
        if not r.ok or r.json()["state"] not in ("done", "failed"):
            return None
        return r.json() if (row(nid) or ("", "pending"))[1] not in ("pending", "sorting") else None
    return until(one, secs)


def ids(s, hdr=None, **q):
    r = s.get(B + "/api/docs", params={"ws": "all", "facets": "0", "limit": "200", **q}, headers=hdr or {})
    assert r.ok, r.text
    return [d["id"] for d in r.json()["docs"]]


def area(s, nid, to, hdr=None):
    return s.post(B + f"/api/docs/{nid}/area", json={"to": to}, headers=hdr or {})


# ==== a person with two organisations, workspace "All"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALPHA = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ALICE}).json()["id"]
for oid, name in ((ALPHA, "Alpha Studio GmbH"), (BETA, "Beta Werkstatt GmbH")):
    A.patch(B + "/api/settings", json={"workspace": f"org:{oid}"})
    r = A.put(B + "/api/office/settings", json={"company_fields": {"name": name, "vat_id": "DE999888777"}})
    check(r.ok, f"setup: the office of {name} " + r.text[:160])
A.patch(B + "/api/settings", json={"workspace": "all"})
HA, HB = {HS: f"org:{ALPHA}"}, {HS: f"org:{BETA}"}

d1 = upload(A, "rechnung-a.txt")
check(settled(A, d1) is not None, "setup: the document is read")
check(area(A, d1, "office").status_code == 409, "without the header under 'All' with two organisations: no office (409, as before)")
r = area(A, d1, "office", HA)
check(r.ok and r.json().get("org_id") == ALPHA and row(d1)[0] == "office" and row(d1)[2] == f"o{ALPHA}",
      f"#4823: 'Move to office' with the open area Alpha lands in Alpha's documents {r.status_code} {r.text[:200]} {row(d1)}")
check(d1 in ids(A, HA, area="office") and d1 not in ids(A, HB, area="office"),
      "#4823: Alpha's open office lists it, Beta's not")
d = A.get(B + f"/api/docs/{d1}", headers=HA).json()
check((d.get("area") or {}).get("area") == "office" and d["area"].get("office") == "org", f"#4823: the sheet in Alpha's office {d.get('area')}")
check(A.get(B + f"/api/docs/{d1}").json().get("area") is None, "the sheet without the header: no office (as before)")

# ---- a foreign organisation in the header: as before, never that organisation
G = freelancer(B, A, "gina", features=FEAT)
GAMMA = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": G[0]}).json()["id"]
d2 = upload(A, "rechnung-b.txt")
settled(A, d2)
r = area(A, d2, "office", {HS: f"org:{GAMMA}"})
check(r.status_code == 409 and row(d2)[2] == f"u{ALICE}", f"#4823: a foreign organisation in the header: as before (409) {r.status_code} {row(d2)}")
check(area(A, d2, "office", {HS: "org:x"}).status_code == 409, "a malformed header: as before (409)")

# ---- the queue (no request): the header of the upload does not decide the sorting
d3 = upload(A, "rechnung-c.txt", sort=True, hdr=HA)
settled(A, d3)
check(row(d3)[:2] == ("", "") and row(d3)[2] == f"u{ALICE}", f"#4823: the general input under 'All' sorts nothing, as before {row(d3)}")

# ==== a person without an organisation (freelancer-matrix: files)
FRIDA, Fr = freelancer(B, A, "frida", features=FEAT)
check(Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Frida Grafik", "vat_id": "DE111222333"}}).ok,
      "setup: her personal office")
Fr.patch(B + "/api/settings", json={"workspace": "all"})
f1 = upload(Fr, "rechnung-f.txt")
settled(Fr, f1)
r = area(Fr, f1, "office", {HS: f"org:{ALPHA}"})
check(r.ok and r.json().get("org_id") is None and row(f1)[:1] == ("office",) and row(f1)[2] == f"u{FRIDA}",
      f"#4823: without an organisation a foreign area changes nothing: her own office {r.status_code} {row(f1)}")
check(f1 in ids(Fr, {HS: "private"}, area="office"), "her own office with the header private")

print(f"p2654_a_office_area: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
