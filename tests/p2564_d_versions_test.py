#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.564.0 D (#4701, audit #2822 B-F4 + C-F2): the dialogs outside the office that save a whole object check the version
the dialog opened with (expect_updated_at, kalmido/core/conflict.py ccf_check) instead of overwriting: comments, team chat
messages, channel settings, polls, habits, the document sheet, calendar subscriptions, sprints and the sprint settings, the
booking page and its appointment types, an agent's rule text. Per area, two clients: A read version v0, B saves with v0
(200, a new version), A saves with v0 -> 409 with the current state under its own key and B's change stays; an invented
old version -> 409; without expect_updated_at (old clients, the API) -> 200 as before. Own container (kt.fresh, mode
workspaces). Invented names only (example.com); the person without an organisation (tests/freelancer_fixture.py) and an
organisation admin do every step.
freelancer-matrix: tasks, time, files, pim, polls, lists
usage: p2564_d_versions_test.py <datadir>      (KMT_NOSTART=1: a running server)"""
import json
import os
import sys
from datetime import datetime, timezone

import dbx as dbxm
import kt
from kt import B, DATA, check, done
from freelancer_fixture import FEATURES, freelancer

OLD = "2020-01-02T03:04:05+00:00"  # a version from long ago: another device saved since


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # noqa: BLE001 - an INSERT / UPDATE without rows to read
            return []
    finally:
        c.close()


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2564D")
A = kt.setup()
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})
A = kt.sess("alice")
check(A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok, "setup: Alice's features")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})  # personal agents (their rules)
AID = A.get(B + "/api/state").json()["me"]["id"]
FID, Fr = freelancer(B, A)


def trio(S, who, what, method, url, b1, b2, key, v0, ver, mark):
    """v0 = the version both clients read. B saves b1 with v0 -> 200 and a new version; A saves b2 with v0 -> 409 with the
    current state under key (b1's mark in it: B's change stays); an old invented version -> 409; without one -> 200."""
    t = f"{who} {what}"
    check(bool(v0), f"{t}: the object carries a version {v0!r}")
    r = S.request(method, B + url, json={**b1, "expect_updated_at": OLD})
    check(r.status_code == 409 and isinstance(r.json().get(key), dict), f"{t}: an old version -> 409 with the state under {key} {r.status_code} {r.text[:200]}")
    r = S.request(method, B + url, json={**b1, "expect_updated_at": v0})
    check(r.ok, f"{t}: B saves with the version it read -> 200 {r.status_code} {r.text[:200]}")
    v1 = ver(r.json()) if r.ok else None
    check(v1 and v1 != v0, f"{t}: the answer carries the new version {v0!r} -> {v1!r}")
    r = S.request(method, B + url, json={**b2, "expect_updated_at": v0})
    check(r.status_code == 409 and isinstance(r.json().get(key), dict) and mark in json.dumps(r.json()[key]),
          f"{t}: A saves with the version it read before -> 409, B's change in the answer {r.status_code} {r.text[:240]}")
    r = S.request(method, B + url, json={**b2, "expect_updated_at": v1})
    check(r.ok, f"{t}: A again with the current version -> 200 {r.status_code} {r.text[:200]}")
    v2 = ver(r.json()) if r.ok else None
    r = S.request(method, B + url, json=b1)
    check(r.ok, f"{t}: without expect_updated_at as before -> 200 {r.status_code} {r.text[:200]}")
    if v2:
        r = S.request(method, B + url, json={**b2, "expect_updated_at": v2})
        check(r.status_code == 409, f"{t}: a save without version moved the version on too {r.status_code}")


def run(S, who, uid):
    # 1. comments (task of an own list)
    L = S.post(B + "/api/lists", json={"name": f"Notes {who}"}).json()["id"]
    T = S.post(B + "/api/tasks", json={"title": "Call the bank", "list_id": L}).json()["id"]
    r = S.post(B + f"/api/tasks/{T}/comments", json={"body": "first words"})
    check(r.status_code in (200, 201), f"{who}: a comment {r.status_code} {r.text[:160]}")
    cm = r.json()
    trio(S, who, "comment", "PATCH", f"/api/comments/{cm['id']}", {"body": "Text of B"}, {"body": "Text of A"}, "comment",
         cm.get("edited_at") or cm["created_at"], lambda j: j.get("edited_at"), "Text of B")
    # 2. team chat: a channel of my own space, a message in it, its settings
    r = S.post(B + "/api/team/channels", json={"name": f"Chan {who}"})
    check(r.status_code in (200, 201), f"{who}: a channel {r.status_code} {r.text[:160]}")
    if r.ok:
        room = r.json()
        trio(S, who, "room", "PATCH", f"/api/team/rooms/{room['id']}", {"name": f"Room B {who}"}, {"name": f"Room A {who}"}, "room",
             room.get("updated_at"), lambda j: j.get("updated_at"), f"Room B {who}")
        r = S.post(B + f"/api/team/rooms/{room['id']}/messages", json={"body": "hello all"})
        check(r.status_code in (200, 201), f"{who}: a chat message {r.status_code} {r.text[:160]}")
        m = r.json()
        trio(S, who, "chat message", "PATCH", f"/api/team/messages/{m['id']}", {"body": "Chat of B"}, {"body": "Chat of A"}, "message",
             m.get("edited_at") or m.get("created_at"), lambda j: j.get("edited_at"), "Chat of B")
    # 3. polls
    r = S.post(B + "/api/polls", json={"title": "Team lunch", "duration": 60, "tz": "Europe/Berlin",
                                       "options": [{"start": "2031-03-10T10:00"}, {"start": "2031-03-11T14:30"}]})
    check(r.status_code == 201, f"{who}: a poll {r.status_code} {r.text[:160]}")
    p = r.json()["poll"]
    trio(S, who, "poll", "PATCH", f"/api/polls/{p['id']}", {"title": "Lunch of B"}, {"title": "Lunch of A"}, "poll",
         p["updated_at"], lambda j: j["poll"]["updated_at"], "Lunch of B")
    # 4. habits (a new column: a habit never edited counts with its created_at)
    hid = S.post(B + "/api/habits", json={"name": "Read"}).json()["id"]
    h = next(x for x in S.get(B + "/api/state").json()["habits"] if x["id"] == hid)
    trio(S, who, "habit", "PATCH", f"/api/habits/{hid}", {"name": "Habit of B"}, {"name": "Habit of A"}, "habit",
         h.get("updated_at") or h["created_at"], lambda j: j.get("updated_at"), "Habit of B")
    # 5. the document sheet (after the recognition: a real state, not a time)
    r = S.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("beleg.txt", b"Beleg 0815 Material", "text/plain")})
    check(r.status_code == 201, f"{who}: a document {r.status_code} {r.text[:160]}")
    nid = r.json()["ids"][0]
    d = kt.until(lambda: (lambda j: j if j.get("state") not in ("wait", "run") else None)(S.get(B + f"/api/docs/{nid}").json()), timeout=90)
    check(bool(d), f"{who}: the document's recognition ended")
    d = d or S.get(B + f"/api/docs/{nid}").json()
    trio(S, who, "document", "PATCH", f"/api/docs/{nid}", {"name": "Doc of B"}, {"name": "Doc of A"}, "doc",
         d["edited_at"], lambda j: j.get("edited_at"), "Doc of B")  # 2.570.0 (#4770): a document's version is edited_at
    # 6. a calendar subscription (stored directly: no feed to fetch)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sql("INSERT INTO cal_subs(user_id,kind,name,color,visible,interval,url,url_hint,username,password,created_at,changed_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (uid, "ics", "Holidays", "#3b82f6", 1, 60, "", "example.com/x.ics", "", "", ts, ts))
    sid = sql("SELECT MAX(id) FROM cal_subs WHERE user_id=?", (uid,))[0][0]
    trio(S, who, "calendar", "PATCH", f"/api/calendars/{sid}", {"name": "Cal of B"}, {"name": "Cal of A"}, "calendar",
         ts, lambda j: j.get("updated_at"), "Cal of B")
    # 7. sprints: the settings of a project list, then the running sprint
    P = S.post(B + "/api/lists", json={"name": f"Product {who}", "kind": "project"}).json()["id"]
    r = S.put(B + f"/api/lists/{P}/sprint-settings", json={"on": True})
    check(r.ok and r.json().get("started_id"), f"{who}: sprints on {r.status_code} {r.text[:160]}")
    trio(S, who, "sprint settings", "PUT", f"/api/lists/{P}/sprint-settings", {"dow": 3}, {"dow": 5}, "settings",
         r.json()["settings"].get("updated_at"), lambda j: j["settings"].get("updated_at"), '"dow": 3')
    spr = next(x for x in S.get(B + f"/api/lists/{P}/sprints").json()["sprints"] if x["id"] == r.json()["started_id"])
    trio(S, who, "sprint", "PATCH", f"/api/sprints/{spr['id']}", {"goal": "Goal of B"}, {"goal": "Goal of A"}, "sprint",
         spr.get("updated_at"), lambda j: j.get("updated_at"), "Goal of B")
    # 8. the booking page and an appointment type
    r = S.put(B + "/api/appt/page", json={"title": "Book me"})
    check(r.ok and r.json().get("exists"), f"{who}: the booking page {r.status_code} {r.text[:160]}")
    trio(S, who, "booking page", "PUT", "/api/appt/page", {"title": "Page of B"}, {"title": "Page of A"}, "current",
         r.json()["page"].get("updated_at"), lambda j: j["page"].get("updated_at"), "Page of B")
    r = S.post(B + "/api/appt/types", json={"name": "Talk"})
    check(r.status_code == 201, f"{who}: an appointment type {r.status_code} {r.text[:160]}")
    trio(S, who, "appointment type", "PATCH", f"/api/appt/types/{r.json()['id']}", {"name": "Type of B"}, {"name": "Type of A"}, "type",
         r.json().get("updated_at"), lambda j: j.get("updated_at"), "Type of B")
    # 9. the rule text of my own agent
    r = S.post(B + "/api/my/agents", json={"username": f"helper{uid}", "display_name": "Helper", "scopes": ["read", "comments"]})
    check(r.status_code in (200, 201), f"{who}: a personal agent {r.status_code} {r.text[:160]}")
    aid = r.json()["id"]
    r = S.post(B + f"/api/agents/{aid}/rules", json={"text": "Answer in German"})
    check(r.status_code == 201, f"{who}: a rule {r.status_code} {r.text[:160]}")
    rule = r.json()["rule"]
    trio(S, who, "agent rule", "PATCH", f"/api/agents/{aid}/rules/{rule['id']}", {"text": "Rule of B"}, {"text": "Rule of A"}, "rule",
         rule["updated_at"], lambda j: j["rule"]["updated_at"], "Rule of B")


run(Fr, "freelancer", FID)
run(A, "org", AID)

sys.exit(done("p2564_d_versions"))
