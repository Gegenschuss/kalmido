#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.891.0 C (#5270, rebuilt from 2.820.0 D and 2.788.0 C; stage Q2 of the cross-section audit #3563): one send decision (core/objnotify.py obj_notify) -- every
recipient is cut with obj_role >= view of the shared core before a News entry or a push. Own container. Invented people only.
freelancer-matrix: tasks
 - News about a task (collab/news.py news_add): the member gets it; a person taken off the project, a person of another
   organisation with a leftover member row and an agent without a share get nothing; a task in the trash reaches only who may
   restore it (regression: task_visible did not look at the trash)
 - watchers (tasks/watchers.py wat_note): a status change reaches the watcher who still reads the task (News + push), not a
   watcher who lost the project, of another organisation, or an agent
 - team chat (collab/teamchat.py tchat_notify): the project's conversation pushes an @mention to the member, not to the
   removed one / the leftover row; a direct message reaches the partner (the pair is the reader of a direct message)
 - task reminders (notify/push.py wd_task_notify): the member yes, the removed person and the other organisation no; the
   watchdog's way without a request (the tick's memo, core/objlight.py _task_tick) answers like obj_role (also the trash)
 - calendar reminders (events/model.py _wd_events, the watchdog): the owner and the member of an organisation's calendar get
   one, a member taken back does not
 - obj_notify knows no fallback: an unknown kind is an error
 - the other task events that checked their people themselves ask it too: a new task (tasks/dependencies.py
   newtask_events), a review (tasks/review.py _notify), an approval decision (team/approvals.py approval_notify), the urgent
   bell (notify/taskbell.py tbl_news), a new error report (integrations/errorreports.py errreport_events): the member yes,
   the removed person, the other organisation's leftover row no
 - a person without an organisation: News and a watcher's News about the own task, the own task reminder and the own
   calendar reminder (the watchdog) arrive
usage: p2891_c_notify_test.py <datadir>      (KMT_NOSTART=1 / P2891C_NOSTART=1: a running server)"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402
from kt import B, CT, check, dbx, done, until  # noqa: E402

FEAT = "cal,collab,comments,events"
kt.fresh(env={"KALMIDO_API_RATE": "100000"}, prefix="P2891C")

import requests  # noqa: E402
s0 = requests.Session()
s0.headers.update(kt.H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab", "events"]})
A = login(B, "alice")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta"})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
U = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})


def person(name, org):
    r = A.post(B + "/api/users", json={"orgs": [{"id": org, "role": "member"}], "username": name, "display_name": name.title(),
                                       "password": "password123", "email": f"{name}@example.com"})
    assert r.ok, r.text
    U[name] = r.json()["id"]
    s = login(B, name)
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT}).ok
    return s


Bo = person("bob", ORG)
person("erin", ORG)
Da = person("dave", ORG)
person("carl", BETA)
FID, Fr = freelancer(B, A)
U["frida"] = FID
r = A.post(B + "/api/my/agents", json={"username": "scout", "display_name": "Scout", "scopes": ["read"]})
check(r.status_code in (200, 201), f"setup: an agent of alice {r.status_code} {r.text[:160]}")
U["scout"] = (r.json() or {}).get("id")

LA = A.post(B + "/api/lists", json={"name": "Shoot plan", "org_id": ORG}).json()["id"]
for n in ("bob", "dave", "erin"):
    check(A.put(B + f"/api/lists/{LA}/members", json={"user_id": U[n], "role": "edit"}).ok, f"setup: {n} in the project")
TA = A.post(B + "/api/tasks", json={"title": "Book the van", "list_id": LA}).json()["id"]
TB = A.post(B + "/api/tasks", json={"title": "Old idea", "list_id": LA}).json()["id"]
check(A.delete(B + f"/api/lists/{LA}/members/{U['dave']}").ok, "setup: dave taken off the project")
check(Da.get(B + f"/api/tasks/{TA}").status_code == 404, "setup: dave no longer reads the task")
dbx("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,?,?)", (LA, U["carl"], "edit", "2026-11-02T08:00:00"))
check(A.delete(B + f"/api/tasks/{TB}").ok, "setup: a task in the trash")

FL = Fr.post(B + "/api/lists", json={"name": "Own work"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Send the invoice", "list_id": FL}).json()["id"]

team = {x.get("list_id"): x for x in A.get(B + "/api/team").json()["rooms"]}
RA = (team.get(LA) or {}).get("id")
r = A.post(B + f"/api/team/rooms/{RA}/messages", json={"body": "Van is booked"})
MA = r.json().get("id") if r.status_code == 201 else None
r = A.post(B + "/api/team/dm", json={"user_id": U["bob"]})
RD = r.json().get("id") if r.ok else None
r = A.post(B + f"/api/team/rooms/{RD}/messages", json={"body": "Lunch?"})
MD = r.json().get("id") if r.status_code == 201 else None
check(bool(RA and MA and RD and MD), "setup: a message in the project's conversation and in a direct message")


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app, json\n" + code],
                       capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    return out[-1] if out else "ERR " + r.stderr[-1200:]


# every case in a transaction that is rolled back: the setup rows, then the call; News = the rows it wrote, pushes = g.pushes
CODE = r"""
from flask import g
from kalmido.core.config import app as fa
from kalmido.core.db import connect, usettings
from kalmido.collab import teamchat as T
from kalmido.collab.news import news_add
from kalmido.tasks.watchers import wat_note
from kalmido.notify.push import wd_task_notify
from kalmido.core.objnotify import obj_notify, obj_readers
from kalmido.tasks.dependencies import newtask_events
from kalmido.tasks import review as RV
from kalmido.team.approvals import approval_notify
from kalmido.notify.taskbell import tbl_news
from kalmido.integrations.errorreports import errreport_events
U, LA, TA, TB, FL, FT, RA, MA, RD, MD = %(ids)s
PEOPLE = ("bob", "dave", "carl", "frida", "alice", "erin")
SETUP = [("INSERT INTO user_settings(user_id,key,value) VALUES(?,'ntfy_topic',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
          (U[n], "t-" + n)) for n in PEOPLE]
SETUP += [("INSERT INTO user_settings(user_id,key,value) VALUES(?,'notify',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
           (U[n], json.dumps({k: {"news": 1, "push": 1} for k in ("complete", "newtask", "review", "assign", "errreport")}))) for n in PEOPLE]
def case(fn, sender, extra=()):
    c = connect()
    try:
        for q, a in SETUP + list(extra):
            c.execute(q, a)
        with fa.test_request_context('/api/x', method='POST'):
            g.user, g.pushes = c.execute("SELECT * FROM users WHERE id=?", (sender,)).fetchone(), []
            n0 = c.execute("SELECT COALESCE(MAX(id),0) FROM notifications").fetchone()[0]
            res = fn(c)
            news = sorted(r[0] for r in c.execute("SELECT user_id FROM notifications WHERE id>?", (n0,)))
            return {"news": news, "push": sorted(p[0] for p in g.pushes), "res": res}
    except Exception as e:
        return {"err": type(e).__name__ + ": " + str(e)[:300]}
    finally:
        c.rollback()
        c.close()
ALL = [U[n] for n in ("bob", "dave", "carl", "scout")]
watch = lambda tid, ids: [("INSERT INTO task_watchers(task_id,user_id,created_at) VALUES(?,?,'2026-11-09T08:00:00') ON CONFLICT DO NOTHING",
                           (tid, u)) for u in ids]
def room(c, rid, mid, ment):
    r = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (rid,)).fetchone()
    m = c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone()
    T.tchat_notify(c, r, m, ment)
def remind(c, tid, lid, who):
    t = {"id": tid, "list_id": lid}
    return sorted(u for u in who if wd_task_notify(c, t, u, usettings(c, u), "reminder", None))
def unknown(c):
    try:
        obj_notify(c, "no_such_kind", 1, [U["bob"]], row="chat")
        return "no error"
    except ValueError:
        return "ValueError"
out = {}
out["news"] = case(lambda c: [news_add(c, u, "comment", task_id=TA) for u in ALL], U["alice"])
out["news_trash"] = case(lambda c: [news_add(c, u, "comment", task_id=TB) for u in ALL + [U["erin"], U["alice"]]], U["bob"])
out["watch"] = case(lambda c: wat_note(c, TA, "wont", U["alice"]), U["alice"], watch(TA, ALL))
out["chat_list"] = case(lambda c: room(c, RA, MA, [U["bob"], U["dave"], U["carl"]]), U["alice"])
out["chat_dm"] = case(lambda c: room(c, RD, MD, []), U["alice"])
out["remind"] = case(lambda c: remind(c, TA, LA, ALL), U["alice"])
out["readers_agent"] = case(lambda c: sorted(obj_readers(c, "task", TA, [U["scout"], U["bob"]])), U["alice"],
                            [("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,'view','2026-11-09T08:00:00') ON CONFLICT DO NOTHING", (LA, U["scout"]))])
out["unknown"] = case(unknown, U["alice"])
# 2.891.0 (#5270, review of the first build): the News entry belongs to the checked object; the tick's rule refuses an agent on its own
def mismatch(c):
    try:
        obj_notify(c, "task", TA, [U["bob"]], row="comment", push=False, news={"kind": "comment", "task_id": TB})
        return "no error"
    except ValueError:
        return "ValueError"
out["mismatch"] = case(mismatch, U["alice"])
def tick_agent(c):
    from kalmido.core.objlight import _task_tick
    return [_task_tick(c, U["scout"], TA, {}), _task_tick(c, U["bob"], TA, {})]
out["tick_agent"] = case(tick_agent, U["alice"],
                         [("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,'view','2026-11-09T08:00:00') ON CONFLICT DO NOTHING", (LA, U["scout"]))])
# 2.891.0: the other task events (their own task_visible / collab_user checks are gone)
trow = lambda c, tid: c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
out["newtask"] = case(lambda c: newtask_events(c, TA), U["alice"])
out["review"] = case(lambda c: [RV._notify(c, trow(c, TA), u, "pending", "look") for u in ALL], U["alice"])
out["apdecide"] = case(lambda c: [approval_notify(c, trow(c, TA), "approved", "ok", u) for u in ALL], U["alice"])
out["urgent"] = case(lambda c: tbl_news(c, TA, LA, ALL, None), U["alice"])
out["errreport"] = case(lambda c: errreport_events(c, TA, LA, {"title": "Crash on save", "level": "error"}), U["alice"])
# a person without an organisation: News about the own task, the watcher's News, the own reminder
out["fr_news"] = case(lambda c: news_add(c, U["frida"], "comment", task_id=FT), U["alice"])
out["fr_watch"] = case(lambda c: wat_note(c, FT, "wont", U["alice"]), U["alice"], watch(FT, [U["frida"]]))
out["fr_remind"] = case(lambda c: remind(c, FT, FL, [U["frida"], U["bob"]]), U["alice"])
# the watchdog's way (no request, the tick's memo: core/objlight.py _task_tick) gives the same answers as obj_role
def tick():
    c = connect()
    try:
        for q, a in SETUP:
            c.execute(q, a)
        memo = {}
        who = ALL + [U["erin"], U["alice"]]
        return {"TA": sorted(u for u in who if wd_task_notify(c, {"id": TA, "list_id": LA}, u, usettings(c, u), "reminder", None, memo)),
                "TB": sorted(u for u in who if wd_task_notify(c, {"id": TB, "list_id": LA}, u, usettings(c, u), "reminder", None, memo)),
                "FT": sorted(u for u in [U["frida"], U["bob"]] if wd_task_notify(c, {"id": FT, "list_id": FL}, u, usettings(c, u), "reminder", None, memo))}
    except Exception as e:
        return {"err": type(e).__name__ + ": " + str(e)[:300]}
    finally:
        c.rollback()
        c.close()
out["tick"] = tick()
print(json.dumps(out))
""" % {"ids": json.dumps([U, LA, TA, TB, FL, FT, RA, MA, RD, MD])}

raw = in_app(CODE)
try:
    res = json.loads(raw)
except ValueError:
    res = None
    check(False, f"the cases ran inside the app: {raw[:900]}")
if res:
    for k, v in res.items():
        if "err" in v:
            check(False, f"case {k}: {v['err']}")
    bob, dave, carl, scout, alice, frida, erin = (U[n] for n in ("bob", "dave", "carl", "scout", "alice", "frida", "erin"))

    def g_(k, f):
        return (res.get(k) or {}).get(f)

    check(g_("news", "news") == [bob], f"News about a task: only bob (dave taken off, carl of Beta with a leftover row, the agent: nothing) {res.get('news')}")
    check(g_("news_trash", "news") == [alice],
          f"a task in the trash: only alice, who may restore it -- not erin, an editor (regression: task_visible ignored the trash) {res.get('news_trash')}")
    check(g_("watch", "news") == [bob] and g_("watch", "push") == [bob],
          f"watchers: the status change reaches bob as News and push, not dave / carl / the agent {res.get('watch')}")
    check(g_("chat_list", "push") == [bob], f"the project's conversation: the @mention pushes bob only {res.get('chat_list')}")
    check(g_("chat_dm", "push") == [bob], f"a direct message reaches the partner (the pair reads it) {res.get('chat_dm')}")
    check(g_("remind", "res") == [bob], f"task reminder: bob yes, dave / carl / the agent no {res.get('remind')}")
    check(g_("readers_agent", "res") == [bob], f"an agent is never a recipient of obj_notify (it gets events) {res.get('readers_agent')}")
    check(g_("unknown", "res") == "ValueError", f"obj_notify: an unknown kind is an error, no fallback {res.get('unknown')}")
    check(g_("mismatch", "res") == "ValueError" and g_("mismatch", "news") == [], f"obj_notify: a News entry about another task than the checked one is an error {res.get('mismatch')}")
    check(g_("tick_agent", "res") == [False, True], f"the tick's task rule: an agent with a project role never, bob yes {res.get('tick_agent')}")
    check(g_("fr_news", "news") == [frida], f"person without an organisation: News about the own task {res.get('fr_news')}")
    check(g_("fr_watch", "news") == [frida] and g_("fr_watch", "push") == [frida],
          f"person without an organisation: the watcher's News and push {res.get('fr_watch')}")
    check(g_("fr_remind", "res") == [frida], f"person without an organisation: the own task reminder (bob: no) {res.get('fr_remind')}")

    # 2.891.0: the other task events -- carl's leftover row (another organisation) and dave (taken off) hear nothing
    check(g_("newtask", "news") == sorted([bob, erin]) and g_("newtask", "push") == sorted([bob, erin]),
          f"a new task: News + push for bob and erin, not carl (leftover row of Beta) {res.get('newtask')}")
    check(g_("review", "news") == [bob] and g_("review", "push") == [bob], f"a review: only bob {res.get('review')}")
    check(g_("apdecide", "news") == [bob] and g_("apdecide", "push") == [bob], f"an approval decision: only bob {res.get('apdecide')}")
    check(g_("urgent", "news") == [bob] and g_("urgent", "push") == [bob], f"the urgent bell: only bob {res.get('urgent')}")
    check(g_("errreport", "news") == sorted([bob, erin]), f"a new error report: bob and erin, not carl {res.get('errreport')}")

    tk = res.get("tick") or {}
    check(tk.get("TA") == sorted([bob, erin, alice]) and tk.get("TB") == [alice] and tk.get("FT") == [frida],
          f"task reminders in the watchdog's way (no request, the tick's memo): the same readers as obj_role -- the members and "
          f"the owner, not dave / carl / the agent; a task in the trash only alice; frida her own {tk}")

# ---------------------------------------------------------------- calendar reminders through the watchdog
st = (datetime.now(timezone.utc) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M")
en = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M")
KA = A.post(B + "/api/evcals", json={"name": "Crew rota", "org_id": ORG}).json().get("id")
for n in ("bob", "dave"):
    check(A.put(B + f"/api/evcals/{KA}/members", json={"user_id": U[n], "role": "view"}).ok, f"setup: the calendar shared with {n}")
check(A.delete(B + f"/api/evcals/{KA}/members/{U['dave']}").ok, "setup: dave's share taken back")
r = A.post(B + "/api/events", json={"cal_id": KA, "title": "Load-in", "start": st, "end": en, "reminders": [1440]})
check(r.ok, f"setup: an event with a due reminder {r.text[:160]}")
EV = (r.json() or {}).get("id")
KF = Fr.post(B + "/api/evcals", json={"name": "Frida's days", "org_id": None}).json().get("id")
r = Fr.post(B + "/api/events", json={"cal_id": KF, "title": "Dentist", "start": st, "end": en, "reminders": [1440]})
check(r.ok, f"setup: frida's own event with a due reminder {r.text[:160]}")
EF = (r.json() or {}).get("id")


def seen(eid, u):
    return dbx("SELECT 1 FROM ev_reminded WHERE event_id=? AND user_id=?", (eid, u))


check(bool(until(lambda: seen(EV, U["bob"]), 30)), "calendar reminder: bob (still shared) gets it -- the watchdog ran")
check(bool(until(lambda: seen(EV, U["alice"]), 10)), "calendar reminder: alice, the owner")
check(not seen(EV, U["dave"]), "calendar reminder: none for dave, whose share was taken back")
check(bool(until(lambda: seen(EF, FID), 30)), "person without an organisation: the own calendar reminder")

sys.exit(done("p2891_c_notify"))
