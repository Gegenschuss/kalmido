#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.567.0 B (#4711): the shared core, stage 2 -- the office rows of group 1 and the clients save through ONE write call
(kalmido/office/owrite.py ow_write on core/writes.py). Own container (org encryption on). Invented names only.
freelancer-matrix: office
 - per object (letter, client, business contract, document template, generated document, deal, letter block, vehicle,
   drive): two writers -- B saves without a version (old clients: as before), A with the version it opened -> 409 with the
   current state under "current" (2.576.0 #4794: the route's old key went), nothing written; only the fields sent change (another
   field stays); the history (obj_history) has the change with before / after; updated_by names who saved
 - a letter: the session undo (header X-Kalmido-Undo, POST /api/office/undo/letter/<id>) takes the own step back; a
   change of someone else in between: 409
 - the same for a person without an organisation in the personal office
 - an encrypted column stays sealed in the history (no plain text of a letter's body there)
usage: p2567_b_office_core_test.py <datadir>"""
import base64
import json
import os
import sys
from datetime import date

import kt
from kt import B, check
from freelancer_fixture import freelancer

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2567B")

A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,files,docs", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
O = "/api/office"
D = date.today().isoformat()
SECRET = "Geheimer Brieftext 4711"


def sql(q, args=()):
    return kt.dbx(q, args)


def stored(table, rid):
    r = sql(f"SELECT * FROM {table} WHERE id=?", (rid,))
    return dict(r[0]) if r else {}


def two(s, who, what, kind, table, rid, url, b1, b2, alias="row", hist=None, keep=None, method="PATCH", uid=None):
    """B saves b1 without a version, A then saves b2 with the version it opened (before B): 409, nothing written; the
    fresh version passes. hist = a column b1 changes (the history names it); keep = a column neither sends (it stays)."""
    p = f"{who} {what}: "
    t0 = stored(table, rid).get("updated_at")
    check(bool(t0), p + "the row carries updated_at")
    k0 = stored(table, rid).get(keep) if keep else None
    r = s.request(method, B + url, json=b1)
    check(r.ok, p + f"without expect_updated_at as before {r.status_code} {r.text[:200]}")
    t1 = stored(table, rid).get("updated_at")
    check(t1 and t1 != t0, p + f"the save made a new version {t0} -> {t1}")
    snap = stored(table, rid)
    r = s.request(method, B + url, json={**b2, "expect_updated_at": t0})
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    check(r.status_code == 409 and isinstance(j.get("current"), dict), p + f"an old version: 409 with the state under current {r.status_code} {r.text[:200]}")
    check(r.status_code != 409 or alias is None or alias not in j, p + f"2.576.0 (#4794): the old key {alias} went (only current)")
    check(stored(table, rid) == snap, p + "the 409 wrote nothing")
    r = s.request(method, B + url, json={**b2, "expect_updated_at": t1})
    check(r.ok, p + f"the fresh version: 200 {r.status_code} {r.text[:200]}")
    if keep:
        check(stored(table, rid).get(keep) == k0, p + f"only the fields sent change: {keep} stays")
    if uid:
        check(stored(table, rid).get("updated_by") == uid, p + f"updated_by names who saved {stored(table, rid).get('updated_by')}")
    h = sql("SELECT vals_before, vals_after, action FROM obj_history WHERE kind=? AND ref_id=? ORDER BY id", (kind, rid))
    # 2.585.0 (#4795): a new deal / lead starts with a create entry, the changes follow as updates
    h = [x for x in h if x[2] != "create"] if kind == "office_deal" else h
    check(len(h) >= 1 and all(x[2] == "update" for x in h), p + f"the history has the change ({len(h)})")
    if hist and h:
        names = set()
        for x in h:
            names |= set(json.loads(x[0])) | set(json.loads(x[1]))
        check(hist in names, p + f"the history names {hist}: {sorted(names)}")
    return h


for who, s, cl_org, uid in (("org", A, ORG, ALICE), ("freelancer", Fr, None, FID)):
    cli = s.post(B + "/api/clients", json={"name": f"Example Client {who}", "note": "keep me", **({"org_id": cl_org} if cl_org else {})}).json()["id"]

    # ---- clients (the old key: client)
    two(s, who, "client", "client", "clients", cli, f"/api/clients/{cli}", {"phone": "+49 30 1"}, {"email": "b@example.com"}, alias="client",
        hist="phone", keep="note", uid=uid)

    # ---- letters (the old key: letter); the body is encrypted at rest and stays sealed in the history
    r = s.post(B + O + "/letters", json={"subject": "Kündigung", "body": SECRET, "client_id": cli})
    check(r.status_code == 201, f"{who}: a letter {r.status_code} {r.text[:200]}")
    lid = r.json()["id"]
    two(s, who, "letter", "office_letter", "office_letters", lid, f"{O}/letters/{lid}", {"body": SECRET + " B"}, {"ref_line": "A-1"}, alias="letter",
        hist="body", keep="subject", uid=uid)
    raw = " ".join(x[0] + x[1] for x in sql("SELECT vals_before, vals_after FROM obj_history WHERE kind='office_letter' AND ref_id=?", (lid,)))
    check(SECRET not in raw, f"{who} letter: the history keeps the encrypted body sealed")

    # ---- the session undo of a letter
    tok = ("%032x" % (0x4711b0 + uid))
    r = s.patch(B + f"{O}/letters/{lid}", json={"subject": "Kündigung zum Jahresende"}, headers={"X-Kalmido-Undo": tok})
    check(r.ok, f"{who} letter: a step with the undo header {r.status_code}")
    r = s.post(B + f"{O}/undo/letter/{lid}", json={"sess": tok, "op": "undo"})
    check(r.ok and r.json().get("subject") == "Kündigung" and r.json().get("undo_steps") == {"undone": 1},
          f"{who} letter: undo takes the own step back {r.status_code} {r.text[:200]}")
    r = s.post(B + f"{O}/undo/letter/{lid}", json={"sess": tok, "op": "redo"})
    check(r.ok and r.json().get("subject") == "Kündigung zum Jahresende", f"{who} letter: redo {r.status_code} {r.text[:200]}")
    check(s.patch(B + f"{O}/letters/{lid}", json={"ref_line": "other device"}).ok, f"{who} letter: a change without the session")
    r = s.post(B + f"{O}/undo/letter/{lid}", json={"sess": tok, "op": "undo"})
    check(r.status_code == 409 and s.get(B + f"{O}/letters/{lid}").json().get("ref_line") == "other device",
          f"{who} letter: changed in between: 409, it stays {r.status_code}")
    check(any(x[0] == "undo" for x in sql("SELECT action FROM obj_history WHERE kind='office_letter' AND ref_id=?", (lid,))), f"{who} letter: the undo is in the history")

    # ---- business contracts
    r = s.post(B + O + "/agreements", json={"kind": "rent", "name": f"Studio rent {who}", "provider": "Example Landlord", "cost": "900", "per": "month", "task": 0})
    check(r.status_code == 201, f"{who}: a contract {r.status_code} {r.text[:200]}")
    aid = r.json()["id"]
    two(s, who, "contract", "office_agreement", "office_agreements", aid, f"{O}/agreements/{aid}", {"note": "B"}, {"number": "A-7"}, hist="note", uid=uid)

    # ---- document templates and generated documents
    r = s.post(B + O + "/doc-templates", json={"name": "Confirmation", "kind": "other", "body": "Hello {{client.name}}", "sign": 0})
    check(r.status_code == 201, f"{who}: a template {r.status_code} {r.text[:200]}")
    tid = r.json()["id"]
    two(s, who, "template", "office_doctpl", "office_doc_templates", tid, f"{O}/doc-templates/{tid}", {"name": "Confirmation B"}, {"body": "Text A"},
        hist="name", uid=uid)
    r = s.post(B + O + "/gen-docs", json={"title": "Note", "body": "First text", "client_id": cli})
    check(r.status_code == 201, f"{who}: a generated document {r.status_code} {r.text[:200]}")
    gid = r.json()["id"]
    two(s, who, "gendoc", "office_gendoc", "office_gen_docs", gid, f"{O}/gen-docs/{gid}", {"title": "Note B"}, {"body": "Tab A text"}, hist="title", uid=uid)

    # ---- deals
    r = s.post(B + O + "/deals", json={"title": f"Image film {who}", "note": "keep"})
    check(r.status_code == 201, f"{who}: a deal {r.status_code} {r.text[:200]}")
    did = r.json()["id"]
    two(s, who, "deal", "office_deal", "office_deals", did, f"{O}/deals/{did}", {"value": "5000"}, {"next_step": "call back"}, hist="value", uid=uid)

    # ---- letter blocks (master data texts: office_update writes, the check sits before the field filter now)
    r = s.post(B + O + "/letter-blocks", json={"name": "Objection", "body": "I object."})
    check(r.status_code == 201, f"{who}: a letter block {r.status_code} {r.text[:200]}")
    bid = r.json()["id"]
    two(s, who, "block", "office_md_texts", "office_texts", bid, f"{O}/letter-blocks/{bid}", {"name": "Objection B"}, {"body": "I object hereby."}, hist="key")

    # ---- logbook: vehicles and drives
    r = s.post(B + O + "/vehicles", json={"name": f"Wagen {who}", "kind": "company"})
    check(r.status_code in (200, 201), f"{who}: a vehicle {r.status_code} {r.text[:200]}")
    vid = r.json()["id"]
    two(s, who, "vehicle", "office_vehicle", "office_vehicles", vid, f"{O}/vehicles/{vid}", {"plate": "XX-A 1"}, {"name": f"Wagen {who} 2"}, uid=uid)
    r = s.post(B + O + "/drives", json={"vehicle_id": vid, "day": D, "dest": "Kunde", "purpose": "Termin", "km": 20, "kind": "business"})
    check(r.status_code in (200, 201), f"{who}: a drive {r.status_code} {r.text[:200]}")
    drv = r.json()["id"]
    two(s, who, "drive", "office_drive", "office_drives", drv, f"{O}/drives/{drv}", {"dest": "Kunde A"}, {"purpose": "Termin B"}, uid=uid)

sys.exit(kt.done("p2567_b_office_core"))
