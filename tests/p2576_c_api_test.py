#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.576.0 (#4487) API tests: Office > Receipts and the file store apart (decision 04.11.2026), the filter of an
organisation's office. Invented companies, names and figures only; the documents are plain text written here.
freelancer-matrix: files  tenant-matrix: document
 - an organisation's office: the file store (?area=private) hides only the office's documents (an office upload, a receipt),
   the organisation's contract stays there (decision of this part, note on #4487); Office > Receipts (GET
   /api/office/receipts/tree) lists the office upload not recorded yet, never the contract or a private document
 - the contract's sheet carries no area (no "Wrong area", no "Move to office"), the office upload's sheet the office
 - a member (no admin) of the organisation: every filtered list is part of her unfiltered list (the filter only narrows),
   another person's private document in none of them
 - a person without an organisation with her personal office: the office upload in Office > Receipts and ?area=office, her
   private document only in ?area=private; another person (and the server's admin) sees neither in any list or tree
usage: p2576_c_api_test.py <datadir>      (a fresh container; P2576C_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, FAILS, OKS, check, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(prefix="P2576C")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]

CONTRACT = ("Mietvertrag\n\nzwischen Beispiel Immobilien GmbH und Alpha Studio GmbH\n\nDie Mieträume im Erdgeschoss werden ab dem "
            "1. April 2026 vermietet. Der Vertrag läuft auf unbestimmte Zeit.\n").encode()
OFFICE = ("Beispiel Büromarkt KG\nRechnung Nr. BM-2026-17\nDatum 12.03.2026\n\nOrdner und Papier\nNetto 50,00 EUR\nUSt 19 % 9,50 EUR\n"
          "Gesamt 59,50 EUR\n").encode()
PRIVATE = "Liebe Grüße aus dem Urlaub\n\nDas Wetter ist schön, bis bald.\n".encode()


def upload(s, name, data, ws="private", **form):
    r = s.post(B + "/api/docs", data={"ws": ws, **form}, files=[("files", (name, data, "text/plain"))])
    assert r.ok and r.json().get("ids"), r.text
    return r.json()["ids"][0]


def done(s, nid, secs=90):
    def one():
        r = s.get(B + f"/api/docs/{nid}")
        return r.json() if r.ok and r.json()["state"] in ("done", "failed") else None
    return until(one, secs)


def ids(s, **q):
    r = s.get(B + "/api/docs", params={"ws": "all", "facets": "0", "limit": "200", **q})
    return [d["id"] for d in r.json()["docs"]] if r.ok else []


def tree(s):
    r = s.get(B + "/api/office/receipts/tree")
    return r.json() if r.ok else {"http": r.status_code, "docs": []}


def tree_ids(s):
    return [d["id"] for d in tree(s).get("docs", [])]


def row(nid):
    x = kt.dbx("SELECT area, area_sort, ws FROM doc_meta WHERE node_id=?", (nid,))
    return tuple(x[0]) if x else None


def narrows(s, who):
    """Every filtered list of s is part of its unfiltered list (the filter is only ANDed to the visibility)."""
    full = set(ids(s))
    for q in ({"area": "private"}, {"area": "office"}, {"area": "office", "unbooked": "1"}):
        extra = set(ids(s, **q)) - full
        check(not extra, f"{who}: ?{q} shows nothing the unfiltered list hides {sorted(extra)}")


# ==== an organisation's office (Alice is its admin)
A.patch(B + "/api/settings", json={"lang": "en", "features": "docs,files,office", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.put(B + "/api/office/settings", json={"company_fields": {"name": "Alpha Studio GmbH", "vat_id": "DE999888777"}})
check(r.ok, "setup: Alpha's office " + r.text[:160])

contract = upload(A, "mietvertrag.txt", CONTRACT, ws=f"org:{ORG}")
office = upload(A, "bueromarkt.txt", OFFICE, ws=f"org:{ORG}", area="office")
private = upload(A, "urlaub.txt", PRIVATE)
for n in (contract, office, private):
    done(A, n)
check(row(contract)[0] == "" and row(office)[0] == "office", f"#4487: an office upload of the organisation is marked office {row(contract)} {row(office)}")
fs = ids(A, area="private")
check(contract in fs and private in fs, "#4487: the organisation's contract and the private document stay in the file store")
check(office not in fs, "#4487: the office's upload is not in the file store")
of = ids(A, area="office")
check(office in of and contract not in of and private not in of, f"?area=office: only the office's document {of}")
check(office in ids(A, area="office", unbooked="1"), "the office upload is 'New in the office'")
d = A.get(B + f"/api/docs/{contract}").json()
check(d.get("area") is None, f"the contract's sheet: no area, no 'Wrong area' / 'Move to office' {d.get('area')}")
check(A.post(B + f"/api/docs/{contract}/area", json={"to": "private"}).status_code == 409, "the contract is not moved by 'Wrong area' (409)")
d = A.get(B + f"/api/docs/{office}").json()
check((d.get("area") or {}).get("area") == "office" and d["area"].get("office") == "org" and d.get("parent_id"),
      f"the office upload's sheet: the office (its folder for 'Also in: File store') {d.get('area')} {d.get('parent_id')}")
t = tree(A)
td = {x["id"]: x for x in t.get("docs", [])}
check(office in td and td[office]["kind"] == "doc" and td[office]["open"] == f"docs/{office}",
      f"#4487: Office > Receipts lists the office upload not recorded yet {t.get('http')} {td.get(office)}")
check(contract not in td and private not in td, "Office > Receipts: never the contract nor a private document")
r = A.put(B + f"/api/docs/{office}/receipt", json={"project_id": None, "category": "Material"})
check(r.ok, f"setup: recorded as a receipt {r.status_code} {r.text[:160]}")
if r.ok:  # recorded as a receipt: still in Office > Receipts (once), still not in the file store
    t = tree_ids(A)
    check(t.count(office) == 1 and office not in ids(A, area="private"), f"a recorded receipt: once in Office > Receipts {t}")
narrows(A, "the organisation's admin")

# ---- a member (no admin) of the organisation
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bert", "display_name": "Bert",
                                   "password": "password123", "email": "bert@example.com"})
check(r.ok, "setup: bert, a member of Alpha " + r.text[:160])
Be = kt.sess("bert")
Be.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "docs,files,office", "workspace": f"org:{ORG}"})
narrows(Be, "a member")
every = set(ids(Be)) | set(ids(Be, area="private")) | set(ids(Be, area="office")) | set(tree_ids(Be))
check(private not in every, "a member never sees Alice's private document (lists, Office > Receipts)")
check((contract in ids(Be, area="private")) == (contract in ids(Be)), "a member: the contract in the file store exactly when she may see it")
check(office not in ids(Be, area="private"), "a member: the office's upload not in her file store")
b1 = upload(Be, "bert-urlaub.txt", PRIVATE + b"Bert\n")
done(Be, b1)
check(b1 not in set(ids(A)) | set(ids(A, area="private")) | set(tree_ids(A)), "the admin does not see the member's private document")

# ==== a person without an organisation, her personal office (freelancer-matrix: files)
FRIDA, Fr = freelancer(B, A)
r = Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Frida Grafik", "vat_id": "DE111222333"}})
check(r.ok, "setup: the personal office " + r.text[:160])
f1 = upload(Fr, "frida-buero.txt", OFFICE.replace(b"BM-2026-17", b"BM-2026-18"), area="office")
f2 = upload(Fr, "frida-urlaub.txt", PRIVATE + b"Frida\n")
for n in (f1, f2):
    done(Fr, n)
check(row(f1)[0] == "office" and f1 in ids(Fr, area="office") and f1 not in ids(Fr, area="private"), f"her office upload: in the office {row(f1)}")
check(f2 in ids(Fr, area="private") and f2 not in ids(Fr, area="office"), "her private document: only in the file store")
ft = tree_ids(Fr)
check(f1 in ft and f2 not in ft, f"#4487: her Office > Receipts lists the office upload, not the private one {ft}")
narrows(Fr, "a person without an organisation")
G = freelancer(B, A, "gina")[1]
gina = set(ids(G)) | set(ids(G, area="private")) | set(ids(G, area="office")) | set(tree_ids(G))
check(not gina & {f1, f2, contract, office, private}, "another person sees none of them (tenant-matrix: document)")
check(not {f1, f2} & (set(ids(A)) | set(ids(A, area="private")) | set(tree_ids(A))), "the server's admin sees none of Frida's")

print(f"p2576_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
