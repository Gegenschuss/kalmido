#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.560.0 C (#4700): the office dialogs that save a whole object check the version (expect_updated_at) instead of overwriting
what another device saved meanwhile. Own container (start.sh through kt.fresh, org encryption on). Invented names only.
freelancer-matrix: office
 - per route: an old expect_updated_at -> 409 with the current state under "row" (nothing written), without expect -> 200 as
   before (old clients, agents), the fresh one -> 200 and the answer brings the new updated_at
 - routes: document templates, generated documents (a draft's autosave: the own next save with the answer's updated_at
   passes, a second tab with the old one gets 409), business contracts, deals, fixed costs / subscriptions, cash flow
   corrections, invoice series, bank rules, letter blocks (office_texts got updated_at, 4700_c)
 - the lists the dialogs open from carry updated_at (else the client could not send it)
 - the same for a person without an organisation in the personal office
usage: p2560_c_conflict_test.py <datadir>"""
import base64
import os
import sys
import time

import kt
from kt import B, check
from freelancer_fixture import freelancer
import testclock

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2560C")

A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,files,docs", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
O = "/api/office"
MONTH = testclock.today().isoformat()[:7]


def ts_of(j):
    return (j.get("rule") or j)["updated_at"]


def row_of(j):
    return j.get("rule") or j


def route(s, who, name, url, first, second, method="PATCH", same=None):
    """A saved object at url (its updated_at at t0): device B saves first (no expect, the old way), device A (opened at t0)
    then saves second: 409; with the fresh version: 200. same(row) -> True when the row holds first's change."""
    p = f"{who} {name}: "
    t0 = START[name]
    # device B saves without expect_updated_at (old client / agent) -- until the second has moved on (whole seconds)
    deadline, j1 = time.monotonic() + 5, None
    while time.monotonic() < deadline:
        r = s.request(method, B + url, json=first)
        check(r.ok, p + f"without expect_updated_at: 200 {r.status_code} {r.text[:200]}")
        if not r.ok:
            return
        j1 = r.json()
        if ts_of(j1) != t0:
            break
    t1 = ts_of(j1)
    check(t1 and t1 != t0, p + f"the answer brings the new updated_at {t0} -> {t1}")
    # device A, opened before: its expect is old -> 409 with the current state, nothing written
    r = s.request(method, B + url, json={**second, "expect_updated_at": t0})
    cur = (r.json().get("current") or r.json().get("row")) if r.status_code == 409 else None  # 2.567.0 (#4711): "current" of the core's write layer, "row" of the older routes
    check(r.status_code == 409 and isinstance(cur, dict) and cur.get("updated_at") == t1,
          p + f"an old expect_updated_at: 409 with the current row {r.status_code} {r.text[:200]}")
    if r.status_code == 409 and same:
        check(same(cur), p + f"the 409 shows device B's change {cur}")
    # after "Reload": the fresh version -> 200, and the next save with the answer's version passes too (the own autosave)
    r = s.request(method, B + url, json={**second, "expect_updated_at": t1})
    check(r.ok, p + f"the fresh expect_updated_at: 200 {r.status_code} {r.text[:200]}")
    if r.ok:
        t2 = ts_of(r.json())
        r = s.request(method, B + url, json={**first, "expect_updated_at": t2})
        check(r.ok, p + f"the next save with the answer's updated_at: 200 {r.status_code} {r.text[:200]}")


START = {}


def made(name, r, key=None):
    assert r.status_code in (200, 201), (name, r.status_code, r.text[:300])
    j = r.json()
    j = j.get(key) if key else j
    START[name] = ts_of(j)
    check(bool(START[name]), f"{name}: a new object carries updated_at {j}")
    return row_of(j)["id"]


def has_ts(who, name, items, oid):
    x = next((i for i in items if i["id"] == oid), None)
    check(x is not None and x.get("updated_at"), f"{who} {name}: the list carries updated_at {x}")


for who, s, cl_org in (("org", A, ORG), ("freelancer", Fr, None)):
    cli = s.post(B + "/api/clients", json={"name": f"Example Client {who}", **({"org_id": cl_org} if cl_org else {})}).json()["id"]

    # ---- document templates
    tid = made("template", s.post(B + O + "/doc-templates", json={"name": "Confirmation", "kind": "other", "body": "Hello {{client.name}}", "sign": 0}))
    route(s, who, "template", f"{O}/doc-templates/{tid}", {"name": "Confirmation B"}, {"body": "Text A"}, same=lambda x: x["name"] == "Confirmation B")
    has_ts(who, "template", s.get(B + O + "/doc-templates").json().get("templates", []), tid)

    # ---- generated documents: a draft's autosave from two tabs
    gid = made("gendoc", s.post(B + O + "/gen-docs", json={"title": "Note", "body": "First text", "client_id": cli}))
    route(s, who, "gendoc", f"{O}/gen-docs/{gid}", {"body": "Tab B text"}, {"body": "Tab A text"}, same=lambda x: x["body"] == "Tab B text")
    d = s.get(B + O + "/gen-docs").json()
    has_ts(who, "gendoc", d.get("docs", []), gid)

    # ---- business contracts
    aid = made("contract", s.post(B + O + "/agreements", json={"kind": "rent", "name": "Studio rent", "provider": "Example Landlord", "cost": "900",
                                                              "per": "month", "task": 0}))
    route(s, who, "contract", f"{O}/agreements/{aid}", {"provider": "Other Landlord"}, {"cost": "950"}, same=lambda x: x["provider"] == "Other Landlord")

    # ---- deals
    did = made("deal", s.post(B + O + "/deals", json={"title": "Image film"}))
    route(s, who, "deal", f"{O}/deals/{did}", {"value": "5000"}, {"note": "call back"}, same=lambda x: float(x["value"]) == 5000)

    # ---- fixed costs / subscriptions (the same route)
    fid = made("fixed", s.post(B + O + "/fixed-costs", json={"label": "Rent", "amount": "500", "start": f"{MONTH}-01", "repeat": "monthly"}))
    route(s, who, "fixed", f"{O}/fixed-costs/{fid}", {"amount": "550"}, {"label": "Rent office"}, same=lambda x: float(x["amount"]) == 550)
    has_ts(who, "fixed", s.get(B + O + "/fixed-costs").json()["items"], fid)

    # ---- cash flow corrections
    cid = made("adjust", s.post(B + O + "/cashflow/adjust", json={"month": MONTH, "dir": "in", "amount": "100", "note": "expected"}))
    route(s, who, "adjust", f"{O}/cashflow/adjust/{cid}", {"amount": "120"}, {"note": "other"}, same=lambda x: float(x["amount"]) == 120)
    has_ts(who, "adjust", s.get(B + O + f"/cashflow?from={MONTH}&months=1").json().get("adjust", []), cid)

    # ---- invoice series
    r = s.post(B + O + "/docs", json={"kind": "invoice", "client_id": cli})
    assert r.status_code in (200, 201), r.text
    sid = made("series", s.post(B + O + "/series", json={"template_id": r.json()["id"], "every": "monthly", "start": "2030-03-01"}))
    route(s, who, "series", f"{O}/series/{sid}", {"title": "Retainer B"}, {"auto_send": 1}, same=lambda x: x["title"] == "Retainer B")

    # ---- bank rules (PUT, the answer {rule})
    rid = made("rule", s.post(B + O + "/bank/rules", json={"name": "Fees", "counterpart": "bank example", "action": "private"}), key="rule")
    route(s, who, "rule", f"{O}/bank/rules/{rid}", {"name": "Fees B"}, {"purpose": "fee"}, method="PUT", same=lambda x: x["name"] == "Fees B")
    has_ts(who, "rule", s.get(B + O + "/bank/rules").json()["items"], rid)

    # ---- letter blocks (office_texts.updated_at, 4700_c)
    bid = made("block", s.post(B + O + "/letter-blocks", json={"name": "Objection", "body": "I object."}))
    route(s, who, "block", f"{O}/letter-blocks/{bid}", {"body": "I object hereby."}, {"name": "Objection 2"}, same=lambda x: x["body"] == "I object hereby.")
    has_ts(who, "block", s.get(B + O + "/letter-blocks").json()["blocks"], bid)

sys.exit(kt.done("p2560_c_conflict"))
