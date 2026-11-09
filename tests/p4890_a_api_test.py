#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.772.0 API tests, part A (#4890): the filters of the documents with their numbers (GET /api/docs/facets, the facets of
GET /api/docs), the archive number as a filter (asn=143 | asn=140-150, has_asn=1, no_asn=1) and the custom fields of type
selection / checkbox (cf=<field ids>:<value>). Own container (start.sh). Invented names and generated texts only.
 - every number equals the total of the list filtered by that value (same rights, same workspace)
 - the archive number: one number, a range (also backwards), with / without one, kept by a saved view
 - a reader sees only the values and numbers of the documents she may open (a sender only on a closed document never shows)
 - another organisation's admin gets nothing of this organisation (no names, all numbers 0)
 - the palette's form {name, ids} stays (count comes along)
tenant-matrix: document (another organisation's admin: no values, no numbers of this organisation's documents)
freelancer-matrix: files (a person without an organisation: the numbers of her private documents, archive number and field filters)
usage: p4890_a_api_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, docker_logs_on_first_fail, done, fresh, sess, until  # noqa: E402

fresh(prefix="P4890A")
docker_logs_on_first_fail()
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
WS = f"org:{ORG}"
uid = {}
for u, rk in (("rita", "readonly"),):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rk}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as {rk} " + r.text[:200])
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
check(A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]}).ok, "setup: another organisation (olga its admin)")
Ri, Ol = sess("rita"), sess("olga")
for s in (Ri, Ol):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
FID, Fr = freelancer(B, A)


def folder(s, name, space):
    r = s.post(B + "/api/files/folders", json={"name": name, "space": space})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def doc_new(s, name, text, ws):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text.encode(), "text/plain"))])
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 120)
    return nid


def field(s, ws, name, ftype, options=None):
    r = s.post(B + "/api/docs/fields", json={"ws": ws, "name": name, "type": ftype, **({"options": options} if options else {})})
    assert r.status_code == 201, r.text
    f = next(x for x in r.json()["fields"] if x["name"] == name)
    return f["id"], {o["name"]: o["id"] for o in f.get("options", [])}


def setv(s, nid, **kw):
    r = s.patch(B + f"/api/docs/{nid}", json=kw)
    check(r.ok, f"setup: values of {nid} {kw} ({r.status_code} {r.text[:200]})")


def facets(s, ws):
    r = s.get(B + "/api/docs/facets", params={"ws": ws})
    return r.json() if r.ok else r.status_code


def total(s, ws, **params):
    r = s.get(B + "/api/docs", params={"ws": ws, "facets": "0", **params})
    return r.json()["total"] if r.ok else r.status_code


def ids(s, ws, **params):
    r = s.get(B + "/api/docs", params={"ws": ws, "facets": "0", "limit": "100", **params})
    return sorted(d["id"] for d in r.json()["docs"]) if r.ok else r.status_code


def counts(f, key):
    return {x["name"]: x["count"] for x in f.get(key, [])}


def field_vals(f, name):
    x = next((e for e in f.get("fields", []) if e["name"] == name), None)
    return {v["name"]: v["count"] for v in x["values"]} if x else None


# ---------------------------------------------------------------- the documents: two every member reads, one only the admin
OPEN, SHUT = folder(A, "Open letters", WS), folder(A, "Board only", WS)
check(A.patch(B + f"/api/files/nodes/{OPEN}", json={"org_access": "view"}).ok, "setup: a folder every member reads")
STATUS, OPT = field(A, WS, "Status", "select", [{"name": "Paid"}, {"name": "Open"}])
BOX, _ = field(A, WS, "Archived", "checkbox")
D1 = doc_new(A, "bill-1.txt", "Quokka bill one", WS)
D2 = doc_new(A, "bill-2.txt", "Quokka letter two", WS)
D3 = doc_new(A, "bill-3.txt", "Quokka secret three", WS)
for d, f in ((D1, OPEN), (D2, OPEN), (D3, SHUT)):
    check(A.patch(B + f"/api/files/nodes/{d}", json={"parent_id": f}).ok, f"setup: document {d} in its folder")
setv(A, D1, sender="Telekom Example", type="Invoice", tags=["Tax"], asn=143, custom_fields={str(STATUS): OPT["Paid"], str(BOX): "1"})
setv(A, D2, sender="Telekom Example", type="Letter", tags=["Tax", "Car"], asn=148, custom_fields={str(STATUS): OPT["Open"]})
setv(A, D3, sender="Hidden Sender Ltd", type="Invoice", tags=["Board"], custom_fields={str(STATUS): OPT["Paid"]})
check(ids(Ri, WS) == sorted([D1, D2]), "setup: the reader sees the two open documents, not the third")

# ---------------------------------------------------------------- the numbers of the admin = the totals of the list
f = facets(A, WS)
check(isinstance(f, dict), f"facets: an answer ({f})")
check(counts(f, "senders") == {"Telekom Example": 2, "Hidden Sender Ltd": 1}, f"senders with numbers {counts(f, 'senders')}")
check(counts(f, "types") == {"Invoice": 2, "Letter": 1}, f"types with numbers {counts(f, 'types')}")
check(counts(f, "tags") == {"Tax": 2, "Car": 1, "Board": 1}, f"tags with numbers {counts(f, 'tags')}")
check(f.get("asn") == {"with": 2, "without": 1}, f"archive number: with / without {f.get('asn')}")
check(field_vals(f, "Status") == {"Paid": 2, "Open": 1}, f"selection field: values with numbers {field_vals(f, 'Status')}")
check(field_vals(f, "Archived") == {"Ticked": 1, "Not ticked": 2}, f"checkbox: ticked / not ticked {field_vals(f, 'Archived')}")
for key, param in (("senders", "sender"), ("types", "type"), ("tags", "tag")):
    for x in f[key]:
        check(total(A, WS, **{param: ",".join(map(str, x["ids"]))}) == x["count"], f"{key} {x['name']}: the number = the list's total")
for e in f["fields"]:
    for v in e["values"]:
        k = ",".join(map(str, e["ids"])) + ":" + v["value"]
        check(total(A, WS, cf=k) == v["count"], f"field {e['name']} = {v['name']}: the number = the list's total ({total(A, WS, cf=k)})")
check(total(A, WS, has_asn="1") == 2 and total(A, WS, no_asn="1") == 1, "with / without archive number: the list's totals")
lst = A.get(B + "/api/docs", params={"ws": WS}).json()["facets"]
check(all(set(x) >= {"name", "ids", "count"} for x in lst["senders"]) and "asn" in lst and "fields" in lst,
      "the list's facets: {name, ids} kept for the palette, count, archive number and fields along")

# ---------------------------------------------------------------- the archive number: one, a range, backwards, nonsense
check(ids(A, WS, asn="143") == [D1], "asn=143: exactly that document")
check(ids(A, WS, asn="140-150") == sorted([D1, D2]), "asn=140-150: the range")
check(ids(A, WS, asn="150-140") == sorted([D1, D2]), "asn=150-140: a range backwards is the same range")
check(ids(A, WS, asn="149-150") == [], "asn=149-150: no document in that range")
check(ids(A, WS, asn="abc") == sorted([D1, D2, D3]), "asn=abc: no number = no filter")
check(ids(A, WS, no_asn="1") == [D3], "no_asn=1: the one without a number")
check(ids(A, WS, cf=f"{STATUS}:paid") == sorted([D1, D3]), "cf: the option's name without regard to case")
check(ids(A, WS, cf=f"{STATUS}:Nothing") == [], "cf: an unknown option = no hit")
check(ids(A, WS, cf=f"{BOX}:0") == sorted([D2, D3]), "cf: checkbox not ticked")
check(ids(A, WS, cf=f"{STATUS}:Paid", asn="140-150") == [D1], "field and archive number together")

# ---------------------------------------------------------------- a saved view keeps the new filters
r = A.post(B + "/api/obj/docview", json={"title": "Paid in range", "query": f"asn=140-150&cf={STATUS}:Paid&has_asn=1", "ws": WS})
check(r.status_code == 201 and "asn=140-150" in r.json().get("query", "") and "cf=" in r.json().get("query", ""), f"a view keeps asn and cf ({r.status_code} {r.text[:200]})")
if r.status_code == 201:
    v = A.get(B + "/api/docs/views", params={"ws": WS}).json()["items"]
    check(next((x["count"] for x in v if x["id"] == r.json()["id"]), None) == 1, f"the view's count with the new filters {v}")

# ---------------------------------------------------------------- the reader: only values of what she may open
fr = facets(Ri, WS)
check(isinstance(fr, dict) and "Hidden Sender Ltd" not in counts(fr, "senders") and "Board" not in counts(fr, "tags"),
      f"rueckfall: the reader sees no sender / tag only on a closed document {fr}")
check(counts(fr, "senders") == {"Telekom Example": 2} and counts(fr, "types") == {"Invoice": 1, "Letter": 1}, f"the reader's numbers {fr}")
check(fr.get("asn") == {"with": 2, "without": 0} and field_vals(fr, "Status") == {"Paid": 1, "Open": 1}, f"the reader: archive number and field only of her documents {fr}")
check(field_vals(fr, "Archived") == {"Ticked": 1, "Not ticked": 1}, f"the reader: the checkbox of her documents {field_vals(fr, 'Archived')}")
check(total(Ri, WS, cf=f"{STATUS}:Paid") == 1 and total(Ri, WS, asn="140-200") == 2, "the reader's filters find only her documents")

# ---------------------------------------------------------------- another organisation's admin: nothing of this one
fo = facets(Ol, WS)
check(isinstance(fo, dict) and not fo["senders"] and not fo["types"] and not fo["tags"] and fo["asn"] == {"with": 0, "without": 0} and fo["fields"] == [],
      f"another organisation's admin: no values, no numbers {fo}")
check(ids(Ol, WS, cf=f"{STATUS}:Paid") == [] and ids(Ol, "all", asn="140-150") == [], "another organisation's admin: the filters find nothing")

# ---------------------------------------------------------------- a person without an organisation (her own admin)
PF, PO = field(Fr, "private", "Paid by", "select", [{"name": "Card"}, {"name": "Cash"}])
P1 = doc_new(Fr, "receipt-1.txt", "Wombat receipt one", "private")
P2 = doc_new(Fr, "receipt-2.txt", "Wombat receipt two", "private")
setv(Fr, P1, sender="Bakery Example", asn=7, custom_fields={str(PF): PO["Card"]})
setv(Fr, P2, sender="Bakery Example", custom_fields={str(PF): PO["Cash"]})
ff = facets(Fr, "private")
check(isinstance(ff, dict) and counts(ff, "senders") == {"Bakery Example": 2} and ff["asn"] == {"with": 1, "without": 1}
      and field_vals(ff, "Paid by") == {"Card": 1, "Cash": 1}, f"freelancer: her numbers {ff}")
check(ids(Fr, "private", asn="5-9") == [P1] and ids(Fr, "private", no_asn="1") == [P2] and ids(Fr, "private", cf=f"{PF}:Cash") == [P2],
      "freelancer: archive number and field filters")
check(ids(Fr, "all", cf=f"{STATUS}:Paid") == [] and "Telekom Example" not in counts(facets(Fr, "all"), "senders"),
      "freelancer: nothing of the organisation's documents")
sys.exit(done("p4890_a_api"))
