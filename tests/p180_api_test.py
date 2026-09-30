#!/usr/bin/env python3
"""1.8.0 API tests (fresh DB on the TEST container :3048): the sample project. POST /api/sample creates "Example: Image
film for client Muster" (project: 5 sections, 15 tasks + 3 subtasks around today, start dates, 4 dependencies, all four
priorities, Markdown checklist, tags, a repeating task, a comment, 2 custom fields, a time entry, a status) and the
checklist "Example: Shoot day packing list"; idempotent (also two requests at once), CSRF, login, private (not for
other users), quiet (no pushes, News, activity, not in the daily digest), in the user's language, a simpler version
without the project modules. DELETE /api/sample removes exactly what it created: edited sample tasks and the done copy
of the repeating task go, tasks the user added (also below a sample task) stay with their list, section and field.
The setup's {sample} flag creates it / stops the tour from asking."""
import json, os, sys, threading, time
from datetime import date, timedelta
import requests

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1]
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
ALL = "cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields"


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what)


def sess(u=None):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok
    return s


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def wait_for(fn, timeout=8):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return True
        time.sleep(0.2)
    return False


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
Bb = sess("bob")
A.patch(B + "/api/settings", json={"features": ALL, "push_channel": "ntfy"})
Bb.patch(B + "/api/settings", json={"features": ALL, "lang": "de"})
st = lambda s=A: s.get(B + "/api/state").json()  # noqa: E731
T0 = date.today()
D = lambda n: (T0 + timedelta(days=n)).isoformat()  # noqa: E731

# ---- guards
check(requests.post(B + "/api/sample", headers=H).status_code == 401, "no login: 401")
r = requests.post(B + "/api/sample", cookies=A.cookies)
check(r.status_code in (400, 403), f"CSRF: no X-Requested-With header -> refused ({r.status_code})")
check(st()["sample"] is None, "before: no sample")
check(A.delete(B + "/api/sample").status_code == 404, "remove without a sample: 404")
n_push0 = len(pushes())

# ---- create
r = A.post(B + "/api/sample", json={}).json()
check(r.get("created") is True and r.get("list_id"), "created: " + str(r)[:120])
S = st()
sm = S["sample"]
check(sm and len(sm["lists"]) == 2 and sm["tasks"] == 27, "state.sample: 2 lists, 27 tasks: " + str(sm)[:200])
L = next(l for l in S["lists"] if l["id"] == r["list_id"])
check(L["name"] == "Example: Image film for client Muster" and L["kind"] == "project", "project list: " + L["name"] + " " + L["kind"])
check(L.get("status") == "on_track", "project status set")
PK = next((l for l in S["lists"] if l["name"] == "Example: Shoot day packing list"), None)
check(PK and PK["kind"] == "checklist" and PK["checklist"] == 1, "packing list is a checklist")
secs = [s for s in S["sections"] if s["list_id"] == L["id"]]
check([s["name"] for s in secs] == ["Concept", "Pre-production", "Shoot", "Edit", "Approval"], "sections: " + str([s["name"] for s in secs]))
TT = [t for t in S["tasks"] if t["list_id"] == L["id"]]
main = [t for t in TT if not t["parent_id"]]
subs = [t for t in TT if t["parent_id"]]
check(len(main) == 15 and len(subs) == 3, f"15 tasks + 3 subtasks ({len(main)}, {len(subs)})")
check(len([t for t in S["tasks"] if t["list_id"] == PK["id"]]) == 9, "9 packing items")
by = {t["title"]: t for t in TT}
check({t["priority"] for t in main} == {0, 1, 3, 5}, "all four priorities (matrix quadrants)")
opn = [t for t in main if t["status"] == 0]
check(any(t["due"] and t["due"] < D(0) for t in opn), "an overdue task")
check(any(t["due"] == D(0) for t in opn), "a task due today")
check(any(t["due"] and D(7) <= t["due"] <= D(14) for t in opn), "tasks next week")
check(any(not t["due"] for t in opn), "an undated task")
check(sum(1 for t in main if t["start"] and t["due"] and t["start"] < t["due"]) >= 5, "start dates (timeline bars)")
check(by["Briefing with the client"]["status"] == 2, "one done task (progress)")
con = by["Write the concept and treatment"]
check("- [ ] " in con["content"] and "**Goal:**" in con["content"], "Markdown description with a checklist")
check("concept" in con["tags"] and "client" in by["Get the quote and budget approved"]["tags"], "tags")
call = by["Weekly status call with the client"]
check(call["repeat"] == "FREQ=WEEKLY;BYDAY=TU" and date.fromisoformat(call["due"]).weekday() == 1 and call["due_time"] == "10:00", "repeating task on the next Tuesday")
check(call["reminders"] == "" and all(t["reminders"] == "" for t in TT), "no reminders anywhere")
check(by["Shoot day 1: interviews"]["duration"] == 540, "timed shoot day with a duration")
nb = sum(len(t["blockers"]) for t in TT)
check(nb == 4, f"4 dependencies ({nb})")
check(by["Get the quote and budget approved"]["blocked"] and not con["blocked"], "budget waits on the concept, the concept is doable")
fl = [f for f in S["fields"] if f["list_id"] == L["id"]]
check(sorted(f["name"] for f in fl) == ["Budget", "Effort"] and all(f["pinned"] for f in fl), "two pinned custom fields")
bud = next(f for f in fl if f["name"] == "Budget")
check(by["Get the quote and budget approved"]["fields"].get(str(bud["id"])) == "12500", "budget value: " + str(by["Get the quote and budget approved"]["fields"]))
tl = A.get(B + f"/api/tasks/{by['Get the quote and budget approved']['id']}/timeline").json()
check(len(tl["comments"]) == 1 and "budget" in tl["comments"][0]["body"], "a comment")
check(tl["activity"] == [], "no activity entries (quiet)")
te = A.get(B + f"/api/time/entries?task_id={con['id']}").json()
ents = te.get("entries", te if isinstance(te, list) else [])
check(len(ents) == 1 and ents[0]["seconds"] == 5400, "a 1.5 h time entry: " + str(te)[:160])
check(A.get(B + "/api/news").json().get("items", []) == [] and Bb.get(B + "/api/news").json().get("items", []) == [], "no News")
time.sleep(1.5)
check(len(pushes()) == n_push0, "no pushes")

# ---- idempotent (also two requests at once)
r2 = A.post(B + "/api/sample", json={}).json()
check(r2.get("created") is False and r2.get("exists") is True and r2.get("list_id") == L["id"], "second create: exists, same list")
check(st()["sample"]["tasks"] == 27 and len([l for l in st()["lists"] if l["name"].startswith("Example:")]) == 2, "no duplicates")

# ---- private: bob sees nothing of it and has none himself
Sb = st(Bb)
check(Sb["sample"] is None and not any(l["id"] in (L["id"], PK["id"]) for l in Sb["lists"]), "bob: not visible")
check(Bb.get(B + f"/api/tasks/{con['id']}").status_code in (403, 404), "bob: sample task not readable")
check(Bb.delete(B + "/api/sample").status_code == 404, "bob: nothing to remove (alice's stays)")
check(st()["sample"]["tasks"] == 27, "alice's sample untouched by bob")

# ---- German, two at once
res = []
th = [threading.Thread(target=lambda: res.append(Bb.post(B + "/api/sample", json={}).json())) for _ in range(2)]
[t.start() for t in th]
[t.join() for t in th]
check(sorted(bool(x.get("created")) for x in res) == [False, True], "two requests at once: one creates: " + str([x.get("created") for x in res]))
Sb = st(Bb)
names = sorted(l["name"] for l in Sb["lists"] if l["name"].startswith("Beispiel"))
check(names == ["Beispiel: Imagefilm für Kunde Muster", "Beispiel: Packliste Drehtag"], "German names: " + str(names))
check("Konzept" in [s["name"] for s in Sb["sections"]] and any(t["title"] == "Konzept und Treatment schreiben" for t in Sb["tasks"]), "German content")
check(Bb.delete(B + "/api/sample").json().get("tasks") == 27, "bob removes his")

# ---- daily digest leaves the sample out
own = A.post(B + "/api/tasks", json={"title": "Pay the invoice", "due": D(0)}).json()["id"]
A.patch(B + "/api/settings", json={"digest_time": "00:00"})
check(wait_for(lambda: any("Pay the invoice" in (p.get("message") or p.get("body") or json.dumps(p)) for p in pushes())), "digest sent for the own task")
dig = [json.dumps(p, ensure_ascii=False) for p in pushes() if "Pay the invoice" in json.dumps(p)]
check(dig and not any(x in dig[0] for x in ("treatment", "budget", "Weekly status")), "digest without sample tasks: " + (dig[0][:200] if dig else ""))
check("1 task today" in dig[0] if dig else False, "digest counts only the own task")
A.delete(B + f"/api/tasks/{own}")

# ---- the user works with it: edit, complete the repeating task, add tasks
A.patch(B + f"/api/tasks/{con['id']}", json={"title": "Treatment v2", "content": "mine now"})
cr = A.post(B + f"/api/tasks/{call['id']}/complete", json={}).json()
check(cr.get("next_due"), "repeating sample task completed (done copy + next date)")
mine1 = A.post(B + "/api/tasks", json={"title": "My own idea", "list_id": L["id"], "section_id": secs[1]["id"]}).json()["id"]
mine2 = A.post(B + "/api/tasks", json={"title": "My subtask", "parent_id": by["Rough cut"]["id"]}).json()["id"]
A.patch(B + f"/api/tasks/{mine1}", json={"fields": {str(bud["id"]): "99"}})
check(st()["sample"]["lists"][0]["extra"] == 2, "state: 2 tasks the user added: " + str(st()["sample"]["lists"]))
rm = A.delete(B + "/api/sample")
j = rm.json()
check(rm.ok and j.get("tasks") == 28 and j.get("lists") == 1 and j.get("kept_lists") == 1 and j.get("kept_tasks") == 1, "removed: " + str(j))
S = st()
check(S["sample"] is None, "state.sample gone")
left = [t for t in S["tasks"] if t["list_id"] == L["id"]]
check(sorted(t["title"] for t in left) == ["My own idea", "My subtask"], "only the user's tasks stay: " + str([t["title"] for t in left]))
check(next(t for t in left if t["title"] == "My subtask")["parent_id"] is None, "user subtask of a sample task became a main task")
check(any(l["id"] == L["id"] for l in S["lists"]) and not any(l["id"] == PK["id"] for l in S["lists"]), "project list kept (user tasks), packing list deleted")
check([s["name"] for s in S["sections"] if s["list_id"] == L["id"]] == ["Pre-production"], "only the section with a user task stays")
check([f["name"] for f in S["fields"] if f["list_id"] == L["id"]] == ["Budget"], "only the field with a user value stays")
check(not any(t["title"] in ("Treatment v2", "Weekly status call with the client") for t in S["tasks"]), "edited sample task removed too")
done = A.get(B + "/api/tasks?scope=done&limit=500").json()
done = done.get("tasks", done) if isinstance(done, dict) else done
check(not any(t["title"] == "Weekly status call with the client" for t in done), "the done copy of the repeating task is gone")
te = A.get(B + "/api/time/entries?scope=mine").json()
check(not any(e.get("note") == "First draft of the treatment" for e in te.get("entries", [])), "time entry removed")
check(A.delete(B + "/api/sample").status_code == 404, "second remove: 404")

# ---- again, and without the project modules: simpler version, no errors
A.patch(B + f"/api/lists/{L['id']}", json={"archived": True})
A.delete(B + f"/api/lists/{L['id']}")
A.patch(B + "/api/settings", json={"features": "cal,timeline,matrix"})
r = A.post(B + "/api/sample", json={}).json()
check(r.get("created") is True, "created again (modules off)")
S = st()
L2 = next(l for l in S["lists"] if l["id"] == r["list_id"])
TT = [t for t in S["tasks"] if t["list_id"] == L2["id"]]
check(L2["kind"] == "list" and not L2.get("status"), "plain list without the project modules")
check(not any(t["blockers"] for t in TT) and not [f for f in S["fields"] if f["list_id"] == L2["id"]], "no dependencies / fields")
check(len(TT) == 18 and any(t["start"] for t in TT) and any(t["repeat"] for t in TT), "still 18 tasks with dates, start and repeat")
tlr = A.get(B + f"/api/tasks/{TT[0]['id']}/timeline")
check(tlr.status_code in (200, 403), "timeline endpoint fine")
check(A.delete(B + "/api/sample").json().get("lists") == 2, "removed (both lists)")

# ---- setup flag: sample: true creates it, false stops the tour from asking
A.patch(B + "/api/settings", json={"features": ALL})
r = A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ALL.split(","), "sample": True})
check(r.ok and st()["sample"] and st()["sample"]["tasks"] == 27, "setup {sample: true}: created")
check(st()["settings"]["sample_ask"] == "0", "created once: the tour does not ask")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ALL.split(","), "sample": True})
check(st()["sample"]["tasks"] == 27, "setup twice: no duplicate")
A.delete(B + "/api/sample")
c3 = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"}).json()["id"]
C = sess("carol")
check(st(C)["settings"]["sample_ask"] == "1", "new user: the tour may offer it")
A.patch(B + "/api/settings", json={"sample_ask": "1"})
check(st()["settings"]["sample_ask"] == "0", "sample_ask not writable by the client")
check(Bb.post(B + "/api/admin/setup", json={"modules": [], "sample": True}).status_code == 403, "setup: admins only")
check(st(Bb)["sample"] is None, "non-admin setup call created nothing")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
