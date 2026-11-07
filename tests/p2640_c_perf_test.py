#!/usr/bin/env python3
# kalmido-suite:
"""2.640.0 API tests, part C: the load of the 4-second poll and of /api/state (#4183, #4185). Invented names only.
 - #4183 the team chat marker t of /api/version comes from the counters per room (tchat_room_sig, kept by a trigger): a new,
   an edited, a pinned / unpinned, a deleted and a restored message move it, in a direct conversation and in a channel; nothing
   changed = the same t; a message written straight into the database moves it too (the trigger, no app code); the counters
   equal the real numbers of the room (also a room that gets its row only now: counted once); a change of the counter row
   alone moves t (the poll reads the counters, not the messages: red with the old COUNT over the messages)
 - #4185 the helpers of /api/state with set queries, the same numbers: progress (a done copy of a recurring task counts not,
   also when its original is deleted; won't do and the trash count not), the budgets of two projects in one state (once per
   branch), the clients with their lists, the formula text with the field names; the storage badge: an own upload / deletion
   shows at once, a change without an own write (straight into the database) only in the fresh measure (/api/me/storage)
   while the badge keeps its cached value (red without the cache)
 - freelancer-matrix: teamchat, lists, clients, storage (frida without an organisation: the same checks)
usage: p2640_c_perf_test.py <datadir>   (a fresh container; P2640C_NOSTART=1 = the server already runs)"""
import os
import sys
from datetime import datetime, timedelta, timezone

import dbx as dbxm
import kt
from freelancer_fixture import freelancer
from kt import B, check, sess

FEAT = "collab,comments,fields,progress,clients,time,files"
kt.fresh(prefix="P2640C")
kt.docker_logs_on_first_fail()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
uid = {"alice": kt.me_id(A)}


def wdb(sql, args=()):
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def person(name, orgs):
    r = A.post(B + "/api/users", json={"orgs": orgs, "username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com"})
    assert r.ok, r.text
    uid[name] = r.json()["id"]
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
    return s


ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha"}).json()["id"]  # alice (the creator) is its member
Bo = person("bob", [ORG])
FID, Fr = freelancer(B, A, "frida", features=FEAT)
uid["frida"] = FID
ver = lambda s: s.get(B + "/api/version").json()["t"]  # noqa: E731


def sig_row(rid):
    r = kt.dbx("SELECT n, pins, max_id, rev FROM tchat_room_sig WHERE room_id=?", (rid,))
    return tuple(r[0]) if r else None


def real(rid):
    return tuple(kt.dbx("SELECT COUNT(*), COUNT(pinned_at), COALESCE(MAX(id),0) FROM tchat_msgs WHERE room_id=?", (rid,))[0])


# ================================================================ #4183 the team chat marker from the counters
def chat_case(S, P, other, who, channel=None):
    """S writes, P polls; a direct conversation with the person other, or a channel S makes (channel = {org_id?, members?})."""
    if channel is not None:
        r = S.post(B + "/api/team/channels", json={"name": f"Plans {who}", **channel})
    else:
        r = S.post(B + "/api/team/dm", json={"user_id": other})
    check(r.ok, f"{who}: the room {r.status_code} {r.text[:200]}")
    rid = r.json()["id"]
    t0 = ver(P)
    check(ver(P) == t0, f"{who}: nothing changed -> the same t {t0}")
    m1 = S.post(B + f"/api/team/rooms/{rid}/messages", json={"body": "First draft"}).json()["id"]
    t1 = ver(P)
    check(t1 != t0, f"{who}: a new message moves t {t0} -> {t1}")
    check(ver(P) == t1, f"{who}: and stays when nothing changes")
    m2 = S.post(B + f"/api/team/rooms/{rid}/messages", json={"body": "Second note"}).json()["id"]
    t2 = ver(P)
    check(t2 != t1, f"{who}: a second message moves t")
    r = S.patch(B + f"/api/team/messages/{m1}", json={"body": "First draft, fixed"})
    t3 = ver(P)
    check(r.ok and t3 != t2, f"{who}: an edit moves t {r.status_code} {r.text[:120]}")
    r = S.post(B + f"/api/team/messages/{m2}/pin", json={"pinned": True})
    t4 = ver(P)
    check(r.ok and t4 != t3, f"{who}: a pin moves t {r.status_code} {r.text[:120]}")
    r = S.post(B + f"/api/team/messages/{m2}/pin", json={"pinned": False})
    t5 = ver(P)
    check(r.ok and t5 != t4, f"{who}: an unpin moves t {r.status_code}")
    r = S.delete(B + f"/api/team/messages/{m1}")
    t6 = ver(P)
    check(r.ok and t6 != t5, f"{who}: a deletion moves t {r.status_code}")
    r = S.post(B + f"/api/team/messages/{m1}/restore")
    t7 = ver(P)
    check(r.ok and t7 != t6, f"{who}: a restore moves t {r.status_code} {r.text[:120]}")
    check(sig_row(rid) and sig_row(rid)[:3] == real(rid), f"{who}: the counters equal the room {sig_row(rid)} {real(rid)}")
    # straight into the database (no app code): the trigger keeps the counters
    wdb("INSERT INTO tchat_msgs(room_id,user_id,body,created_at) VALUES(?,?,?,?)", (rid, other, "By hand", "2026-11-07T10:00:00Z"))
    t8 = ver(P)
    check(t8 != t7 and sig_row(rid)[:3] == real(rid), f"{who}: a message written in the database moves t, counters right {sig_row(rid)} {real(rid)}")
    wdb("DELETE FROM tchat_msgs WHERE room_id=? AND body='By hand'", (rid,))
    t9 = ver(P)
    # the newest id stays where it was after a hard delete (it only grows; the count and the change counter move)
    check(t9 != t8 and sig_row(rid)[:2] == real(rid)[:2] and sig_row(rid)[2] >= real(rid)[2],
          f"{who}: a hard delete in the database moves t {sig_row(rid)} {real(rid)}")
    # the poll reads the counters, not the messages: only the counter row changes -> t moves (old COUNT: the same t)
    wdb("UPDATE tchat_room_sig SET rev=rev+100 WHERE room_id=?", (rid,))
    check(ver(P) != t9, f"{who}: t comes from the counter row (#4183)")
    # a room without a row yet (the rooms from before this version): its first change counts it once
    wdb("DELETE FROM tchat_room_sig WHERE room_id=?", (rid,))
    t10 = ver(P)
    S.post(B + f"/api/team/rooms/{rid}/messages", json={"body": "After the update"})
    check(ver(P) != t10 and sig_row(rid)[:3] == real(rid), f"{who}: a room gets its row on its first change, counted {sig_row(rid)} {real(rid)}")
    return rid


SHARED = A.post(B + "/api/lists", json={"name": "Shared plans"}).json()["id"]  # a direct conversation needs a common list
check(A.put(B + f"/api/lists/{SHARED}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "bob joins alice's list")
chat_case(A, Bo, uid["bob"], "direct alice -> bob")
chat_case(A, Bo, uid["bob"], "channel of Alpha, alice + bob", channel={"org_id": ORG, "members": [uid["bob"]]})
chat_case(Fr, Fr, uid["frida"], "own channel of frida (no organisation)", channel={})


# ================================================================ #4185 progress: set queries, the same numbers
def progress_case(S, who):
    lid = S.post(B + "/api/lists", json={"name": f"Progress {who}"}).json()["id"]
    ids = [S.post(B + "/api/tasks", json={"title": f"Step {i}", "list_id": lid}).json()["id"] for i in range(5)]
    due = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
    for tid, b in ((ids[0], {"status": 2}), (ids[1], {"status": -1}), (ids[3], {"due": due})):  # done; won't do: not counted
        r = S.patch(B + f"/api/tasks/{tid}", json=b)
        check(r.ok, f"{who}: task {b} {r.status_code} {r.text[:160]}")
    r = S.delete(B + f"/api/tasks/{ids[2]}")  # the trash: not counted
    check(r.ok, f"{who}: a task into the trash {r.status_code} {r.text[:160]}")
    # a done copy of a recurring task: same list, created_at and title as an older task (the original open, then deleted)
    for tid in (ids[3], ids[4]):
        wdb("""INSERT INTO tasks(list_id,title,content,status,created_at,updated_at,created_by)
               SELECT list_id, title, '', 2, created_at, updated_at, created_by FROM tasks WHERE id=?""", (tid,))
    wdb("UPDATE tasks SET deleted_at=? WHERE id=?", ("2026-11-07T10:00:00Z", ids[4]))
    pr = lambda: next(x for x in S.get(B + "/api/state").json()["lists"] if x["id"] == lid)["progress"]  # noqa: E731
    p = pr()
    print(f"{who}: tasks of the list {kt.dbx('SELECT id, title, status, created_at, deleted_at, parent_id FROM tasks WHERE list_id=? ORDER BY id', (lid,))}", flush=True)
    check(p["done"] == 1 and p["total"] == 2 and p["overdue"] == 1,
          f"{who}: #4185 progress: 1 done of 2 (won't do, trash, done copies out, also of a deleted original), 1 overdue {p}")
    S.patch(B + f"/api/tasks/{ids[3]}", json={"status": 2})
    p = pr()
    check(p["done"] == 2 and p["total"] == 2 and p["overdue"] == 0, f"{who}: the original done -> 2 of 2 {p}")


progress_case(A, "alice")
progress_case(Fr, "frida")


# ================================================================ #4185 budgets of two projects, formula names, clients
def budget_case(S, who):
    out, fxt = {}, {}
    for name, vals in (("One", ((10, (6, 3)), (4, ()))), ("Two", ((8, ()), (5, (2,))))):
        P = S.post(B + "/api/lists", json={"name": f"Budget {name} {who}", "ptype": "agency", "time_tracking": True}).json()["id"]
        S.post(B + f"/api/lists/{P}/fields", json={"name": "Budget h", "type": "number"})
        S.post(B + f"/api/lists/{P}/fields", json={"name": "Rate", "type": "number"})
        r = S.post(B + f"/api/lists/{P}/fields", json={"name": "Cost", "type": "formula", "formula": "{Budget h} * {Rate}"})
        check(r.ok and "Budget h" in r.json()["options"].get("formula", ""), f"{who}: a formula field {r.status_code} {r.text[:160]}")
        fxt[r.json()["id"]] = r.json()["options"]["formula"]  # what the field's own answer names (field_dict with its query)
        fb = next(f for f in S.get(B + "/api/state").json()["fields"] if f["list_id"] == P and f["name"] == "Budget h")
        for own, subs in vals:
            t = S.post(B + "/api/tasks", json={"title": f"Part {own}", "list_id": P, "fields": {str(fb["id"]): str(own)}}).json()["id"]
            for x in subs:
                S.post(B + "/api/tasks", json={"title": f"Sub {x}", "list_id": P, "parent_id": t, "fields": {str(fb["id"]): str(x)}})
        out[name] = P
    start = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    check(S.post(B + "/api/time/entries", json={"list_id": out["Two"], "start": start, "minutes": 90}).ok, f"{who}: a time entry")
    st = S.get(B + "/api/state").json()
    tl = st.get("time_lists", {})
    one, two = tl.get(str(out["One"])) or {}, tl.get(str(out["Two"])) or {}
    check(one.get("b") == 13 and two.get("b") == 10 and two.get("s") == 90 * 60,
          f"{who}: #4185 two budgets in one state, once per branch (6+3+4 = 13, 8+2 = 10), the time 1.5 h {one} {two}")
    fx = [f for f in st["fields"] if f["list_id"] in out.values() and f["type"] == "formula"]
    check(len(fx) == 2 and all(f["options"].get("formula") == fxt.get(f["id"]) for f in fx),
          f"{who}: #4185 the formula text with the field names as the field's own answer {[f['options'].get('formula') for f in fx]} {fxt}")
    # the clients with their lists, from one query
    c1 = S.post(B + "/api/clients", json={"name": f"Studio North {who}"}).json()["id"]
    c2 = S.post(B + "/api/clients", json={"name": f"Studio South {who}"}).json()["id"]
    c3 = S.post(B + "/api/clients", json={"name": f"Studio Empty {who}"}).json()["id"]
    check(S.patch(B + f"/api/lists/{out['One']}", json={"client_id": c1}).ok and S.patch(B + f"/api/lists/{out['Two']}", json={"client_id": c1}).ok,
          f"{who}: two projects of the first client")
    L3 = S.post(B + "/api/lists", json={"name": f"Brochure {who}"}).json()["id"]
    S.patch(B + f"/api/lists/{L3}", json={"client_id": c2})
    cl = {x["id"]: x for x in S.get(B + "/api/state").json().get("clients", [])}
    check(c1 in cl and sorted(cl[c1]["lists"]) == sorted(out.values()) and cl[c2]["lists"] == [L3] and cl[c3]["lists"] == [],
          f"{who}: #4185 the clients with their lists {[(k, v['lists']) for k, v in cl.items()]}")
    check(all(set(x) >= {"id", "name", "label", "icon", "color", "org_id", "archived", "lists"} for x in cl.values()), f"{who}: the client keys stay")


budget_case(A, "alice")
budget_case(Fr, "frida")


# ================================================================ #4185 the storage badge: once a minute, an own write at once
def storage_case(S, who):
    lid = S.post(B + "/api/lists", json={"name": f"Files {who}"}).json()["id"]
    tid = S.post(B + "/api/tasks", json={"title": "with files", "list_id": lid}).json()["id"]
    badge = lambda: S.get(B + "/api/state").json()["storage"]["used"]  # noqa: E731
    fresh = lambda: S.get(B + "/api/me/storage").json()["used"]  # noqa: E731
    u0 = badge()
    check(u0 == fresh(), f"{who}: the badge and the fresh measure agree {u0}")
    r = S.post(B + f"/api/tasks/{tid}/attachments", files={"file": ("a.bin", os.urandom(120_000), "application/octet-stream")})
    check(r.ok, f"{who}: an upload {r.status_code} {r.text[:120]}")
    aid = max(x["id"] for x in r.json()["attachments"])  # the answer is the task with its files
    check(badge() == u0 + 120_000, f"{who}: #4185 the own upload shows in the badge at once {badge()} {u0}")
    # a change without an own write (straight into the database): the fresh measure sees it, the badge keeps its value
    wdb("UPDATE attachments SET size=size+5000 WHERE id=?", (aid,))
    check(fresh() == u0 + 125_000, f"{who}: the fresh measure counts the database change {fresh()}")
    check(badge() == u0 + 120_000, f"{who}: #4185 the badge comes from the cache (at most once a minute) {badge()}")
    r = S.delete(B + f"/api/attachments/{aid}")
    check(r.ok and badge() == u0, f"{who}: #4185 the own deletion shows in the badge at once {r.status_code} {badge()} {u0}")


storage_case(A, "alice")
storage_case(Fr, "frida")

sys.exit(kt.done("p2640_c_perf"))
