#!/usr/bin/env python3
"""2.269.0 C (#3017): a dialog that saves a whole object no longer overwrites a change of another tab / device.
freelancer-matrix: clients
 - client: PATCH with expect_updated_at of an older state -> 409 with the current client (two tabs, the audit's replay);
   without expect_updated_at as before (200), and a contact person missing in the list stays (only contacts_removed
   deletes); two parallel saves with the same base -> exactly one 200 and one 409 (the row lock)
 - the same check for the office master data (a service), a letter draft, a budget entry and a recurring entry, the journal
   ("" = no entry seen)
 - a person without an organisation (private office): client, service, letter, budget, journal the same way
usage: p2269_c_clients_test.py <datadir>"""
import os
import sys
import threading
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check  # noqa: E402

FEAT = "collab,comments,office,clients,time,review,budget"
kt.fresh(prefix="P2269C")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})


def names(j):
    return [k["name"] for k in j.get("contacts") or []]


def clients(s, who):
    # ---- the audit's replay: tab A and tab B both opened the client with contact person "Alt"
    r = s.post(B + "/api/clients", json={"name": f"Example Studio {who}", "contacts": [{"name": "Alt", "email": "alt@example.com"}]})
    check(r.status_code == 201, f"{who}: a client ({r.status_code} {r.text[:200]})")
    c0 = r.json()
    CL, K_ALT, base = c0["id"], c0["contacts"][0]["id"], c0["updated_at"]
    check(bool(base) and "." in base, f"{who}: updated_at with milliseconds ({base})")
    r = s.patch(B + f"/api/clients/{CL}", json={"note": "tab A", "expect_updated_at": base,
                                                "contacts": [{"id": K_ALT, "name": "Alt"}, {"name": "Neu", "email": "neu@example.com"}]})
    check(r.ok and names(r.json()) == ["Alt", "Neu"] and r.json()["updated_at"] != base, f"{who}: tab A adds Neu ({r.status_code} {r.text[:200]})")
    a = r.json()
    r = s.patch(B + f"/api/clients/{CL}", json={"note": "tab B", "expect_updated_at": base, "contacts": [{"id": K_ALT, "name": "Alt"}]})
    j = r.json()
    check(r.status_code == 409 and j.get("client", {}).get("note") == "tab A" and names(j["client"]) == ["Alt", "Neu"] and j.get("error"),
          f"{who}: tab B with the old base -> 409 with the current client ({r.status_code} {r.text[:300]})")
    cur = s.get(B + f"/api/clients/{CL}").json()
    check(cur["note"] == "tab A" and names(cur) == ["Alt", "Neu"], f"{who}: nothing of tab B was written {cur.get('note')} {names(cur)}")
    # ---- without a version (agents, the API, old clients): as before, but a missing contact person stays
    r = s.patch(B + f"/api/clients/{CL}", json={"note": "no version", "contacts": [{"id": K_ALT, "name": "Alt"}]})
    check(r.ok and r.json()["note"] == "no version" and names(r.json()) == ["Alt", "Neu"], f"{who}: without expect 200, Neu stays {names(r.json())}")
    k_neu = [k["id"] for k in r.json()["contacts"] if k["name"] == "Neu"][0]
    # ---- removed on purpose: deleted
    r = s.patch(B + f"/api/clients/{CL}", json={"contacts": [{"id": K_ALT, "name": "Alt"}], "contacts_removed": [k_neu],
                                                "expect_updated_at": r.json()["updated_at"]})
    check(r.ok and names(r.json()) == ["Alt"], f"{who}: contacts_removed deletes Neu ({r.status_code} {r.text[:200]})")
    check(s.patch(B + f"/api/clients/{CL}", json={"contacts_removed": ["x"]}).status_code == 400, f"{who}: contacts_removed must be ids (400)")
    r = s.patch(B + f"/api/clients/{CL}", json={"contacts_removed": [K_ALT]})
    check(r.ok and names(r.json()) == [] and r.json()["contact"] == "", f"{who}: the last one removed without a list, contact empty {r.text[:200]}")
    check(a["id"] == CL, f"{who}: the answer is the client")
    return CL


def parallel(s, url, mk, n=6):
    """n pairs of two saves with the same base at the same time -> per pair exactly one 200 and one 409."""
    good = 0
    for i in range(n):
        base = s.get(B + url).json()["updated_at"]
        out = []
        go = threading.Barrier(2)

        def one(k):
            go.wait()
            out.append(s.patch(B + url, json={**mk(i, k), "expect_updated_at": base}).status_code)
        ts = [threading.Thread(target=one, args=(k,)) for k in (0, 1)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        good += sorted(out) == [200, 409]
    return good


def master(s, who):
    r = s.post(B + "/api/office/services", json={"name_de": f"Beratung {who}", "daily_rate": 800})
    check(r.status_code in (200, 201), f"{who}: a service ({r.status_code} {r.text[:200]})")
    sv = r.json()
    r = s.patch(B + f"/api/office/services/{sv['id']}", json={"daily_rate": 900, "expect_updated_at": sv["updated_at"]})
    check(r.ok and r.json()["daily_rate"] == 900, f"{who}: master data saved with its base ({r.status_code} {r.text[:200]})")
    r = s.patch(B + f"/api/office/services/{sv['id']}", json={"daily_rate": 700, "expect_updated_at": sv["updated_at"]})
    check(r.status_code == 409 and r.json().get("row", {}).get("daily_rate") == 900, f"{who}: master data, old base -> 409 with the row ({r.status_code} {r.text[:200]})")
    check(s.patch(B + f"/api/office/services/{sv['id']}", json={"daily_rate": 650}).ok, f"{who}: master data without expect as before")


def letter(s, who):
    r = s.post(B + "/api/office/letters", json={})
    check(r.status_code == 201, f"{who}: a letter draft ({r.status_code} {r.text[:200]})")
    d = r.json()
    r = s.patch(B + f"/api/office/letters/{d['id']}", json={"subject": "Tab A", "expect_updated_at": d["updated_at"]})
    check(r.ok and r.json()["subject"] == "Tab A", f"{who}: the letter saved with its base ({r.status_code} {r.text[:200]})")
    r = s.patch(B + f"/api/office/letters/{d['id']}", json={"subject": "Tab B", "expect_updated_at": d["updated_at"]})
    check(r.status_code == 409 and r.json().get("letter", {}).get("subject") == "Tab A", f"{who}: letter, old base -> 409 ({r.status_code} {r.text[:200]})")
    check(s.get(B + f"/api/office/letters/{d['id']}").json()["subject"] == "Tab A", f"{who}: the letter kept tab A")
    check(s.patch(B + f"/api/office/letters/{d['id']}", json={"subject": "API"}).ok, f"{who}: letter without expect as before")


def budget(s, who):
    lid = s.post(B + "/api/budget/lists", json={}).json().get("list_id")
    check(bool(lid), f"{who}: a budget list")
    e = s.post(B + f"/api/budget/{lid}/entries", json={"day": "2026-09-03", "amount": 10, "kind": "out", "title": "Paint"}).json()
    r = s.patch(B + f"/api/budget/entries/{e['id']}", json={"day": "2026-09-03", "amount": 12, "kind": "out", "title": "Paint A", "expect_updated_at": e["updated_at"]})
    check(r.ok and r.json()["title"] == "Paint A", f"{who}: budget entry saved with its base ({r.status_code} {r.text[:200]})")
    r = s.patch(B + f"/api/budget/entries/{e['id']}", json={"day": "2026-09-03", "amount": 14, "kind": "out", "title": "Paint B", "expect_updated_at": e["updated_at"]})
    check(r.status_code == 409 and r.json().get("entry", {}).get("title") == "Paint A", f"{who}: budget entry, old base -> 409 ({r.status_code} {r.text[:200]})")
    check(s.patch(B + f"/api/budget/entries/{e['id']}", json={"day": "2026-09-03", "amount": 15, "kind": "out", "title": "Paint C"}).ok, f"{who}: entry without expect")
    rc = s.post(B + f"/api/budget/{lid}/recurring", json={"title": "Rent", "amount": 900, "kind": "out", "per": "month", "start": "2026-01"}).json()
    check(bool(rc.get("updated_at")), f"{who}: a recurring entry carries updated_at {rc}")
    r = s.patch(B + f"/api/budget/recurring/{rc['id']}", json={"title": "Rent A", "amount": 950, "kind": "out", "per": "month", "start": "2026-01", "expect_updated_at": rc["updated_at"]})
    check(r.ok and r.json()["title"] == "Rent A", f"{who}: recurring saved with its base ({r.status_code} {r.text[:200]})")
    r = s.patch(B + f"/api/budget/recurring/{rc['id']}", json={"title": "Rent B", "amount": 990, "kind": "out", "per": "month", "start": "2026-01", "expect_updated_at": rc["updated_at"]})
    check(r.status_code == 409 and r.json().get("item", {}).get("title") == "Rent A", f"{who}: recurring, old base -> 409 ({r.status_code} {r.text[:200]})")


def journal(s, who):
    day = (date.today() - timedelta(days=2)).isoformat()
    r = s.put(B + f"/api/life/journal/{day}", json={"text": "Phone", "expect_updated_at": ""})
    check(r.ok and r.json().get("updated_at"), f"{who}: journal, a new entry with base \"\" ({r.status_code} {r.text[:200]})")
    j = r.json()
    r = s.put(B + f"/api/life/journal/{day}", json={"text": "Computer", "expect_updated_at": ""})
    check(r.status_code == 409 and r.json().get("entry", {}).get("text") == "Phone", f"{who}: journal, the other device saw no entry -> 409 ({r.status_code} {r.text[:200]})")
    r = s.put(B + f"/api/life/journal/{day}", json={"text": "Phone 2", "expect_updated_at": j["updated_at"]})
    check(r.ok and r.json()["text"] == "Phone 2", f"{who}: journal with its base ({r.status_code} {r.text[:200]})")
    r = s.put(B + f"/api/life/journal/{day}", json={"text": "Phone 3", "expect_updated_at": j["updated_at"]})
    check(r.status_code == 409, f"{who}: journal, old base -> 409 ({r.status_code})")
    check(s.put(B + f"/api/life/journal/{day}", json={"text": "No check"}).ok, f"{who}: journal without expect as before")


# ---------------------------------------------------------------- an organisation's office
CL = clients(A, "org")
good = parallel(A, f"/api/clients/{CL}", lambda i, k: {"note": f"pair {i} tab {k}"})
check(good == 6, f"org: two parallel saves with the same base -> one 200, one 409 (6 of 6 pairs: {good})")
master(A, "org")
letter(A, "org")
budget(A, "org")
journal(A, "org")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: clients)
FID, Fr = freelancer(B, A)
FCL = clients(Fr, "freelancer")
check(A.patch(B + f"/api/clients/{FCL}", json={"note": "x", "expect_updated_at": "1"}).status_code in (403, 404), "freelancer: another person cannot reach the client")
master(Fr, "freelancer")
letter(Fr, "freelancer")
budget(Fr, "freelancer")
journal(Fr, "freelancer")

sys.exit(kt.done("p2269_c_clients"))
