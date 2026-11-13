#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.674.0 API test, part B (#4194): agents_for, the job list and news_items check in batches, with the same answers.
Invented names only.
freelancer-matrix: agents, tasks
 - old against new in the app (same database, same request): agents_for = agent_public + agent_shares one by one,
   prop_agents, job_visible row by row = jobs_seen, job_dict / job_may_act one by one = the job list's batch
   (without the log), tasks_visible = task_visible per task (full and not); for an organisation member (bob), a read-only
   member without shares (carol, a participant in one list), a person without an organisation (frida), the admin (alice)
   and an agent (ada)
 - statements (counted in the app): agents_for no longer asks 15-25 queries per agent; the job list does not grow with
   the number of jobs; GET /api/news does not grow with the number of items and computes the feed once
 - GET /api/agents/jobs: an older own job of frida is listed behind 600 newer foreign jobs (the old list read the 500
   newest of the instance and filtered them); the list carries log_last / has_log, not the log; ?id= carries the log
 - GET /api/news: the same items for bob and carol as expected (hidden task, participant), filter=me = the To-me kinds
 - GET /api/sheets (sh_index): the attached sheets of visible lists only (list_roles instead of list_role per list)
usage: p2674_b_api_test.py <datadir>      (a fresh container; P2674B_NOSTART=1 = the server already runs)"""
import json
import os
import re
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, CT, check, sess  # noqa: E402

TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')
TS = "2026-10-20T10:00:00+00:00"

kt.fresh(prefix="P2674B")
A = kt.setup()
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": kt.PASSWORD,
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
kt.dbx("UPDATE org_members SET role='readonly' WHERE org_id=? AND user_id=?", (ORG, uid["carol"]))
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})
FID, Fr = freelancer(B, A)  # freelancer-matrix: agents, tasks
uid["frida"] = FID


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app, json\n" + code],
                       capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    return out[-1] if out else "ERR " + r.stderr[-1500:]


def mklist(s, name, **kw):
    r = s.post(B + "/api/lists", json={"name": name, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def mktask(s, lid, title):
    r = s.post(B + "/api/tasks", json={"list_id": lid, "title": title})
    assert r.ok, r.text
    return r.json()["id"]


def member(lid, who, role="edit"):
    kt.dbx("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING", (lid, who, role, TS))


def agent(name, owner=None):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": name, "display_name": name.title(),
                                              **({"owner_id": owner} if owner else {})})
    assert r.ok, r.text
    return (r.json().get("agent") or r.json()).get("id") or r.json().get("user_id")


def job(aid, title, state="done", task=None, user=None, at=TS, log="", **kw):
    cols = ["agent_id", "task_id", "user_id", "title", "state", "log", "created_at", "updated_at", *kw]
    return kt.dbx(f"INSERT INTO agent_jobs({','.join(cols)}) VALUES({','.join('?' * len(cols))}) RETURNING id",
                  (aid, task, user, title, state, log, at, at, *kw.values()))[0][0]


# ================================================================ setup
STUDIO = mklist(Bo, "Studio")                       # bob's own list, shared with the agents ada and cleo
ORGL = mklist(Bo, "Org board", org_id=ORG)          # an organisation list everyone in Alpha reads
PART = mklist(Bo, "Casting")                        # carol only a participant
FRL = mklist(Fr, "Frida's cuts")                    # frida's own list, shared with ada
kt.dbx("UPDATE lists SET org_visibility='org' WHERE id=?", (ORGL,))
T1, T2 = mktask(Bo, STUDIO, "Grade reel"), mktask(Bo, ORGL, "Plan shoot")
T4a, T4b = mktask(Bo, PART, "Carol's scene"), mktask(Bo, PART, "Someone else's scene")
T3 = mktask(Fr, FRL, "Frida's edit")
member(PART, uid["carol"], "participant")
kt.dbx("UPDATE tasks SET assignee_id=? WHERE id=?", (uid["carol"], T4a))
ADA, CLEO = agent("ada"), agent("cleo")
BEA = agent("bea", owner=uid["bob"])                # bob's personal agent
for lid in (STUDIO, ORGL, PART):
    member(lid, ADA)
member(STUDIO, CLEO)
member(FRL, ADA)
member(STUDIO, BEA)
uid["ada"] = ADA
check(all(isinstance(x, int) for x in (ADA, CLEO, BEA)), f"setup: three agents {ADA} {CLEO} {BEA}")

# jobs of every kind of visibility; a chain (continue_of), part jobs (parent_id) and a job of several tasks
J = {}
J["t1"] = job(ADA, "Grade the reel", "running", T1, uid["bob"], log="start\nhalf way\nnearly done")
J["t2"] = job(ADA, "Shoot plan", "waiting", T2, uid["alice"], approval="1")
J["t3"] = job(ADA, "Frida cut", "done", T3, uid["frida"], log="cut ready")
J["t4a"] = job(ADA, "Carol scene", "done", T4a, None)
J["t4b"] = job(ADA, "Other scene", "done", T4b, None)
J["none"] = job(CLEO, "No task", "done", None, uid["carol"])
J["bea"] = job(BEA, "Personal", "running", None, uid["bob"])
J["cont"] = job(ADA, "Grade part 2", "done", T1, uid["bob"], continue_of=J["t1"])
J["part1"] = job(ADA, "Part one", "running", T2, None, parent_id=J["t2"])
J["part2"] = job(ADA, "Part two", "done", T3, None, parent_id=J["t2"])
kt.dbx("INSERT INTO agent_job_tasks(job_id, task_id, pos) VALUES(?,?,0), (?,?,1), (?,?,2)", (J["t1"], T1, J["t1"], T3, J["t1"], T2))
# unread chat + an open approval card of ada to bob
kt.dbx("INSERT INTO agent_chat(agent_id,user_id,sender,body,created_at) VALUES(?,?,'agent','hello',?), (?,?,'agent','again',?)",
       (ADA, uid["bob"], TS, ADA, uid["bob"], TS))
kt.dbx("UPDATE agents SET status_task=? WHERE user_id=?", (T4b, ADA))  # a status task carol must not see

PROBE = r"""
from flask import g
from kalmido.core.config import app as kapp
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx, rt_begin, rt_end
from kalmido.core.access import task_visible, tasks_visible
from kalmido.agents.core import (agent_public, agent_shares, agents_for, job_dict, job_may_act, job_visible, jobs_seen,
                                 job_vis_sql, jl_cols, agent_is_ai)
from kalmido.agents.proposals import prop_agents, prop_agent_ok
from kalmido.agents.chat import ag_jobs_out
from kalmido.accounts.pictures import avatar_url
from kalmido.agents.usage import usage_block
from kalmido.agents.core import agent_online
UID = WHO
TIME = ("contact_age", "poll_age", "typing", "online", "status_at", "pending_age")  # 2.826.0 (#5509): pending_age counts seconds too
res = {}
c = connect()


def ctx():
    t = kapp.test_request_context('/api/agents', method='GET')
    t.push()
    g.user = dict(c.execute('SELECT * FROM users WHERE id=?', (UID,)).fetchone())
    return t


def counted(fn):
    t = ctx()
    rt_begin()
    try:
        out = fn()
    finally:
        n = rt_end()[0]
        t.pop()
    return out, n


def strip(xs):
    return [{k: v for k, v in x.items() if k not in TIME} for x in xs]


def old_agents():
    rows = c.execute("SELECT a.*, u.username, u.display_name, u.avatar, u.disabled FROM agents a JOIN users u ON u.id=a.user_id "
                     "WHERE u.kind='agent' ORDER BY u.id").fetchall()
    # 2.777.0 (#5378): + a team agent of an organisation the person is a member / admin of, also without a shared list ("shared":
    # false, "projects", nothing of its work) - written out as plain SQL here, not with agents_for's helpers
    me_ = c.execute("SELECT kind FROM users WHERE id=?", (UID,)).fetchone()
    orgs = set() if (me_["kind"] or "user") == "agent" else {r[0] for r in c.execute(
        "SELECT m.org_id FROM org_members m JOIN orgs o ON o.id=m.org_id WHERE m.user_id=? AND m.role IN ('admin','member') AND o.retired_at IS NULL", (UID,))}
    out = []
    for a in rows:
        sh = agent_shares(c, a["user_id"], UID)
        if not sh and not (a["owner_id"] is None and a["org_id"] in orgs):
            continue
        d = agent_public(c, a, UID)
        if a["owner_id"] is None:
            d["shared"] = sh
            d["projects"] = c.execute("SELECT COUNT(*) FROM list_members m JOIN lists l ON l.id=m.list_id WHERE m.user_id=? AND NOT l.is_inbox "
                                      "AND l.deleted_at IS NULL AND l.owner_id<>?", (a["user_id"], a["user_id"])).fetchone()[0]
            if not sh:
                # 2.777.0 (#5378, review F3): nothing of its work, host, model, rights mode, usage, costs or contact times either
                d.update(shared=False, status="idle", status_text="", status_at=None, status_key="", status_key_at="", status_task=None,
                         paused=False, pause_reason="", job_tasks=[], running=0, waiting=0, my_job=False, typing=0, limit_reached=False,
                         last_poll_at=None, poll_age=None, contact_age=None, pending_age=None, no_service=False, host=None, runtime_model="",
                         model_split=False,  # 2.992.0 (#5684): the model per run is not shown either
                         permission_mode="", may_set_mode=False, quota=None, cost=None, flows=None, approvals_open=0)
        out.append(d)
    return out


def old_prop():
    rows = c.execute("SELECT a.*, u.username, u.display_name, u.avatar, u.disabled FROM agents a JOIN users u ON u.id=a.user_id "
                     "WHERE u.kind='agent' ORDER BY u.id").fetchall()
    return [{"id": a["user_id"], "name": a["display_name"] or a["username"],
             "avatar": avatar_url(c.execute("SELECT * FROM users WHERE id=?", (a["user_id"],)).fetchone()),
             "limit_reached": bool(usage_block(c, a["user_id"])), "online": agent_online(a) is not False}
            for a in rows if prop_agent_ok(c, a, UID)]


def old_jobs_out(rows):
    return [{**job_dict(c, j), "can_act": job_may_act(c, j, UID, "approve"), "can_stop": job_may_act(c, j, UID, "stop")} for j in rows]


with system_ctx(c):
    oa, res["n_agents_old"] = counted(old_agents)
    na, res["n_agents_new"] = counted(lambda: agents_for(c, UID))
    res["agents_same"] = strip(oa) == strip(na)
    res["agents"] = [x["id"] for x in na]
    res["agents_diff"] = [[a, b] for a, b in zip(strip(oa), strip(na)) if a != b][:1] or ([len(oa), len(na)] if len(oa) != len(na) else [])
    res["agents_detail"] = {str(x["id"]): {"running": x["running"], "waiting": x["waiting"], "job_tasks": x["job_tasks"],
                                           "chat_unread": x["chat_unread"], "status_task": x["status_task"]} for x in na}
    op, _ = counted(old_prop)
    np_, _ = counted(lambda: prop_agents(c, UID))
    res["prop_same"] = op == np_
    res["prop"] = [x["id"] for x in np_]
    allj = c.execute("SELECT * FROM agent_jobs ORDER BY id").fetchall()
    t = ctx()
    old = {j["id"] for j in allj if job_visible(c, j, UID)}
    t.pop()
    t = ctx()
    new = jobs_seen(c, allj, UID)
    vc, va = job_vis_sql(c, UID)
    pre = {r[0] for r in c.execute("SELECT id FROM agent_jobs WHERE " + vc, va)}
    t.pop()
    res["jobs_same"] = old == new
    res["jobs_superset"] = old <= pre
    res["jobs"] = sorted(new)
    vis = [j for j in allj if j["id"] in old]
    o, n_old = counted(lambda: old_jobs_out(vis))
    lst = c.execute(f"SELECT {jl_cols(c)} FROM agent_jobs WHERE id = ANY(CAST(? AS BIGINT[])) ORDER BY id",
                    ("{" + ",".join(str(j["id"]) for j in vis) + "}",)).fetchall()
    nw, n_new = counted(lambda: ag_jobs_out(c, lst))
    LOG = ("log", "log_last", "has_log", "steps")
    res["jobdict_same"] = [{k: v for k, v in x.items() if k not in LOG} for x in o] == [{k: v for k, v in x.items() if k not in LOG} for x in nw]
    res["jobdict_diff"] = [[a, b] for a, b in zip(o, nw) if {k: v for k, v in a.items() if k not in LOG} != {k: v for k, v in b.items() if k not in LOG}][:1]
    res["log_last"] = {str(x["id"]): [x.get("log"), x.get("log_last"), x.get("has_log")] for x in nw}
    res["n_jobs_old"], res["n_jobs_new"], res["n_jobs_rows"] = n_old, n_new, len(vis)
    tids = [r[0] for r in c.execute("SELECT id FROM tasks ORDER BY id")]
    t = ctx()
    tv_old = {x for x in tids if task_visible(c, x, UID, full=True)}
    tv_old_r = {x for x in tids if task_visible(c, x, UID)}
    t.pop()
    t = ctx()
    res["tasks_same"] = tv_old == tasks_visible(c, tids, UID, full=True) and tv_old_r == tasks_visible(c, tids, UID)
    t.pop()
    # outside a GET (no request cache, the data lock asked in one query)
    t = kapp.test_request_context('/api/x', method='POST')
    t.push()
    g.user = dict(c.execute('SELECT * FROM users WHERE id=?', (UID,)).fetchone())
    res["tasks_same_post"] = tv_old == tasks_visible(c, tids, UID, full=True)
    res["jobs_same_post"] = old == jobs_seen(c, allj, UID)
    t.pop()
c.close()
print(json.dumps(res))
"""


def probe(who):
    out = in_app(PROBE.replace("WHO", str(uid[who])))
    try:
        return json.loads(out)
    except ValueError:
        check(False, f"in-app comparison for {who} ran: {out[:1500]}")
        return {}


EXPECT_JOBS = {  # job_visible's answers, written out (a reference that does not run the app)
    "bob": {J[k] for k in ("t1", "t2", "t4a", "t4b", "bea", "cont", "part1")},
    "carol": {J["t2"], J["t4a"], J["none"], J["part1"]},
    "frida": {J["t3"], J["part2"]},
    "ada": {J[k] for k in ("t1", "t2", "t3", "t4a", "t4b", "cont", "part1", "part2")},
}
# alice (instance admin, no list shared with an agent): her own job, the organisation board's jobs if she is in Alpha, nothing else
P = {}
for who in ("bob", "carol", "frida", "alice", "ada"):
    p = P[who] = probe(who)
    if not p:
        continue
    exp_ok = set(p["jobs"]) == EXPECT_JOBS[who] if who in EXPECT_JOBS else \
        J["t2"] in p["jobs"] and not set(p["jobs"]) & {J[k] for k in ("t1", "t3", "t4a", "t4b", "bea", "cont", "none")}
    check(p["jobs_same"] and p["jobs_same_post"] and exp_ok,
          f"#4194 {who}: jobs_seen = job_visible row by row (GET and POST) {p['jobs']} / expected {sorted(EXPECT_JOBS.get(who, []))}")
    check(p["jobs_superset"], f"#4194 {who}: the SQL pre-filter of the job list keeps every visible job")
    check(p["jobdict_same"], f"#4194 {who}: the job list's batch = job_dict / job_may_act one by one {str(p['jobdict_diff'])[:900]}")
    check(p["tasks_same"] and p["tasks_same_post"], f"#4194 {who}: tasks_visible = task_visible per task (full and not, GET and POST)")
    check(p["agents_same"], f"#4194 {who}: agents_for = agent_public + agent_shares one by one {str(p['agents_diff'])[:900]}")
    check(p["prop_same"], f"#4194 {who}: prop_agents = prop_agent_ok one by one {p['prop']}")
if P.get("bob"):
    p = P["bob"]
    check(p["agents"] == [ADA, CLEO, BEA], f"#4194 bob reaches ada, cleo and his own bea {p['agents']}")
    d = p["agents_detail"].get(str(ADA), {})
    check(d.get("running") == 2 and d.get("waiting") == 1 and d.get("job_tasks") == sorted([T1, T2]) and d.get("chat_unread") == 2
          and d.get("status_task") == T4b, f"#4194 ada for bob: jobs, unread chat, status task {d}")
    check(p["log_last"].get(str(J["t1"])) == [None, "nearly done", True] and p["log_last"].get(str(J["t2"])) == [None, "", False],
          f"#4194 the list carries the log's last line, not the log {p['log_last']}")
    check(p["n_agents_old"] > 0 and p["n_agents_new"] < p["n_agents_old"],
          f"PERF agents_for for bob: {p['n_agents_new']} statements (one by one: {p['n_agents_old']})")
    check(p["n_jobs_new"] < p["n_jobs_old"], f"PERF job list of {p['n_jobs_rows']} jobs for bob: {p['n_jobs_new']} statements (one by one: {p['n_jobs_old']})")
for who, p in P.items():
    if p:
        print(f"PERF {who}: agents_for {p['n_agents_old']} -> {p['n_agents_new']} statements, job list of {p['n_jobs_rows']} jobs "
              f"{p['n_jobs_old']} -> {p['n_jobs_new']}", flush=True)
if P.get("carol"):
    p = P["carol"]
    check(p["agents"] == [], f"#4194 carol (read-only, no own list) reaches no agent {p['agents']}")
if P.get("frida"):
    check(P["frida"]["agents"] == [ADA], f"#4194 frida reaches ada through her own list {P['frida']['agents']}")

# ================================================================ statements: more agents, more jobs, more news
n0 = nstmt(Bo.get(B + "/api/agents"))
for i in range(6):
    a = agent(f"extra{i}x")
    member(STUDIO, a)
    for k in range(3):
        job(a, f"Extra {i}.{k}", "running", T1, uid["bob"])
r = Bo.get(B + "/api/agents")
n1 = nstmt(r)
check(r.ok and len(r.json()["agents"]) == 9, f"setup: bob reaches 9 agents {len(r.json().get('agents', []))}")
check(0 < n1 <= n0 + 6 * 2, f"#4194 GET /api/agents: 3 -> 9 agents costs {n0} -> {n1} statements (at most 2 more per agent; one by one 15-25)")

r = Bo.get(B + "/api/agents/jobs")
m0 = nstmt(r)
c0 = len(r.json()["jobs"])
MORE_T2 = set()
for k in range(40):  # half his own, half alice's on the organisation board (bob sees them through the task)
    x = job(ADA, f"More {k}", "done", T1 if k % 2 else T2, uid["bob"] if k % 2 else uid["alice"])
    if not k % 2:
        MORE_T2.add(x)
r = Bo.get(B + "/api/agents/jobs")
m1 = nstmt(r)
check(r.ok and len(r.json()["jobs"]) == c0 + 40, f"setup: bob's job list grows by 40 ({c0} -> {len(r.json()['jobs'])})")
check(0 < m1 <= m0 + 3, f"#4194 GET /api/agents/jobs: {c0} -> {c0 + 40} jobs costs {m0} -> {m1} statements (does not grow per job)")
one = next((x for x in r.json()["jobs"] if x["id"] == J["t1"]), {})
check(one.get("log") is None and one.get("log_last") == "nearly done" and one.get("has_log") is True,
      f"#4194 the job list without the log {str(one)[:300]}")
r = Bo.get(B + "/api/agents/jobs", params={"id": J["t1"]})
check(r.ok and r.json()["jobs"] and r.json()["jobs"][0]["log"] == "start\nhalf way\nnearly done", f"#4194 ?id= carries the whole log {r.text[:300]}")
r = Bo.get(B + "/api/agents/jobs", params={"id": J["t1"], "state": "open"})
check(r.ok and [x["id"] for x in r.json()["jobs"]] == [J["t1"]], "#4194 ?id=&state=open: a running job stays found")
r = Bo.get(B + "/api/agents/jobs", params={"id": J["cont"], "state": "open"})
check(r.ok and r.json()["jobs"] == [], "#4194 ?id=&state=open: an ended job is left out as before")
r = Bo.get(B + "/api/agents/jobs", params={"limit": 5})
check(r.ok and r.json()["next"] and len([x for x in r.json()["jobs"] if x["state"] not in ("running", "waiting")]) == 5,
      f"#4194 ?limit=5 pages as before {r.text[:200]}")

# frida's older own job behind 600 newer foreign ones (the old list read the 500 newest of the instance, then filtered)
kt.dbx("""INSERT INTO agent_jobs(agent_id, task_id, user_id, title, state, log, created_at, updated_at)
          SELECT ?, ?, ?, 'Foreign ' || g, 'done', '', ?, ? FROM generate_series(1, 600) g""",
       (CLEO, T1, uid["bob"], "2026-10-21T10:00:00+00:00", "2026-10-21T10:00:00+00:00"))
r = Fr.get(B + "/api/agents/jobs")
check(r.ok and {J["t3"], J["part2"]} <= {x["id"] for x in r.json()["jobs"]},
      f"#4194 frida's older jobs are listed behind 600 newer foreign ones {[x['id'] for x in r.json().get('jobs', [])][:10]}")
r = Ca.get(B + "/api/agents/jobs")
check(r.ok and {x["id"] for x in r.json()["jobs"]} == EXPECT_JOBS["carol"] | MORE_T2, f"#4194 carol's job list over HTTP (+ the board's 20) {[x['id'] for x in r.json().get('jobs', [])]}")
# 2.674.0 (#4194 review F2): the list without ?limit reads at most AG_JOBS_SCAN rows - carol (a participant of PART, T4b is not hers)
# passes the database filter for every job of T1 and drops them only in the exact check; more of them must not mean more reads
qn = []
for g in (1, 2):
    kt.dbx("""INSERT INTO agent_jobs(agent_id, task_id, user_id, title, state, log, created_at, updated_at)
              SELECT ?, ?, ?, 'Cap ' || g, 'done', '', ?, ? FROM generate_series(1, 6000) g""",
           (CLEO, T4b, uid["bob"], "2026-10-22T10:00:00+00:00", "2026-10-22T10:00:00+00:00"))
    r = Ca.get(B + "/api/agents/jobs")
    qn.append(nstmt(r) if r.ok else -1)
kt.dbx("DELETE FROM agent_jobs WHERE title LIKE 'Cap %'")
print("F2 reads", qn, flush=True)
check(qn[0] > 0 and qn[0] == qn[1], f"#4194 review F2: 6000 or 12000 hidden rows cost carol the same reads (capped) {qn}")
r = Ca.get(B + "/api/agents/jobs", params={"limit": 50})
check(r.ok and {x["id"] for x in r.json()["jobs"]} == EXPECT_JOBS["carol"] | MORE_T2, "#4194 carol's job pages (?limit) over HTTP: the same jobs")
r = Fr.get(B + "/api/agents/jobs", params={"limit": 20})
check(r.ok and {J["t3"], J["part2"]} <= {x["id"] for x in r.json()["jobs"]}, "#4194 frida's first page finds her jobs too (the database filters)")

# ================================================================ news
def note(who, kind, task=None, lst=None, data=None, read=None):
    return kt.dbx("INSERT INTO notifications(user_id, kind, task_id, list_id, actor_id, data, created_at, read_at) "
                  "VALUES(?,?,?,?,?,?,?,?) RETURNING id", (uid[who], kind, task, lst, uid["alice"], json.dumps(data or {}), TS, read))[0][0]


kt.dbx("DELETE FROM notifications")
NB = {"assign": note("bob", "assign", T1), "complete": note("bob", "complete", T2, read=TS),
      "share": note("bob", "share", None, STUDIO)}
note("bob", "proposal", data={"job": J["t3"]})              # not his proposal job: hidden
NC = {"assign": note("carol", "assign", T4a), "role": note("carol", "role", None, PART)}
note("carol", "assign", T4b)                                # a participant: not her task
note("carol", "complete", T1)                               # a list she is not in
NF = {"complete": note("frida", "complete", T3)}            # freelancer-matrix: tasks (news)
note("frida", "assign", T1)


def feed(s, **params):
    r = s.get(B + "/api/news", params=params)
    assert r.ok, r.text
    return r, {x["id"] for x in r.json()["items"]}, r.json()


r, ids, j = feed(Bo)
check(ids == {NB["assign"], NB["complete"], NB["share"]} and j["unread"] == 2,
      f"#4194 bob's news: visible tasks and list, not a foreign proposal job ({sorted(ids)}, unread {j['unread']})")
r, ids, j = feed(Bo, filter="me")
check(ids == {NB["assign"]} and j["unread"] == 2, f"#4194 bob's news filter=me: the To-me kinds, counters of the whole feed {sorted(ids)}")
r, ids, j = feed(Ca)
check(ids == {NC["assign"], NC["role"]}, f"#4194 carol's news: her own task in the participant list only {sorted(ids)}")
r, ids, j = feed(Fr)
check(ids == {NF["complete"]}, f"#4194 frida's news: her own list only {sorted(ids)}")
k0 = nstmt(feed(Bo)[0])
kt.dbx("""INSERT INTO notifications(user_id, kind, task_id, actor_id, data, created_at)
          SELECT ?, 'assign', ?, ?, '{}', ? FROM generate_series(1, 60)""", (uid["bob"], T1, uid["alice"], TS))
kt.dbx("""INSERT INTO notifications(user_id, kind, task_id, actor_id, data, created_at)
          SELECT ?, 'complete', ?, ?, '{}', ? FROM generate_series(1, 60)""", (uid["bob"], T4b, uid["alice"], TS))
kt.dbx("""INSERT INTO notifications(user_id, kind, actor_id, data, created_at)
          SELECT ?, 'proposal', ?, ?, ? FROM generate_series(1, 30)""", (uid["bob"], uid["alice"], json.dumps({"job": J["t3"]}), TS))
r, ids, j = feed(Bo)
k1 = nstmt(r)
check(len(ids) == 3 + 120 and j["unread"] == 2 + 120, f"setup: bob's feed with 120 more items ({len(ids)}, unread {j['unread']})")
print(f"PERF /api/agents {n0} -> {n1}, /api/agents/jobs {m0} -> {m1}, /api/news {k0} -> {k1}", flush=True)
check(0 < k1 <= k0 + 3, f"#4194 GET /api/news: 3 -> 123 items (+30 hidden proposals) costs {k0} -> {k1} statements (no query per item)")
r, ids, j = feed(Bo, filter="me")
k2 = nstmt(r)
check(len(ids) == 61 and k2 <= k1 + 2, f"#4194 GET /api/news?filter=me computes the feed once ({len(ids)} items, {k2} statements)")
r = Bo.post(B + "/api/news/read", json={"ids": [NB["assign"]]})
check(r.ok and r.json()["unread"] == 121 and "unread_me" in r.json() and r.json().get("sig"), f"#4194 news/read answers the counters {r.text[:200]}")

# ================================================================ sheets: sh_index with list_roles
def sheet(s, title, lid=None):
    r = s.post(B + "/api/sheets", json={"title": title, "space": "private", **({"list_id": lid} if lid else {})})
    check(r.ok, f"setup: sheet {title} {r.text[:200]}")
    return r.json().get("id") if r.ok else None


S1 = sheet(Fr, "Frida's sums", FRL)  # a sheet of frida's private list (no organisation: reached only through the list)
if S1:
    def index(s):
        r = s.get(B + "/api/sheets", params={"space": "all"})
        return {x["id"] for x in (r.json().get("sheets") or [])} if r.ok else {"ERR", r.status_code}
    check(S1 in index(Fr), "#4194 sh_index: frida sees the sheet of her list")
    check(S1 not in index(Bo) and S1 not in index(Ca), "#4194 sh_index: bob and carol do not (not in her list)")
    member(FRL, uid["bob"], "view")
    check(S1 in index(Bo) and S1 not in index(Ca), "#4194 sh_index: once bob is in her list he sees it, carol still not")
sys.exit(kt.done("p2674_b_api"))
