#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.483.0 (#2007): agents read invoice series and the subscriptions overview (GET /api/v1/office/series, /office/subs),
and the invoices made by a series carry series_id + series_period in GET /api/v1/office/docs. Invented companies only.
 - the scope office is needed (an agent without it: 403 required_scope office); a person's own token: 403 (agents only)
 - the series of the agent's office area only, never another organisation's (tenant-matrix: office); the newest invoices
   made with their period; never a change (no write route)
 - the person (requested_by) must reach them in the app: series = the office admin (a member's agent 403); subscriptions =
   the area "Subscriptions & tools" (an organisation's agent without an office group has no such area: 403)
 - a person without an organisation (personal office): her agent reads her series, her subscriptions and the series fields
   of her invoices (freelancer-matrix: office)
usage: p2483_a_series_api_test.py <datadir>"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, H, OKS, check, fresh, sess  # noqa: E402,F401

O = "/api/office"
D = O + "/docs"
S = O + "/series"
V = B + "/api/v1/office"
FEAT = "cal,comments,collab,office,clients"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}

fresh(prefix="P2483S")
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})


def office(s):
    s.get(B + O + "/settings")
    assert s.put(B + O + "/settings", json={"lang": "de", "company_fields": COMPANY}).ok


def invoice(s, cl, title="Retainer {month}"):
    r = s.post(B + D, json={"kind": "invoice", "lang": "de", "client_id": cl, "project_title": title,
                            "items": [{"title": "Betreuung", "qty": 1, "rate": 500}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def series(s, tpl, title):
    r = s.post(B + S, json={"template_id": tpl, "every": "monthly", "start": "2027-01-31", "title": title})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = s.post(B + f"{S}/{sid}/run")
    assert r.ok and r.json().get("doc_id"), r.text
    return sid, r.json()["doc_id"]


def sub(s, label):
    r = s.post(B + O + "/fixed-costs", json={"label": label, "amount": 50, "vat_rate": 19, "start": "2026-01-31", "repeat": "monthly",
                                            "category": "Software", "sub": 1})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def hdr(tok):
    return {**H, "Authorization": "Bearer " + tok}


def agent(s, scopes, name, org=None):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": scopes, **({"org_id": org} if org else {})})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    return aid, hdr(r.json()["token"])


def get(h, path, **q):
    return requests.get(V + path, headers=h, params=q)


office(A)
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH"}).json()["id"]
TPL = invoice(A, CL)
S1, D1 = series(A, TPL, "Retainer Kunde Eins")
SUB1 = sub(A, "Design Suite")
office(Ca)
CL2 = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG"}).json()["id"]
SB, DB_ = series(Ca, invoice(Ca, CL2), "Fremde Serie")
sub(Ca, "Fremdes Abo")

A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
AG, AH = agent(A, ["read", "office"], "seriesbot", ORG)
AGN, ANH = agent(A, ["read"], "plainbot", ORG)
BG, BH = agent(Bo, ["read", "office"], "bobbot", ORG)
for x in (AG, AGN, BG):
    check(A.patch(B + f"{O}/agents/{x}", json={"office_drafts": True}).ok, f"setup: the office switch of agent {x}")
check(A.put(B + O + "/settings", json={"agents_read": 1}).ok, "setup: agents may read the office data of Alpha")

# ================================================================ 1. scope and kind of token
r = get(ANH, "/series")
check(r.status_code == 403 and (r.json().get("error") or {}).get("required_scope") == "office", f"without the scope office: 403 ({r.status_code} {r.text[:160]})")
check(get(ANH, "/subs").status_code == 403, "without the scope office: no subscriptions (403)")
# 2.595.0 (#4505): a person's own token cannot get the scope office at all (400); the office routes stay for agents
r = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "office"]})
check(r.status_code == 400, f"a person's own token with the scope office: 400 ({r.status_code} {r.text[:160]})")

# ================================================================ 2. the organisation's agent
r = get(AH, "/series")
check(r.ok and [x["id"] for x in r.json().get("data", [])] == [S1], f"the agent: the series of its office area only ({r.status_code} {r.text[:200]})")
s1 = (r.json().get("data") or [{}])[0] if r.ok else {}
check(s1.get("title") == "Retainer Kunde Eins" and s1.get("every") == "monthly" and (s1.get("template") or {}).get("id") == TPL
      and [m.get("doc_id") for m in s1.get("made") or []] == [D1] and (s1.get("made") or [{}])[0].get("period") == "2027-01-31"
      and s1.get("next_periods") and "deleted_at" not in s1,
      f"the series: template, interval, the invoice made with its period, the next periods ({s1})")
check(SB not in [x["id"] for x in r.json().get("data", [])] if r.ok else False, "never the series of another organisation")
r = get(AH, "/docs", kind="invoice")
docs = {x["id"]: x for x in r.json().get("data", [])} if r.ok else {}
check(docs.get(D1, {}).get("series_id") == S1 and docs.get(D1, {}).get("series_period") == "2027-01-31",
      f"/office/docs: the invoice made carries series_id and series_period ({docs.get(D1)})")
check(TPL in docs and docs[TPL].get("series_id") is None and docs[TPL].get("series_period") is None, f"... the template carries none ({docs.get(TPL)})")
check(DB_ not in docs, "/office/docs: never another organisation's invoice")
r = get(AH, f"/docs/{D1}")
check(r.ok and r.json().get("series_id") == S1 and r.json().get("series_period") == "2027-01-31", "one document: series_id / series_period as before")
r = get(AH, "/subs")
check(r.status_code == 403, f"an organisation's agent without an office group: no area Subscriptions & tools (403) ({r.status_code} {r.text[:160]})")
check(requests.post(V + "/series", headers=AH, json={"template_id": TPL}).status_code in (403, 404, 405), "no write route for series")
check(A.get(B + f"{S}").ok and len(A.get(B + S).json()["items"]) == 1, "the series is unchanged in the app")
r = get(BH, "/series")
check(r.status_code == 403, f"a member's agent (the app's series are for office admins): 403 ({r.status_code} {r.text[:160]})")
check(get(BH, "/docs", kind="invoice").ok, "... while the member's agent reads the documents as before")
# review 2.483 F2: a person ruled by office groups with only "view" in Quotes & invoices sees no series in the app, nor does the agent
check(A.put(B + f"/api/office/rights/people/{BOB}", json={"groups": ["tpl:readonly"]}).ok, "setup: bob in the group Read only")
r = get(BH, "/series")
check(r.status_code == 403, f"a group ruled member with view only: 403 like the app ({r.status_code} {r.text[:160]})")
check(Bo.get(B + S).status_code == 403, "... the app refuses the person too")

# ================================================================ 3. a person without an organisation (personal office)
FID, Fr = freelancer(B, A, "frida", features=FEAT)
Fr.patch(B + "/api/settings", json={"workspace": "private", "features": FEAT})
office(Fr)
FC = Fr.post(B + "/api/clients", json={"name": "Privatkunde"}).json()["id"]
FT = invoice(Fr, FC, "Wartung {month}")
FS, FD = series(Fr, FT, "Wartung Privatkunde")
FSUB = sub(Fr, "Schnittprogramm")
FA, FAH = agent(Fr, ["read", "office"], "fridabot")
check(Fr.patch(B + f"{O}/agents/{FA}", json={"office_drafts": True}).ok and Fr.put(B + O + "/settings", json={"agents_read": 1}).ok,
      "setup: the switches of her personal office")
r = get(FAH, "/series")
check(r.ok and [x["id"] for x in r.json().get("data", [])] == [FS], f"her agent: her series only ({r.status_code} {r.text[:200]})")
r = get(FAH, "/subs")
items = {x["id"]: x for x in r.json().get("items", [])} if r.ok else {}
check(r.ok and list(items) == [FSUB] and items[FSUB].get("label") == "Schnittprogramm" and items[FSUB].get("sub") == 1
      and items[FSUB].get("per_month") and "totals" in r.json() and "candidates" in r.json() and "people" not in r.json(),
      f"her agent: her subscriptions with totals, without the people lists ({r.status_code} {r.text[:240]})")
check(SUB1 not in items, "never another office's subscription")
r = get(FAH, "/docs", kind="invoice")
fd = {x["id"]: x for x in r.json().get("data", [])} if r.ok else {}
check(fd.get(FD, {}).get("series_id") == FS and fd.get(FD, {}).get("series_period") == "2027-01-31", f"her invoice made by the series carries its fields ({fd.get(FD)})")
check(S1 not in [x["id"] for x in get(FAH, "/series").json().get("data", [])], "her agent never sees Alpha's series")

print(f"p2483_a_series_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
