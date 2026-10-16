#!/usr/bin/env python3
"""2.37.0 (#1150) row-level security, stage 1 -- the policies themselves, against the test database (not through the app's
own checks): mode workspaces, two organisations (Alpha: alice + bob, Beta: carol), a row of each organisation in every RLS
table. Then, per table, with the role the app works as (kalmido_app) and the context the app sets:
 - app.role user + the other organisation's ids -> 0 rows of Alpha; INSERT / UPDATE onto Alpha's org_id -> refused
 - no context at all -> no organisation's rows (only org_id NULL)
 - app.role system -> everything
 - orgs: only the own ones; org_members: own rows + rows of the own organisations
and through the API: CalDAV of carol never shows Alpha's calendar, a public link of an Alpha list shows exactly that list
(resolved past RLS, read as "anon" inside Alpha), a form of an Alpha list takes a submission, the watchdog fires a reminder of
an Alpha task (background = "system"), the instance admin's overview counts both organisations,; the app role exists without a bypass
and may use the tables.
usage: rls_direct_test.py <datadir>      (a fresh container; the suite restarts it itself in mode workspaces)"""
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta

import dbx as dbxm
import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CONTAINER = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
MARK = "Rls7Alpha"
FEAT = "cal,collab,comments,events,contacts,clients,forms,office"
APP_ROLE = "kalmido_app"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sql(text, args=()):
    """Superuser psql (like every suite: bypasses row-level security) -> rows."""
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=20)
    try:
        return c.execute(text, args).fetchall()
    finally:
        c.close()


def as_app(stmts, role=None, orgs=None, uid=None):
    """Run statements as the app's role with the given context (None = not set at all) -> stdout lines / error text."""
    dbc, dbn = dbxm._target(DATA)
    pre = [f"SET ROLE {APP_ROLE};"]
    for k, v in (("app.role", role), ("app.org_ids", orgs), ("app.user_id", uid)):
        if v is not None:
            pre.append(f"SET {k} = '{v}';")
    try:
        return dbxm._psql(dbc, dbn, "\n".join(pre + stmts) + "\n").strip().split("\n"), None
    except dbxm.DbError as e:
        return None, str(e)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def restart(extra):
    e = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + extra)
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
# 2.46.0 (#1592): no organisation from the start any more: the admin creates the one these tests use (id 1), new people join it
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
A.post(B + "/api/admin/orgs", json={"name": "Kalmido"})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [1], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
restart("-e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_PUBLIC_LINKS=1")
A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALPHA = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
sql("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=1", (ALPHA,))  # alice administers Alpha (start-up sync only in mode organisation)
check(A.delete(B + f"/api/orgs/{ALPHA}/members/{CAROL}").ok, "setup: carol leaves Alpha")
check(sorted(x[0] for x in sql("SELECT user_id FROM org_members WHERE org_id=?", (ALPHA,))) == sorted([1, BOB])
      and [x[0] for x in sql("SELECT user_id FROM org_members WHERE org_id=?", (BETA,))] == [CAROL],
      "setup: Alpha = alice + bob, Beta = carol")

# ---- objects through the API (each organisation)
LA = Bo.post(B + "/api/lists", json={"name": f"{MARK} list", "org_id": ALPHA}).json()["id"]
LB = Ca.post(B + "/api/lists", json={"name": "Beta list", "org_id": BETA}).json()["id"]
for s, nm in ((Bo, f"{MARK} cal"), (Ca, "Beta cal")):
    assert s.post(B + "/api/evcals", json={"name": nm}).ok
    assert s.post(B + "/api/books", json={"name": nm.replace("cal", "book")}).ok
for s, o, nm in ((Bo, ALPHA, f"{MARK} client"), (Ca, BETA, "Beta client")):
    s.post(B + "/api/clients", json={"name": nm, "org_id": o})
for o in (ALPHA, BETA):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": f"bot{o}", "display_name": f"Bot {o}"})
    if r.ok:
        sql("UPDATE agents SET org_id=? WHERE user_id=?", (o, r.json()["id"]))

# ---- every other RLS table: one row per organisation straight in SQL (superuser), filled from the table's own columns
TABLES = [r[0] for r in sql("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                            "WHERE c.relrowsecurity AND c.relforcerowsecurity AND n.nspname=current_schema() ORDER BY 1")]
check(len(TABLES) >= 19 and {"lists", "agents", "orgs", "org_members", "office_docs", "ev_cals", "books", "clients"} <= set(TABLES),
      f"ENABLE + FORCE on every RLS table ({len(TABLES)}: {' '.join(TABLES)})")
check(all(sql("SELECT COUNT(*) FROM pg_policies WHERE tablename=?", (t,))[0][0] == 1 for t in TABLES), "one policy per table")
ORG_T = [t for t in TABLES if t not in ("orgs", "org_members")]
FK = {}
for t, col, ref in sql("""SELECT tc.table_name, kcu.column_name, ccu.table_name FROM information_schema.table_constraints tc
                          JOIN information_schema.key_column_usage kcu ON kcu.constraint_name=tc.constraint_name
                          JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name=tc.constraint_name
                          WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema=current_schema()"""):
    FK[(t, col)] = ref


def fill_row(t, org):
    cols = sql("""SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?
                  AND is_nullable='NO' AND column_default IS NULL AND is_identity='NO' AND column_name!='org_id'""", (t,))
    names, vals = ["org_id"], [str(org)]
    for name, typ in cols:
        ref = FK.get((t, name))
        if ref:
            has_org = sql("SELECT 1 FROM information_schema.columns WHERE table_name=? AND column_name='org_id'", (ref,))
            r = sql(f"SELECT MIN(id) FROM {ref}" + (" WHERE org_id=?" if has_org and ref != "orgs" else ""), (org,) if has_org and ref != "orgs" else ())
            v = r[0][0] if r and r[0][0] is not None else 1
        elif "int" in typ or typ in ("numeric", "double precision"):
            v = 0
        elif typ == "bytea":
            v = None
        elif typ == "jsonb":
            v = "{}"
        else:
            v = f"{MARK if org == ALPHA else 'b'}-{t}"
        if v is None:
            names.append(name)
            vals.append("'\\x00'::bytea")
            continue
        names.append(name)
        vals.append("'" + str(v).replace("'", "''") + "'")
    # 2.50.1 (#1194): quoted names - hub_bookings has the columns start / end (end is a reserved word)
    sql(f"INSERT INTO {t}({','.join(chr(34) + n + chr(34) for n in names)}) VALUES({','.join(vals)}) ON CONFLICT DO NOTHING")


for _ in range(3):  # a few rounds: tables that point at others of the same organisation
    for t in ORG_T:
        for o in (ALPHA, BETA):
            if not sql(f"SELECT 1 FROM {t} WHERE org_id=?", (o,)):
                try:
                    fill_row(t, o)
                except dbxm.DbError as e:
                    if _ == 2:
                        print("setup:", t, str(e)[:200])
for t in ORG_T:
    check(all(sql(f"SELECT 1 FROM {t} WHERE org_id=?", (o,)) for o in (ALPHA, BETA)), f"setup: {t} has a row of each organisation")


def count(t, where, **ctx):
    out, e = as_app([f"SELECT COUNT(*) FROM {t} WHERE {where};"], **ctx)
    return int(out[-1]) if out else e


# ---- reading
for t in ORG_T:
    total = sql(f"SELECT COUNT(*) FROM {t}")[0][0]
    check(count(t, f"org_id={ALPHA}", role="user", orgs=str(BETA), uid=CAROL) == 0, f"{t}: Beta's context sees no Alpha row")
    check(count(t, f"org_id={BETA}", role="user", orgs=str(BETA), uid=CAROL) >= 1, f"{t}: Beta's context sees its own rows")
    check(count(t, "org_id IS NOT NULL") == 0, f"{t}: without a context no organisation's row")
    check(count(t, "org_id IS NOT NULL", role="", orgs="") == 0, f"{t}: an empty context ('') = no organisation")
    check(count(t, f"org_id={ALPHA}", role="anon", orgs="") == 0, f"{t}: anon without a bound organisation: nothing")
    check(count(t, "true", role="system") == total, f"{t}: system sees all {total}")
check(count("orgs", "true", role="user", orgs=str(BETA), uid=CAROL) == 1, "orgs: only the own organisation")
check(count("orgs", "true") == 0 and count("orgs", "true", role="system") >= 2, "orgs: none without a context, all as system")
check(count("org_members", f"org_id={ALPHA}", role="user", orgs=str(BETA), uid=CAROL) == 0, "org_members: no rows of a foreign organisation")
check(count("org_members", f"user_id={CAROL}", role="user", orgs="", uid=CAROL) == 1, "org_members: the own rows (also without the organisation)")
# 2.46.0 (#1592): + the agents placed in Alpha (an organisation's agent is its member)
check(count("org_members", f"org_id={ALPHA}", role="user", orgs=str(ALPHA), uid=BOB) == sql("SELECT COUNT(*) FROM org_members WHERE org_id=?", (ALPHA,))[0][0] >= 2,
      "org_members: every row of the own organisation")
check(count("lists", f"org_id IS NULL AND owner_id={CAROL}", role="user", orgs=str(BETA), uid=CAROL) >= 1, "lists: private rows (org_id NULL) stay visible")

# ---- writing
for t in ORG_T:
    out, e = as_app([f"UPDATE {t} SET org_id={ALPHA} WHERE org_id={BETA};"], role="user", orgs=str(BETA), uid=CAROL)
    check(e is not None and "row-level security" in e, f"{t}: moving a row into a foreign organisation is refused ({(e or '')[:80]})")
    out, e = as_app([f"WITH u AS (UPDATE {t} SET org_id=org_id WHERE org_id={ALPHA} RETURNING 1) SELECT COUNT(*) FROM u;"],
                    role="user", orgs=str(BETA), uid=CAROL)
    check(e is None and out and out[-1] == "0", f"{t}: updating a foreign organisation's rows touches nothing ({e or out})")
    out, e = as_app([f"DELETE FROM {t} WHERE org_id={ALPHA};"], role="user", orgs=str(BETA), uid=CAROL)
    check(e is None and sql(f"SELECT COUNT(*) FROM {t} WHERE org_id=?", (ALPHA,))[0][0] >= 1, f"{t}: deleting a foreign organisation's rows removes nothing")
out, e = as_app([f"INSERT INTO lists(name,created_at,owner_id,org_id) VALUES('x','2026-01-01',{CAROL},{ALPHA});"], role="user", orgs=str(BETA), uid=CAROL)
check(e is not None and "row-level security" in e, "lists: INSERT with a foreign org_id is refused")
out, e = as_app([f"INSERT INTO org_list_log(org_id,action,created_at) VALUES({ALPHA},'x','2026-01-01');"], role="anon", orgs="")
check(e is not None and "row-level security" in e, "org_list_log: INSERT without a context is refused")
out, e = as_app([f"INSERT INTO org_members(org_id,user_id) VALUES({ALPHA},{BOB}) ON CONFLICT DO NOTHING;"], role="user", orgs=str(BETA), uid=CAROL)
check(e is not None and "row-level security" in e, "org_members: putting somebody else into a foreign organisation is refused")
out, e = as_app([f"INSERT INTO orgs(name,created_at) VALUES('Gamma','2026-01-01');"], role="user", orgs=str(BETA), uid=CAROL)
check(e is not None and "row-level security" in e, "orgs: a new organisation only as system (the app: instance admin, system_ctx)")
out, e = as_app([f"SELECT COUNT(*) FROM lists WHERE org_id={ALPHA};"], role="system")
check(out and int(out[-1]) >= 1, "system: reads every organisation")

# ---- the app's connections: kalmido_app with the request's context
st = Ca.get(B + "/api/state").json()
names = " ".join(x["name"] for x in st["lists"])
check(MARK not in names and "Beta list" in names, "API: carol's state has Beta's list, nothing of Alpha")
r = sql("SELECT CASE WHEN r.rolsuper OR r.rolbypassrls THEN 1 ELSE 0 END FROM pg_roles r WHERE r.rolname=?", (APP_ROLE,))
check(bool(r) and int(r[0][0]) == 0, f"{APP_ROLE}: exists, no superuser, no BYPASSRLS")
r = sql(f"SELECT CASE WHEN has_table_privilege('{APP_ROLE}', 'tasks', 'SELECT,INSERT,UPDATE,DELETE') THEN 1 ELSE 0 END")
check(bool(r) and int(r[0][0]) == 1, f"{APP_ROLE} may use the tables")

# ---- DAV: carol's calendar home has no Alpha calendar
pw = Ca.post(B + "/api/me/app-passwords", json={"name": "phone"}).json()
dav = requests.Session()
dav.auth = ("carol", pw.get("password") or "")
r = dav.request("PROPFIND", B + "/dav/calendars/carol/", headers={"Depth": "1"})
check(r.status_code == 207 and MARK not in r.text and "Beta cal" in r.text, f"DAV: carol sees her calendars, none of Alpha ({r.status_code})")
KA = sql("SELECT id FROM ev_cals WHERE org_id=? ORDER BY id LIMIT 1", (ALPHA,))[0][0]
check(dav.request("PROPFIND", B + f"/dav/calendars/carol/e{KA}/", headers={"Depth": "1"}).status_code in (403, 404), "DAV: Alpha's calendar by id: refused")
pwb = Bo.post(B + "/api/me/app-passwords", json={"name": "phone"}).json()
davb = requests.Session()
davb.auth = ("bob", pwb.get("password") or "")
r = davb.request("PROPFIND", B + "/dav/calendars/bob/", headers={"Depth": "1"})
check(r.status_code == 207 and f"{MARK} cal" in r.text, "DAV: bob sees Alpha's calendar (DAV requests read with bob's context)")

# ---- a public link of an Alpha list: resolved past RLS, shows exactly that list
TA = Bo.post(B + "/api/tasks", json={"title": f"{MARK} public task", "list_id": LA}).json()["id"]
Bo.post(B + "/api/tasks", json={"title": "other list task", "list_id": sql("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (BOB,))[0][0]})
r = Bo.put(B + f"/api/lists/{LA}/public-link", json={"mode": "tick"})
check(r.ok, "public link of an Alpha list " + r.text[:100])
url = r.json()["link"]["url"].replace("https://kalmido.example", "")
page = requests.get(B + url)
check(page.status_code == 200 and f"{MARK} public task" in page.text and "other list task" not in page.text,
      f"public link: the list's tasks, nothing else ({page.status_code})")
r = requests.post(B + url + "/tick", data={"task": str(TA), "to": "done"}, allow_redirects=False)
check(r.status_code == 303 and sql("SELECT status FROM tasks WHERE id=?", (TA,))[0][0] != 0, "public link: ticking writes inside Alpha (anon bound to it)")

# ---- a form of an Alpha list (public): the submission lands in the list
r = Bo.post(B + f"/api/lists/{LA}/forms", json={"title": f"{MARK} form", "access": "public"})
if r.status_code == 201:
    furl = r.json()["url"].replace("https://kalmido.example", "")
    requests.get(B + furl)
    r2 = requests.post(B + furl, data={"subject": "Form request", "text": "hello", "name": "Visitor"})
    check(r2.status_code == 200 and sql("SELECT COUNT(*) FROM tasks WHERE list_id=? AND title='Form request'", (LA,))[0][0] == 1,
          f"form: a visitor's request becomes a task of the Alpha list ({r2.status_code})")
else:
    check(False, "setup: a public form " + r.text[:120])

# ---- 2.37.0 (review K2-2): carol (signed in, organisation Beta) opens the public link and the public form of the Alpha list:
# both work as for a visitor without an account (read and written inside Alpha only), nothing of carol's own shows
TC = Bo.post(B + "/api/tasks", json={"title": f"{MARK} carol ticks", "list_id": LA}).json()["id"]
page = Ca.get(B + url)
check(page.status_code == 200 and f"{MARK} carol ticks" in page.text and "Beta list" not in page.text
      and "other list task" not in page.text and "Carol" not in page.text,
      f"K2-2: carol (Beta) opens the public link of an Alpha list: its tasks, nothing else ({page.status_code})")
r = Ca.post(B + url + "/tick", data={"task": str(TC), "to": "done"}, allow_redirects=False)
check(r.status_code == 303 and sql("SELECT status, completed_by FROM tasks WHERE id=?", (TC,))[0][0] != 0,
      f"K2-2: carol ticks through the public link ({r.status_code})")
if "furl" in globals():
    fp = Ca.get(B + furl)
    check(fp.status_code == 200 and f"{MARK} form" in fp.text and "Carol" not in fp.text and 'name="name"' in fp.text,
          f"K2-2: carol opens the public form of an Alpha list like a visitor ({fp.status_code})")
    r2 = Ca.post(B + furl, data={"subject": "Carol request", "text": "hi", "name": "Visitor C"})
    row = sql("SELECT created_by, content FROM tasks WHERE list_id=? AND title='Carol request'", (LA,))
    check(r2.status_code == 200 and len(row) == 1 and row[0][0] is None and "Visitor C" in row[0][1],
          f"K2-2: carol's form request lands in the Alpha list as a visitor's ({r2.status_code} {row})")
    check(MARK not in " ".join(x["name"] for x in Ca.get(B + "/api/state").json()["lists"]),
          "K2-2: afterwards carol's own state still has no Alpha list")

# ---- background work is "system": a reminder of an Alpha task fires
now = datetime.fromisoformat(subprocess.run(["docker", "exec", CONTAINER, "date", "+%Y-%m-%dT%H:%M:%S"], capture_output=True, text=True).stdout.strip())
due = now - timedelta(minutes=2)
TR = Bo.post(B + "/api/tasks", json={"title": f"{MARK} remind me", "list_id": LA}).json()["id"]
sql("UPDATE tasks SET due=?, due_time=?, reminders='0', reminded='[]' WHERE id=?", (due.date().isoformat(), due.strftime("%H:%M"), TR))
fired = False
for _ in range(30):
    time.sleep(0.5)
    if sql("SELECT reminded FROM tasks WHERE id=?", (TR,))[0][0] not in ("", "[]"):
        fired = True
        break
check(fired, "watchdog: the reminder of an organisation's task fires (background = system)")

# ---- the instance admin: the overview counts every organisation (structure as system), the content only his own
o = A.get(B + "/api/admin/orgs").json()
check({x["id"] for x in o["orgs"]} >= {ALPHA, BETA} and [x for x in o["orgs"] if x["id"] == BETA][0]["members"] == [CAROL],
      "admin overview: both organisations with their members")
cl = A.get(B + "/api/clients").json()
cl = cl.get("clients", cl) if isinstance(cl, dict) else cl
check(MARK + " client" in str(cl) and "Beta client" not in str(cl),
      "2.37.0 decision: the instance admin sees the clients of his own organisations only (was: all)")
st = A.get(B + "/api/state").json()
check("Beta list" not in " ".join(x["name"] for x in st["lists"]), "the instance admin's state: no list of an organisation he is not in")

print(f"\nrls_direct: {OKS[0]} ok, {len(FAILS)} failed")
raise SystemExit(1 if FAILS else 0)
