#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.567.0 D (#4711, the shared core stage 2, group 2): the saves of travel (trip, receipt, purpose), cash flow (fixed costs
with their subscription fields, corrections), credit cards (card, position), bank rules, invoice series and entertainment
(receipt, place / person choice) go through office/owrite.py ow_write. Per object, two writers who opened the same version:
 - the first saves with it -> 200, only the column sent changes in the row (the other columns, also the encrypted ones, stay
   byte for byte), a new updated_at in the answer, updated_by = the person
 - the second with the old version -> 409 with the current state under "current" (the first one's change), nothing written
 - without expect_updated_at -> 200 as before (old clients)
 - obj_history holds the change (kind, the fields of both saves, not an agent)
The person without an organisation (tests/freelancer_fixture.py) and an organisation admin do every step. Own container
(kt.fresh, mode workspaces, org encryption on). Invented names only (example.com).
freelancer-matrix: office
usage: p2567_d_office_core_test.py <datadir>      (KMT_NOSTART=1: a running server)"""
import base64
import json
import os
import sys
from datetime import date

import requests

import dbx as dbxm
import kt
from kt import B, DATA, check, done
from freelancer_fixture import FEATURES, freelancer

O = "/api/office"
D = date.today().isoformat()
MONTH = D[:7]
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
STAMP = ("updated_at", "updated_by")


def kt_src(rel):
    with open(os.path.join(SRC, rel), encoding="utf-8") as f:
        return f.read()


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        try:
            return [dict(x) for x in r.fetchall()]
        except Exception:  # noqa: BLE001 - an UPDATE without rows to read
            return []
    finally:
        c.close()


def row(table, rid):
    return sql(f"SELECT * FROM {table} WHERE id=?", (rid,))[0]


KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2567D")
s0 = requests.Session()
s0.headers.update(kt.H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": kt.PASSWORD}).ok
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})  # Alice admins the organisation Alpha
A = kt.sess("alice")
check(A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok, "setup: Alice's features")
AID = A.get(B + "/api/state").json()["me"]["id"]
FID, Fr = freelancer(B, A)


def two(S, who, uid, what, kind, table, rid, url, first, second, ver, method="PATCH", same=None):
    """Writer 1 and writer 2 opened the object at its stored version v0 (module docstring)."""
    p = f"{who} {what}: "
    v0 = row(table, rid)["updated_at"]
    check(bool(v0), p + "the object has a version")
    before = row(table, rid)
    r = S.request(method, B + url, json={**first, "expect_updated_at": v0})
    check(r.ok, p + f"writer 1 with the version it opened: 200 {r.status_code} {r.text[:200]}")
    if not r.ok:
        return
    after = row(table, rid)
    moved = {k for k in after if after[k] != before.get(k) and k not in STAMP}
    check(moved and moved <= set(first), p + f"only the field sent changes in the row: {sorted(moved)} (sent {sorted(first)})")
    v1 = after["updated_at"]
    check(v1 and v1 != v0, p + f"a new updated_at {v0} -> {v1}")
    check(ver(r.json()) == v1, p + f"the answer carries the new updated_at {ver(r.json())!r} == {v1!r}")
    if "updated_by" in after:
        check(after["updated_by"] == uid, p + f"updated_by = the person {after['updated_by']} == {uid}")
    # writer 2, opened at v0: 409 with the current state under "current" (writer 1's change), nothing written
    r = S.request(method, B + url, json={**second, "expect_updated_at": v0})
    cur = r.json().get("current") if r.status_code == 409 else None
    check(r.status_code == 409 and isinstance(cur, dict), p + f"writer 2 with the old version: 409 with 'current' {r.status_code} {r.text[:200]}")
    if isinstance(cur, dict):
        check(ver(cur) == v1, p + f"'current' is the stored version {ver(cur)!r} == {v1!r}")
        if same:
            check(same(cur), p + f"'current' shows writer 1's change {cur}")
    check(row(table, rid) == after, p + "the 409 wrote nothing")
    # without expect_updated_at: as before
    r = S.request(method, B + url, json=second)
    check(r.ok, p + f"without expect_updated_at as before {r.status_code} {r.text[:200]}")
    check(row(table, rid)["updated_at"] != v1, p + "that save got a new version too")
    # the history: one entry (the same person merges) with both fields, not an agent
    h = sql("SELECT * FROM obj_history WHERE kind=? AND ref_id=? ORDER BY id", (kind, rid))
    fields = set()
    for x in h:
        fields |= set(json.loads(x["vals_after"] or "{}"))
    check(bool(h) and set(first) | set(second) <= fields, p + f"obj_history has the change ({kind}): {sorted(fields)}")
    check(all(not x["agent"] and x["user_id"] == uid for x in h), p + "the history names the person, no agent")


def made(r, p, key=None):
    check(r.status_code in (200, 201), p + f" created {r.status_code} {r.text[:200]}")
    j = r.json()
    return (j.get(key) if key else j)["id"]


def run(S, who, uid):
    # ---- travel: a trip, its receipt, an own purpose
    r = S.post(B + O + "/trips", json={"date_from": D, "date_to": D, "dest": f"Kernstadt {who}", "note": "first", "items": [{"date": D, "category": "taxi", "amount": 12, "text": "Taxi"}]})
    tid = made(r, f"{who} trip")
    two(S, who, uid, "trip", "office_trip", "office_trips", tid, f"{O}/trips/{tid}", {"dest": f"Ziel A {who}"}, {"note": "B"},
        lambda j: j.get("updated_at"), same=lambda x: x.get("dest") == f"Ziel A {who}")
    iid = r.json()["items"][0]["id"]
    item = lambda j: next((x for x in j.get("items") or [] if x["id"] == iid), j).get("updated_at")  # noqa: E731 -- the answer is the trip; "current" the receipt
    two(S, who, uid, "receipt", "office_trip_item", "office_trip_items", iid, f"{O}/trips/{tid}/items/{iid}", {"text": "Taxi A"}, {"datev_no": "77"}, item,
        same=lambda x: x.get("text") == "Taxi A")
    pid = made(S.post(B + O + "/trips/purposes", json={"name": f"Messe {who}"}), f"{who} purpose")
    two(S, who, uid, "purpose", "office_trip_purpose", "office_trip_purposes", pid, f"{O}/trips/purposes/{pid}", {"name": f"Messe A {who}"},
        {"name": f"Messe B {who}"}, lambda j: j.get("updated_at"))
    # ---- cash flow: a fixed cost (subscription fields through the same route), a correction by hand
    fid = made(S.post(B + O + "/fixed-costs", json={"label": "Rent", "amount": "500", "start": f"{MONTH}-01", "repeat": "monthly"}), f"{who} fixed cost")
    two(S, who, uid, "fixed cost", "office_fixed_cost", "office_fixed_costs", fid, f"{O}/fixed-costs/{fid}", {"amount": "550.00"}, {"notice_days": 30},
        lambda j: j.get("updated_at"), same=lambda x: float(x["amount"]) == 550)
    aid = made(S.post(B + O + "/cashflow/adjust", json={"month": MONTH, "dir": "in", "amount": "100", "note": "expected"}), f"{who} correction")
    two(S, who, uid, "correction", "office_cf_adjust", "office_cf_adjust", aid, f"{O}/cashflow/adjust/{aid}", {"amount": "120.00"}, {"note": "other"},
        lambda j: j.get("updated_at"), same=lambda x: float(x["amount"]) == 120)
    # ---- credit cards: the card, a position of a draft statement
    cid = made(S.post(B + O + "/cards", json={"holder_id": uid, "last4": "2468", "account": "Konto"}), f"{who} card")
    two(S, who, uid, "card", "office_cc_card", "office_cc_cards", cid, f"{O}/cards/{cid}", {"account": "Konto A"}, {"last4": "1357"},
        lambda j: j.get("updated_at"), same=lambda x: x.get("account") == "Konto A")
    st = S.post(B + f"{O}/cards/{cid}/statements", files={"file": ("stmt.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")}, data={"month": MONTH})
    check(st.ok, f"{who}: a statement {st.status_code} {st.text[:160]}")
    sid = st.json()["statement"]["id"]
    lid = made(S.post(B + f"{O}/cards/statements/{sid}/lines", json={"day": D, "merchant": "Kernladen", "amount": "9.00"}), f"{who} position", key="line")
    two(S, who, uid, "card position", "office_cc_line", "office_cc_lines", lid, f"{O}/cards/lines/{lid}", {"merchant": "Laden A"}, {"amount": "8.00"},
        lambda j: (j.get("line") or j).get("updated_at"), same=lambda x: x.get("merchant") == "Laden A")
    # ---- bank rules (PUT, the answer {rule})
    rid = made(S.post(B + O + "/bank/rules", json={"name": "Fees", "counterpart": "bank example", "action": "private"}), f"{who} rule", key="rule")
    two(S, who, uid, "bank rule", "office_bank_rule", "office_bank_rules", rid, f"{O}/bank/rules/{rid}", {"name": "Fees A"}, {"purpose": "fee"},
        lambda j: (j.get("rule") or j).get("updated_at"), method="PUT", same=lambda x: x.get("name") == "Fees A")
    # ---- invoice series
    cli = S.post(B + "/api/clients", json={"name": f"Example Client {who}"}).json()["id"]
    r = S.post(B + O + "/docs", json={"kind": "invoice", "client_id": cli})
    check(r.status_code in (200, 201), f"{who}: an invoice {r.status_code} {r.text[:160]}")
    srid = made(S.post(B + O + "/series", json={"template_id": r.json()["id"], "every": "monthly", "start": "2030-03-01"}), f"{who} series")
    two(S, who, uid, "series", "office_inv_series", "office_inv_series", srid, f"{O}/series/{srid}", {"title": "Retainer A"}, {"auto_send": 1},
        lambda j: j.get("updated_at"), same=lambda x: x.get("title") == "Retainer A")
    # ---- entertainment: the receipt, a place choice
    mid = made(S.post(B + O + "/meals", json={"occasion": "first", "note": "n"}), f"{who} entertainment")
    two(S, who, uid, "entertainment", "office_meal", "office_meals", mid, f"{O}/meals/{mid}", {"occasion": "Besprechung A"}, {"note": "B"},
        lambda j: j.get("updated_at"), same=lambda x: x.get("occasion") == "Besprechung A")
    chid = made(S.post(B + O + "/meals/choices", json={"kind": "place", "name": f"Kernlokal {who}", "extra": "Weg 1"}), f"{who} place")
    two(S, who, uid, "place", "office_meal_choice", "office_meal_choices", chid, f"{O}/meals/choices/{chid}", {"extra": "Weg 2"}, {"name": f"Kernlokal B {who}"},
        lambda j: j.get("updated_at"), same=lambda x: x.get("extra") == "Weg 2")


run(Fr, "freelancer", FID)
run(A, "org", AID)

# the dialogs read the 409's state under "current" (the older routes' "row" still works)
tj = kt_src("static/js/office_travel.js")
check("x?.data?.current || x?.data?.row" in tj and "(x.data?.current || x.data?.row)" in tj, "UI: ofcVerConflict / ofcVerLate take 'current'")
for f in ("office_cashflow.js", "office_subs.js", "office_bankrules.js", "office_recurring.js"):
    check("x.data?.current || x.data?.row" in kt_src("static/js/" + f), f"UI: {f} takes 'current'")

sys.exit(done("p2567_d_office_core"))
