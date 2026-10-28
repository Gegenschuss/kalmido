#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.390.0 B (#3355): the task filters of GET /api/v1/tasks are complete, tasks carry sprint, reviewer and review state.
Invented projects and titles only. freelancer-matrix: tasks
 - filters priority (several, repeated, priority_min), section_id, sprint_id (id | current | none), created_by, reviewer,
   review, field_<id> (select by id / name, text contains, number, checkbox), q (title / notes); bad values = 400
 - sort priority / due / title with "-" = descending: cursor pages (limit 1) give every task once, ties by id, no due date
   last; a cursor of another sort = 400
 - the task object has sprint_id, reviewer_id, review; POST / PATCH take sprint_id (only an open sprint of the same project)
   and reviewer_id (only someone with access: else 400 and nothing written)
 - all as a person without an organisation (the own project, a personal token); an organisation's admin the same filters
usage: p2390_0_b_api_test.py <datadir>      (KMT_NOSTART=1 / P23900B_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup

fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="P23900B")  # many requests of one token within a minute
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, F = freelancer(B, A)
V = B + "/api/v1"
AID = A.get(B + "/api/state").json()["me"]["id"]


def token(s):
    r = s.post(B + "/api/me/tokens", json={"name": "filters", "scopes": ["read", "tasks:write"]})
    assert r.ok, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def run(who, s, uid):
    T = token(s)

    def get(**q):
        return requests.get(V + "/tasks", headers=T, params=q)

    def ids(**q):
        r = get(**q)
        return sorted(t["id"] for t in r.json()["data"]) if r.ok else f"{r.status_code} {r.text[:120]}"

    def walk(sort, lid):
        out, cur = [], None
        for _ in range(20):
            r = get(list_id=lid, sort=sort, limit=1, **({"cursor": cur} if cur else {}))
            if not r.ok:
                return f"{r.status_code} {r.text[:120]}"
            out += [t["id"] for t in r.json()["data"]]
            cur = r.json()["next_cursor"]
            if not cur:
                return out
        return out

    L = s.post(B + "/api/lists", json={"name": "Product", "kind": "project"}).json()["id"]
    L2 = s.post(B + "/api/lists", json={"name": "Errands"}).json()["id"]
    S1 = s.put(B + f"/api/lists/{L}/sprint-settings", json={"on": True}).json().get("started_id")
    S2 = s.post(B + f"/api/lists/{L}/sprints", json={"goal": "Next"}).json().get("id")
    SEC = s.post(B + "/api/sections", json={"list_id": L, "name": "Doing"}).json().get("id")
    check(S1 and S2 and SEC, f"{who}: setup sprints {S1} {S2} and a column {SEC}")
    fd = lambda name, typ, **o: s.post(B + f"/api/lists/{L}/fields", json={"name": name, "type": typ, **o}).json()
    sel = fd("Kind", "select", options={"options": [{"name": "Bug"}, {"name": "Idea"}]})
    BUG, IDEA = (o["id"] for o in sel["options"]["options"])
    FT, FN, FC = fd("Remark", "text")["id"], fd("Cost", "number")["id"], fd("Urgent", "checkbox")["id"]
    FS = sel["id"]

    def mk(**b):
        r = requests.post(V + "/tasks", headers=T, json={"list_id": L, **b})
        check(r.status_code == 201, f"{who}: create {b.get('title')} ({r.status_code} {r.text[:160]})")
        return r.json()

    t1 = mk(title="Alpha login crash", priority="high", section_id=SEC, sprint_id=S1, due="2026-11-02",
            fields={str(FS): BUG, str(FT): "needs the Logs", str(FN): 12.5, str(FC): True})
    t2 = mk(title="Beta export", priority="medium", sprint_id=S2, due="2026-11-01", fields={str(FS): IDEA, str(FN): "3"})
    t3 = mk(title="Gamma crash report", priority="high", reviewer_id=uid, notes="the parser")
    t4 = mk(title="Delta", priority="low", due="2026-11-01")
    t5 = mk(title="Epsilon")
    T1, T2, T3, T4, T5 = (t["id"] for t in (t1, t2, t3, t4, t5))
    ALL = sorted([T1, T2, T3, T4, T5])

    # the task object
    check(t1.get("sprint_id") == S1 and t1.get("reviewer_id") is None and "review" in t1 and t1["review"] is None,
          f"{who}: a task carries sprint_id, reviewer_id and review {[t1.get(k) for k in ('sprint_id', 'reviewer_id', 'review')]}")
    check(t3.get("reviewer_id") == uid and t3.get("sprint_id") is None, f"{who}: created with a reviewer {t3.get('reviewer_id')}")
    check(t1.get("created_by") == uid, f"{who}: created_by in the task {t1.get('created_by')}")

    # priority
    check(ids(list_id=L, priority="high") == sorted([T1, T3]), f"{who}: priority=high {ids(list_id=L, priority='high')}")
    check(ids(list_id=L, priority="high,low") == sorted([T1, T3, T4]), f"{who}: priority=high,low")
    r = requests.get(V + "/tasks", headers=T, params=[("list_id", L), ("priority", "medium"), ("priority", "none")])
    check(r.ok and sorted(t["id"] for t in r.json()["data"]) == sorted([T2, T5]), f"{who}: priority repeated {r.text[:120]}")
    check(ids(list_id=L, priority_min="medium") == sorted([T1, T2, T3]), f"{who}: priority_min=medium")
    check(get(priority="urgent").status_code == 400 and get(priority_min="5").status_code == 400, f"{who}: an unknown priority = 400")
    # column, sprint, creator, reviewer, review
    check(ids(list_id=L, section_id=SEC) == [T1], f"{who}: section_id {ids(list_id=L, section_id=SEC)}")
    check(ids(list_id=L, section_id="none") == sorted([T2, T3, T4, T5]), f"{who}: section_id=none")
    check(ids(list_id=L, sprint_id=S1) == [T1] and ids(sprint_id=S2) == [T2], f"{who}: sprint_id = a sprint")
    check(ids(sprint_id="current") == [T1], f"{who}: sprint_id=current = the active sprint {ids(sprint_id='current')}")
    check(ids(list_id=L, sprint_id="none") == sorted([T3, T4, T5]), f"{who}: sprint_id=none = the backlog")
    check(ids(list_id=L, created_by="me") == ALL and ids(list_id=L, created_by=AID if uid != AID else FID) == [],
          f"{who}: created_by")
    check(get(created_by="none").status_code == 400, f"{who}: created_by=none = 400")
    check(ids(list_id=L, reviewer="me") == [T3] and ids(list_id=L, reviewer=uid) == [T3], f"{who}: reviewer = me / my id")
    check(ids(list_id=L, reviewer="none") == sorted([T1, T2, T4, T5]), f"{who}: reviewer=none")
    r = s.post(B + f"/api/tasks/{T3}/review", json={"action": "request"})
    check(r.ok, f"{who}: setup: review requested ({r.status_code} {r.text[:120]})")
    check(ids(list_id=L, reviewer="me", review="pending") == [T3], f"{who}: what waits for my review {ids(reviewer='me', review='pending')}")
    check(ids(list_id=L, review="none") == sorted([T1, T2, T4, T5]) and get(review="maybe").status_code == 400, f"{who}: review=none / bad")
    # custom fields
    check(ids(**{f"field_{FS}": BUG}) == [T1] and ids(**{f"field_{FS}": "idea"}) == [T2], f"{who}: select by option id / name")
    check(get(**{f"field_{FS}": "Nope"}).status_code == 400, f"{who}: an unknown option = 400")
    check(ids(**{f"field_{FT}": "logs"}) == [T1] and ids(**{f"field_{FT}": "50%"}) == [], f"{who}: text contains (any case, % literal)")
    check(ids(**{f"field_{FN}": "12.5"}) == [T1] and ids(**{f"field_{FN}": "3"}) == [T2], f"{who}: number")
    check(ids(**{f"field_{FC}": "true"}) == [T1] and ids(**{f"field_{FC}": "false"}) == sorted([T2, T3, T4, T5]), f"{who}: checkbox")
    check(get(field_99999="x").status_code == 400 and get(field_abc="x").status_code == 400, f"{who}: an unknown field = 400")
    # text
    check(ids(list_id=L, q="crash") == sorted([T1, T3]) and ids(list_id=L, q="crash alpha") == [T1], f"{who}: q {ids(list_id=L, q='crash')}")
    check(ids(list_id=L, q="parser") == [T3], f"{who}: q finds the notes")
    check(get(q="!!!").status_code == 400, f"{who}: q without words = 400")
    # sort + cursor (limit 1: every tie crosses a page)
    check(walk("-priority", L) == [T1, T3, T2, T4, T5], f"{who}: sort=-priority, ties by id {walk('-priority', L)}")
    check(walk("priority", L) == [T5, T4, T2, T1, T3], f"{who}: sort=priority {walk('priority', L)}")
    check(walk("due", L) == [T2, T4, T1, T3, T5], f"{who}: sort=due, no due date last {walk('due', L)}")
    check(walk("-due", L) == [T1, T2, T4, T3, T5], f"{who}: sort=-due, no due date still last {walk('-due', L)}")
    check(walk("title", L) == [T1, T2, T4, T5, T3], f"{who}: sort=title {walk('title', L)}")
    check(walk("created", L) == ALL and walk("-updated", L) and len(walk("manual", L)) == 5, f"{who}: sort created / updated / manual")
    r = get(list_id=L, sort="-priority", limit=2, fields="compact")
    cur = r.json().get("next_cursor")
    check(r.ok and set(r.json()["data"][0]) == {"id", "title", "list_id", "section_id", "parent_id", "status", "due", "due_time",
                                                "priority", "tags", "list_tags", "assignee_id"} and cur, f"{who}: sorted + compact")
    check(get(list_id=L, sort="due", cursor=cur).status_code == 400, f"{who}: a cursor of another sort = 400")
    plain = get(list_id=L, limit=1).json()["next_cursor"]
    check(get(list_id=L, sort="due", cursor=plain).status_code == 400 and get(sort="size").status_code == 400, f"{who}: bad sort / cursor = 400")
    check(ids(list_id=L, priority="high", sort="-due") == sorted([T1, T3]), f"{who}: filters and sort together")
    # writing sprint and reviewer
    r = requests.patch(V + f"/tasks/{T4}", headers=T, json={"sprint_id": S2})
    check(r.ok and r.json().get("sprint_id") == S2 and ids(sprint_id=S2) == sorted([T2, T4]), f"{who}: PATCH sprint_id {r.text[:120]}")
    r = requests.patch(V + f"/tasks/{T4}", headers=T, json={"sprint_id": None})
    check(r.ok and r.json().get("sprint_id") is None, f"{who}: PATCH sprint_id null = backlog")
    r = requests.post(V + "/tasks", headers=T, json={"list_id": L2, "title": "Other"})
    check(r.status_code == 201, f"{who}: setup: a task in another project ({r.status_code} {r.text[:160]})")
    x = r.json().get("id")
    r = requests.patch(V + f"/tasks/{x}", headers=T, json={"sprint_id": S1})
    check(r.status_code == 400 and requests.get(V + f"/tasks/{x}", headers=T).json().get("sprint_id") is None,
          f"{who}: a sprint of another project = 400 ({r.status_code})")
    stranger = AID if uid != AID else FID
    r = requests.patch(V + f"/tasks/{T4}", headers=T, json={"reviewer_id": stranger, "title": "Delta changed"})
    t = requests.get(V + f"/tasks/{T4}", headers=T).json()
    check(r.status_code == 400 and t["reviewer_id"] is None and t["title"] == "Delta", f"{who}: a reviewer without access = 400, nothing written ({r.status_code})")
    r = requests.patch(V + f"/tasks/{T4}", headers=T, json={"reviewer_id": uid})
    check(r.ok and r.json().get("reviewer_id") == uid, f"{who}: PATCH reviewer_id {r.text[:120]}")
    r = requests.patch(V + f"/tasks/{T4}", headers=T, json={"reviewer_id": None})
    check(r.ok and r.json().get("reviewer_id") is None, f"{who}: PATCH reviewer_id null clears it")
    check(requests.patch(V + f"/tasks/{T4}", headers=T, json={"reviewer_id": "x"}).status_code == 400, f"{who}: reviewer_id not a number = 400")
    n = len(get(list_id=L, status="all").json()["data"])
    r = requests.post(V + "/tasks", headers=T, json={"list_id": L, "title": "Refused", "reviewer_id": stranger})
    check(r.status_code == 400 and len(get(list_id=L, status="all").json()["data"]) == n, f"{who}: create with a bad reviewer = 400, no task")
    r = requests.post(V + f"/tasks/{T1}/subtasks", headers=T, json={"title": "Sub", "reviewer_id": uid})
    check(r.status_code == 201 and r.json().get("reviewer_id") == uid, f"{who}: a subtask with a reviewer ({r.status_code})")
    r = requests.post(V + "/tasks/batch", headers=T, json={"ids": [T5], "action": "update", "changes": {"reviewer_id": uid}})
    check(r.status_code == 400, f"{who}: batch refuses reviewer_id instead of dropping it ({r.status_code})")


run("freelancer", F, FID)
run("admin", A, AID)
sys.exit(done("p2390_0_b_api"))
