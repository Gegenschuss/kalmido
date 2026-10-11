#!/usr/bin/env python3
"""2.37.0 (review W2-4, W2-2, K2-1) row-level security with a login role that is NOT the postgres image's superuser, in an
own database container (a fresh cluster: the shared test cluster already has the role kalmido_app).
1. "owner" (start.sh KALMIDO_TEST_DB_LOGIN=owner): owner of the database, no superuser, no BYPASSRLS. Mode workspaces, two
   organisations (Alpha: alice + bob, Beta: carol). The app needs no app role (none is created); the policies hold for the
   owner itself (FORCE): without context it sees no organisation's rows, with an organisation's context only those, as
   "system" all; kalmido_org_count() counts every organisation; the API keeps the organisations apart; a backup and its
   restore come back complete (rows per organisation, policies, FORCE). K2-1: a write the database refuses (SQLSTATE 42501,
   here a revoked privilege) answers 403 "no permission" instead of a 500.
2. "bypass" (BYPASSRLS, may not create roles, no kalmido_app): mode workspaces -> the app refuses to start (exit 3, the
   log says why); mode not set (one organisation) -> it starts, says so in the log and in the admin alerts settings
   (rls_off) and raises a security alert.
usage: rls_owner_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CONTAINER = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
DBC = CONTAINER + "-rlsdb"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
MARK = "Own3rAlpha"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def start(login, extra="", keep=False):
    e = dict(os.environ, KALMIDO_TEST_DB_CONTAINER=DBC, KALMIDO_TEST_DB_LOGIN=login, KALMIDO_ADMIN_ALERTS="1",
             EXTRA=os.environ.get("EXTRA", "") + " " + extra)
    if keep:
        e["KEEP"] = "1"
    else:
        e.pop("KEEP", None)
    return subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)


def sql(text, args=()):
    """Superuser psql (bypasses row-level security) -> rows."""
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=20)
    try:
        return c.execute(text, args).fetchall()
    finally:
        c.close()


def as_login(stmts):
    """psql as the app's own login role (k_owner) -> the last line of output, or the error text."""
    dbn = open(os.path.join(DATA, ".kalmido-db")).read().split()[1]
    p = subprocess.run(["docker", "exec", DBC, "psql", "-U", "k_owner", "-d", dbn, "-Atq", "-v", "ON_ERROR_STOP=1",
                        *sum([["-c", s] for s in stmts], [])], capture_output=True, text=True)
    return (p.stdout.strip().splitlines() or [""])[-1] if p.returncode == 0 else "ERROR " + p.stderr.strip()[:200]


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def logs():
    p = subprocess.run(["docker", "logs", CONTAINER], capture_output=True, text=True)
    return p.stdout + p.stderr


def titles(s):
    return sorted(t["title"] for t in s.get(B + "/api/state").json()["tasks"])


subprocess.run(["docker", "rm", "-f", DBC], capture_output=True)
try:
    # ------------------------------------------------------------------ 1. owner without superuser / BYPASSRLS
    r = start("owner")
    assert r.returncode == 0, r.stdout + r.stderr
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
    A = sess("alice")
    A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
    ids = {}
    for u in ("bob", "carol"):
        r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
        assert r.ok, r.text
        ids[u] = r.json()["id"]
    BOB, CAROL = ids["bob"], ids["carol"]
    r = start("owner", "-e KALMIDO_INSTANCE_MODE=workspaces", keep=True)
    assert r.returncode == 0, r.stdout + r.stderr
    A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
    for s in (A, Bo, Ca):
        s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    ALPHA = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
    r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
    assert r.status_code == 201, r.text
    BETA = r.json()["id"]
    sql("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=1", (ALPHA,))
    A.delete(B + f"/api/orgs/{ALPHA}/members/{CAROL}")
    LA = Bo.post(B + "/api/lists", json={"name": f"{MARK} list", "org_id": ALPHA}).json()["id"]
    LB = Ca.post(B + "/api/lists", json={"name": "Beta list", "org_id": BETA}).json()["id"]
    Bo.post(B + "/api/tasks", json={"title": f"{MARK} task", "list_id": LA})
    Ca.post(B + "/api/tasks", json={"title": "Beta task", "list_id": LB})

    role = sql("SELECT rolsuper, rolbypassrls, rolcreaterole FROM pg_roles WHERE rolname='k_owner'")
    check(role and not any(bool(x) for x in role[0]), f"the app's login role: no superuser, no BYPASSRLS, no CREATEROLE ({role})")
    check(sql("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()")[0][0] == "k_owner",
          "the login role owns the database")
    check(not sql("SELECT 1 FROM pg_roles WHERE rolname='kalmido_app'"), "no app role needed (none created)")
    check(sql("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='lists'")[0][0] == "k_owner"
          and sql("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE relname='lists'")[0][0] in (True, 1, "t"),
          "lists: owned by the login role, row security forced")
    check("NOT enforced" not in logs(), "no row-level security warning in the log")

    # the policies hold for the owner (FORCE)
    total = sql("SELECT COUNT(*) FROM lists WHERE org_id IS NOT NULL")[0][0]
    check(total >= 2, f"setup: organisation lists exist ({total})")
    check(as_login(["SELECT COUNT(*) FROM lists WHERE org_id IS NOT NULL"]) == "0", "owner without context: no organisation's lists")
    check(as_login(["SET app.role = 'user'", f"SET app.org_ids = '{BETA}'",
                    "SELECT string_agg(name, ',') FROM lists WHERE org_id IS NOT NULL"]) == "Beta list",
          "owner with Beta's context: Beta's list only")
    check(as_login(["SET app.role = 'user'", f"SET app.org_ids = '{BETA}'",
                    f"UPDATE lists SET name = 'hijacked' WHERE id = {LA}", f"SELECT name FROM lists WHERE id = {LA}"]) == "",
          "owner with Beta's context: Alpha's list cannot be changed")
    check(as_login(["SET app.role = 'user'", f"SET app.org_ids = '{BETA}'",
                    f"INSERT INTO lists(owner_id, name, org_id, created_at) VALUES({CAROL}, 'x', {ALPHA}, '2026-01-01')"]).find("row-level security") > 0,
          "owner with Beta's context: no row into Alpha (WITH CHECK)")
    check(as_login(["SET app.role = 'system'", "SELECT COUNT(*) FROM lists WHERE org_id IS NOT NULL"]) == str(total),
          "owner as system: every organisation's lists")
    n_orgs = sql("SELECT COUNT(*) FROM orgs")[0][0]
    check(n_orgs >= 2 and as_login(["SELECT kalmido_org_count()"]) == str(n_orgs),
          f"kalmido_org_count() counts every organisation for the owner without context ({n_orgs})")

    # the app keeps the organisations apart
    check(MARK not in json.dumps(Ca.get(B + "/api/state").json()["lists"]), "API: carol sees nothing of Alpha")
    check("Beta list" not in json.dumps(Bo.get(B + "/api/state").json()["lists"]), "API: bob sees nothing of Beta")
    check(f"{MARK} task" in titles(Bo) and "Beta task" in titles(Ca), "API: each sees the own organisation's task")

    # backup + restore as the owner (pg_dump / pg_restore with --enable-row-security, app.role=system)
    def per_org():
        return sorted(tuple(x) for x in sql("SELECT COALESCE(org_id, 0), COUNT(*) FROM lists GROUP BY 1"))

    def code():
        return (sql("SELECT COUNT(*) FROM pg_policy")[0][0],
                sql("SELECT COUNT(*) FROM pg_class WHERE relrowsecurity AND relforcerowsecurity")[0][0])
    before_lists, before_code, before_tasks = per_org(), code(), sql("SELECT COUNT(*) FROM tasks")[0][0]
    n = len(A.get(B + "/api/admin/backups").json()["items"])
    check(A.post(B + "/api/admin/backups").status_code == 202, "backup started")
    j = {}
    for _ in range(120):
        j = A.get(B + "/api/admin/backups").json()
        if not j["running"] and (len(j["items"]) > n or j["last_error"]):
            break
        time.sleep(0.5)
    check(not j.get("last_error") and len(j.get("items", [])) > n, f"backup as the owner: written ({j.get('last_error')})")
    name = [x["name"] for x in j.get("items", []) if x["kind"] == "manual"][:1]
    Bo.post(B + "/api/tasks", json={"title": "after the backup", "list_id": LA})
    r = A.post(B + "/api/admin/backups/restore", json={"confirm": "RESTORE", "name": name[0] if name else "x"})
    check(r.ok, f"restore as the owner: ok ({r.status_code} {r.text[:200]})")
    Bo = sess("bob")
    check("after the backup" not in titles(Bo) and f"{MARK} task" in titles(Bo), "restore: the state of the backup")
    check(per_org() == before_lists and sql("SELECT COUNT(*) FROM tasks")[0][0] == before_tasks,
          f"restore: lists per organisation and tasks as before ({per_org()} / {before_lists})")
    check(code() == before_code, f"restore: policies and forced row security as before ({code()} / {before_code})")
    check(as_login(["SELECT COUNT(*) FROM lists WHERE org_id IS NOT NULL"]) == "0" and as_login(["SELECT kalmido_org_count()"]) == str(n_orgs),
          "restore: the policies hold for the owner again, kalmido_org_count() counts")
    check(not sql("SELECT 1 FROM pg_roles WHERE rolname='kalmido_app'"), "restore: still no app role")

    # K2-1: the database refuses a write (42501) -> 403 "no permission", not a 500
    Bo = sess("bob")
    sql("REVOKE UPDATE ON lists FROM k_owner")
    try:
        r = Bo.patch(B + f"/api/lists/{LA}", json={"name": "renamed"})
        check(r.status_code == 403 and r.json().get("error") == "no permission", f"K2-1: 42501 -> 403 no permission ({r.status_code} {r.text[:160]})")
    finally:
        sql("GRANT UPDATE ON lists TO k_owner")
    check("database error (403)" in logs(), "K2-1: logged")
    check(Bo.patch(B + f"/api/lists/{LA}", json={"name": f"{MARK} list 2"}).ok, "K2-1: the next request works again")

    # ------------------------------------------------------------------ 2. BYPASSRLS without CREATEROLE, no kalmido_app
    r = start("bypass", "-e KALMIDO_INSTANCE_MODE=workspaces")
    ec = subprocess.run(["docker", "inspect", "-f", "{{.State.ExitCode}}", CONTAINER], capture_output=True, text=True).stdout.strip()
    lg = logs()
    check(r.returncode != 0 and ec == "3", f"W2-2: mode workspaces, row security not enforceable -> exit 3 (start {r.returncode}, exit {ec})")
    check("FATAL: row-level security is NOT enforced" in lg and "CREATEROLE" in lg and "kalmido_app" in lg,
          "W2-2: the log says why and how to fix it")
    r = start("bypass")
    check(r.returncode == 0, f"W2-2: one organisation: it starts ({r.stderr[-300:]})")
    if r.returncode == 0:
        check("warning: row-level security is NOT enforced" in logs(), "W2-2: one organisation: the log warns")
        assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
        A = sess("alice")
        j = A.get(B + "/api/admin/alerts").json()
        check(j.get("rls_off") is True, f"W2-2: admin alerts settings say row security is off ({j.get('rls_off')})")
        r = start("bypass", keep=True)  # with an admin: the alert of the start is stored (and sent)
        found = []
        for _ in range(40):
            found = sql("SELECT key FROM admin_alerts WHERE kind='security' AND key LIKE 'rls:off%'")
            if found:
                break
            time.sleep(0.5)
        check(r.returncode == 0 and found, "W2-2: security alert at the start")
finally:
    subprocess.run(["docker", "rm", "-f", DBC], capture_output=True)

print(f"\nrls_owner: {OKS[0]} ok, {len(FAILS)} failed")
raise SystemExit(1 if FAILS else 0)
