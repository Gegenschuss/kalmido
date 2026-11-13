#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.658.0 D (#4193) the background runs: the same results with less load. Own container (start.sh). Invented names only.
freelancer-matrix: own
 - reminders: the tick reads only the columns it uses (no t.*, no notes) and only the due days that can fire now
   (wd_due_window in SQL); a reminder in the window still fires at the same moment - a time of day, an all-day one in
   another person's time zone, the largest offset (366 days before) and the smallest (one day after the due time), a
   repeating task; tasks far outside the window are not even read; a nag of a task long overdue still comes
 - webhooks: after a failed delivery the rest of that webhook waits for the next tick (was: only after a timeout), and the
   batch takes the deliveries in turns over the webhooks: 25 waiting ones of a dead webhook are tried once, a second
   webhook (of a person without an organisation) is still delivered in the same tick
 - git: the poll holds no open database transaction while the provider answers (every call of git_http sees an idle
   connection), and it still stores what came (the linked pull request, polled_at)
 - agents: an event wakes only the long-polls of its agent (own condition per agent); a wake-up without ids wakes all
 - 2.665.0 (#5113) channels: like the webhooks - after a failed send the rest of that channel waits (also for the next
   chn_tick of the same round of chn_loop), the batch takes the messages in turns over the channels: 40 waiting ones of a
   dead channel are tried once, a second channel (of a person without an organisation) is still served, in its order
 - 2.665.0 (#5113) git issue sync push (gsy_push): no open database transaction while the provider answers (every call of
   git_http sees an idle connection), the change and the comment are stored; a failed send stays as the link's state
   (push_err / push_fails / push_due, issue_error) instead of being rolled back; a comment whose POST went out but whose
   answer was not stored (send_at set) is found in the issue's comments and adopted, not sent a second time
usage: p2658_d_background_test.py <datadir>"""
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
import kt  # noqa: E402
from kt import B, CT, check, done  # noqa: E402

HOOK = "http://127.0.0.1:8099"
kt.fresh({"KALMIDO_WEBHOOK_ALLOW_HOSTS": "127.0.0.1:8099", "KALMIDO_WEBHOOK_TICK": "3600",
          "KALMIDO_CHANNEL_TICK": "3600", "KALMIDO_GIT_TICK": "3600"})  # 2.665.0 (#5113): the loops never take the suite's rows
A = kt.setup()
FU, Fr = freelancer(B, A, "fenja")


def py(code):
    """Runs code inside the test container; -> the last JSON line it printed."""
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=300)
    if r.returncode:
        print("PY FAILED:", r.stdout[-2000:], r.stderr[-3000:], flush=True)
    for ln in reversed((r.stdout or "").splitlines()):
        if ln.startswith("{"):
            return json.loads(ln)
    return {}


LID = A.post(B + "/api/lists", json={"name": "Background"}).json()["id"]


def task(title, **kw):
    r = A.post(B + "/api/tasks", json={"title": title, "list_id": LID, **kw})
    check(r.ok, f"setup: task {title} {r.status_code} {r.text[:160]}")
    return r.json().get("id") if r.ok else 0


# ---------------------------------------------------------------- 1. reminders and nags
# All in 2030 (the running watchdog of the container, on the real clock, never fires them).
task("Rem time", due="2030-01-10", due_time="10:00", reminders="15")
task("Rem allday tz", due="2030-05-10", reminders="0")
task("Rem far ahead", due="2031-01-10", due_time="10:00", reminders=str(366 * 1440))
task("Rem after due", due="2030-03-01", due_time="10:00", reminders="-1440")
task("Rem repeat", due="2030-07-01", due_time="08:00", reminders="0", repeat="FREQ=WEEKLY")
task("Rem long past", due="2029-06-01", due_time="10:00", reminders="0")
task("Rem beyond", due="2032-06-01", due_time="10:00", reminders="0")
TN = task("Nag overdue", due="2030-06-01", due_time="10:00")
check(A.patch(B + f"/api/tasks/{TN}", json={"nag": "5"}).ok, "setup: nag every 5 minutes")
REM = r"""
import json, app
from datetime import datetime, timezone
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.notify import push as P
c = connect()
out = {"runs": {}, "sql": [], "keys": []}
class W:
    def __init__(s, c): s.c = c
    def execute(s, sql, *a, **k):
        if "FROM tasks t JOIN lists" in sql:
            out["sql"].append([sql, list(a[0]) if a else []])
        return s.c.execute(sql, *a, **k)
    def __getattr__(s, k): return getattr(s.c, k)
sent = []
P.notify = lambda *a, **k: sent.append(" ".join(str(x) for x in a[:3]))
seen = []
orig = P.wd_rem_maybe
def maybe(t, *a, **k):
    seen.append(t["title"])
    if not out["keys"]:
        out["keys"] = sorted(t.keys())
    return orig(t, *a, **k)
P.wd_rem_maybe = maybe
with system_ctx(c):
    users = {r["id"]: r for r in c.execute("SELECT * FROM users WHERE NOT disabled")}
    S = P._wd_settings(c, users)
    LG = {u: "en" for u in users}
    for u in S:
        S[u] = {**S[u], "tz": "Pacific/Kiritimati"}  # UTC+14, far from the server's clock
    # in the order of time: a later run marks the reminders it finds missed by more than 6 h as fired (as always)
    for name, at in (("far", "2030-01-09T10:01:00+14:00"), ("time", "2030-01-10T09:50:00+14:00"), ("after", "2030-03-02T10:01:00+14:00"),
                     ("tz", "2030-05-10T09:01:00+14:00"), ("repeat", "2030-07-01T08:00:30+14:00"), ("nothing", "2030-08-15T12:00:00+14:00")):
        sent.clear()
        seen.clear()
        P._wd_reminders(W(c), users, S, LG, datetime.fromisoformat(at).astimezone(timezone.utc))
        out["runs"][name] = {"sent": list(sent), "seen": list(seen)}
    sent.clear()
    P._wd_nags(W(c), users, S, LG, datetime(2030, 9, 1, 0, 0, tzinfo=timezone.utc))  # 14:00 on the person's clock, no quiet hours
    out["nag"] = list(sent)
    out["reminded"] = {r[0]: r[1] for r in c.execute("SELECT title, reminded FROM tasks WHERE title LIKE 'Rem %'")}
c.commit()
c.close()
print(json.dumps(out))
"""
j = py(REM)
runs = j.get("runs") or {}


def fired(name, title):
    return any(title in x for x in (runs.get(name) or {}).get("sent", []))


check(j.get("sql") and all("t.*" not in s and "t.notes" not in s and "t.content" not in s for s, _ in j["sql"]),
      f"the reminder / nag ticks no longer read t.* (no notes) {[s[:80] for s, _ in j.get('sql') or []]}")
check(j.get("keys") and "notes" not in j["keys"] and "content" not in j["keys"] and len(j["keys"]) <= 18,
      f"a row holds only the columns used {j.get('keys')}")
check(any(len(p) == 2 and "t.due >= ?" in s for s, p in j.get("sql") or []), "the reminder tick has its time window in SQL")
check(fired("time", "Rem time"), f"a reminder with a time of day (15 min before, the person's clock) fires {runs.get('time')}")
check(fired("tz", "Rem allday tz"), f"an all-day reminder fires at the all-day time of the person's time zone {runs.get('tz')}")
check(fired("far", "Rem far ahead"), f"the largest offset (366 days before) is inside the window {runs.get('far')}")
check(fired("after", "Rem after due"), f"the smallest offset (one day after the due time) is inside the window {runs.get('after')}")
check(fired("repeat", "Rem repeat"), f"a repeating task's reminder fires {runs.get('repeat')}")
check(not any("Rem time" in x for r in ("tz", "after", "repeat", "nothing") for x in runs.get(r, {}).get("sent", [])),
      "a reminder fires once")
allseen = {t for r in runs.values() for t in r.get("seen", [])}
check("Rem long past" not in allseen and "Rem beyond" not in allseen,
      f"tasks far outside the window are not read any more {sorted(allseen)}")
check(not (runs.get("nothing") or {}).get("sent"), f"nothing due: nothing sent {runs.get('nothing')}")
check(any("Nag overdue" in x for x in j.get("nag") or []), f"a nag of a task overdue for months still comes {j.get('nag')}")

# ---------------------------------------------------------------- 2. webhooks: a dead one does not hold up the others
WIDS = []
for name in ("Dead", "Alive"):
    r = Fr.post(B + "/api/me/webhooks", json={"name": name, "url": HOOK + "/" + name.lower(), "events": ["task.created"]})
    check(r.status_code in (200, 201), f"the freelancer's webhook {name} {r.status_code} {r.text[:200]}")
    WIDS.append((r.json() or {}).get("id") if r.ok else 0)
WHT = r"""
import json, time, app
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.integrations import webhooks as WH
DEAD, ALIVE = %d, %d
c = connect()
with system_ctx(c):
    c.execute("DELETE FROM webhook_queue WHERE webhook_id IN (?, ?)", (DEAD, ALIVE))
    t0 = time.time() - 60
    for i in range(25):
        c.execute("INSERT INTO webhook_queue(webhook_id,delivery,event,payload,attempt,next_at,created_at) VALUES(?,?,?,?,0,?,?)",
                  (DEAD, f"d{i}", "ping", "{}", t0 + i * 0.001, "2030-01-01T00:00:00Z"))
    for i in range(2):
        c.execute("INSERT INTO webhook_queue(webhook_id,delivery,event,payload,attempt,next_at,created_at) VALUES(?,?,?,?,0,?,?)",
                  (ALIVE, f"a{i}", "ping", "{}", t0 + 1 + i * 0.001, "2030-01-01T00:00:00Z"))
c.commit()
calls = []
WH.wh_send = lambda url, key, event, delivery, *a: calls.append(delivery) or ((True, 200, 3, "") if url.endswith("/alive") else (False, 500, 3, "status"))
WH.wh_tick()
out = {"calls": calls, "batch": WH.WH_BATCH}
with system_ctx(c):
    out["dead"] = sorted(r[0] for r in c.execute("SELECT attempt FROM webhook_queue WHERE webhook_id=?", (DEAD,)))
    out["alive"] = c.execute("SELECT COUNT(*) FROM webhook_queue WHERE webhook_id=?", (ALIVE,)).fetchone()[0]
c.close()
print(json.dumps(out))
"""
j = py(WHT % (int(WIDS[0] or 0), int(WIDS[1] or 0)))
calls = j.get("calls") or []
dead = [x for x in calls if x.startswith("d")]
check(dead == ["d0"] and (j.get("dead") or []).count(1) == 1 and (j.get("dead") or []).count(0) == 24,
      f"a webhook that failed (an error status, not a timeout) is tried once per tick, the rest waits unchanged ({dead}, batch {j.get('batch')})")
check(sorted(x for x in calls if x.startswith("a")) == ["a0", "a1"] and j.get("alive") == 0,
      f"a second webhook is still delivered in the same tick, though 25 of the dead one wait before it ({calls}, left {j.get('alive')})")
check(calls.index("a0") < calls.index("a1") if "a0" in calls and "a1" in calls else False, "one webhook's deliveries keep their order")

# ---------------------------------------------------------------- 3. git: no open transaction while the provider answers
TG = task("Fix the export")
GIT = r"""
import json, time, app
from kalmido.core.db import connect, insert_id
from kalmido.core.pg import system_ctx
from kalmido.integrations import git as G
LID, TID = %d, %d
c = connect()
with system_ctx(c):
    cid = insert_id(c, "INSERT INTO git_conns(list_id,provider,base_url,owner,repo,default_branch,created_at,next_at,hash_ids) "
                       "VALUES(?,?,?,?,?,?,?,?,1)", (LID, "github", "", "acme", "tool", "main", "2026-01-01T00:00:00Z", time.time() + 86400))
c.commit()
seen = []
def fake(k, path, etag, method, data, until):
    seen.append([path, c.in_transaction])
    if path.endswith("/pulls?state=all&sort=updated&direction=desc&per_page=50") or "/pulls" in path:
        return 200, {}, [{"number": 7, "title": f"Fix #{TID}", "body": "", "state": "open", "user": {"login": "dev"},
                          "html_url": "https://example.com/acme/tool/pull/7", "head": {"ref": "fix", "sha": "abc1234"},
                          "updated_at": "2026-01-02T00:00:00Z", "merged_at": None}]
    return 200, {}, []
G._git_http1 = fake
with system_ctx(c):
    G.git_poll(c, cid)
    c.commit()
    row = c.execute("SELECT polled_at, fails, last_error FROM git_conns WHERE id=?", (cid,)).fetchone()
    link = c.execute("SELECT COUNT(*) FROM git_links WHERE conn_id=? AND task_id=? AND kind='pr'", (cid, TID)).fetchone()[0]
    c.execute("DELETE FROM git_conns WHERE id=?", (cid,))
c.commit()
c.close()
print(json.dumps({"seen": seen, "polled": bool(row["polled_at"]), "fails": row["fails"], "err": row["last_error"], "link": link}))
"""
j = py(GIT % (LID, int(TG or 0)))
seen = j.get("seen") or []
check(len(seen) >= 3 and not any(x[1] for x in seen),
      f"the git poll holds no database transaction while the provider answers ({len(seen)} calls, open at {[x[0] for x in seen if x[1]]})")
check(j.get("polled") and j.get("fails") == 0 and j.get("err") == "" and j.get("link") == 1,
      f"the poll still stores what came: the linked pull request, polled_at ({j})")

# ---------------------------------------------------------------- 5. #5113 channels: a dead one does not hold up the others
CIDS = []
for name in ("Dead", "Alive"):
    r = Fr.post(B + "/api/me/channels", json={"kind": "slack", "name": name, "url": HOOK + "/chn-" + name.lower()})
    check(r.status_code in (200, 201), f"the freelancer's channel {name} {r.status_code} {r.text[:200]}")
    CIDS.append((r.json() or {}).get("id") if r.ok else 0)
CHT = r"""
import json, time, app
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.notify import channels as CH
DEAD, ALIVE = %d, %d
c = connect()
with system_ctx(c):
    c.execute("DELETE FROM notify_channel_queue WHERE channel_id IN (?, ?)", (DEAD, ALIVE))
    t0 = time.time() - 60
    for i in range(40):
        c.execute("INSERT INTO notify_channel_queue(channel_id,text,created_at) VALUES(?,?,?)", (DEAD, f"d{i}", t0 + i * 0.001))
    for i in range(2):
        c.execute("INSERT INTO notify_channel_queue(channel_id,text,created_at) VALUES(?,?,?)", (ALIVE, f"a{i}", t0 + 1 + i * 0.001))
c.commit()
calls = []
CH.chn_send = lambda kind, t, text, allow: calls.append(text) or ((True, 200, "") if text.startswith("a") else (False, 500, "http"))
skip, n = set(), 0
while CH.chn_tick(skip) >= CH.CH_BATCH and n < 5:  # one round of chn_loop
    n += 1
out = {"calls": calls, "batch": CH.CH_BATCH}
with system_ctx(c):
    out["dead"] = [[r[0], r[1] > 0] for r in c.execute("SELECT text, retry_at FROM notify_channel_queue WHERE channel_id=? ORDER BY created_at, id", (DEAD,))]
    out["alive"] = c.execute("SELECT COUNT(*) FROM notify_channel_queue WHERE channel_id=?", (ALIVE,)).fetchone()[0]
    out["fails"] = [c.execute("SELECT fails FROM notify_channels WHERE id=?", (x,)).fetchone()[0] for x in (DEAD, ALIVE)]
    c.execute("DELETE FROM notify_channel_queue WHERE channel_id IN (?, ?)", (DEAD, ALIVE))
c.commit()
c.close()
print(json.dumps(out))
"""
j = py(CHT % (int(CIDS[0] or 0), int(CIDS[1] or 0)))
calls = j.get("calls") or []
dead = j.get("dead") or []
check([x for x in calls if x.startswith("d")] == ["d0"] and len(dead) == 40 and dead[0] == ["d0", True]
      and all(not x[1] for x in dead[1:]) and j.get("fails") == [1, 0],
      f"#5113: a channel that failed (an error status, not a timeout) is tried once per round, the rest waits unchanged "
      f"({[x for x in calls if x.startswith('d')]}, {dead[:3]}..., fails {j.get('fails')}, batch {j.get('batch')})")
check([x for x in calls if x.startswith("a")] == ["a0", "a1"] and j.get("alive") == 0,
      f"#5113: a second channel is still served, in its order, though 40 of the dead one wait before it ({calls}, left {j.get('alive')})")

# ---------------------------------------------------------------- 6. #5113 git issue sync: the push holds no transaction
TP = task("Push me")
# 2.972.0 (#5272): the task comments are rows of the core's obj_comments (kind 'task', ref_id = the task)
GSP = r"""
import json, time, app
from kalmido.core.db import connect, insert_id
from kalmido.core.pg import system_ctx
from kalmido.calendars.subscriptions import CalError
from kalmido.integrations import git as G
from kalmido.integrations import git_sync as GS
LID, TID = %d, %d
c = connect()
with system_ctx(c):
    cid = insert_id(c, "INSERT INTO git_conns(list_id,provider,base_url,owner,repo,default_branch,created_at,next_at,hash_ids,issue_sync,issue_rw) "
                       "VALUES(?,?,?,?,?,?,?,?,1,1,1)", (LID, "github", "", "acme", "push", "main", "2026-01-01T00:00:00Z", time.time() + 86400))
    snap = json.dumps({"title": "Old title", "body": "", "state": "open", "labels": [], "tail": ""})
    c.execute("INSERT INTO git_issue_links(conn_id,issue_no,task_id,created_at,snap,dirty,push_due) VALUES(?,5,?,?,?,?,0)",
              (cid, TID, "2026-01-01T00:00:00Z", snap, json.dumps({"title": "2026-11-08T00:00:00.000Z"})))
    uid = c.execute("SELECT owner_id FROM lists WHERE id=?", (LID,)).fetchone()[0]
    def comment(text):
        mid = insert_id(c, "INSERT INTO obj_comments(kind, ref_id,user_id,body,created_at) VALUES('task', ?,?,?,?)", (TID, uid, text, "2026-11-08T00:00:00Z"))
        return insert_id(c, "INSERT INTO git_issue_comments(conn_id,issue_no,remote_id,comment_id,created_at) VALUES(?,5,NULL,?,?)", (cid, mid, "2026-11-08T00:00:00Z"))
    x1 = comment("First from here")
c.commit()
calls, issue, mode = [], {"number": 5, "title": "Old title", "body": "", "state": "open", "labels": [], "user": {"login": "dev"},
                          "html_url": "https://example.com/acme/push/issues/5", "created_at": "2026-01-01T00:00:00Z",
                          "updated_at": "2026-01-02T00:00:00Z", "comments": 0}, {"fail": False, "remote": []}
def fake(k, path, etag, method, data, until):
    calls.append([method, path, c.in_transaction])
    if method == "GET" and "/issues/5/comments" in path:
        return 200, {}, mode["remote"]
    if method == "GET" and path.endswith("/issues/5"):
        return 200, {}, dict(issue)
    if method == "PATCH":
        if mode["fail"]:
            raise CalError("network")
        issue.update(data)
        return 200, {}, dict(issue, updated_at="2026-11-08T01:00:00Z")
    if method == "POST" and path.endswith("/issues/5/comments"):
        return 201, {}, {"id": 9001 + len([x for x in calls if x[0] == "POST"])}
    raise CalError("not_found")
G._git_http1 = fake
def push():
    with system_ctx(c):
        c.execute("UPDATE git_issue_links SET push_due=1 WHERE conn_id=?", (cid,))
        c.commit()
        GS.gsy_push(c)
        c.commit()
def state():
    with system_ctx(c):
        L = c.execute("SELECT snap, push_due, push_err, push_fails FROM git_issue_links WHERE conn_id=?", (cid,)).fetchone()
        k = c.execute("SELECT issue_error FROM git_conns WHERE id=?", (cid,)).fetchone()
        cm = [list(r) for r in c.execute("SELECT id, remote_id, send_at<>'' FROM git_issue_comments WHERE conn_id=? ORDER BY id", (cid,))]
        c.commit()
    return {"title": json.loads(L["snap"]).get("title"), "due": L["push_due"], "err": L["push_err"], "fails": L["push_fails"],
            "ierr": k["issue_error"], "cm": cm, "now": time.time()}
out = {}
push()
out["ok"] = {"calls": calls[:], "state": state()}
# a failed send: the state is stored, nothing rolled back
del calls[:]
with system_ctx(c):
    c.execute("UPDATE tasks SET title='Push again' WHERE id=?", (TID,))
    x2 = comment("Second from here")
c.commit()
mode["fail"] = True
push()
out["fail"] = {"calls": calls[:], "state": state()}
# the comment's POST went out earlier but its answer was not stored: found in the repository, not sent again
del calls[:]
mode["fail"] = False
with system_ctx(c):
    c.execute("UPDATE git_issue_comments SET send_at=? WHERE id=?", ("2026-11-08T00:00:00Z", x2))
    row = c.execute("SELECT m.body, m.user_id FROM git_issue_comments x JOIN obj_comments m ON m.id=x.comment_id WHERE x.id=?", (x2,)).fetchone()
    text = GS._comment_text(c, row)
c.commit()
mode["remote"] = [{"id": 9500, "user": {"login": "dev"}, "body": text, "created_at": "2026-11-08T00:00:30Z"}]
push()
out["again"] = {"calls": calls[:], "state": state()}
# 2.665.0 (#5113 review M1): the provider is too slow to read the comments since the mark completely: unsure, nothing posted
del calls[:]
with system_ctx(c):
    x3 = comment("Third from here")
    c.execute("UPDATE git_issue_comments SET send_at=? WHERE id=?", ("2026-11-08T00:00:00Z", x3))
c.commit()
mode["remote"] = []
GS.GSY_ROUND_S = -1
push()
GS.GSY_ROUND_S = 60
out["slow"] = {"calls": calls[:], "state": state()}
with system_ctx(c):
    c.execute("DELETE FROM git_conns WHERE id=?", (cid,))
c.commit()
c.close()
print(json.dumps(out))
"""
j = py(GSP % (LID, int(TP or 0)))
ok, fail, again = j.get("ok") or {}, j.get("fail") or {}, j.get("again") or {}
allc = (ok.get("calls") or []) + (fail.get("calls") or []) + (again.get("calls") or [])
check(len(allc) >= 6 and not any(x[2] for x in allc),
      f"#5113: the git push holds no database transaction while the provider answers ({len(allc)} calls, open at "
      f"{[x[:2] for x in allc if x[2]]})")
st = ok.get("state") or {}
check([x[0] for x in ok.get("calls") or []] == ["GET", "PATCH", "POST"] and st.get("title") == "Push me" and st.get("due") == 0
      and [x[1] for x in st.get("cm") or []] == [9002],
      f"#5113: the push still sends and stores the change and the comment ({ok})")
st = fail.get("state") or {}
check(st.get("err") == "network" and st.get("fails") == 1 and (st.get("due") or 0) > (st.get("now") or 0) and st.get("ierr") == "network"
      and [x[1] for x in st.get("cm") or []] == [9002, None],
      f"#5113: a failed send stays as the link's state (push_err, push_fails, push_due later, issue_error), the comment waits ({st})")
st = again.get("state") or {}
posts = [x for x in again.get("calls") or [] if x[0] == "POST"]
check(not posts and [x[1] for x in st.get("cm") or []] == [9002, 9500] and st.get("title") == "Push again" and st.get("due") == 0,
      f"#5113: a comment sent before whose answer was not stored is found and adopted, never posted twice ({again})")
slow = j.get("slow") or {}
st = slow.get("state") or {}
check(not [x for x in slow.get("calls") or [] if x[0] == "POST"] and (st.get("cm") or [[0, 0]])[-1][1] is None,
      f"#5113 review M1: comments not read completely in time: the marked comment is not posted again ({slow})")

# ---------------------------------------------------------------- 4. agents: an event wakes only its agent's long-polls
AG = r"""
import json, threading, time, app
from kalmido.agents import core as AC, api as AA
out = {}
AA._waiter(901, True)
AA._waiter(902, True)
woke = {}
def wait(aid):
    t0 = time.monotonic()
    with AC._AGENT_COND:
        gen = (AC._AGENT_GEN[0], AC._AGENT_GENS.get(aid, 0))
        while (AC._AGENT_GEN[0], AC._AGENT_GENS.get(aid, 0)) == gen and time.monotonic() - t0 < 3:
            AC._AGENT_CONDS[aid].wait(3 - (time.monotonic() - t0))
    woke[aid] = round(time.monotonic() - t0, 2)
ts = [threading.Thread(target=wait, args=(a,)) for a in (901, 902)]
for t in ts:
    t.start()
time.sleep(0.3)
g0 = AC._AGENT_GEN[0]
AC.agent_notify(aids=[901])
ts[0].join(5)
out["gens"] = [AC._AGENT_GENS.get(901), AC._AGENT_GENS.get(902), AC._AGENT_GEN[0] - g0]
ts[1].join(5)
out["woke"] = woke
AC.agent_notify()
out["all"] = AC._AGENT_GEN[0] - g0
AA._waiter(901, False)
AA._waiter(902, False)
out["left"] = [901 in AC._AGENT_CONDS, 902 in AC._AGENT_CONDS]
out["ids"] = [AC.agent_wake_ids([3, 4]), AC.agent_wake_ids(None), AC.agent_wake_ids(["x"]), AC.agent_wake_ids([True])]
print(json.dumps(out))
"""
j = py(AG)
w = j.get("woke") or {}
check(j.get("gens") == [1, 0, 0], f"an event of agent 901 counts only for 901 ({j.get('gens')})")
check(w.get("901", 9) < 1.5 and w.get("902", 0) >= 2.5, f"only agent 901's long-poll wakes up, 902's waits on ({w})")
check(j.get("all") == 1, "a wake-up without ids still wakes all")
check(j.get("left") == [False, False], "the condition of an agent goes with its last waiter")
check(j.get("ids") == [[3, 4], None, None, None], f"agent_wake_ids: only a list of ints, else all ({j.get('ids')})")

sys.exit(done("p2658_d_background"))
