#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.564.0 B (#4702, audit #2822 B-F2): an agent account must say which version it read when it changes an event, a contact,
its quotation draft, its letter draft or a lead over /api/v1 (and MCP). Own container (kt.fresh). Invented names only.
Per area, two clients: the agent reads, a person changes, the agent writes with the old version:
 - agent without a version: 400 version_required, nothing changes
 - agent with the old version: 409 conflict with error.current (the object now), the person's change stays
 - agent with the version as read now: 200
 - a person's own token without a version: as before (200, last write wins; old clients)
 - events also with ?occurrence= and with the header If-Match; contacts with expect_updated_at as the name of expect
 - all of it also as a person without an organisation (freelancer-matrix: pim, office); the office areas are hers (personal office)
usage: p2564_b_agent_version_test.py <datadir>   (P2564B_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}


def hd(token):
    return {**H, "Authorization": "Bearer " + token}


def bad_version(r):
    j = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
    return r.status_code == 400 and (j.get("error") or {}).get("code") == "version_required"


def stale(r, oid):
    j = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
    cur = (j.get("error") or {}).get("current") or j.get("current") or {}  # the quotation draft keeps its older answer (current next to error)
    return r.status_code == 409 and cur.get("id") == oid


def person_changes(save, read, old):
    """The person saves until the object's updated_at moved past old (seconds resolution in some areas) -> the new one."""
    return kt.until(lambda: save() and read() != old and read())


# ---------------------------------------------------------------- events + contacts (pim)
def pim(who, s, ag_tok, own_tok):
    AH, PH = hd(ag_tok), hd(own_tok)
    agid = requests.get(V + "/me", headers=AH).json().get("id")
    cal = s.post(B + "/api/evcals", json={"name": f"Team {who}"}).json()["id"]
    check(s.put(B + f"/api/evcals/{cal}/members", json={"user_id": agid, "role": "edit"}).ok, f"{who}: setup: the calendar shared with the agent")
    r = s.post(B + "/api/events", json={"title": "Planung", "start": "2026-12-03T09:00", "end": "2026-12-03T10:00", "cal_id": cal})
    check(r.ok, f"{who}: setup: an event {r.text[:160]}")
    eid = r.json()["id"]
    seen = requests.get(V + f"/events/{eid}", headers=AH).json()
    check(bool(seen.get("updated_at")), f"{who}: the agent's read carries updated_at")
    rd = lambda: s.get(B + f"/api/events/{eid}").json().get("updated_at")  # noqa: E731
    person_changes(lambda: s.patch(B + f"/api/events/{eid}", json={"location": "Raum 2"}).ok, rd, seen["updated_at"])
    r = requests.patch(V + f"/events/{eid}", headers=AH, json={"location": "Agent"})
    check(bad_version(r), f"{who}: event: agent without a version 400 version_required {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/events/{eid}", headers=AH, json={"location": "Agent", "expect_updated_at": seen["updated_at"]})
    check(stale(r, eid) and r.json()["error"]["current"]["location"] == "Raum 2", f"{who}: event: an old version 409 with the event now {r.status_code} {r.text[:200]}")
    check(s.get(B + f"/api/events/{eid}").json()["location"] == "Raum 2", f"{who}: event: the person's change stays")
    r = requests.patch(V + f"/events/{eid}", headers={**AH, "If-Match": '"' + seen["updated_at"] + '"'}, json={"location": "Agent"})
    check(r.status_code == 409, f"{who}: event: an old If-Match 409 {r.status_code}")
    r = requests.patch(V + f"/events/{eid}", headers=AH, json={"location": "Agent", "expect_updated_at": rd()})
    check(r.ok and r.json()["location"] == "Agent", f"{who}: event: the version as read 200 {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/events/{eid}", headers={**AH, "If-Match": rd()}, json={"location": "Agent 2"})
    check(r.ok and r.json()["location"] == "Agent 2", f"{who}: event: If-Match as read 200 {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/events/{eid}", headers=PH, json={"location": "Person token"})
    check(r.ok and r.json()["location"] == "Person token", f"{who}: event: a person's token without a version as before {r.status_code} {r.text[:200]}")
    r = requests.patch(V + "/events/99999999", headers=AH, json={"location": "x"})
    check(r.status_code == 404, f"{who}: event: an unknown id stays 404 before the version rule {r.status_code}")

    # one occurrence of a series
    r = s.post(B + "/api/events", json={"title": "Daily", "start": "2026-12-07T08:00", "end": "2026-12-07T08:15", "cal_id": cal, "rrule": "FREQ=DAILY;COUNT=3"})
    sid = r.json()["id"]
    sseen = requests.get(V + f"/events/{sid}", headers=AH).json()["updated_at"]
    rs = lambda: s.get(B + f"/api/events/{sid}").json().get("updated_at")  # noqa: E731
    person_changes(lambda: s.patch(B + f"/api/events/{sid}", json={"description": "Bitte pünktlich"}).ok, rs, sseen)
    occ = {"occurrence": "2026-12-08T08:00"}
    r = requests.patch(V + f"/events/{sid}", headers=AH, params=occ, json={"title": "Daily (später)"})
    check(bad_version(r), f"{who}: occurrence: agent without a version 400 {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/events/{sid}", headers=AH, params=occ, json={"title": "Daily (später)", "expect_updated_at": sseen})
    check(stale(r, sid), f"{who}: occurrence: an old version 409 with the series {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/events/{sid}", headers=AH, params=occ, json={"title": "Daily (später)", "expect_updated_at": rs()})
    ov = [o for o in (r.json().get("overrides") or []) if o.get("title") == "Daily (später)"] if r.ok else []
    check(r.ok and ov, f"{who}: occurrence: the version as read 200 {r.status_code} {r.text[:200]}")

    # contacts
    bid = s.post(B + "/api/books", json={"name": f"Kunden {who}"}).json()["id"]
    check(s.put(B + f"/api/books/{bid}/members", json={"user_id": agid, "role": "edit"}).ok, f"{who}: setup: the address book shared with the agent")
    r = s.post(B + "/api/contacts", json={"fn": "Erika Beispiel", "book_id": bid})
    check(r.ok, f"{who}: setup: a contact {r.text[:160]}")
    cid = r.json()["id"]
    cseen = requests.get(V + f"/contacts/{cid}", headers=AH).json()
    check(bool(cseen.get("updated_at")), f"{who}: contact: the agent's read carries updated_at")
    rc = lambda: s.get(B + f"/api/contacts/{cid}").json().get("updated_at")  # noqa: E731
    person_changes(lambda: s.patch(B + f"/api/contacts/{cid}", json={"note": "Ruft Montag zurück"}).ok, rc, cseen["updated_at"])
    r = requests.patch(V + f"/contacts/{cid}", headers=AH, json={"note": "Agent"})
    check(bad_version(r), f"{who}: contact: agent without a version 400 version_required {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/contacts/{cid}", headers=AH, json={"note": "Agent", "expect_updated_at": cseen["updated_at"]})
    check(stale(r, cid) and r.json()["error"]["current"]["note"] == "Ruft Montag zurück", f"{who}: contact: an old version 409 with the contact now {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/contacts/{cid}", headers=AH, json={"note": "Agent", "expect": cseen["updated_at"]})
    check(r.status_code == 409, f"{who}: contact: the old name expect checks too {r.status_code}")
    check(s.get(B + f"/api/contacts/{cid}").json()["note"] == "Ruft Montag zurück", f"{who}: contact: the person's change stays")
    r = requests.patch(V + f"/contacts/{cid}", headers=AH, json={"note": "Agent", "expect_updated_at": rc()})
    check(r.ok and r.json()["note"] == "Agent", f"{who}: contact: the version as read 200 {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/contacts/{cid}", headers=PH, json={"note": "Person token"})
    check(r.ok and r.json()["note"] == "Person token", f"{who}: contact: a person's token without a version as before {r.status_code} {r.text[:200]}")


# ---------------------------------------------------------------- office: quotation draft, letter draft, lead
def office(who, s, ag_tok):
    AH = hd(ag_tok)
    O = "/api/office"
    cl = s.post(B + "/api/clients", json={"name": f"Beispiel GmbH {who}"}).json()["id"]
    r = requests.post(V + "/office/offers", headers=AH, json={"client_id": cl, "title": "Portrait", "items": [{"text": "Kamera", "qty": 1, "unit": "day", "price": 500}]})
    check(r.status_code == 201, f"{who}: setup: the agent's quotation draft {r.text[:200]}")
    did = r.json()["doc"]["id"]
    seen = requests.get(V + f"/office/docs/{did}", headers=AH).json()["updated_at"]
    rd = lambda: requests.get(V + f"/office/docs/{did}", headers=AH).json().get("updated_at")  # noqa: E731

    def psave():
        d = s.get(B + f"{O}/docs/{did}").json()
        its = d.get("doc", d)["items"]
        its[0]["qty"] = float(its[0]["qty"]) + 1
        return s.put(B + f"{O}/docs/{did}/items", json={"items": its}).ok
    person_changes(psave, rd, seen)
    r = requests.patch(V + f"/office/offers/{did}", headers=AH, json={"title": "Portrait lang"})
    check(bad_version(r), f"{who}: offer: agent without a version 400 {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/office/offers/{did}", headers=AH, json={"title": "Portrait lang", "expect_updated_at": seen})
    check(stale(r, did), f"{who}: offer: an old version 409 with the draft {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/office/offers/{did}", headers=AH, json={"title": "Portrait lang", "expect_updated_at": rd()})
    check(r.ok and r.json()["doc"]["project_title"] == "Portrait lang", f"{who}: offer: the version as read 200 {r.status_code} {r.text[:200]}")

    r = requests.post(V + "/office/letters", headers=AH, json={"subject": "Termin", "body": "Guten Tag"})
    check(r.status_code == 201, f"{who}: setup: the agent's letter draft {r.text[:200]}")
    lid = r.json()["id"]
    lseen = r.json()["updated_at"]
    rl = lambda: s.get(B + f"{O}/letters/{lid}").json().get("updated_at")  # noqa: E731
    person_changes(lambda: s.patch(B + f"{O}/letters/{lid}", json={"body": "Guten Tag, von Hand ergänzt"}).ok, rl, lseen)
    r = requests.patch(V + f"/office/letters/{lid}", headers=AH, json={"subject": "Termin neu"})
    check(bad_version(r), f"{who}: letter: agent without a version 400 {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/office/letters/{lid}", headers=AH, json={"body": "Agent", "expect_updated_at": lseen})
    check(stale(r, lid) and r.json()["error"]["current"]["body"] == "Guten Tag, von Hand ergänzt", f"{who}: letter: an old version 409 with the letter now {r.status_code} {r.text[:200]}")
    check(s.get(B + f"{O}/letters/{lid}").json()["body"] == "Guten Tag, von Hand ergänzt", f"{who}: letter: the person's text stays")
    r = requests.patch(V + f"/office/letters/{lid}", headers=AH, json={"subject": "Termin neu", "expect_updated_at": rl()})
    check(r.ok and r.json()["subject"] == "Termin neu", f"{who}: letter: the version as read 200 {r.status_code} {r.text[:200]}")

    r = requests.post(V + "/office/leads", headers=AH, json={"contact": "Hanna Hinweis", "company": f"Hinweis GmbH {who}", "next_step": "Anrufen"})
    check(r.status_code == 201, f"{who}: setup: the agent's lead {r.text[:200]}")
    dl = r.json()["id"]
    dseen = r.json()["updated_at"]
    rdl = lambda: next((x["updated_at"] for x in requests.get(V + "/office/leads", headers=AH).json().get("data", []) if x["id"] == dl), None)  # noqa: E731
    person_changes(lambda: s.patch(B + f"{O}/deals/{dl}", json={"note": "Will erst im Januar"}).ok, rdl, dseen)
    r = requests.patch(V + f"/office/leads/{dl}", headers=AH, json={"note": "Agent"})
    check(bad_version(r), f"{who}: lead: agent without a version 400 {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/office/leads/{dl}", headers=AH, json={"note": "Agent", "expect_updated_at": dseen})
    check(stale(r, dl) and r.json()["error"]["current"]["note"] == "Will erst im Januar", f"{who}: lead: an old version 409 with the lead now {r.status_code} {r.text[:200]}")
    r = requests.patch(V + f"/office/leads/{dl}", headers=AH, json={"note": "Agent", "expect_updated_at": rdl()})
    check(r.ok and r.json()["note"] == "Agent", f"{who}: lead: the version as read 200 {r.status_code} {r.text[:200]}")


kt.fresh(prefix="P2564B")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,events,contacts,collab,comments", "tour": "done", "workspace": f"org:{ORG}"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/admin/agents", json={"username": "claude", "display_name": "Claude", "scopes": ["read", "calendar", "contacts"], "org_id": ORG})
check(r.ok, "setup: alice's agent " + r.text[:200])
ATK = r.json()["token"]
APT = A.post(B + "/api/me/tokens", json={"name": "Own", "scopes": ["read", "write", "calendar", "contacts"]}).json()["token"]
pim("alice", A, ATK, APT)

# freelancer-matrix: pim, office
FID, Fr = freelancer(B, A)
O = "/api/office"
Fr.get(B + O + "/settings")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "calendar", "contacts", "office"]})
check(r.status_code == 201, "setup: the freelancer's own agent " + r.text[:200])
FAG, FTK = r.json()["id"], r.json()["token"]
FPT = Fr.post(B + "/api/me/tokens", json={"name": "Own", "scopes": ["read", "write", "calendar", "contacts"]}).json()["token"]
pim("frida", Fr, FTK, FPT)
check(Fr.patch(B + f"{O}/agents/{FAG}", json={"office_drafts": True}).ok and Fr.put(B + O + "/settings", json={"agents_read": 1}).ok,
      "setup: both office switches of the personal office")
office("frida", Fr, FTK)
sys.exit(kt.done("p2564_b_agent_version"))
