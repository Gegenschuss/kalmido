"""2.192.0 C (#2514): the upgrade test -- the current server starts on the database of an OLDER release with data in it.
freelancer-matrix: office

Every other suite starts from an empty database; this one loads each dump of tests/fixtures/upgrade/<version>.sql.gz
(made by tools/make_upgrade_dump.sh + tests/upgrade_seed.py from that release, invented data; the first: 2.101.0.sql.gz) into the group's database
and starts the current image on it:
- the migrations run through: the start succeeds, the log has no traceback / error, every MIGRATIONS step is recorded,
  kalmido_meta.app_version is the current VERSION, and the upgraded schema holds everything a fresh install has (columns
  with type + NULL rule, indexes, row-level security + policies, triggers; extra old columns only reported)
- the data is complete through the API: the old accounts sign in with their passwords; per person the same lists and tasks
  (due date + time, repeat rule, subtasks, done state, attachment names) as the old release showed (<version>.json),
  comments, clients, office documents (number, net, gross), time entries, the personal agent
- a write works (a new task + comment in the org project, frida edits her own task)
- the boundary holds: frida (no organisation) sees no org task / office document, bob not alice's private list
- a second start is idempotent: no migration step runs again, schema and data stay the same
Replaces the group's database (own group with `fresh` in run_all.sh). P2192C_NOSTART / KMT_NOSTART: not supported (the
suite restarts the container itself)."""
import glob
import gzip
import json
import os
import subprocess
import sys

import kt
from kt import B, DATA, check, sess

N = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(N, "fixtures", "upgrade")
ROOT = os.path.dirname(N)
VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()


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


def logs():
    r = subprocess.run(["docker", "logs", kt.CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def bad_lines(text):
    return [ln for ln in text.splitlines() if "Traceback" in ln or " ERROR" in ln or ln.startswith("ERROR")]


def load(dump):
    """The container stops, the group's database is replaced by the dump (start.sh KEEP=1 then keeps it)."""
    subprocess.run(["docker", "rm", "-f", kt.CT], capture_output=True)
    with open(os.path.join(DATA, ".kalmido-db"), encoding="utf-8") as f:
        dbc, dbn = f.read().split()
    psql = ["docker", "exec", "-i", dbc, "psql", "-U", "kalmido", "-v", "ON_ERROR_STOP=1", "-q"]
    r = subprocess.run(psql + ["-d", "kalmido", "-c", f"DROP DATABASE IF EXISTS {dbn} WITH (FORCE)", "-c", f"CREATE DATABASE {dbn}"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    with gzip.open(dump, "rb") as f:
        r = subprocess.run(psql + ["-d", dbn], input=f.read(), capture_output=True)
    assert r.returncode == 0, r.stderr.decode()[-2000:]


# --- the API views: the same shapes as upgrade_seed.py wrote
def view(s):
    st = s.get(B + "/api/state").json()
    lists = {x["id"]: x["name"] for x in st["lists"]}
    tasks = sorted([lists.get(t["list_id"], "?"), t["title"], t.get("due") or "", t.get("due_time") or "", t.get("repeat") or "",
                    bool(t.get("parent_id")), t.get("status") or 0, sorted(a["name"] for a in t.get("attachments") or [])]
                   for t in st["tasks"])
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
    users = {u: sess(u, E["password"]) for u in ("alice", "bob", "frida")}
    check(True, f"{tag}: the old accounts sign in with their passwords")  # sess() asserts the login
    for u, s in users.items():
        v = view(s)
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
    # the boundary between the organisation, alice's private space and frida (no organisation)
    check(Fr.get(B + f"/api/tasks/{ids['t1']}").status_code in (403, 404), f"{tag}: frida cannot read the org task")
    check(Fr.get(B + f"/api/office/docs/{ids['invoice']}").status_code in (403, 404), f"{tag}: frida cannot read the org invoice")
    check(A.get(B + f"/api/tasks/{ids['frida_task']}").status_code in (403, 404), f"{tag}: alice cannot read frida's task")
    check(A.get(B + f"/api/office/docs/{ids['frida_offer']}").status_code in (403, 404), f"{tag}: alice cannot read frida's quotation")
    priv = [t for t in kt.dbx("SELECT id FROM tasks WHERE list_id=?", (ids["private"],))]
    check(priv and all(Bo.get(B + f"/api/tasks/{r[0]}").status_code in (403, 404) for r in priv), f"{tag}: bob cannot read alice's private tasks")
    return users


DUMPS = sorted(glob.glob(os.path.join(FIX, "*.sql.gz")))
check(DUMPS, "at least one dump in tests/fixtures/upgrade")
kt.fresh()  # the current server on an empty database: the reference schema of a fresh install
REF = schema()
check(len(REF["cols"]) > 500 and REF["policies"], "reference schema of a fresh install read")
for dump in DUMPS:
    with open(dump[:-len(".sql.gz")] + ".json", encoding="utf-8") as f:
        E = json.load(f)
    tag = "from " + E["version"]
    load(dump)
    before = kt.dbx("SELECT COUNT(*) FROM tasks")[0][0]
    try:
        kt.fresh(keep=True)
        started = True
    except AssertionError as e:
        started = False
        print(str(e)[-3000:])
    check(started, f"{tag}: the current server starts on the old database")
    if not started:
        continue
    log1 = logs()
    check(not bad_lines(log1), f"{tag}: start log without traceback / error: {bad_lines(log1)[:5]}")
    check("step(s) applied" in log1, f"{tag}: the migrations ran ('migrations: N step(s) applied' in the log)")
    meta = dict(kt.dbx("SELECT key, value FROM kalmido_meta"))
    check(meta.get("app_version") == VERSION, f"{tag}: kalmido_meta.app_version = {VERSION} ({meta.get('app_version')})")
    migs = dict(kt.dbx("SELECT note, COUNT(*) FROM kalmido_migrations WHERE id NOT LIKE 'flag:%' GROUP BY note"))
    ref_migs = kt.dbx("SELECT COUNT(*) FROM kalmido_migrations WHERE id NOT LIKE 'flag:%'")[0][0]
    check(migs.get("applied", 0) > 0 and "again" not in migs, f"{tag}: steps recorded as applied / present, none again: {migs}")
    gaps, extra = schema_gaps(REF, schema())
    check(not gaps, f"{tag}: the upgraded schema holds everything of a fresh install ({len(gaps)} gaps)")
    for g in gaps[:40]:
        print("   gap:", g)
    if extra:
        print(f"   info: {len(extra)} column(s) only in the upgraded database: {', '.join(extra[:30])}")
    check(kt.dbx("SELECT COUNT(*) FROM tasks")[0][0] == before, f"{tag}: no task lost by the migrations")
    users = data_checks(E, tag)
    A, Fr = users["alice"], users["frida"]
    ids = E["ids"]
    # a write works
    r = A.post(B + "/api/tasks", json={"list_id": ids["team"], "title": "Nach dem Update angelegt", "due": "2026-06-01"})
    check(r.ok, f"{tag}: a new task in the old org project: {r.status_code} {r.text[:200]}")
    nt = r.json().get("id") if r.ok else None
    check(nt and A.post(B + f"/api/tasks/{nt}/comments", json={"body": "geht"}).ok, f"{tag}: a comment on it")
    check(nt and any(t["id"] == nt for t in users["bob"].get(B + "/api/state").json()["tasks"]), f"{tag}: bob sees the new org task")
    check(Fr.patch(B + f"/api/tasks/{ids['frida_task']}", json={"title": "Website-Texte (neu)"}).ok, f"{tag}: frida edits her task")
    check(not any(t["id"] == nt for t in Fr.get(B + "/api/state").json()["tasks"]), f"{tag}: frida does not see the new org task")
    # the second start: nothing runs again
    snap = schema()
    kt.fresh(keep=True)
    log2 = logs()
    check(not bad_lines(log2), f"{tag}: second start without traceback / error: {bad_lines(log2)[:5]}")
    check("step(s) applied" not in log2, f"{tag}: second start applies no migration step")
    check(kt.dbx("SELECT COUNT(*) FROM kalmido_migrations WHERE id NOT LIKE 'flag:%'")[0][0] == ref_migs, f"{tag}: no new migration rows")
    check(schema() == snap, f"{tag}: schema unchanged by the second start")
    A2 = sess("alice", E["password"])
    titles = {t["title"] for t in A2.get(B + "/api/state").json()["tasks"]}
    check("Nach dem Update angelegt" in titles and "Imagefilm schneiden" in titles, f"{tag}: old and new tasks after the second start")
    check(any(t["title"] == "Website-Texte (neu)" for t in sess("frida", E["password"]).get(B + "/api/state").json()["tasks"]),
          f"{tag}: frida's change kept")

sys.exit(kt.done("p2192_c_upgrade"))
