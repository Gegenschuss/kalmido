#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.570.0 A (#4783): the history of an office row is readable -- GET <the save route's path>/history (office/owrite.py
ow_history), with exactly the rights of the save route. Own container (org encryption on). Invented names only.
freelancer-matrix: office
tenant-matrix: office
 - per object on ow_write (trip, receipt, purpose, fixed cost, correction, card, card position, bank rule, invoice series,
   entertainment receipt, place, client, letter, business contract, document template, generated document, deal, letter
   block, vehicle, drive): one change, then its history names the person and the changed field (no values: an encrypted
   column stays sealed)
 - the person without an organisation (tests/freelancer_fixture.py) in the personal office does the same
 - another organisation's admin: the history answers like the save route does (404), an org member ("Previous access"):
   denied where saving is denied (the same answer as an empty save)
 - office groups: "Read only" sees a trip but not its history (saving needs "edit"); "Staff" (level own) reads the history
   of an own trip, somebody else's is 404; "Bookkeeping" (travel edit) reads a trip's history but not a vehicle's (the
   vehicles' save needs "manage")
 - 2.570.0 (#4783 review F1): read-only / accounting / guest get no history (403 like saving), also inside an office group
 - two writers: A opened, B saved, A saves with the old version -> 409 with the current state under "current", B's change stays
usage: p2570_a_office_test.py <datadir>"""
import base64
import os
import sys
from datetime import date

import kt
from kt import B, check
from freelancer_fixture import freelancer, login

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2570A")

FEAT = "cal,comments,collab,office,clients,files,docs"
A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": kt.PASSWORD, "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} {r.status_code} {r.text[:120]}")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok, "setup: bob in Alpha")
CARL_ID = [x for x in kt.dbx("SELECT id FROM users WHERE username='carl'")][0][0]
BOB = [x for x in kt.dbx("SELECT id FROM users WHERE username='bob'")][0][0]
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CARL_ID}).json()["id"]
Bo, Ca = login(B, "bob"), login(B, "carl")
for s, ws in ((Bo, f"org:{ORG}"), (Ca, f"org:{BETA}")):
    check(s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": ws}).ok, f"setup: {ws}")
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
O = "/api/office"
D = date.today().isoformat()
MONTH = D[:7]
SECRET = "Geheimer Brieftext 4783"


def made(r, p, key=None):
    check(r.status_code in (200, 201), p + f" created {r.status_code} {r.text[:200]}")
    j = r.json() if r.status_code in (200, 201) else {}
    return ((j.get(key) if key else j) or {}).get("id", 0)


def objects(s, who, uid, cl_org=None):
    """-> [(what, save path, method, change, the field the history names, the history path)] after creating each object."""
    out = []
    r = s.post(B + "/api/office/trips", json={"date_from": D, "date_to": D, "dest": f"Kernstadt {who}", "items": [{"date": D, "category": "taxi", "amount": 12, "text": "Taxi"}]})
    tid = made(r, f"{who} trip")
    iid = r.json()["items"][0]["id"] if r.ok else 0
    out.append(("trip", f"/api/office/trips/{tid}", "PATCH", {"dest": f"Ziel {who}"}, "dest", f"/api/office/trips/{tid}/history"))
    out.append(("receipt", f"/api/office/trips/{tid}/items/{iid}", "PATCH", {"text": "Taxi A"}, "text", f"/api/office/trips/{tid}/items/{iid}/history"))
    pid = made(s.post(B + "/api/office/trips/purposes", json={"name": f"Messe {who}"}), f"{who} purpose")
    out.append(("purpose", f"/api/office/trips/purposes/{pid}", "PATCH", {"name": f"Messe A {who}"}, "name", f"/api/office/trips/purposes/{pid}/history"))
    fid = made(s.post(B + "/api/office/fixed-costs", json={"label": "Rent", "amount": "500", "start": f"{MONTH}-01", "repeat": "monthly"}), f"{who} fixed cost")
    out.append(("fixed cost", f"/api/office/fixed-costs/{fid}", "PATCH", {"amount": "550.00"}, "amount", f"/api/office/fixed-costs/{fid}/history"))
    aid = made(s.post(B + "/api/office/cashflow/adjust", json={"month": MONTH, "dir": "in", "amount": "100", "note": "expected"}), f"{who} correction")
    out.append(("correction", f"/api/office/cashflow/adjust/{aid}", "PATCH", {"note": "other"}, "note", f"/api/office/cashflow/adjust/{aid}/history"))
    cid = made(s.post(B + "/api/office/cards", json={"holder_id": uid, "last4": "2468", "account": "Konto"}), f"{who} card")
    out.append(("card", f"/api/office/cards/{cid}", "PATCH", {"account": "Konto A"}, "account", f"/api/office/cards/{cid}/history"))
    st = s.post(B + f"/api/office/cards/{cid}/statements", files={"file": ("stmt.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")}, data={"month": MONTH})
    sid = st.json()["statement"]["id"] if st.ok else 0
    lid = made(s.post(B + f"/api/office/cards/statements/{sid}/lines", json={"day": D, "merchant": "Kernladen", "amount": "9.00"}), f"{who} position", key="line")
    out.append(("card position", f"/api/office/cards/lines/{lid}", "PATCH", {"merchant": "Laden A"}, "merchant", f"/api/office/cards/lines/{lid}/history"))
    rid = made(s.post(B + "/api/office/bank/rules", json={"name": "Fees", "counterpart": "bank example", "action": "private"}), f"{who} rule", key="rule")
    out.append(("bank rule", f"/api/office/bank/rules/{rid}", "PUT", {"name": "Fees A"}, "name", f"/api/office/bank/rules/{rid}/history"))
    cli = made(s.post(B + "/api/clients", json={"name": f"Example Client {who}", **({"org_id": cl_org} if cl_org else {})}), f"{who} client")
    out.append(("client", f"/api/clients/{cli}", "PATCH", {"phone": "+49 30 1"}, "phone", f"/api/clients/{cli}/history"))
    inv = made(s.post(B + "/api/office/docs", json={"kind": "invoice", "client_id": cli}), f"{who} invoice")
    srid = made(s.post(B + "/api/office/series", json={"template_id": inv, "every": "monthly", "start": "2030-03-01"}), f"{who} series")
    out.append(("series", f"/api/office/series/{srid}", "PATCH", {"title": "Retainer A"}, "title", f"/api/office/series/{srid}/history"))
    mid = made(s.post(B + "/api/office/meals", json={"occasion": "first", "note": "n"}), f"{who} entertainment")
    out.append(("entertainment", f"/api/office/meals/{mid}", "PATCH", {"occasion": "Besprechung A"}, "occasion", f"/api/office/meals/{mid}/history"))
    chid = made(s.post(B + "/api/office/meals/choices", json={"kind": "place", "name": f"Kernlokal {who}", "extra": "Weg 1"}), f"{who} place")
    out.append(("place", f"/api/office/meals/choices/{chid}", "PATCH", {"extra": "Weg 2"}, "extra", f"/api/office/meals/choices/{chid}/history"))
    ltid = made(s.post(B + "/api/office/letters", json={"subject": "Kündigung", "body": SECRET, "client_id": cli}), f"{who} letter")
    out.append(("letter", f"/api/office/letters/{ltid}", "PATCH", {"body": SECRET + " B"}, "body", f"/api/office/letters/{ltid}/history"))
    agid = made(s.post(B + "/api/office/agreements", json={"kind": "rent", "name": f"Studio {who}", "provider": "Example Landlord", "cost": "900", "per": "month", "task": 0}), f"{who} contract")
    out.append(("contract", f"/api/office/agreements/{agid}", "PATCH", {"note": "B"}, "note", f"/api/office/agreements/{agid}/history"))
    tpl = made(s.post(B + "/api/office/doc-templates", json={"name": "Confirmation", "kind": "other", "body": "Hello {{client.name}}", "sign": 0}), f"{who} template")
    out.append(("template", f"/api/office/doc-templates/{tpl}", "PATCH", {"name": "Confirmation B"}, "name", f"/api/office/doc-templates/{tpl}/history"))
    gid = made(s.post(B + "/api/office/gen-docs", json={"title": "Note", "body": "First text", "client_id": cli}), f"{who} gendoc")
    out.append(("gendoc", f"/api/office/gen-docs/{gid}", "PATCH", {"title": "Note B"}, "title", f"/api/office/gen-docs/{gid}/history"))
    did = made(s.post(B + "/api/office/deals", json={"title": f"Image film {who}"}), f"{who} deal")
    out.append(("deal", f"/api/office/deals/{did}", "PATCH", {"value": "5000"}, "value", f"/api/office/deals/{did}/history"))
    bid = made(s.post(B + "/api/office/letter-blocks", json={"name": "Objection", "body": "I object."}), f"{who} block")
    out.append(("letter block", f"/api/office/letter-blocks/{bid}", "PATCH", {"name": "Objection B"}, None, f"/api/office/letter-blocks/{bid}/history"))
    vid = made(s.post(B + "/api/office/vehicles", json={"name": f"Wagen {who}", "kind": "company"}), f"{who} vehicle")
    out.append(("vehicle", f"/api/office/vehicles/{vid}", "PATCH", {"plate": "XX-A 1"}, "plate", f"/api/office/vehicles/{vid}/history"))
    drv = made(s.post(B + "/api/office/drives", json={"vehicle_id": vid, "day": D, "dest": "Kunde", "purpose": "Termin", "km": 20, "kind": "business"}), f"{who} drive")
    out.append(("drive", f"/api/office/drives/{drv}", "PATCH", {"dest": "Kunde A"}, "dest", f"/api/office/drives/{drv}/history"))
    return out


def run(s, who, uid, cl_org=None):
    objs = objects(s, who, uid, cl_org)
    for what, url, method, change, field, hist in objs:
        p = f"{who} {what}: "
        r = s.get(B + hist)
        check(r.status_code == 200 and r.json().get("items") == [], p + f"a new row: an empty history {r.status_code} {r.text[:160]}")
        r = s.request(method, B + url, json=change)
        check(r.ok, p + f"a change {r.status_code} {r.text[:160]}")
        r = s.get(B + hist)
        items = r.json().get("items") if r.status_code == 200 else None
        check(isinstance(items, list) and len(items) >= 1, p + f"the history after the change {r.status_code} {r.text[:200]}")
        if items:
            x = items[0]
            check(x["user_id"] == uid and x["name"] and not x["agent"] and x["action"] == "update", p + f"the entry names the person {x}")
            check(field is None or field in x["fields"], p + f"the entry names the field {field}: {x['fields']}")
            check(SECRET not in r.text, p + "no plain value in the history")
    return objs


objs_org = run(A, "org", ALICE, ORG)
run(Fr, "freelancer", FID)

# ---- another organisation's admin and an org member: the history answers what saving answers (denied = denied)
DENY = (403, 404)
for s, who in ((Ca, "another org's admin"), (Bo, "a member (Previous access)")):
    for what, url, method, change, field, hist in objs_org:
        h = s.get(B + hist)
        w = s.request(method, B + url, json={})
        check(h.status_code != 200 or w.status_code not in DENY, f"{who} {what}: saving is denied ({w.status_code}), so the history too: {h.status_code}")
        check(h.status_code not in DENY or w.status_code in DENY, f"{who} {what}: the history is denied ({h.status_code}), so is saving: {w.status_code}")
        if w.status_code in DENY:  # 2.570.0 (#4783): one answer per case - denied saving = denied history, else the history
            check(h.status_code in DENY, f"{who} {what}: saving denied, the history refused too {h.status_code} {h.text[:120]}")
        else:
            check(h.status_code == 200, f"{who} {what}: saving allowed, the history readable {h.status_code} {h.text[:120]}")
        if who.startswith("another"):
            check(h.status_code in DENY, f"{who} {what}: nothing of Alpha {h.status_code}")
            check("Kernstadt" not in h.text and "Example Client" not in h.text, f"{who} {what}: no content")

# ---- 2.570.0 (#4783 review F1): the organisation roles that read but do not save (read-only, accounting, guest) get no
# history (403 like the save; accounting and guests may not see the client at all: 404); the member keeps it
cli = next(x for x in objs_org if x[0] == "client")
r = Bo.get(B + cli[5])
check(r.status_code == 200 and r.json().get("items"), f"member: the client's history {r.status_code} {r.text[:120]}")
for role in ("readonly", "accounting", "guest"):
    check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": BOB, "role": role}).ok, f"role: bob {role}")
    check(Bo.request(cli[2], B + cli[1], json=cli[3]).status_code in DENY, f"{role}: saving the client is denied")
    h = Bo.get(B + cli[5])
    check(h.status_code == 403 or (role != "readonly" and h.status_code == 404), f"{role}: the client's history is denied like the save {h.status_code} {h.text[:120]}")
    for what, url, method, change, field, hist in objs_org:
        h = Bo.get(B + hist)
        check(h.status_code in DENY, f"{role} {what}: the history needs the role of saving {h.status_code} {h.text[:120]}")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": BOB, "role": "member"}).ok, "role: bob member again")
trip = next(x for x in objs_org if x[0] == "trip")
veh = next(x for x in objs_org if x[0] == "vehicle")
# ---- office groups: read only, staff (own), bookkeeping
check(A.put(B + f"/api/office/rights/people/{BOB}", json={"groups": ["tpl:readonly"]}).ok, "rights: bob read only")
check(Bo.get(B + "/api/office/trips").status_code == 200, "read only: the trips are readable")
check(Bo.get(B + trip[5]).status_code == 403, f"read only: its history needs edit like saving: {Bo.get(B + trip[5]).status_code}")
check(A.put(B + f"/api/office/rights/people/{BOB}", json={"groups": ["tpl:bookkeeping"]}).ok, "rights: bob bookkeeping")
r = Bo.get(B + trip[5])
check(r.status_code == 200 and r.json().get("items"), f"bookkeeping (travel edit): the trip's history {r.status_code} {r.text[:120]}")
check(Bo.get(B + veh[5]).status_code == 403, f"bookkeeping: a vehicle's history needs manage like saving it {Bo.get(B + veh[5]).status_code}")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": BOB, "role": "readonly"}).ok, "role: bob read-only in bookkeeping")
check(Bo.get(B + trip[5]).status_code == 403, f"bookkeeping + read-only role (#4783 review F1): no history, the role cannot save {Bo.get(B + trip[5]).status_code}")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": BOB, "role": "member"}).ok, "role: bob member in bookkeeping")
check(A.put(B + f"/api/office/rights/people/{BOB}", json={"groups": ["tpl:staff"]}).ok, "rights: bob staff")
r = Bo.post(B + "/api/office/trips", json={"date_from": D, "date_to": D, "dest": "Bobs Ziel"})
btid = made(r, "staff: an own trip")
check(Bo.patch(B + f"/api/office/trips/{btid}", json={"dest": "Bobs Ziel B"}).ok, "staff: changes the own trip")
r = Bo.get(B + f"/api/office/trips/{btid}/history")
check(r.status_code == 200 and r.json().get("items") and r.json()["items"][0]["user_id"] == BOB, f"staff: the own trip's history {r.status_code} {r.text[:160]}")
check(Bo.get(B + trip[5]).status_code == 404, f"staff: somebody else's trip history is 404 {Bo.get(B + trip[5]).status_code}")
check(Bo.get(B + veh[5]).status_code == 403, "staff: no vehicle history")

# ---- two writers on a trip and a letter: A opened, B saved, A saves with the old version -> 409 with "current", B's change stays
A2 = kt.sess("alice")
A2.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
for what, table, field, v_b, v_a in (("trip", "office_trips", "dest", "Ziel von B", "Ziel von A"), ("letter", "office_letters", "subject", "Betreff von B", "Betreff von A")):
    url = next(x for x in objs_org if x[0] == what)[1]
    rid = int(url.rsplit("/", 1)[1])
    seen = kt.dbx(f"SELECT updated_at FROM {table} WHERE id=?", (rid,))[0][0]  # what A's dialog opened
    check(A2.patch(B + url, json={field: v_b, "expect_updated_at": seen}).ok, f"{what}: B saves")
    r = A.patch(B + url, json={field: v_a, "expect_updated_at": seen})
    cur = r.json().get("current") if r.status_code == 409 else None
    check(r.status_code == 409 and isinstance(cur, dict) and cur.get(field) == v_b, f"{what}: A with the old version: 409 with B's state under current {r.status_code} {r.text[:200]}")
    check(kt.dbx(f"SELECT updated_at FROM {table} WHERE id=?", (rid,))[0][0] != seen and (what != "letter" or A.get(B + url).json().get(field) == v_b), f"{what}: B's change stays")

sys.exit(kt.done("p2570_a_office"))
