"""The comparison of an upgraded server with what the old release showed (2.192.0 C, #2514): shared by p2192_c_upgrade (the server
starts on an old database) and p4286_restore (2.510.0 #4286: an old backup is restored into a running server)."""
import json

import kt
from kt import B, check, sess


def schema():
    """The parts of the schema a fresh install and an upgraded database must share."""
    q = kt.dbx
    return {
        "cols": {(r[0], r[1]): (r[2], r[3]) for r in q("SELECT table_name, column_name, data_type, is_nullable FROM "
                                                         "information_schema.columns WHERE table_schema='public'")},
        "indexes": {r[0] for r in q("SELECT indexname FROM pg_indexes WHERE schemaname='public'")},
        "rls": {r[0]: (bool(r[1]), bool(r[2])) for r in q("SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
                                                           "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r'")},
        "policies": {(r[0], r[1]) for r in q("SELECT tablename, policyname FROM pg_policies WHERE schemaname='public'")},
        "triggers": {(r[0], r[1]) for r in q("SELECT DISTINCT event_object_table, trigger_name FROM information_schema.triggers "
                                             "WHERE trigger_schema='public'")},
    }


def schema_gaps(ref, got):
    """What a fresh install has and the upgraded database lacks (-> failures) and the old leftovers (-> info)."""
    gaps = []
    for k, v in ref["cols"].items():
        if k not in got["cols"]:
            gaps.append(f"column {k[0]}.{k[1]} missing")
        elif got["cols"][k] != v:
            gaps.append(f"column {k[0]}.{k[1]}: {got['cols'][k]} instead of {v}")
    gaps += [f"index {i} missing" for i in sorted(ref["indexes"] - got["indexes"])]
    gaps += [f"row-level security of {t}: {got['rls'].get(t)} instead of {v}" for t, v in sorted(ref["rls"].items()) if got["rls"].get(t) != v]
    gaps += [f"policy {p} missing" for p in sorted(ref["policies"] - got["policies"])]
    gaps += [f"trigger {t} missing" for t in sorted(ref["triggers"] - got["triggers"])]
    extra = sorted(f"{t}.{c}" for t, c in set(got["cols"]) - set(ref["cols"]))
    return gaps, extra


# --- the API views: the same shapes as upgrade_seed.py wrote
def state_all(s):
    """/api/state with every completed task: the start state carries completed tasks only for 14 days (core/state.py st_where),
    so the old fixture's done task left it 14 days after it was written (2.570.0, #3506: red from 06.11.2026 06:08 UTC on, the
    fixture's completed_at is 23.10.2026). The rest comes from the completed page (GET /api/tasks?scope=done), as the app's
    "Completed" view loads it -- the comparison no longer depends on the day it runs."""
    st = s.get(B + "/api/state").json()
    seen = {t["id"] for t in st["tasks"]}
    st["tasks"] = st["tasks"] + [t for t in s.get(B + "/api/tasks?scope=done&limit=2000").json()["tasks"] if t["id"] not in seen]
    return st


# 2.1154.0 (#6059, CI red p2192_c_upgrade): the office's own inbox tasks (office/recurring.py rin_task, link into #office/...)
# come from the server's ticks after the start, not from the data: the 2.101.0 dump's invoice of 23.10.2026 is overdue past
# the dunning grace since 14.11.2026 and the first tick suggests a payment reminder - right behaviour, no migration's doing
OFFICE_INBOX = "SELECT id FROM tasks WHERE url LIKE '%/#office/%'"


def office_inbox_ids():
    return {int(r[0]) for r in kt.dbx(OFFICE_INBOX)}


def view(s, office=False):
    st = state_all(s)
    skip = office_inbox_ids() if office else set()  # read after the state: a task the state holds is in the table by then
    lists = {x["id"]: x["name"] for x in st["lists"]}
    tasks = sorted([lists.get(t["list_id"], "?"), t["title"], t.get("due") or "", t.get("due_time") or "", t.get("repeat") or "",
                    bool(t.get("parent_id")), t.get("status") or 0, sorted(a["name"] for a in t.get("attachments") or [])]
                   for t in st["tasks"] if t["id"] not in skip)
    return {"lists": sorted(lists.values()), "tasks": tasks}


def comments(s, tid):
    return sorted(c["body"] for c in s.get(B + f"/api/tasks/{tid}/timeline").json()["comments"])


def docs(s):
    out = []
    for kind in ("offer", "invoice"):
        for d in s.get(B + "/api/office/docs", params={"kind": kind}).json()["docs"]:
            full = s.get(B + f"/api/office/docs/{d['id']}").json()
            out.append({"id": d["id"], "kind": kind, "number": full.get("number") or "", "net": float(full["totals"]["net"]),
                        "gross": float(full["totals"]["gross"])})
    return sorted(out, key=lambda d: d["id"])


def minutes(s):
    es = s.get(B + "/api/time/entries", params={"scope": "all", "from": "2026-01-01"}).json()["entries"]
    return sorted(round((e.get("seconds") or e.get("minutes", 0) * 60) / 60) for e in es)


def same(got, exp, what):
    if not check(got == exp, what):
        print("   expected:", json.dumps(exp, ensure_ascii=False)[:1500])
        print("   got:     ", json.dumps(got, ensure_ascii=False)[:1500])


def data_checks(E, tag):
    users = {u: sess(u, E["password"], soft=True) for u in ("alice", "bob", "frida")}
    if not check(all(users.values()), f"{tag}: the old accounts sign in with their passwords"):
        raise SystemExit(f"{tag}: no login for {[u for u, s in users.items() if s is None]}")  # the views below need all three
    for u, s in users.items():
        v = view(s, office=True)
        exp = E["users"][u]
        same(v["lists"], exp["lists"], f"{tag}: {u}'s lists as before")
        same(v["tasks"], [list(t) for t in exp["tasks"]], f"{tag}: {u}'s tasks (due, repeat, subtasks, done, attachments) as before")
    A, Bo, Fr = users["alice"], users["bob"], users["frida"]
    ids = E["ids"]
    same(comments(A, ids["t1"]), E["comments"]["t1"], f"{tag}: comments of two people on the org task")
    same(comments(Fr, ids["frida_task"]), E["comments"]["frida_task"], f"{tag}: frida's comment")
    for u, s in (("alice", A), ("frida", Fr)):
        same(docs(s), [{**d, "net": float(d["net"]), "gross": float(d["gross"])} for d in E["docs"][u]],
             f"{tag}: {u}'s office documents (number, net, gross)")
        same(sorted(c["name"] for c in s.get(B + "/api/clients").json()["clients"]), E["clients"][u], f"{tag}: {u}'s clients")
        same(minutes(s), E["minutes"][u], f"{tag}: {u}'s time entries")
    same(sorted(a["username"] for a in A.get(B + "/api/my/agents").json()["agents"]), E["agents"], f"{tag}: the personal agent")
    # the boundary between the organisation, alice's private workspace and frida (no organisation)
    check(Fr.get(B + f"/api/tasks/{ids['t1']}").status_code in (403, 404), f"{tag}: frida cannot read the org task")
    check(Fr.get(B + f"/api/office/docs/{ids['invoice']}").status_code in (403, 404), f"{tag}: frida cannot read the org invoice")
    check(A.get(B + f"/api/tasks/{ids['frida_task']}").status_code in (403, 404), f"{tag}: alice cannot read frida's task")
    check(A.get(B + f"/api/office/docs/{ids['frida_offer']}").status_code in (403, 404), f"{tag}: alice cannot read frida's quotation")
    priv = [t for t in kt.dbx("SELECT id FROM tasks WHERE list_id=?", (ids["private"],))]
    check(priv and all(Bo.get(B + f"/api/tasks/{r[0]}").status_code in (403, 404) for r in priv), f"{tag}: bob cannot read alice's private tasks")
    return users
