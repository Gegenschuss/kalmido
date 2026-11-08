#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.662.0 (#4602): tasks, comments, events and contacts carry their parent's organisation (org_id, filled by the triggers of
core/orgrows.py), so row-level security guards them as the second floor under vis_sql. Mode workspaces, Alpha (alice + bob),
Beta (carol), a freelancer without an organisation.
 1. writing through the app: a task / comment of an Alpha list, an event of an Alpha calendar, a contact of an Alpha address book
    get Alpha; the private ones NULL
 2. moves: a task to a private list and back (its comment follows), a list / calendar / address book changing organisation
    (and to private and back) carries its children
 3. the database itself as the app role: Beta's context sees no Alpha row of the four tables (a query without vis_sql), Alpha's
    sees them; an INSERT into an Alpha list from Beta's context is refused; a forged org_id is replaced by the parent's; an
    INSERT without org_id (the version before) is filled; anon bound to Alpha / unbound; an agent of Alpha / a private agent
 4. the freelancer keeps reading and writing their private tasks, comments, events and contacts
 5. the rows from before: with the fill triggers gone and org_id emptied, the next start fills the rows and puts the triggers back
 6. an organisation removed for good: its rows become private, the foreign keys do not fail
usage: p2662_a_rls_test.py <datadir>"""
import os
import sys

import kt
from kt import B, DATA, check, dbx, sess
import dbx as dbxm
from freelancer_fixture import freelancer

APP_ROLE = "kalmido_app"
FEAT = "cal,collab,comments,events,contacts,clients,forms,office"


def as_app(stmts, role=None, orgs=None, uid=None):
    """Statements as the app's role with the given context (None = not set) -> (stdout lines, error text) - like rls_direct."""
    dbc, dbn = dbxm._target(DATA)
    pre = [f"SET ROLE {APP_ROLE};"]
    for k, v in (("app.role", role), ("app.org_ids", orgs), ("app.user_id", uid)):
        if v is not None:
            pre.append(f"SET {k} = '{v}';")
    try:
        return dbxm._psql(dbc, dbn, "\n".join(pre + stmts) + "\n").strip().split("\n"), None
    except dbxm.DbError as e:
        return None, str(e)


def count(t, where, **ctx):
    out, e = as_app([f"SELECT COUNT(*) FROM {t} WHERE {where};"], **ctx)
    return int(out[-1]) if out else e


def org_of(t, i):
    r = dbx(f"SELECT org_id FROM {t} WHERE id=?", (i,))
    return r[0][0] if r else "missing"


kt.fresh()
A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
A.post(B + "/api/admin/orgs", json={"name": "Kalmido"})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [1], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_PUBLIC_LINKS": "1"}, keep=True)
A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALPHA = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=1", (ALPHA,))  # alice administers Alpha (moves tasks out of it)
check(A.delete(B + f"/api/orgs/{ALPHA}/members/{CAROL}").ok, "setup: carol leaves Alpha")
trg = sorted(x[0] for x in dbx("SELECT tgname FROM pg_trigger WHERE tgname LIKE 'kalmido_orw_%'"))
check(len(trg) == 8, f"eight triggers in place: four fill, four carry ({trg})")

# ---- 1. writing through the app
LA = A.post(B + "/api/lists", json={"name": "Alpha list", "org_id": ALPHA}).json()["id"]
LB = Ca.post(B + "/api/lists", json={"name": "Beta list", "org_id": BETA}).json()["id"]
INBOX = dbx("SELECT id FROM lists WHERE owner_id=1 AND is_inbox=1")[0][0]
check(dbx("SELECT org_id FROM lists WHERE id=?", (LA,))[0][0] == ALPHA and dbx("SELECT org_id FROM lists WHERE id=?", (INBOX,))[0][0] is None,
      "setup: an Alpha list, alice's private inbox")
TA = A.post(B + "/api/tasks", json={"title": "Alpha task", "list_id": LA}).json()["id"]
TP = A.post(B + "/api/tasks", json={"title": "Private task", "list_id": INBOX}).json()["id"]
TB = Ca.post(B + "/api/tasks", json={"title": "Beta task", "list_id": LB}).json()["id"]
r = A.post(B + f"/api/tasks/{TA}/comments", json={"body": "Alpha comment"})
check(r.ok, "comment on the Alpha task " + r.text[:120])
CA = dbx("SELECT id FROM comments WHERE task_id=? ORDER BY id DESC LIMIT 1", (TA,))[0][0]
A.post(B + f"/api/tasks/{TP}/comments", json={"body": "Private comment"})
CP = dbx("SELECT id FROM comments WHERE task_id=? ORDER BY id DESC LIMIT 1", (TP,))[0][0]
check(org_of("tasks", TA) == ALPHA and org_of("comments", CA) == ALPHA, "a task / comment of an Alpha list: org_id Alpha")
check(org_of("tasks", TP) is None and org_of("comments", CP) is None, "a task / comment of a private list: org_id NULL")
check(org_of("tasks", TB) == BETA, "a task of a Beta list: org_id Beta")
r = A.post(B + "/api/evcals", json={"name": "Alpha cal", "org_id": ALPHA})
check(r.status_code in (200, 201), "an Alpha calendar " + r.text[:120])
KA = r.json()["id"]
KP = A.post(B + "/api/evcals", json={"name": "Private cal", "org_id": None}).json()["id"]
check(dbx("SELECT org_id FROM ev_cals WHERE id=?", (KA,))[0][0] == ALPHA and dbx("SELECT org_id FROM ev_cals WHERE id=?", (KP,))[0][0] is None,
      "setup: an Alpha calendar, a private one")
day = kt.today().isoformat()
r = A.post(B + "/api/events", json={"title": "Alpha event", "cal_id": KA, "start": day + "T10:00", "end": day + "T11:00"})
check(r.status_code in (200, 201), "an event in the Alpha calendar " + r.text[:120])
EA = r.json()["id"]
EP = A.post(B + "/api/events", json={"title": "Private event", "cal_id": KP, "start": day + "T12:00", "end": day + "T13:00"}).json()["id"]
check(org_of("events", EA) == ALPHA and org_of("events", EP) is None, "events: Alpha calendar -> Alpha, private calendar -> NULL")
r = A.post(B + "/api/books", json={"name": "Alpha book", "org_id": ALPHA})
check(r.status_code in (200, 201), "an Alpha address book " + r.text[:120])
BA = r.json()["id"]
BP = A.post(B + "/api/books", json={"name": "Private book", "org_id": None}).json()["id"]
PA = A.post(B + "/api/contacts", json={"book_id": BA, "given": "Ada", "family": "Alpha"}).json()["id"]
PP = A.post(B + "/api/contacts", json={"book_id": BP, "given": "Pia", "family": "Private"}).json()["id"]
check(org_of("contacts", PA) == ALPHA and org_of("contacts", PP) is None, "contacts: Alpha book -> Alpha, private book -> NULL")

# ---- 2. moves
r = A.patch(B + f"/api/tasks/{TA}", json={"list_id": INBOX})
check(r.ok, "alice (admin of Alpha) moves the Alpha task into her private inbox " + r.text[:120])
check(org_of("tasks", TA) is None and org_of("comments", CA) is None, "moved to a private list: the task and its comment become private")
r = A.patch(B + f"/api/tasks/{TA}", json={"list_id": LA})
check(r.ok and org_of("tasks", TA) == ALPHA and org_of("comments", CA) == ALPHA, "moved back: Alpha again, with its comment")
# a parent changing its organisation: whatever the write path (here straight in SQL), the children follow
for parent, pid, kids in (("lists", LA, (("tasks", TA), ("comments", CA))), ("ev_cals", KA, (("events", EA),)),
                          ("books", BA, (("contacts", PA),))):
    dbx(f"UPDATE {parent} SET org_id=? WHERE id=?", (BETA, pid))
    check(all(org_of(t, i) == BETA for t, i in kids), f"{parent} moved to Beta: {', '.join(t for t, _ in kids)} follow")
    dbx(f"UPDATE {parent} SET org_id=NULL WHERE id=?", (pid,))
    check(all(org_of(t, i) is None for t, i in kids), f"{parent} made private: {', '.join(t for t, _ in kids)} become private")
    dbx(f"UPDATE {parent} SET org_id=? WHERE id=?", (ALPHA, pid))
    check(all(org_of(t, i) == ALPHA for t, i in kids), f"{parent} back in Alpha: {', '.join(t for t, _ in kids)} follow")
dbx("UPDATE events SET cal_id=? WHERE id=?", (KP, EA))
check(org_of("events", EA) is None, "an event moved to a private calendar: private")
dbx("UPDATE events SET cal_id=? WHERE id=?", (KA, EA))
check(org_of("events", EA) == ALPHA, "and back: Alpha")
dbx("UPDATE comments SET task_id=? WHERE id=?", (TP, CA))
check(org_of("comments", CA) is None, "a comment put on a private task: private")
dbx("UPDATE comments SET task_id=? WHERE id=?", (TA, CA))

# ---- 3. the database itself, as the app's role (no vis_sql: the second floor alone)
ROWS = (("tasks", TA), ("comments", CA), ("events", EA), ("contacts", PA))
for t, i in ROWS:
    check(count(t, f"id={i}", role="user", orgs=str(BETA), uid=CAROL) == 0, f"{t}: Beta's context does not see the Alpha row")
    check(count(t, f"id={i}", role="user", orgs=str(ALPHA), uid=BOB) == 1, f"{t}: Alpha's context sees it")
    check(count(t, f"id={i}", role="anon", orgs="") == 0, f"{t}: anon without a bound organisation: nothing")
    check(count(t, f"id={i}", role="anon", orgs=str(ALPHA)) == 1, f"{t}: anon bound to Alpha (a public link): the row")
    check(count(t, f"id={i}", role="agent", orgs=str(ALPHA), uid=BOB) == 1, f"{t}: an agent of Alpha: the row")
    check(count(t, f"id={i}", role="agent", orgs="", uid=BOB) == 0, f"{t}: a private agent: not the Alpha row")
    check(count(t, f"id={i}", role="system") == 1, f"{t}: system sees it")
for t, i in (("tasks", TP), ("comments", CP), ("events", EP), ("contacts", PP)):
    check(count(t, f"id={i}", role="user", orgs="", uid=1) == 1, f"{t}: the private row stays visible (org_id NULL)")
out, e = as_app([f"INSERT INTO tasks(list_id,title,created_at,updated_at) VALUES({LA},'carol sneaks in','2026-01-01','2026-01-01');"],
                role="user", orgs=str(BETA), uid=CAROL)
check(e is not None and "row-level security" in e, f"a task into an Alpha list from Beta's context is refused ({(e or out)})")
check(not dbx("SELECT 1 FROM tasks WHERE title='carol sneaks in'"), "... and not written")
out, e = as_app([f"INSERT INTO comments(task_id,body,created_at) VALUES({TA},'carol comments','2026-01-01');"], role="user", orgs=str(BETA), uid=CAROL)
check(e is not None and "row-level security" in e, f"a comment on an Alpha task from Beta's context is refused ({(e or out)})")
out, e = as_app([f"INSERT INTO tasks(list_id,title,created_at,updated_at,org_id) VALUES({LB},'forged','2026-01-01','2026-01-01',{ALPHA});"],
                role="user", orgs=f"{BETA}", uid=CAROL)
check(e is None and [x[0] for x in dbx("SELECT org_id FROM tasks WHERE title='forged'")] == [BETA],
      f"a forged org_id is replaced by the list's ({e or out})")
out, e = as_app([f"INSERT INTO tasks(list_id,title,created_at,updated_at) VALUES({LA},'old version','2026-01-01','2026-01-01');",
                 f"INSERT INTO comments(task_id,body,created_at) VALUES({TA},'old version','2026-01-01');",
                 f"INSERT INTO events(cal_id,uid,href,title,start,\"end\",created_at,updated_at) VALUES({KA},'u-old','h-old','old version','{day}T08:00','{day}T09:00','2026-01-01','2026-01-01');",
                 f"INSERT INTO contacts(book_id,uid,href,fn,created_at,updated_at) VALUES({BA},'c-old','c-old','old version','2026-01-01','2026-01-01');"],
                role="user", orgs=str(ALPHA), uid=BOB)
check(e is None, f"the version before writes without org_id ({e})")
for t in ("tasks", "events"):
    check([x[0] for x in dbx(f"SELECT org_id FROM {t} WHERE title='old version'")] == [ALPHA], f"{t}: a row without org_id gets the parent's")
check([x[0] for x in dbx("SELECT org_id FROM comments WHERE body='old version'")] == [ALPHA], "comments: a row without org_id gets the task's list's")
check([x[0] for x in dbx("SELECT org_id FROM contacts WHERE fn='old version'")] == [ALPHA], "contacts: a row without org_id gets the book's")
out, e = as_app([f"UPDATE tasks SET list_id={LB} WHERE id={TA};"], role="user", orgs=str(ALPHA), uid=BOB)
check(e is not None and "row-level security" in e and org_of("tasks", TA) == ALPHA,
      f"bob (Alpha only) cannot move a task into a Beta list on the database either ({(e or '')[:80]})")
# the search's trigram index under row-level security (information for the review, not a check: ILIKE is not leakproof)
out, e = as_app(["EXPLAIN SELECT id FROM tasks WHERE title ILIKE '%alpha%';"], role="user", orgs=str(ALPHA), uid=BOB)
print("info: search plan under row-level security:", " | ".join((out or [e or ""])[1:]))

# ---- 4. the freelancer: private rows, read and written as before
FID, Fr = freelancer(B, A)
st = Fr.get(B + "/api/state").json()
FIN = [x for x in st["lists"] if x.get("is_inbox")][0]["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Freelance task", "list_id": FIN}).json()["id"]
check(Fr.post(B + f"/api/tasks/{FT}/comments", json={"body": "Freelance note"}).ok, "freelancer: comments on the own task")
FK = Fr.post(B + "/api/evcals", json={"name": "Freelance cal"}).json()["id"]
FE = Fr.post(B + "/api/events", json={"title": "Freelance event", "cal_id": FK, "start": day + "T14:00", "end": day + "T15:00"})
check(FE.status_code in (200, 201), "freelancer: an event in the own calendar " + FE.text[:120])
FB = Fr.post(B + "/api/books", json={"name": "Freelance book"}).json()["id"]
FC = Fr.post(B + "/api/contacts", json={"book_id": FB, "given": "Fred", "family": "Client"})
check(FC.status_code in (200, 201), "freelancer: a contact in the own book " + FC.text[:120])
own_org = {x[0] for x in dbx("SELECT org_id FROM lists WHERE id=?", (FIN,))}
check(org_of("tasks", FT) in own_org, "freelancer: the task carries the inbox's organisation (NULL / the personal office)")
st = Fr.get(B + "/api/state").json()
check(any(t["id"] == FT for t in st["tasks"]), "freelancer: the own task in the state")
check("Freelance note" in Fr.get(B + f"/api/tasks/{FT}/timeline").text, "freelancer: the own comment is read back")
check("Freelance event" in Fr.get(B + f"/api/events?from={day}&to={day}").text, "freelancer: the own event is read back")
check("Fred" in Fr.get(B + f"/api/contacts?book_id={FB}").text, "freelancer: the own contact is read back")
check(Fr.patch(B + f"/api/tasks/{FT}", json={"title": "Freelance task 2"}).ok, "freelancer: the own task is changed")

# ---- 5. the rows from before: fill triggers gone, org_id empty -> the next start fills them and puts the triggers back
for t in ("tasks", "comments", "events", "contacts"):
    dbx(f"DROP TRIGGER IF EXISTS kalmido_orw_{t} ON {t}")
dbx("UPDATE tasks SET org_id=NULL WHERE id=?", (TA,))
dbx("UPDATE comments SET org_id=NULL WHERE id=?", (CA,))
dbx("UPDATE events SET org_id=NULL WHERE id=?", (EA,))
dbx("UPDATE contacts SET org_id=NULL WHERE id=?", (PA,))
check(all(org_of(t, i) is None for t, i in ROWS), "setup: the rows from before (no org_id)")
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_PUBLIC_LINKS": "1"}, keep=True)
check(all(org_of(t, i) == ALPHA for t, i in ROWS), "the start fills org_id from the parents")
check(len(dbx("SELECT tgname FROM pg_trigger WHERE tgname LIKE 'kalmido_orw_%'")) == 8, "... and the triggers are back")
A = sess("alice")
check(any(t["id"] == TA for t in A.get(B + "/api/state").json()["tasks"]), "alice still sees the Alpha task after the start")

# ---- 6. an organisation removed for good: the rows become private, no foreign key fails
r = A.post(B + "/api/admin/orgs", json={"name": "Gamma"})
GAMMA = r.json()["id"]
LG = dbx("INSERT INTO lists(name,created_at,owner_id,org_id) VALUES('Gamma list','2026-01-01',1,?) RETURNING id", (GAMMA,))[0][0]
TG = dbx("INSERT INTO tasks(list_id,title,created_at,updated_at) VALUES(?,'Gamma task','2026-01-01','2026-01-01') RETURNING id", (LG,))[0][0]
CG = dbx("INSERT INTO comments(task_id,body,created_at) VALUES(?,'Gamma comment','2026-01-01') RETURNING id", (TG,))[0][0]
check(org_of("tasks", TG) == GAMMA and org_of("comments", CG) == GAMMA, "setup: a Gamma task and comment")
try:
    dbx("DELETE FROM orgs WHERE id=?", (GAMMA,))
    check(org_of("tasks", TG) is None and org_of("comments", CG) is None, "the organisation removed: its task and comment became private")
except dbxm.DbError as e:  # another table may hold the organisation (not ours): only our foreign keys must not be the reason
    check(not any(x in str(e) for x in ("tasks_org_id", "comments_org_id", "events_org_id", "contacts_org_id")),
          f"removing the organisation fails on none of the new foreign keys ({str(e)[:160]})")

sys.exit(kt.done("p2662_a_rls"))
