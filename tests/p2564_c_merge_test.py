#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.564.0 C (#4701): whole lists / forms replaced without the version the writer saw -- outside the office. Two clients each
time: A reads, B changes, A writes with the old state -> B's change stays (merge) or 409 with the current state. Invented
names only. freelancer-matrix: fields, tasks, templates, files, sheets
 - field options (PATCH /api/fields/<id>) with _prev.options: another admin added an option meanwhile -> 409 {field}, the new
   option and its values stay; with the current list it goes through, only the removed option loses its values; without
   _prev (old clients) the old behaviour
 - tasks.people with _prev.people: a person added elsewhere stays when this client removes another one
 - PUT /api/tasks/<id>/waiting sets only the fields sent: a note alone keeps the follow-up day, until alone keeps the note
 - PATCH /api/templates/<id> with an older expect_updated_at -> 409 {template}, nothing written; without it as before
 - PUT /api/files/nodes/<id>/tags with _prev.tags: a tag set elsewhere stays
 - a table's title, a sheet's name, the chart, a cell's name and freeze land in the table's history (what, before / after)
The same as a person without an organisation (frida, two sessions of hers), people in a shared list of alice.
usage: p2564_c_merge_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, login  # noqa: E402
from kt import B, check  # noqa: E402

kt.fresh(prefix="P2564C")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
IDS = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": kt.PASSWORD, "email": f"{u}@example.com"})
    assert r.ok, r.text
    IDS[u] = r.json()["id"]
Bo = kt.sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
FID, Fr = freelancer(B, A)
Fr2 = login(B, "frida")  # her second device


def task_of(s, tid):
    return s.get(B + f"/api/tasks/{tid}").json()


def new_list(s, name):
    r = s.post(B + "/api/lists", json={"name": name})
    assert r.ok, r.text
    return r.json()["id"]


def new_task(s, lid, title):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid})
    assert r.ok, r.text
    return r.json()["id"]


def run(who, s1, s2):
    """s1 = client A, s2 = client B (another admin / another device)."""
    # ============================================================ field options
    L = new_list(s1, f"Shoot {who}")
    r = s1.post(B + f"/api/lists/{L}/fields", json={"name": "Colour", "type": "select", "options": {"options": [{"name": "Red"}, {"name": "Blue"}]}})
    check(r.ok, f"{who}: a select field " + r.text[:200])
    f = r.json()
    FD, seen = f["id"], f["options"]["options"]
    red, blue = seen[0]["id"], seen[1]["id"]
    T1, T2, T3 = new_task(s1, L, "One"), new_task(s1, L, "Two"), new_task(s1, L, "Three")
    s1.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FD): red}})
    s1.patch(B + f"/api/tasks/{T3}", json={"fields": {str(FD): blue}})
    r = s2.patch(B + f"/api/fields/{FD}", json={"options": {"options": seen + [{"name": "Green"}]}, "_prev": {"options": seen}})
    check(r.ok and len(r.json()["options"]["options"]) == 3, f"{who}: B adds Green with the list it saw " + r.text[:200])
    now = r.json()["options"]["options"] if r.ok else seen
    green = now[-1]["id"]
    s2.patch(B + f"/api/tasks/{T2}", json={"fields": {str(FD): green}})
    # A removes Blue from the list it saw before Green came
    r = s1.patch(B + f"/api/fields/{FD}", json={"options": {"options": [seen[0]]}, "_prev": {"options": seen}})
    check(r.status_code == 409 and [o["name"] for o in (r.json().get("field") or {}).get("options", {}).get("options", [])] == ["Red", "Blue", "Green"],
          f"{who}: A with the old option list: 409 with the current field " + r.text[:300])
    check(task_of(s1, T2).get("fields", {}).get(str(FD)) == green, f"{who}: B's option keeps its value")
    check(task_of(s1, T3).get("fields", {}).get(str(FD)) == blue, f"{who}: nothing removed after the 409")
    # A loads the current field and removes Blue again: only Blue's values go
    r = s1.patch(B + f"/api/fields/{FD}", json={"options": {"options": [now[0], now[2]]}, "_prev": {"options": now}})
    check(r.ok and [o["name"] for o in r.json()["options"]["options"]] == ["Red", "Green"], f"{who}: with the current list it goes through " + r.text[:200])
    check(task_of(s1, T3).get("fields", {}).get(str(FD)) is None and task_of(s1, T2).get("fields", {}).get(str(FD)) == green
          and task_of(s1, T1).get("fields", {}).get(str(FD)) == red, f"{who}: only the removed option lost its value")
    r = s1.patch(B + f"/api/fields/{FD}", json={"options": {"options": [now[0]]}})
    check(r.ok and task_of(s1, T2).get("fields", {}).get(str(FD)) is None, f"{who}: without _prev the old behaviour (an old client)")

    # ============================================================ waiting on someone
    W = new_task(s1, L, "Quote from the carpenter")
    r = s1.put(B + f"/api/tasks/{W}/waiting", json={"note": "carpenter Meier", "until": "2031-05-01"})
    check(r.ok and r.json()["wait_until"] == "2031-05-01", f"{who}: waiting set")
    r = s2.put(B + f"/api/tasks/{W}/waiting", json={"note": "carpenter Schulz"})
    check(r.ok and r.json()["wait_note"] == "carpenter Schulz" and r.json()["wait_until"] == "2031-05-01",
          f"{who}: a note alone keeps the follow-up day " + str({k: r.json().get(k) for k in ("wait_note", "wait_until")}))
    r = s1.put(B + f"/api/tasks/{W}/waiting", json={"until": "2031-06-01"})
    check(r.ok and r.json()["wait_note"] == "carpenter Schulz" and r.json()["wait_until"] == "2031-06-01", f"{who}: until alone keeps the note")
    r = s1.put(B + f"/api/tasks/{W}/waiting", json={"until": None})
    check(r.ok and r.json()["wait_until"] is None and r.json()["wait_note"] == "carpenter Schulz", f"{who}: until null clears the day")
    s1.delete(B + f"/api/tasks/{W}/waiting")
    r = s1.put(B + f"/api/tasks/{W}/waiting", json={"note": "the office"})
    check(r.ok and r.json()["wait_until"] is None and r.json()["wait_note"] == "the office", f"{who}: a new waiting state starts empty")

    # ============================================================ templates
    r = s1.post(B + "/api/templates", json={"list_id": L, "name": f"Tpl {who}"})
    check(r.ok, f"{who}: a template " + r.text[:200])
    TP = r.json()["id"]
    r = s2.patch(B + f"/api/templates/{TP}", json={"name": "Renamed by B"})
    check(r.ok, f"{who}: B renames it")
    r = s1.patch(B + f"/api/templates/{TP}", json={"name": "Renamed by A", "expect_updated_at": "2000-01-01T00:00:00+00:00"})
    check(r.status_code == 409 and (r.json().get("template") or {}).get("name") == "Renamed by B", f"{who}: an older version: 409 with the current one " + r.text[:200])
    check(next(t for t in s1.get(B + "/api/templates").json()["templates"] if t["id"] == TP)["name"] == "Renamed by B", f"{who}: B's name stays")
    cur = r.json().get("template", {}).get("updated_at")
    check(s1.patch(B + f"/api/templates/{TP}", json={"name": "Renamed by A", "expect_updated_at": cur}).ok, f"{who}: with the current version it saves")
    check(s1.patch(B + f"/api/templates/{TP}", json={"name": "Again"}).ok, f"{who}: without a version as before")

    # ============================================================ file tags
    r = s1.post(B + "/api/files/upload", data={"space": "private"}, files={"file": (f"brief-{who}.bin", b"\x00\x01plan")})
    check(r.status_code == 201, f"{who}: a file " + r.text[:200])
    NID = r.json()["items"][0]["id"]
    tags = lambda: [t["name"] for t in s1.get(B + f"/api/files/nodes/{NID}/tags").json()["tags"]]  # noqa: E731
    check(s1.put(B + f"/api/files/nodes/{NID}/tags", json={"tags": ["draft", "client"]}).ok, f"{who}: two tags")
    check(s2.put(B + f"/api/files/nodes/{NID}/tags", json={"tags": ["draft", "client", "urgent"], "_prev": {"tags": ["draft", "client"]}}).ok, f"{who}: B adds urgent")
    r = s1.put(B + f"/api/files/nodes/{NID}/tags", json={"tags": ["client"], "_prev": {"tags": ["draft", "client"]}})
    check(r.ok and sorted(t["name"] for t in r.json()["tags"]) == ["client", "urgent"], f"{who}: A removes draft, B's urgent stays " + r.text[:200])
    check(s1.put(B + f"/api/files/nodes/{NID}/tags", json={"tags": ["client"]}).ok and tags() == ["client"], f"{who}: without _prev the list replaces them")

    # ============================================================ table: title, sheet name, chart, cell name, freeze in the history
    r = s1.post(B + "/api/sheets", json={"title": f"Tally {who}", "space": "private"})
    check(r.status_code == 201, f"{who}: a table " + r.text[:200])
    SID = r.json()["id"]
    s1.post(B + f"/api/sheets/{SID}/columns", json={"title": "Sum", "kind": "number"})
    d = s1.get(B + f"/api/sheets/{SID}").json()
    cols = [c["id"] for c in d["columns"]]
    r = s1.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"cell": "A1", "raw": "=1+2"}]})
    check(r.ok, f"{who}: a formula " + r.text[:200])
    cid = next((x["id"] for x in r.json().get("cells", []) if x.get("addr") == "A1"), 0)
    check(s2.patch(B + f"/api/sheets/{SID}", json={"title": f"Tally {who} 2"}).ok, f"{who}: B renames the table")
    check(s2.put(B + f"/api/sheets/{SID}/chart", json={"chart": {"type": "bar", "x": None, "y": [cols[-1]]}}).ok, f"{who}: B adds a chart")
    check(s2.post(B + f"/api/sheets/{SID}/cells/{cid}/name", json={"name": "total"}).ok, f"{who}: B names the cell")
    check(s2.post(B + f"/api/sheets/{SID}/cells/{cid}/freeze", json={"frozen": True}).ok, f"{who}: B freezes it")
    r = s2.post(B + f"/api/sheets/{SID}/tabs", json={})
    check(r.status_code == 201, f"{who}: a second sheet " + r.text[:200])
    S2 = r.json()["tab"]["id"]
    check(s2.patch(B + f"/api/sheets/{SID}/tabs/{S2}", json={"name": "Costs"}).ok, f"{who}: B renames the second sheet")
    es = s1.get(B + f"/api/sheets/{SID}/history").json()["entries"]
    got = {e.get("what"): (e["old"], e["new"]) for e in es if e.get("what")}
    check(got.get("title") == (f"Tally {who}", f"Tally {who} 2"), f"{who}: the title in the history " + str(got))
    check((got.get("chart") or ("", ""))[0] == "" and (got.get("chart") or ("", ""))[1].startswith("Bars"), f"{who}: the chart in the history " + str(got))
    check(got.get("name") == ("", "total") and got.get("freeze") == ("No", "Yes"), f"{who}: name and freeze of the cell " + str(got))
    ce = s1.get(B + f"/api/sheets/{SID}/cells/{cid}/history").json()["entries"]
    check({e.get("what") for e in ce} >= {"name", "freeze"}, f"{who}: the cell's own history has them " + str(ce))
    es2 = s1.get(B + f"/api/sheets/{S2}/history").json()["entries"]
    check([(e.get("what"), e["new"]) for e in es2 if e.get("what")] == [("tab", "Costs")], f"{who}: the sheet name in its history " + str(es2))


# people: alice's list shared with bob and carol
PL = new_list(A, "Team outing")
for u in ("bob", "carol"):
    check(A.put(B + f"/api/lists/{PL}/members", json={"user_id": IDS[u], "role": "edit"}).ok, f"{u} shares the list")
PT = new_task(A, PL, "Boat trip")
check(A.patch(B + f"/api/tasks/{PT}", json={"people": [ALICE, IDS["bob"]]}).ok, "alice and bob come along")
r = Bo.patch(B + f"/api/tasks/{PT}", json={"people": [ALICE, IDS["bob"], IDS["carol"]], "_prev": {"people": [ALICE, IDS["bob"]]}})
check(r.ok, "bob adds carol " + r.text[:200])
r = A.patch(B + f"/api/tasks/{PT}", json={"people": [ALICE], "_prev": {"people": [ALICE, IDS["bob"]]}})
check(r.ok and sorted(task_of(A, PT).get("people") or []) == sorted([ALICE, IDS["carol"]]),
      "alice removes bob with the list she saw: carol (added by bob) stays " + str(task_of(A, PT).get("people")))
check(A.patch(B + f"/api/tasks/{PT}", json={"people": [ALICE]}).ok and task_of(A, PT).get("people") == [ALICE], "without _prev the list replaces them")
# frida: her own list, the merge with herself only
FL = new_list(Fr, "Frida errands")
FT = new_task(Fr, FL, "Market")
check(Fr2.patch(B + f"/api/tasks/{FT}", json={"people": [FID], "_prev": {"people": []}}).ok, "frida (device 2) comes along")
check(Fr.patch(B + f"/api/tasks/{FT}", json={"title": "Market day", "people": [], "_prev": {"people": [], "title": "Market"}}).ok
      and task_of(Fr, FT).get("people") == [FID], "frida (device 1) with the old list: her second device's change stays")

run("alice", A, kt.sess("alice"))  # her second device (templates are her own, the list's fields hers)
run("frida", Fr, Fr2)

sys.exit(kt.done("p2564_c_merge"))
