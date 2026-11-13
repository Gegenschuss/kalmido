#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1019.0 part A (#5633): an agent's proposal and a list rule that move tasks lock the moved tasks with all their subtasks
in id order before the first write (tasks/tasks.py move_lock_subtree, as tasks/batch.py task_batch). Own container, invented
names only.  freelancer-matrix: tasks
 - an agent's triage proposal that renames one task and moves another (with a subtask of lower id) while the restore of
   "Delete all times" holds the subtask: the apply waits BEFORE it wrote any task; undo and redo go through afterwards
 - a list rule "due date" with the chain priority -> move: the task's row is still free while the rule waits for its subtask
 - a person without an organisation: the triage apply as above
The deadlock itself is not forced; the tests show the order (the row the other side would need is free while one waits).
Without the fix the apply writes the renamed task (and the rule the priority) first: that row is locked while it waits.
Taken over from the package 2.998 that did not reach the train (job/4144, p2998_c_locks).
usage: p21019_a_movelock_test.py <datadir>"""
import os
import subprocess
import sys
import threading

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check  # noqa: E402

kt.fresh(prefix="P21019A")


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def free(table, rid):
    """True when the row can be locked at once for a write (FOR NO KEY UPDATE, the lock an UPDATE takes: nobody wrote it), else
    the error text. Not FOR UPDATE: a foreign key check of another row (FOR KEY SHARE, e.g. list_rule_runs -> tasks) would
    block that without anybody having written the row."""
    try:
        return sql(f"SELECT id FROM {table} WHERE id=? FOR NO KEY UPDATE NOWAIT", (rid,)) == [(rid,)]
    except dbxm.DbError as ex:
        return f"locked: {str(ex)[:120]}"


def proc(*lines, hold=True):
    """A transaction of the app in the container (system context, a request context for the helpers that ask for one): runs
    lines, prints 'held' and keeps its locks until a line on stdin (hold=True), then commits and prints 'done'."""
    code = ("import os, sys; os.environ['TASKS_WATCHDOG']='0'\nimport app\nfrom flask import g\nfrom kalmido.core.pg import system_ctx\n"
            "from kalmido.core.config import app as fl\nc=app.connect()\nwith fl.test_request_context('/p21019a'):\n"
            "  g.db = c\n  with system_ctx(c):\n" + "".join("    " + x + "\n" for x in lines) +
            "  print('held', flush=True)\n" + ("  sys.stdin.readline()\n" if hold else "") + "  c.commit()\nprint('done', flush=True)")
    return subprocess.Popen(["docker", "exec", "-i", CT, "python", "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def waits_for(pattern):
    """The query of a backend that waits on a lock and matches pattern (None: none waits)."""
    r = sql("SELECT query FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE ? AND query NOT LIKE '%pg_stat_activity%'",
            (pattern,))
    return r[0][0] if r else None


def race(hold, call, pattern, probe):
    """hold keeps its transaction open; call() runs in a thread. Waits for a real state: the call's backend waits on a lock
    matching pattern (or the call is over). probe() runs while it waits. -> (waited query, probe's result, call's result,
    hold's output)."""
    held_ = hold.stdout.readline().strip()
    res = {}
    th = threading.Thread(target=lambda: res.update(r=call()))
    th.start()
    wq = None
    if held_ == "held":
        wq = kt.until(lambda: waits_for(pattern) or (not th.is_alive() and "-"), timeout=30, step=0.1)
        wq = None if wq == "-" else wq
    pr = probe() if wq else None
    hold.stdin.write("\n")
    hold.stdin.flush()
    out_ = hold.communicate(timeout=60)
    th.join(60)
    check(held_ == "held" and "done" in out_[0], f"setup: the holding side held its transaction and committed {held_} {out_}")
    return wq, pr, res.get("r"), out_


def ids(r):
    j = r.json() if r.ok else {}
    rows = j if isinstance(j, list) else (j.get("items") or [])
    return {x.get("id") for x in rows}


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,events,contacts,comments,collab,files,agents", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
ALICE = kt.me_id(A)
BOB, Bo = freelancer(B, A, "bob")
FID, Fr = freelancer(B, A, "frida", features="cal,events,contacts,comments,collab,files,agents")


# ================================================================== #5633: a triage proposal locks its tasks in id order first
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "sorter", "display_name": "Sorter"})
assert r.status_code in (200, 201), r.text
AG, AGT = r.json()["id"], r.json()["token"]
assert A.patch(B + f"/api/admin/agents/{AG}", json={"proposals": "all"}).ok


def agent_post(p, **kw):
    import requests
    return requests.post(B + "/api/v1" + p, headers={"Authorization": "Bearer " + AGT}, timeout=30, **kw)


def hold_task(tid):
    # as the restore of "Delete all times" holds its tasks (personal/timewipe.py tzw_lock_tasks)
    return proc(f"c.execute('SELECT id FROM tasks WHERE id=? FOR NO KEY UPDATE', ({tid},)).fetchall()")


def triage(s, who):
    lid = s.post(B + "/api/lists", json={"name": f"Target {who}"}).json()["id"]
    ch = s.post(B + "/api/tasks", json={"title": f"child {who}"}).json()["id"]
    pa = s.post(B + "/api/tasks", json={"title": f"parent {who}"}).json()["id"]
    re_ = s.post(B + "/api/tasks", json={"title": f"rename {who}"}).json()["id"]
    check(s.patch(B + f"/api/tasks/{ch}", json={"parent_id": pa}).ok and ch < pa < re_, f"#5633 setup {who}: subtask id below the others")
    r = s.post(B + "/api/proposals", json={"agent_id": AG, "kind": "triage", "task_ids": [re_, pa], "lists": [lid]})
    check(r.status_code == 201, f"#5633 setup {who}: triage asked {r.status_code} {r.text[:200]}")
    jid = r.json()["id"]
    r = agent_post(f"/agent/jobs/{jid}/proposal", json={"items": [{"task_id": re_, "rewrite_title": f"renamed {who}"},
                                                                {"task_id": pa, "rewrite_title": f"moved {who}", "list_id": lid}]})
    check(r.status_code == 201, f"#5633 setup {who}: proposal stored {r.status_code} {r.text[:200]}")
    wq, fr, r, _ = race(hold_task(ch), lambda: s.post(B + f"/api/proposals/{jid}/apply", json={"select": ["0", "1"]}, timeout=60),
                        "%tasks%", lambda: (free("tasks", re_), free("tasks", pa)))
    check(wq is not None and fr == (True, True),
          f"#5633 {who}: the apply waits for the subtask before it wrote any task waiting={(wq or '')[:100]!r} rename/parent={fr}")
    check(r is not None and r.ok and [x[0] for x in sql("SELECT list_id FROM tasks WHERE id IN (?, ?) ORDER BY id", (ch, pa))] == [lid, lid]
          and sql("SELECT title FROM tasks WHERE id=?", (re_,)) == [(f"renamed {who}",)],
          f"#5633 {who}: after the restore the apply goes through, the subtask along {r.status_code if r is not None else None} "
          f"{r.text[:200] if r is not None else ''}")
    # the undo of the apply (the same loop the other way round) goes through as well
    r = s.post(B + f"/api/proposals/{jid}/undo")
    check(r.ok and sql("SELECT title FROM tasks WHERE id=?", (re_,)) == [(f"rename {who}",)],
          f"#5633 {who}: the undo of the apply {r.status_code} {r.text[:160]}")
    # and the redo (the same lock over the changes' after values)
    r = s.post(B + f"/api/proposals/{jid}/redo")
    check(r.ok and sql("SELECT title FROM tasks WHERE id=?", (re_,)) == [(f"renamed {who}",)]
          and [x[0] for x in sql("SELECT list_id FROM tasks WHERE id IN (?, ?) ORDER BY id", (ch, pa))] == [lid, lid],
          f"#5633 {who}: the redo of the apply {r.status_code} {r.text[:160]}")


triage(A, "alice")
triage(Fr, "frida")

# a list rule "due date reached" with the chain priority -> move: the task and its subtask are taken before the first action
SRC = A.post(B + "/api/lists", json={"name": "Rule source"}).json()["id"]
DST = A.post(B + "/api/lists", json={"name": "Rule target"}).json()["id"]
RC = A.post(B + "/api/tasks", json={"list_id": SRC, "title": "rule child"}).json()["id"]
RP = A.post(B + "/api/tasks", json={"list_id": SRC, "title": "rule parent"}).json()["id"]
check(A.patch(B + f"/api/tasks/{RC}", json={"parent_id": RP}).ok and RC < RP, "#5633 setup rule: subtask id below its parent")
r = A.post(B + f"/api/lists/{SRC}/rules", json={"name": "Due: urgent and away", "trigger": {"kind": "due"},
                                                 "actions": [{"kind": "priority", "priority": "urgent"}, {"kind": "move", "list_id": DST}]})
check(r.status_code in (200, 201), f"#5633 setup rule: created {r.status_code} {r.text[:200]}")
RID = r.json().get("id")
sql("UPDATE list_rules SET active=false WHERE id=?", (RID,), write=True)  # the watchdog must not run it before the race
TODAY = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import local_now\nprint(local_now().date())"],
                       capture_output=True, text=True).stdout.strip().splitlines()[-1]
check(A.patch(B + f"/api/tasks/{RP}", json={"due": TODAY}).ok, f"#5633 setup rule: the parent is due today {TODAY}")


def rule_tick():
    p = proc(f"c.execute('UPDATE list_rules SET active=true WHERE id=?', ({RID},))", "c.commit()",
             "from kalmido.lists.rules import rul_due_tick", "rul_due_tick(c)", hold=False)
    return p.communicate(timeout=90)


wq, fr, out, _ = race(hold_task(RC), rule_tick, "%tasks%", lambda: free("tasks", RP))
check(wq is not None and fr is True, f"#5633 rule: the rule waits for the subtask before its first action wrote the task "
      f"waiting={(wq or '')[:100]!r} parent={fr}")
check(out is not None and "done" in out[0] and sql("SELECT list_id, priority FROM tasks WHERE id=?", (RP,))[0][0] == DST
      and sql("SELECT list_id FROM tasks WHERE id=?", (RC,)) == [(DST,)],
      f"#5633 rule: after the restore the rule moved the task with its subtask {out} {sql('SELECT list_id, priority FROM tasks WHERE id=?', (RP,))}")



sys.exit(kt.done("p21019_a_movelock"))
