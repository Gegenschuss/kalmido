#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.560.0 D (#4700, audit #2822 B-F1 + C-F2, office part): the dialogs of trips, travel receipts, vehicles, drives, cash
book entries, credit cards, credit card positions and entertainment receipts save with a version check like the clients
(#3017): an old expect_updated_at -> 409 with the current row under "row" and nothing written; without expect_updated_at
(old clients, the agent API) as before; the fresh one -> 200 with the new updated_at. Own container (kt.fresh, mode
workspaces). Invented names only (example.com); the person without an organisation (tests/freelancer_fixture.py) and an
organisation admin do every step.
freelancer-matrix: office
usage: p2560_d_conflict_test.py <datadir>      (KMT_NOSTART=1: a running server)"""
import os
import sys
from datetime import date

import requests

import dbx as dbxm
import kt
from kt import B, DATA, check, done
from freelancer_fixture import FEATURES, freelancer

O = "/api/office"
OLD = "2020-01-02T03:04:05+00:00"  # the version the other device opened the dialog with
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def kt_src(rel):
    with open(os.path.join(SRC, rel), encoding="utf-8") as f:
        return f.read()


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # noqa: BLE001 - an UPDATE without rows to read
            return []
    finally:
        c.close()


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2560DC")
s0 = requests.Session()
s0.headers.update(kt.H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": kt.PASSWORD}).ok
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})  # Alice admins the organisation Alpha
A = kt.sess("alice")
check(A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok, "setup: Alice's features")
AID = A.get(B + "/api/state").json()["me"]["id"]
FID, Fr = freelancer(B, A)
D = date.today().isoformat()


def three(S, who, what, table, rid, url, b1, b2, ver):
    """The row's stored version goes back to OLD (another device saved, this dialog opened before): an older expect -> 409
    with the row and nothing written; without expect -> 200 as before; the fresh version -> 200 with a new updated_at."""
    sql(f"UPDATE {table} SET updated_at=? WHERE id=?", (OLD, rid))
    before = sql(f"SELECT * FROM {table} WHERE id=?", (rid,))
    r = S.patch(B + url, json={**b1, "expect_updated_at": "2019-12-31T00:00:00+00:00"})
    cur = (r.json().get("current") or r.json().get("row")) if r.status_code == 409 else None  # 2.567.0 (#4711): "current" of the core's write layer, "row" of the older routes
    check(isinstance(cur, dict), f"{who} {what}: an old expect_updated_at -> 409 with the row {r.status_code} {r.text[:200]}")
    check(r.status_code != 409 or ver(cur) == OLD, f"{who} {what}: the 409 names the stored version")
    check(sql(f"SELECT * FROM {table} WHERE id=?", (rid,)) == before, f"{who} {what}: the 409 wrote nothing")
    r = S.patch(B + url, json=b1)
    check(r.ok, f"{who} {what}: without expect_updated_at as before {r.status_code} {r.text[:200]}")
    now = ver(r.json()) if r.ok else None
    check(bool(now) and now != OLD, f"{who} {what}: the answer carries the new updated_at: {now!r}")
    r = S.patch(B + url, json={**b2, "expect_updated_at": now})
    check(r.ok and ver(r.json()) >= now, f"{who} {what}: the fresh expect_updated_at -> 200 {r.status_code} {r.text[:200]}")
    r = S.patch(B + url, json={**b1, "expect_updated_at": OLD})
    check(r.status_code == 409, f"{who} {what}: the version it was opened with is stale after a save -> 409 {r.status_code}")


def run(S, who, holder):
    # trips and travel receipts
    r = S.post(B + O + "/trips", json={"date_from": D, "date_to": D, "dest": f"Versionsstadt {who}", "items": [{"date": D, "category": "taxi", "amount": 12}]})
    check(r.status_code == 201 and r.json().get("updated_at"), f"{who}: a trip with its version {r.status_code} {r.text[:160]}")
    t = r.json()
    three(S, who, "trip", "office_trips", t["id"], f"{O}/trips/{t['id']}", {"dest": f"Ziel A {who}"}, {"note": "B"}, lambda j: j.get("updated_at"))
    iid = t["items"][0]["id"]
    check(bool(t["items"][0].get("updated_at")), f"{who}: a receipt carries its version")
    item = lambda j: next((x for x in j.get("items") or [] if x["id"] == iid), j).get("updated_at")  # the answer is the trip; the 409's row the receipt
    three(S, who, "receipt", "office_trip_items", iid, f"{O}/trips/{t['id']}/items/{iid}", {"text": "Taxi A"}, {"text": "Taxi B"}, item)
    # vehicles and drives
    r = S.post(B + O + "/vehicles", json={"name": f"Wagen {who}", "kind": "company"})
    check(r.status_code == 201 and r.json().get("updated_at"), f"{who}: a vehicle with its version {r.status_code} {r.text[:160]}")
    vid = r.json()["id"]
    three(S, who, "vehicle", "office_vehicles", vid, f"{O}/vehicles/{vid}", {"plate": "XX-A 1"}, {"plate": "XX-B 2"}, lambda j: j.get("updated_at"))
    r = S.post(B + O + "/drives", json={"vehicle_id": vid, "day": D, "dest": "Kunde", "purpose": "Termin", "km": 20, "kind": "business"})
    check(r.status_code == 201, f"{who}: a drive {r.status_code} {r.text[:160]}")
    did = r.json()["id"]
    three(S, who, "drive", "office_drives", did, f"{O}/drives/{did}", {"dest": "Kunde A"}, {"purpose": "Termin B"}, lambda j: j.get("updated_at"))
    # cash book entries (the box's running numbers stay as they are)
    r = S.post(B + O + "/cashbooks", json={"name": f"Kasse {who}", "opening": "100.00", "opening_day": D})
    check(r.status_code == 201, f"{who}: a cash box {r.status_code} {r.text[:160]}")
    bid = r.json()["id"]
    r = S.post(B + f"{O}/cashbooks/{bid}/entries", json={"day": D, "dir": "in", "amount": "5", "text": "Verkauf", "vat_pct": "0"})
    check(r.status_code == 201, f"{who}: a cash entry {r.status_code} {r.text[:160]}")
    eid = r.json()["id"]
    three(S, who, "cash entry", "office_cash_entries", eid, f"{O}/cash-entries/{eid}", {"text": "Verkauf A"}, {"text": "Verkauf B"}, lambda j: j.get("updated_at"))
    check(sql("SELECT no FROM office_cash_entries WHERE id=?", (eid,))[0][0] == 1, f"{who}: the entry keeps its number")
    # credit cards and their positions
    r = S.post(B + O + "/cards", json={"holder_id": holder, "last4": "1357"})
    check(r.status_code == 201 and r.json().get("updated_at"), f"{who}: a card with its version {r.status_code} {r.text[:160]}")
    cid = r.json()["id"]
    three(S, who, "card", "office_cc_cards", cid, f"{O}/cards/{cid}", {"account": "Konto A"}, {"account": "Konto B"}, lambda j: j.get("updated_at"))
    check(S.get(B + O + "/cards").ok, f"{who}: the cards list")
    st = S.post(B + f"{O}/cards/{cid}/statements", files={"file": ("stmt.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")}, data={"month": D[:7]})
    check(st.ok, f"{who}: a statement {st.status_code} {st.text[:160]}")
    sid = st.json()["statement"]["id"]
    r = S.post(B + f"{O}/cards/statements/{sid}/lines", json={"day": D, "merchant": "Versionsladen", "amount": "9.00"})
    check(r.status_code == 201 and r.json()["line"].get("updated_at"), f"{who}: a position with its version {r.status_code} {r.text[:160]}")
    lid = r.json()["line"]["id"]
    line = lambda j: (j.get("line") or j).get("updated_at")
    three(S, who, "card position", "office_cc_lines", lid, f"{O}/cards/lines/{lid}", {"merchant": "Laden A"}, {"merchant": "Laden B"}, line)
    # a position from before the column (NULL): without expect as before
    sql("UPDATE office_cc_lines SET updated_at=NULL WHERE id=?", (lid,))
    r = S.patch(B + f"{O}/cards/lines/{lid}", json={"merchant": "Laden C"})
    check(r.ok and r.json()["line"]["updated_at"], f"{who}: a position without a version saves and gets one {r.status_code} {r.text[:160]}")
    # entertainment receipts
    r = S.post(B + O + "/meals", json={})
    check(r.status_code == 201 and r.json().get("updated_at"), f"{who}: an entertainment receipt {r.status_code} {r.text[:160]}")
    mid = r.json()["id"]
    three(S, who, "entertainment", "office_meals", mid, f"{O}/meals/{mid}", {"occasion": "Besprechung A"}, {"occasion": "Besprechung B"}, lambda j: j.get("updated_at"))


run(Fr, "freelancer", FID)
run(A, "org", AID)

# the dialogs send the version, show the conflict bar and undo only the changed keys (the client side, read from the files)
tj = kt_src("static/js/office_travel.js")
# 2.566.0 (#4704): ofcVerUndo went into core.js undoWrite (only the changed keys, against the save's version)
check("function ofcVerBody" in tj and "function ofcVerConflict" in tj and "async function undoWrite" in kt_src("static/js/core.js"), "UI: the shared helpers are there")
for f, n in (("office_travel.js", 2), ("office_logbook.js", 2), ("office_cashbook.js", 1), ("office_cards.js", 2), ("office_meals.js", 1)):
    js = kt_src("static/js/" + f)
    check(js.count("ofcVerBody(") >= n and js.count("ofcVerConflict(") >= n, f"UI: {f} sends expect_updated_at and shows the conflict bar")
for f in ("office_travel.js", "office_logbook.js", "office_cashbook.js", "office_meals.js"):
    check("undoWrite(" in kt_src("static/js/" + f) and "{now: b" in kt_src("static/js/" + f), f"UI: {f}'s undo writes back only the changed keys")  # 2.566.0 (#4704)
check("api('PATCH', `/api/office/cash-entries/${e.id}`, ofcVerBody(" in kt_src("static/js/office_cashbook.js"), "UI: the cash book still saves through the waiting api()")

sys.exit(done("p2560_d_conflict"))
