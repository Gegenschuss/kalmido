#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1017.0 (rebuilt from 2.998.0 part C): the order of the row locks against deadlocks and the one lock of every share writer. Own container,
invented names only.  freelancer-matrix: pim
 - #5630 a calendar into the trash while an event's save holds its event row: the trash waits for the event BEFORE it wrote
   the calendar's row (the core's obj_trash takes the children in id order first -- the order of an event's save: events,
   then ev_cals); before, it wrote ev_cals first and the event's save then waited for it: deadlock (500)
 - #5645 every writer of fs_shares takes the same lock: while a calendar's members dialog (obj_node_person_put) has put bob
   on the node and not committed, the file store's share dialog (obj_node_share), a team chat member add (obj_member_put) and
   the restore of a share taken back (obj_share_restore) wait for it -- one row of bob on the node, never two
 - a person without an organisation: the calendar's trash as above
The deadlock itself is not forced; the tests show the order (the row the other side would need is free while one waits).
usage: p21017_a_locks_test.py <datadir>"""
import json
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

D = "2026-11-24"
kt.fresh(prefix="P21017A")


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
    """True when the row can be locked at once (nobody holds it), else the error text."""
    try:
        return sql(f"SELECT id FROM {table} WHERE id=? FOR UPDATE NOWAIT", (rid,)) == [(rid,)]
    except dbxm.DbError as ex:
        return f"locked: {str(ex)[:120]}"


def proc(*lines, hold=True):
    """A transaction of the app in the container (system context, a request context for the helpers that ask for one): runs
    lines, prints 'held' and keeps its locks until a line on stdin (hold=True), then commits and prints 'done'."""
    code = ("import os, sys; os.environ['TASKS_WATCHDOG']='0'\nimport app\nfrom flask import g\nfrom kalmido.core.pg import system_ctx\n"
            "from kalmido.core.config import app as fl\nc=app.connect()\nwith fl.test_request_context('/p21017a'):\n"
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


# ================================================================== #5630: the calendar's trash takes its events first
def cal_trash(s, who):
    k = s.post(B + "/api/evcals", json={"name": f"Order {who}"}).json()["id"]
    e = s.post(B + "/api/events", json={"cal_id": k, "title": "Held", "start": f"{D}T09:00", "end": f"{D}T10:00"}).json()["id"]
    hold = proc(f"c.execute('SELECT id FROM events WHERE id=? FOR NO KEY UPDATE', ({e},)).fetchall()")  # an event's save holds it
    wq, fr, r, _ = race(hold, lambda: s.delete(B + f"/api/evcals/{k}"), "%events%", lambda: free("ev_cals", k))
    check(wq is not None and fr is True,
          f"#5630 {who}: the trash waits for the event before it wrote the calendar's row waiting={(wq or '')[:100]!r} ev_cals={fr}")
    check(r is not None and r.ok and sql("SELECT deleted_at IS NOT NULL FROM ev_cals WHERE id=?", (k,)) == [(True,)]
          and sql("SELECT deleted_at IS NOT NULL FROM events WHERE id=?", (e,)) == [(True,)],
          f"#5630 {who}: after the event's save the calendar goes into the trash with its event {r.status_code if r is not None else None}")
    check(k not in ids(s.get(B + "/api/evcals")), f"#5630 {who}: the calendar is gone from the list")
    r = s.post(B + f"/api/evcals/{k}/restore")
    check(r.ok and sql("SELECT deleted_at IS NULL FROM events WHERE id=?", (e,)) == [(True,)] and k in ids(s.get(B + "/api/evcals")),
          f"#5630 {who}: restored with its event {r.status_code} {r.text[:160]}")


cal_trash(A, "alice")
cal_trash(Fr, "frida")


# ================================================================== #5645: one lock for every writer of fs_shares
def node_of(kind, rid):
    r = sql("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (kind, rid))
    return r[0][0] if r else None


def rows_of(nd, who):
    return sql("SELECT COUNT(*) FROM fs_shares WHERE node_id=? AND (user_id=? OR agent_id=?)", (nd, who, who))[0][0]


def put_held(nd, who=None):
    """The members dialog of a calendar (obj_node_person_put) has put who (bob) on node nd and not committed yet."""
    return proc("from kalmido.core.objects import obj_node_person_put",
                f"obj_node_person_put(c, {ALICE}, c.execute('SELECT * FROM fs_nodes WHERE id=?', ({nd},)).fetchone(), {who or BOB}, 'view')")


K = A.post(B + "/api/evcals", json={"name": "Shared"}).json()["id"]
check(A.put(B + f"/api/evcals/{K}/members", json={"user_id": FID, "role": "view"}).ok, "#5645 setup: the calendar's node (shared with frida)")
ND = node_of("evcal", K)
check(ND is not None and rows_of(ND, BOB) == 0, f"#5645 setup: a node without bob {ND}")


# (1) the file store's share dialog (obj_node_share) on the same node, at the same time
def node_share():
    p = proc("from kalmido.core.objects import obj_node_share",
             f"obj_node_share(c, {ALICE}, c.execute('SELECT * FROM fs_nodes WHERE id=?', ({ND},)).fetchone(), 'user_id', {BOB}, 'edit', "
             "None, None, checked=True)", hold=False)
    return p.communicate(timeout=60)


wq, _, out, _ = race(put_held(ND), node_share, "%pg_advisory_xact_lock%", lambda: True)
check(wq is not None and out is not None and "done" in out[0] and rows_of(ND, BOB) == 1,
      f"#5645: the core's share dialog waits for the members dialog -> one row of bob ({rows_of(ND, BOB)}) waited={wq is not None} {out}")

# (2) the restore of a share taken back while the members dialog puts the same person (obj_share_restore); frida, who is a
# member already (the restore's own pool check lets her through)
check(rows_of(ND, FID) == 1, "#5645 setup: frida's share on the node")
sql("DELETE FROM fs_shares WHERE node_id=? AND user_id=?", (ND, FID), write=True)
sql("INSERT INTO obj_revoked(src,org_id,user_id,kind,ref_id,row_json,reason,by_id,created_at) VALUES('fs_shares',NULL,?,'evcal',?,?,"
    "'unshare',?,'2026-11-12T08:00:00Z')", (FID, K, json.dumps({"node_id": ND, "user_id": FID, "role": "view"}), ALICE), write=True)
REV = sql("SELECT MAX(id) FROM obj_revoked WHERE src='fs_shares' AND kind='evcal' AND ref_id=?", (K,))[0][0]
check(REV is not None and rows_of(ND, FID) == 0, f"#5645 setup: frida's share taken back, restorable {REV}")
wq, _, r, _ = race(put_held(ND, FID), lambda: A.post(B + f"/api/obj/evcal/{K}/shares/{REV}/restore"), "%pg_advisory_xact_lock%",
                   lambda: True)
check(wq is not None and r is not None and r.status_code == 409 and "Already shared" in r.text and rows_of(ND, FID) == 1,
      f"#5645: the restore waits for the members dialog -> 'Already shared', one row of frida ({rows_of(ND, FID)}) waited={wq is not None} "
      f"{r.status_code if r is not None else None} {r.text[:160] if r is not None else ''}")

# (3) a team chat member add (obj_member_put) while another writer puts the same person on the room's node
r = A.post(B + "/api/team/channels", json={"name": "Lockroom", "org_id": None, "members": []})
check(r.ok, f"#5645 setup: a channel {r.status_code} {r.text[:160]}")
ROOM = r.json().get("id") if r.ok else None
ND2 = None
if ROOM:
    p = proc("from kalmido.core.objects import obj_node", f"obj_node(c, {ALICE}, 'tchat_room', {ROOM}, make=True)", hold=False)
    p.communicate(timeout=60)
    ND2 = node_of("tchat_room", ROOM)
check(ND2 is not None and rows_of(ND2, BOB) == 0, f"#5645 setup: the room's node without bob {ND2}")


def member_put():
    p = proc("from kalmido.core.objects import obj_member_put", f"obj_member_put(c, {ALICE}, 'tchat_room', {ROOM}, 'user_id', {BOB}, 'edit')",
             hold=False)
    return p.communicate(timeout=60)


if ND2:
    wq, _, out, _ = race(put_held(ND2), member_put, "%pg_advisory_xact_lock%", lambda: True)
    check(wq is not None and out is not None and "done" in out[0] and rows_of(ND2, BOB) == 1,
          f"#5645: the team chat's member add waits for the other writer -> one row of bob ({rows_of(ND2, BOB)}) waited={wq is not None} {out}")

sys.exit(kt.done("p21017_a_locks"))
