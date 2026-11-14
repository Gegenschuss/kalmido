#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1148.0 (#4895): the point "Receipts" below the file store's tree -- references, the receipts stay in their area
(freelancer-matrix: files)
tenant-matrix: files
 - the top of a space lists the collection "Receipts" last, only with its parts that hold something the person may read:
   Office (recorded receipts of the space's office), Entertainment (meals of that office), Household (receipts of budget
   entries of the space's budget lists); none = no collection
 - GET /api/files/collections/receipts | rcoffice | rcmeals | rcbudget: the items carry name, day, amount, currency and
   `open` = the area's address (office/books/receipts, office/meals, budget/<list>/<YYYY-MM>), no file address
 - rights: another person, an organisation member without the office's receipts, an organisation the person is not in
   (404), an agent (404) see nothing; the module "budget" off = no Household
 - the trash: a receipt document / a meal / a budget entry in the trash drops out (and the part with it)
 - a person without an organisation (the fixture): everything in the private workspace with the personal office
usage: p21148_receipts_test.py <datadir>      (KMT_NOSTART=1 / P21148_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import FEATURES, freelancer, login
from kt import B, H, check, done, fresh, setup



def tiny_pdf(text):
    """A one-page PDF with a text layer (as tests/p2110_b_api_test.py)."""
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


NOBUDGET = ",".join(x for x in FEATURES.split(",") if x != "budget")

fresh(prefix="P21148")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Nordwind", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": [ORG]})
assert r.ok, r.text
Bo = login(B, "bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})
FID, Fr = freelancer(B, A, features=FEATURES)


def top(s, space="private"):
    r = s.get(B + "/api/files", params={"space": space})
    assert r.ok, (space, r.status_code, r.text)
    return r.json()


def rc_of(j):
    """The collection "Receipts" of a top listing (None: none)."""
    x = [c for c in j.get("collections", []) if c["key"] == "receipts"]
    return x[0] if x else None


def coll(s, key, space="private"):
    return s.get(B + f"/api/files/collections/{key}", params={"space": space})


def groups(s, key, space="private"):
    r = coll(s, key, space)
    assert r.ok, (key, space, r.status_code, r.text[:200])
    return r.json().get("groups", [])


def receipt(s, ws, name, amount, day):
    """A recorded receipt: a document with amount + date and its assignment (as tests/p2110_b_api_test.py)."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    assert s.patch(B + f"/api/docs/{nid}", json={"date": day, "amount": amount}).ok
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Office", "vat_pct": "19", "keep": True})
    assert r.ok, r.text
    return nid


# ================================================================== a person without an organisation: nothing yet
check(rc_of(top(Fr)) is None, "#4895: no 'Receipts' without a receipt")
check(groups(Fr, "receipts") == [], "#4895: the collection is empty")

# freelancer-matrix: files
DOC = receipt(Fr, "private", "papier.pdf", "59.50", "2026-02-01")
r = Fr.post(B + "/api/office/meals", json={"date": "2026-03-05", "place_name": "Trattoria Esempio", "occasion": "Project talk",
                                           "host": {"id": FID}, "guests": [{"name": "Gina Gast", "extra": "Example GmbH"}],
                                           "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}], "tip": "10"})
check(r.status_code == 201, f"setup: a meal {r.status_code} {r.text[:200]}")
MEAL = r.json().get("id")
BL = Fr.post(B + "/api/budget/lists", json={}).json().get("list_id")
e = Fr.post(B + f"/api/budget/{BL}/entries", json={"day": "2026-09-03", "amount": 10, "kind": "out", "title": "Paint"}).json()
ENT = e.get("id")
check(Fr.post(B + f"/api/budget/entries/{ENT}/files", files=[("file", ("bill.txt", b"paid", "text/plain"))]).ok, "setup: a receipt on a budget entry")

rc = rc_of(top(Fr))
check(rc is not None and rc["name"] == "Receipts", f"#4895: 'Receipts' at the top of the private space {top(Fr).get('collections')}")
check(top(Fr)["collections"][-1]["key"] == "receipts", "#4895: 'Receipts' is the last collection (below the tree)")
check([x["key"] for x in (rc or {}).get("subs", [])] == ["rcoffice", "rcmeals", "rcbudget"]
      and [x["name"] for x in rc["subs"]] == ["Office", "Entertainment", "Household"], f"#4895: its parts {rc}")

g = groups(Fr, "rcoffice")
it = g[0]["items"][0] if g and g[0]["items"] else {}
check(len(g) == 1 and g[0]["open"] == "office/books/receipts" and it.get("id") == DOC and it.get("name") == "papier.pdf",
      f"#4895: Office = the recorded receipt, opening the receipts list {g}")
check(it.get("amount") == "59.50" and it.get("created_at") == "2026-02-01" and it.get("currency") == "EUR", f"#4895: day, amount, currency {it}")
check("url" not in it and "dl" not in it and it.get("open") == "office/books/receipts", "#4895: no file address, only the area's (no copy)")

g = groups(Fr, "rcmeals")
it = g[0]["items"][0] if g and g[0]["items"] else {}
check(len(g) == 1 and g[0]["open"] == "office/meals" and it.get("id") == MEAL and it.get("name") == "Trattoria Esempio",
      f"#4895: Entertainment = the meal, opening the entertainment receipts {g}")
check(it.get("amount") == "129.00" and it.get("sub") == "Project talk" and it.get("created_at") == "2026-03-05", f"#4895: the meal's sum with tip, occasion, day {it}")

g = groups(Fr, "rcbudget")
it = g[0]["items"][0] if g and g[0]["items"] else {}
check(len(g) == 1 and g[0]["open"] == f"budget/{BL}" and it.get("name") == "bill.txt" and it.get("open") == f"budget/{BL}/2026-09",
      f"#4895: Household = the entry's receipt per budget list, opening the entry's month {g}")
check(float(it.get("amount") or 0) == 10 and it.get("sub") == "Paint" and it.get("created_at") == "2026-09-03", f"#4895: the entry's day, amount, title {it}")

g = groups(Fr, "receipts")
check([x["open"] for x in g] == ["office/books/receipts", "office/meals", f"budget/{BL}"], f"#4895: 'Receipts' = all three parts {g}")

# ================================================================== boundaries
check(rc_of(top(Bo)) is None and groups(Bo, "receipts") == [], "#4895: another person's private space shows nothing of hers")
check(groups(A, "rcoffice") == [] and groups(A, "rcbudget") == [], "#4895: the instance admin sees none of her receipts")
check(coll(Fr, "receipts", f"org:{ORG}").status_code == 404, "#4895: an organisation the person is not in 404")
check(coll(Fr, "rcnope").status_code == 404, "#4895: an unknown part 404")
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
r = requests.get(B + "/api/files/collections/receipts", headers={**H, "Authorization": "Bearer " + ag.get("token", "")})
check(bool(ag.get("token")) and r.status_code in (401, 403, 404) and "groups" not in r.text, f"#4895: an agent gets nothing {r.status_code}")

Fr.patch(B + "/api/settings", json={"features": NOBUDGET})
check([x["key"] for x in rc_of(top(Fr))["subs"]] == ["rcoffice", "rcmeals"], "#4895: the module budget off: no Household")
Fr.patch(B + "/api/settings", json={"features": FEATURES})

# ================================================================== an organisation: the office's admin vs. a member
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
ODOC = receipt(A, f"org:{ORG}", "team.pdf", "11.90", "2026-04-01")
g = groups(A, "rcoffice", f"org:{ORG}")
check([x["id"] for x in (g[0]["items"] if g else [])] == [ODOC], f"#4895: the organisation's office receipt for its admin {g}")
check(rc_of(top(A, f"org:{ORG}")) is not None, "#4895: 'Receipts' at the top of the organisation's space")
check(groups(Bo, "rcoffice", f"org:{ORG}") == [] and rc_of(top(Bo, f"org:{ORG}")) is None,
      "#4895: a member without the office's receipts sees neither the part nor the receipt")
check(ODOC not in [x["id"] for gr in groups(A, "rcoffice") for x in gr["items"]], "#4895: the private space shows no receipt of the organisation")
r = A.post(B + "/api/office/meals", json={"date": "2026-04-02", "place_name": "Bistro Nord", "occasion": "Kick-off", "host": {"id": ALICE},
                                          "guests": [{"name": "Gina Gast", "extra": "Example GmbH"}], "amounts": [{"kind": "food", "rate": 19, "gross": "50.00"}]})
check(r.status_code == 201, f"setup: a meal of the organisation {r.status_code} {r.text[:200]}")
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
check(A.put(B + f"/api/office/rights/people/{BOB}", json={"groups": ["tpl:readonly"]}).ok, "setup: bob in the office group Read-only")
check([x["name"] for gr in groups(Bo, "rcmeals", f"org:{ORG}") for x in gr["items"]] == ["Bistro Nord"], "#4895: an office group with 'view' reads the entertainment receipts")
check(A.put(B + f"/api/office/rights/people/{BOB}", json={"groups": ["tpl:staff"]}).ok, "setup: bob in the office group Staff (own only)")
check(groups(Bo, "rcmeals", f"org:{ORG}") == [], "#4895: level 'own': not alice's meal")
check(A.put(B + f"/api/office/rights/people/{BOB}", json={"groups": ["tpl:readonly"]}).ok, "setup: Read-only again")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "guest"}).ok, "setup: bob becomes a guest (keeps his group)")
check(groups(Bo, "rcmeals", f"org:{ORG}") == [] and groups(Bo, "rcoffice", f"org:{ORG}") == [] and rc_of(top(Bo, f"org:{ORG}")) is None,
      "#4895 (review F1): a guest with an office group reads nothing of the office")

# ================================================================== the trash
check(Fr.delete(B + f"/api/budget/entries/{ENT}").ok, "setup: the budget entry into the trash")
check(groups(Fr, "rcbudget") == [] and "rcbudget" not in [x["key"] for x in rc_of(top(Fr))["subs"]], "#4895: an entry in the trash drops its receipt and the part")
check(Fr.delete(B + f"/api/office/meals/{MEAL}").ok, "setup: the meal into the trash")
check(groups(Fr, "rcmeals") == [], "#4895: a meal in the trash is gone")
check(Fr.delete(B + f"/api/files/nodes/{DOC}").ok, "setup: the receipt document into the trash")
check(groups(Fr, "rcoffice") == [] and rc_of(top(Fr)) is None, "#4895: nothing left: no 'Receipts' at the top")
sys.exit(done("p21148_receipts"))
