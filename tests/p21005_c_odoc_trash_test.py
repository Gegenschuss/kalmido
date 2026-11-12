#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1005.0 (#5415, stage 4d of the core's trash, part 1): a document draft of the office goes into the ONE trash of the core
(office/docs.py odoc_trash, kind odoc) instead of a copy in office_trash and the row deleted. Invented names only.
 - a draft quotation / invoice deleted -> the row stays with deleted_at, GET 404, not in the document list, not in the web
   search, not in the agents' API (list 404 by id), listed in the office trash (core odoc, kind doc, sub = its kind)
 - its number and a deal's reference to it are empty while it lies in the trash and come back on restore; a number taken
   since stays empty
 - the toast's undo (?undo=1) by the person who deleted it; no step in GET /api/undo
 - a finalised invoice never goes into the trash: 409, no deleted_at
 - rights: a member 403 (delete, restore), another organisation 404 (restore, delete for good)
 - delete for good from the office trash: the row is gone; the core's retention run deletes an old one, a younger stays
tenant-matrix: office (another organisation: 404 on a draft of the core's trash)
freelancer-matrix: office (a person without an organisation: her draft deleted, listed, restored, deleted for good)
usage: p21005_c_odoc_trash_test.py <datadir>"""
import subprocess
from datetime import timedelta, timezone

import requests

import kt
from kt import B, CT, check, sess
import testclock
from freelancer_fixture import freelancer

kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces"})
FEAT = "cal,comments,collab,office,clients,docs,files"
OFC = "/api/office"
D, T = OFC + "/docs", OFC + "/trash"
H = {"X-Requested-With": "kalmido"}
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
CLIENT = {"name": "Beispiel Kunde AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Musterstadt", "country": "DE"}


def sql(q, args=()):
    return kt.dbx(q, args)


def listed(s, kind, did):
    r = s.get(B + f"{D}?kind={kind}")
    return r.ok and any(x["id"] == did for x in r.json().get("docs", []))


def in_trash(s, did):
    r = s.get(B + T)
    return r.ok and next((x for x in r.json().get("items", []) if x.get("core") == "odoc" and x["id"] == did), None)


def tick():
    """The core's retention run with the switch on (forced)."""
    out = subprocess.run(["docker", "exec", "-e", "KALMIDO_RETENTION_PURGE=1", CT, "python", "-c",
                          "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.writes import obj_trash_tick\n"
                          "c = connect()\nprint('counts', obj_trash_tick(c, True))\nc.close()"], capture_output=True, text=True)
    check("counts" in out.stdout and "Traceback" not in out.stderr, "the retention run ran " + (out.stdout + out.stderr)[-600:])


def scenario(S, who, other, member=None, agent=None):
    cl = S.post(B + "/api/clients", json=CLIENT).json().get("id")
    # ------------------------------------------------------------ a draft quotation with a number and a deal pointing at it
    r = S.post(B + D, json={"kind": "offer", "lang": "en", "project_title": f"Zebrafilm {who}", "client_id": cl,
                            "items": [{"title": "Concept", "qty": 1, "rate": 800}]})
    check(r.status_code == 201, f"{who}: setup quotation {r.text[:200]}")
    did = r.json()["id"]
    num = S.get(B + f"{D}/{did}").json().get("number") or ""
    deal = S.post(B + OFC + "/deals", json={"title": f"Deal {who}"}).json().get("id")
    sql("UPDATE office_deals SET offer_id=? WHERE id=?", (did, deal))
    if member is not None:
        check(member.delete(B + f"{D}/{did}").status_code == 403, f"{who}: a member may not delete it (403)")
    r = S.delete(B + f"{D}/{did}")
    tr_ = r.json().get("trash") if r.ok else None
    check(r.ok and tr_ == {"kind": "odoc", "id": did}, f"{who}: the draft goes into the core's trash {r.text[:200]}")
    row = sql("SELECT deleted_at, number FROM office_docs WHERE id=?", (did,))
    check(row and row[0][0] and row[0][1] == "", f"{who}: the row stays with deleted_at, its number empty {row}")
    check(sql("SELECT offer_id FROM office_deals WHERE id=?", (deal,))[0][0] is None, f"{who}: the deal's reference is empty meanwhile")
    check(S.get(B + f"{D}/{did}").status_code == 404, f"{who}: GET of a draft in the trash 404")
    check(not listed(S, "offer", did), f"{who}: not in the document list")
    s = S.get(B + "/api/search?q=Zebrafilm")
    check(s.ok and f"Zebrafilm {who}" not in s.text, f"{who}: not in the web search {s.text[:300]}")
    if agent is not None:
        g = requests.get(B + f"/api/v1/office/docs/{did}", headers={**H, "Authorization": "Bearer " + agent})
        lst = requests.get(B + "/api/v1/office/docs", headers={**H, "Authorization": "Bearer " + agent})
        check(g.status_code == 404 and lst.ok and f"Zebrafilm {who}" not in lst.text,
              f"{who}: the agents' API does not see it ({g.status_code} {lst.status_code})")
    it = in_trash(S, did)
    check(it and it["kind"] == "doc" and it["sub"] == "offer" and f"Zebrafilm {who}" in it["label"],
          f"{who}: listed in the office trash with its title {it}")
    check(other.post(B + f"{T}/core/odoc/{did}/restore").status_code in (403, 404), f"{who}: another office cannot restore it")
    check(other.delete(B + f"{T}/core/odoc/{did}").status_code in (403, 404), f"{who}: another office cannot delete it for good")
    if member is not None:
        check(member.post(B + f"{T}/core/odoc/{did}/restore").status_code == 403, f"{who}: a member cannot restore it (403)")
    u = S.get(B + "/api/undo")
    check(u.ok and "odoc" not in u.text, f"{who}: no step of the core's undo (its route's checks) {u.text[:200]}")
    # the toast's undo
    r = S.post(B + f"{T}/core/odoc/{did}/restore?undo=1")
    check(r.ok and r.json().get("kind") == "doc" and r.json().get("id") == did, f"{who}: the toast's undo {r.text[:200]}")
    d = S.get(B + f"{D}/{did}").json()
    check(d.get("number") == num and [x["title"] for x in d.get("items") or []] == ["Concept"] and listed(S, "offer", did),
          f"{who}: back with its number, position, in the list {d.get('number')} {num}")
    check(sql("SELECT offer_id FROM office_deals WHERE id=?", (deal,))[0][0] == did, f"{who}: the deal points at it again")
    check(sql("SELECT trash_refs FROM office_docs WHERE id=?", (did,))[0][0] is None, f"{who}: trash_refs emptied")
    # ------------------------------------------------------------ a part of the quotation: trash, sums, restore
    r = S.post(B + f"{D}/{did}/parts", json={"kind": "items", "title": f"Dreh {who}"})
    part = (r.json().get("part") or {}).get("id") if r.status_code == 201 else None
    check(part, f"{who}: setup a part {r.status_code} {r.text[:200]}")
    r = S.put(B + f"{D}/{did}/parts/{part}/items", json={"items": [{"title": "Drehtag", "qty": 1, "rate": 1200}]})
    check(r.ok, f"{who}: setup the part's position {r.text[:200]}")
    net = S.get(B + f"{D}/{did}").json()["totals"]["net"]
    check(net == 2000, f"{who}: concept 800 + part 1200 {net}")
    r = S.delete(B + f"{D}/{did}/parts/{part}")
    check(r.ok and r.json().get("trash") == {"kind": "opart", "id": part}, f"{who}: the part goes into the core's trash {r.text[:200]}")
    d = S.get(B + f"{D}/{did}").json()
    check(d["totals"]["net"] == 800 and not d.get("parts") and [x["title"] for x in d.get("items") or []] == ["Concept"],
          f"{who}: the sums, parts and title page without it {d['totals'].get('net')} {d.get('parts')}")
    check(sql("SELECT COUNT(*) FROM office_doc_items WHERE part_id=? AND deleted_at IS NOT NULL", (part,))[0][0] == 1,
          f"{who}: its position lies in the trash with it")
    it = next((x for x in S.get(B + T).json().get("items", []) if x.get("core") == "opart" and x["id"] == part), None)
    check(it and it["kind"] == "part" and f"Dreh {who}" in it["label"], f"{who}: the office trash lists the part {it}")
    if member is not None:
        check(member.post(B + f"{T}/core/opart/{part}/restore").status_code == 403, f"{who}: a member cannot restore the part (403)")
    r = S.post(B + f"{T}/core/opart/{part}/restore")
    d = S.get(B + f"{D}/{did}").json()
    check(r.ok and r.json().get("doc_id") == did and d["totals"]["net"] == 2000 and [p["id"] for p in d.get("parts") or []] == [part],
          f"{who}: the part is back with its position and title page line {r.text[:200]} {d['totals'].get('net')}")
    # ------------------------------------------------------------ its number taken while it lies in the trash
    if num:
        check(S.delete(B + f"{D}/{did}").ok, f"{who}: into the trash again")
        d2 = S.post(B + D, json={"kind": "offer", "lang": "en", "project_title": f"Spot {who}", "client_id": cl}).json()["id"]
        sql("UPDATE office_docs SET number=? WHERE id=?", (num, d2))
        r = S.post(B + f"{T}/core/odoc/{did}/restore")
        check(r.ok and S.get(B + f"{D}/{did}").json().get("number") == "", f"{who}: restored without the number taken since {r.text[:200]}")
    # ------------------------------------------------------------ a finalised invoice never goes into the trash
    day = testclock.today().isoformat()
    r = S.post(B + D, json={"kind": "invoice", "project_title": f"Rechnung {who}", "client_id": cl, "service_from": day, "service_to": day})
    inv = r.json().get("id")
    S.put(B + f"{D}/{inv}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": 500}]})
    r = S.post(B + f"{D}/{inv}/finalize")
    check(r.ok and r.json().get("locked") is True, f"{who}: setup a finalised invoice {r.text[:200]}")
    r = S.delete(B + f"{D}/{inv}")
    check(r.status_code == 409 and not sql("SELECT deleted_at FROM office_docs WHERE id=?", (inv,))[0][0],
          f"{who}: a finalised invoice: 409, never in the trash {r.status_code}")
    # ------------------------------------------------------------ a draft invoice: delete for good from the office trash
    r = S.post(B + D, json={"kind": "invoice", "project_title": f"Entwurf {who}", "client_id": cl})
    di = r.json().get("id")
    check(S.delete(B + f"{D}/{di}").ok and in_trash(S, di), f"{who}: a draft invoice in the trash")
    check(not listed(S, "invoice", di), f"{who}: the draft invoice is not in the invoice list")
    r = S.delete(B + f"{T}/core/odoc/{di}")
    check(r.ok and not sql("SELECT 1 FROM office_docs WHERE id=?", (di,)), f"{who}: deleted for good {r.text[:200]}")
    # ------------------------------------------------------------ the retention run: an old one goes, a younger stays
    old = S.post(B + D, json={"kind": "offer", "lang": "en", "project_title": f"Alt {who}"}).json()["id"]
    young = S.post(B + D, json={"kind": "offer", "lang": "en", "project_title": f"Jung {who}"}).json()["id"]
    check(S.delete(B + f"{D}/{old}").ok and S.delete(B + f"{D}/{young}").ok, f"{who}: two drafts into the trash")
    sql("UPDATE office_docs SET deleted_at=? WHERE id=?", ((testclock.now() - timedelta(days=40)).astimezone(timezone.utc).isoformat(), old))
    return old, young


s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Fr = freelancer(B, A, "frida")
for s in (A, Fr):
    s.put(B + OFC + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"})
# the agents' API: an agent with the office scope and the office switches (as p21381_a)
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
A.put(B + OFC + "/settings", json={"agents_read": 1})
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "office"], "org_id": ORG})
check(r.status_code == 201, "setup: an agent " + r.text[:200])
AG, AGT = r.json().get("id"), r.json().get("token")
check(A.patch(B + f"{OFC}/agents/{AG}", json={"office_drafts": True}).ok, "setup: the agent's office switch")

outs = [scenario(A, "alice", Ca, member=Bo, agent=AGT), scenario(Fr, "frida", A)]
tick()
for who, (old, young) in zip(("alice", "frida"), outs):
    check(not sql("SELECT 1 FROM office_docs WHERE id=?", (old,)), f"{who}: the retention run deleted the old draft for good")
    check(sql("SELECT deleted_at FROM office_docs WHERE id=?", (young,))[0][0], f"{who}: the younger one stays in the trash")

raise SystemExit(kt.done("p21005_c_odoc_trash"))
