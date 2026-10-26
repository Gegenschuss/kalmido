#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.351.0 B (#2749): address books and contacts in folders (contacts/ctfolder.py). Invented names only.
 - the address book's folders: the first folder makes the root "Address book" of the workspace (GET / POST
   /api/contacts/folders); a book / a single contact is filed with POST /api/files/refs and shows in the tree
 - a folder share (view / edit) gives that role on a filed book (all its contacts, also ones added later) or on a filed
   contact (only that one); never the owner's rights: the book's settings, deleting / moving a contact shared on its own
 - book_members stays valid: the higher role of book share and folder counts, nothing gets narrower
 - filing needs 'edit' from the address book itself; withdrawing the share / taking it out of the folder takes it away
 - CardDAV gives exactly what the person may see: a book through a folder as its collection, single contacts in the
   read-only collection s1 (PUT / DELETE there 403)
 - agents only with a share on exactly them (organisation access gives nothing), a token without the scope contacts never
 - the book share dialog's agents: PUT /api/books/<id>/members with an agent (the server took them already)
 - a folder in the trash deletes no contact; the folder filter of the list (GET /api/contacts?folder=)
 - freelancer-matrix: pim (a person without an organisation: private folder, her own agent)
 - tenant-matrix: contacts_folder (another organisation: 404 on its space, never filed across)
usage: p2351_b_contacts_tree_test.py <datadir>      (P2351B_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FEAT = "contacts,collab,comments,files"

if not os.environ.get("P2351B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments", "contacts"]})  # agents: contacts on
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "olga"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "olga" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["olga"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ol = sess("bob"), sess("olga")
for s in (A, Bo, Ol):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def agent(name, scopes=("read", "write", "contacts"), org=None):
    r = A.post(B + "/api/admin/agents", json={"scopes": list(scopes), "username": name, "display_name": name.title(), "org_id": org})
    assert r.status_code == 201, r.text
    return r.json()["id"], bearer(r.json()["token"])


def folder(s, name, space="private", parent=None):
    r = s.post(B + "/api/contacts/folders", json={"name": name, "space": space, **({"parent_id": parent} if parent else {})})
    assert r.status_code == 201, (name, r.status_code, r.text)
    return r.json()["folder"]["id"]


def book(s, name, org=None):
    r = s.post(B + "/api/books", json={"name": name, "org_id": org})
    assert r.ok, r.text
    return r.json()["id"]


def contact(s, bid, fn):
    r = s.post(B + "/api/contacts", json={"book_id": bid, "fn": fn, "emails": [{"value": fn.split()[0].lower() + "@example.com", "type": ["work"]}]})
    assert r.ok, r.text
    return r.json()["id"]


def place(s, kind, rid, parent):
    return s.post(B + "/api/files/refs", json={"ref_kind": kind, "ref_id": rid, "parent_id": parent})


def fshare(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def role(s, cid):
    r = s.get(B + f"/api/contacts/{cid}")
    return r.json().get("role") if r.ok else None


def tree(s):
    r = s.get(B + "/api/contacts/folders")
    return r.json() if r.ok else {}


def listed(s, **q):
    r = s.get(B + "/api/contacts", params=q)
    return {x["id"] for x in r.json()["items"]} if r.ok else set()


def dav(user, pw, m, path, body=None, **h):
    hd = {"X-Forwarded-Proto": "https", **{k.replace("_", "-"): v for k, v in h.items()}}
    return requests.request(m, B + path, auth=(user, pw), data=body.encode() if isinstance(body, str) else body, headers=hd,
                            allow_redirects=False)


PF = '<?xml version="1.0"?><D:propfind xmlns:D="DAV:"><D:prop><D:displayname/></D:prop></D:propfind>'

# ================================================================ the root, folders, filing
t = tree(A)
check(t and all(x["root"] is None for x in t["spaces"]) and t["folders"] == [] and {x["space"] for x in t["spaces"]} == {"private", SP},
      f"no root before the first folder {t}")
F1 = folder(A, "Friends")
F2 = folder(A, "Suppliers", parent=F1)
t = tree(A)
root = next(x["root"] for x in t["spaces"] if x["space"] == "private")
check(root and [f["id"] for f in t["folders"]] == [F1, F2], f"the root holds the folders {t}")
check(A.get(B + f"/api/files/nodes/{root}").json().get("name") == "Address book", "the root is called Address book (English)")
BK = book(A, "Private people")
P1 = contact(A, BK, "Paula Example")
check(role(Bo, P1) is None, "bob: alice's private contact unseen")
r = place(A, "address_book", BK, F1)
check(r.ok, "alice files her address book into Friends " + r.text[:200])
t = tree(A)
check(any(x["kind"] == "book" and x["id"] == BK and x["parent_id"] == F1 for x in t["items"]), "the tree lists the book in Friends")
check(listed(A, folder=F1) == {P1}, "the folder filter lists the book's contacts")

# ================================================================ a folder share on a book
S1 = fshare(A, F1, user_id=uid["bob"], role="view")
check(role(Bo, P1) == "view", "bob: view on the book's contact through the folder")
check(Bo.patch(B + f"/api/contacts/{P1}", json={"note": "x"}).status_code == 403, "bob: view = no change")
check(any(b["id"] == BK and b["role"] == "view" for b in Bo.get(B + "/api/books").json()["items"]), "bob: the book is in his list (view)")
P2 = contact(A, BK, "Peter Later")
check(role(Bo, P2) == "view", "bob: also a contact added later")
check(place(Bo, "address_book", BK, None).status_code == 403, "bob: filing / taking out needs edit from the book itself")
check(A.patch(B + f"/api/files/shares/{S1}", json={"role": "edit"}).ok and role(Bo, P1) == "edit", "share edit = edit")
check(Bo.patch(B + f"/api/contacts/{P1}", json={"note": "Met at the fair"}).ok, "bob changes the contact")
check(Bo.patch(B + f"/api/books/{BK}", json={"name": "Mine now"}).status_code == 403, "never the book's settings (owner only)")
# book_members stays valid: the higher one counts
check(A.put(B + f"/api/books/{BK}/members", json={"user_id": uid["bob"], "role": "view"}).ok, "alice also shares the book itself (view)")
check(role(Bo, P1) == "edit", "book share view + folder edit = edit (the higher one)")
check(A.patch(B + f"/api/files/shares/{S1}", json={"role": "view"}).ok and A.put(B + f"/api/books/{BK}/members", json={"user_id": uid["bob"], "role": "edit"}).ok
      and role(Bo, P1) == "edit", "book share edit + folder view = edit: nothing gets narrower")
BF = folder(Bo, "Bob's folder")
BK3 = book(A, "Shared directly")
P3 = contact(A, BK3, "Rita Direct")
check(A.put(B + f"/api/books/{BK3}/members", json={"user_id": uid["bob"], "role": "edit"}).ok and role(Bo, P3) == "edit", "a book share with edit")
check(place(Bo, "address_book", BK3, BF).status_code == 403 and place(Bo, "contact", P3, BF).status_code == 403,
      "a book share with edit cannot file the book / its contact into an own folder (it would pass the book on)")
check(A.delete(B + f"/api/books/{BK}/members/{uid['bob']}").ok, "book share withdrawn")
check(A.delete(B + f"/api/files/shares/{S1}").ok and role(Bo, P1) is None, "folder share withdrawn = no role")

# ================================================================ a single contact in a folder
BW = book(A, "Work")
W1, W2 = contact(A, BW, "Carl Supplier"), contact(A, BW, "Dora Other")
check(place(A, "contact", W1, F2).ok, "alice files one contact into Suppliers")
S2 = fshare(A, F2, user_id=uid["bob"], role="edit")
check(role(Bo, W1) == "edit" and role(Bo, W2) is None, "bob: only the filed contact, not the rest of its book")
check(W1 in listed(Bo) and W2 not in listed(Bo), "the list shows the shared contact only")
check(Bo.patch(B + f"/api/contacts/{W1}", json={"title": "Sales"}).ok, "bob changes its fields")
check(Bo.delete(B + f"/api/contacts/{W1}").status_code == 403, "deleting stays with a role on the book")
BB = book(Bo, "Bob's own")
check(Bo.patch(B + f"/api/contacts/{W1}", json={"book_id": BB}).status_code == 403, "moving it into another book: 403")
check(A.patch(B + f"/api/contacts/{W1}", json={"fn": "Carl Supplier Ltd"}).ok and
      any(x["id"] == W1 and x["name"] == "Carl Supplier Ltd" for x in tree(A)["items"]), "the node follows the contact's name")

# ================================================================ CardDAV: exactly what bob may see
PWB = Bo.post(B + "/api/me/app-passwords", json={"name": "Phone"}).json()["password"]
S1b = fshare(A, F1, user_id=uid["bob"], role="view")
ls = dav("bob", PWB, "PROPFIND", "/dav/addressbooks/bob/", PF, Depth="1")
check(ls.status_code == 207 and f"/b{BK}/" in ls.text and "/s1/" in ls.text and f"/b{BW}/" not in ls.text,
      "carddav: the book through the folder and the collection of single contacts, not the rest " + ls.text[:300])
c1 = dav("bob", PWB, "PROPFIND", "/dav/addressbooks/bob/s1/", PF, Depth="1")
check(c1.status_code == 207 and f"c{W1}.vcf" in c1.text and f"c{W2}.vcf" not in c1.text, "carddav s1: only the shared contact")
g1 = dav("bob", PWB, "GET", f"/dav/addressbooks/bob/s1/c{W1}.vcf")
check(g1.status_code == 200 and "Carl Supplier Ltd" in g1.text, "carddav: its vCard")
check(dav("bob", PWB, "PUT", f"/dav/addressbooks/bob/s1/c{W1}.vcf", g1.text, Content_Type="text/vcard").status_code == 403 and
      dav("bob", PWB, "DELETE", f"/dav/addressbooks/bob/s1/c{W1}.vcf").status_code == 403, "carddav s1 is read only")
check(dav("bob", PWB, "GET", f"/dav/addressbooks/bob/s1/c{W2}.vcf").status_code == 404, "carddav: another contact of the book 404")
check(place(A, "contact", W1, None).ok and role(Bo, W1) is None and
      "/s1/" not in dav("bob", PWB, "PROPFIND", "/dav/addressbooks/bob/", PF, Depth="1").text, "taken out of the folder: gone, also over CardDAV")
check(place(A, "contact", W1, F2).ok and role(Bo, W1) == "edit", "filed again")

# ================================================================ the folder into the trash: no contact is deleted
check(A.delete(B + f"/api/files/nodes/{F1}").ok, "alice moves Friends into the trash")
check(role(A, P1) == "owner" and role(A, W1) == "owner" and role(Bo, P1) is None and role(Bo, W1) is None,
      "the contacts stay for alice, bob loses them")
check(A.post(B + f"/api/files/nodes/{F1}/restore").ok and role(Bo, P1) == "view", "restored: back")

# ================================================================ agents: only with a share on exactly them
OB = book(A, "Studio contacts", ORG)
O1 = contact(A, OB, "Olivia Studio")
OF = folder(A, "Crew", SP)
check(place(A, "address_book", OB, OF).ok, "an organisation book into an organisation folder")
AG, ag = agent("crewbot", org=ORG)
NG, ng = agent("nocontacts", scopes=("read", "write"), org=ORG)
r = ag.get(V + f"/contacts/{O1}")
check(r.status_code == 404, f"agent: nothing without a share {r.status_code} {r.text[:200]}")
check(A.patch(B + f"/api/files/nodes/{OF}", json={"org_access": "view"}).ok and ag.get(V + f"/contacts/{O1}").status_code == 404,
      "agent: organisation access gives nothing")
fshare(A, OF, agent_id=AG, role="view")
fshare(A, OF, agent_id=NG, role="view")
r = ag.get(V + f"/contacts/{O1}")
check(r.ok and ag.patch(V + f"/contacts/{O1}", json={"note": "x"}).status_code == 403, f"agent: view through its share {r.status_code} {r.text[:200]}")
check(ng.get(V + f"/contacts/{O1}").status_code in (403, 404), "an agent token without the scope contacts: never")
r = ag.get(V + "/address-books")
check(r.ok and any(b["id"] == OB for b in r.json()["data"]), "agent: the book in its list")
# the book share dialog offers agents: the server takes them (book_members)
B2 = book(A, "Partners", ORG)
Q1 = contact(A, B2, "Quinn Partner")
check(ag.get(V + f"/contacts/{Q1}").status_code == 404, "agent: another book unseen")
check(A.put(B + f"/api/books/{B2}/members", json={"user_id": AG, "role": "view"}).ok and ag.get(V + f"/contacts/{Q1}").ok,
      "the book shared with the agent directly (the dialog's agents)")

# ================================================================ another organisation: never across
check(Ol.post(B + "/api/contacts/folders", json={"name": "X", "space": SP}).status_code == 404, "olga: no folder in Alpha's address book")
OLF = folder(Ol, "Theirs", f"org:{BETA}")
check(place(A, "address_book", OB, OLF).status_code in (403, 404, 409), "never filed across the organisations")
check(Ol.get(B + f"/api/contacts/{O1}").status_code == 404, "olga: alpha's contact 404")

# ================================================================ a person without an organisation
# freelancer-matrix: pim
FID, Fl = freelancer(B, A)
t = tree(Fl)
check([x["space"] for x in t.get("spaces", [])] == ["private"], f"freelancer: only her private address book {t}")
FF = folder(Fl, "Clients")
FB = book(Fl, "Customers")
FC = contact(Fl, FB, "Fiona Customer")
check(place(Fl, "contact", FC, FF).ok and any(x["id"] == FC for x in tree(Fl)["items"]), "freelancer: her contact in her folder")
r = Fl.post(B + "/api/my/agents", json={"username": "fridabook", "display_name": "Fridabook", "scopes": ["read", "contacts"]})
check(r.ok, "freelancer: her own agent " + r.text[:200])
FA, fa = r.json()["id"], bearer(r.json()["token"])
check(fa.get(V + f"/contacts/{FC}").status_code == 404, "her agent: nothing without a share")
fshare(Fl, FF, agent_id=FA, role="view")
check(fa.get(V + f"/contacts/{FC}").ok, "her agent with a share: reads the contact")
check(listed(Fl, folder=FF) == {FC}, "freelancer: the folder filter")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
