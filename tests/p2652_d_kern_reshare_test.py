#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.652.0 part D (#5089): sharing anew in the calendar / address book dialog after the share in the core ran out lets the
person in again, and the boundary check counts a client's contact person in a private book only while the book's share with
the client's creator is live. Own container. People without an organisation (the freelancer case). Invented names only.
freelancer-matrix: pim
 - sharing anew (5089_a.py; 2.924.0 #5069: core/objects.py obj_node_person_put, the mirror is gone): a calendar / an address book shared, the core share's expiry put
   in the past (the person no longer sees it), shared again through PUT /api/evcals|books/<id>/members: the share is without
   end date and the person sees it again (regression: only the role was set, the old expiry stayed)
 - accounts/tenancy.py client_contact: a client (no organisation) of fiona linked to a contact of dora's private book that
   dora shared with fiona: not counted while the share lives, counted once it ran out (regression: the old member row
   book_members still counted), not counted again after sharing anew
usage: p2652_d_kern_reshare_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, check  # noqa: E402

kt.fresh(env={"KALMIDO_API_RATE": "100000"}, prefix="P2652D")
PAST = "2020-01-01T00:00:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"
TS = "2026-11-01T00:00:00+00:00"


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def ids(r):
    j = r.json() if r.ok else {}
    rows = j if isinstance(j, list) else (j.get("items") or j.get("data") or [])
    return {x.get("id") for x in rows}


def share(kind, rid, who):
    """(id, role, expires_at) of who's share on the reference node of the object, or None."""
    r = sql("SELECT s.id, s.role, s.expires_at FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind=? "
            "AND n.ref_id=? AND (s.user_id=? OR s.agent_id=?)", (kind, rid, who, who))
    return tuple(r[0]) if r else None


def connect(a, b):  # an accepted connection request (accounts/discover.py): people without an organisation see each other
    sql("INSERT INTO conn_links(a_id,b_id,created_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (min(a, b), max(a, b), TS), write=True)


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Northwind Studio"})  # workspaces on: the boundary check runs
check(r.status_code in (200, 201), f"setup: an organisation (workspaces) {r.status_code} {r.text[:120]}")
DORA, Do = freelancer(B, A, "dora")
FIONA, Fi = freelancer(B, A, "fiona")
connect(DORA, FIONA)

# ================================================================== the mirror: sharing anew after the core share ran out
K = Do.post(B + "/api/evcals", json={"name": "Dora's rota", "org_id": None}).json()["id"]
BK = Do.post(B + "/api/books", json={"name": "Dora's people"}).json()["id"]
for url, kind, rid, lst in (("evcals", "evcal", K, "/api/evcals"), ("books", "address_book", BK, "/api/books")):
    r = Do.put(B + f"/api/{url}/{rid}/members", json={"user_id": FIONA, "role": "view"})
    s = share(kind, rid, FIONA)
    check(r.ok and s and s[1] == "view" and s[2] is None, f"setup: dora's {url} shared with fiona ({r.status_code} {s})")
    check(rid in ids(Fi.get(B + lst)), f"fiona sees dora's {url}")
    sql("UPDATE fs_shares SET expires_at=? WHERE id=?", (PAST, s[0]), write=True)  # the share in the core ran out
    check(rid not in ids(Fi.get(B + lst)), f"fiona no longer sees dora's {url} (the share ran out)")
    r = Do.put(B + f"/api/{url}/{rid}/members", json={"user_id": FIONA, "role": "view"})
    s = share(kind, rid, FIONA)
    check(r.ok and s and s[1] == "view" and s[2] is None,
          f"#5089: shared again through the {url} dialog: the share is without end date (regression: the old expiry stayed) ({r.status_code} {s})")
    check(rid in ids(Fi.get(B + lst)), f"#5089: fiona sees dora's {url} again (regression: she stayed out)")
    sql("UPDATE fs_shares SET expires_at=? WHERE id=?", (PAST, s[0]), write=True)
    r = Do.put(B + f"/api/{url}/{rid}/members", json={"user_id": FIONA, "role": "edit"})
    s = share(kind, rid, FIONA)
    check(r.ok and s and s[1] == "edit" and s[2] is None and rid in ids(Fi.get(B + lst)),
          f"#5089: shared again with another role: the new role, without end date ({s})")
    sql("UPDATE fs_shares SET expires_at=? WHERE id=?", (FUTURE, s[0]), write=True)  # a deliberate end date, still valid
    r = Do.put(B + f"/api/{url}/{rid}/members", json={"user_id": FIONA, "role": "view"})
    s = share(kind, rid, FIONA)
    check(r.ok and s and s[1] == "view" and s[2] == FUTURE and rid in ids(Fi.get(B + lst)),
          f"#5089 review: a role change keeps a still valid end date (regression: it was lifted) ({s})")
    Do.put(B + f"/api/{url}/{rid}/members", json={"user_id": FIONA, "role": "edit"})  # back to the state the next block expects
    sql("UPDATE fs_shares SET expires_at=NULL WHERE id=?", (s[0],), write=True)

# ================================================================== tenancy client_contact: the core's share counts
sql("INSERT INTO clients(org_id,name,created_by,created_at,updated_at) VALUES(NULL,'Example Client P2652D',?,?,?)", (FIONA, TS, TS), write=True)
CL = sql("SELECT id FROM clients WHERE name='Example Client P2652D'")[0][0]
r = Do.post(B + "/api/contacts", json={"book_id": BK, "given": "Erika", "family": "Example"})
CT = (r.json() or {}).get("id") if r.ok else None
check(CT, f"setup: a contact in dora's book {r.status_code} {r.text[:120]}")
sql("INSERT INTO office_client_contacts(org_id,client_id,name,contact_id,is_default,created_at,updated_at) VALUES(NULL,?,'Erika Example',?,1,?,?)",
    (CL, CT, TS, TS), write=True)


def flagged():
    """Is (fiona's client, fiona) a client_contact of the boundary check (GET /api/admin/orgs, the live count)?"""
    r = A.get(B + "/api/admin/orgs")
    assert r.ok, r.text
    return [CL, FIONA] in ((r.json().get("boundary") or {}).get("sample") or {}).get("client_contact", [])


s = share("address_book", BK, FIONA)
check(s and s[2] is None and not flagged(), f"the book's share with fiona lives: her client's contact person crosses nothing ({s})")
sql("UPDATE fs_shares SET expires_at=? WHERE id=?", (PAST, s[0]), write=True)
# 2.924.0 (#5069): book_members is gone -- the run-out share alone decides
check(flagged(), "#5089: the share ran out: the boundary check counts the client's contact person (regression: book_members still counted)")
check(Do.put(B + f"/api/books/{BK}/members", json={"user_id": FIONA, "role": "view"}).ok and not flagged(),
      "#5089: shared again through the dialog: counted no more")
# the clean-up of the boundary check (POST /api/admin/orgs/boundary/repair) keeps the link of a live share
r = A.post(B + "/api/admin/orgs/boundary/repair")
check(r.ok and sql("SELECT contact_id FROM office_client_contacts WHERE client_id=?", (CL,)) == [(CT,)],
      f"the clean-up keeps the link while the share lives ({r.status_code} {r.text[:120]})")
sql("UPDATE fs_shares SET expires_at=? WHERE id=?", (PAST, share("address_book", BK, FIONA)[0]), write=True)
r = A.post(B + "/api/admin/orgs/boundary/repair")
check(r.ok and sql("SELECT contact_id FROM office_client_contacts WHERE client_id=?", (CL,)) == [(None,)],
      f"#5089: the clean-up drops the link once the share ran out; the contact person stays ({r.status_code} {r.text[:120]})")
sys.exit(kt.done("p2652_d_kern_reshare"))
