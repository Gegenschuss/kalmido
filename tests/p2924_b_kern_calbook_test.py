#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.924.0 part B (#5069, stage 7b of the shared core): calendars and address books are shared only by the shares of their
reference node; ev_cal_members, book_members and the mirror triggers are gone. Own container (mode workspaces, no server key:
the organisation export is a plain ZIP). Invented names only.  freelancer-matrix: pim
 - the start step (events/evkern.py ev_kern_drop, every start until done): the sync triggers are gone; old tables an older
   version left (made again here) -- a row of a calendar / book without a node gets its node and its share; a row whose node
   has no share of that person is deleted (fable F1, the log names the number) and both tables are dropped with the triggers
 - the start check (fable F1): a row the copy cannot give a node keeps the tables AND the triggers (no half state), the log
   says "waits" and the admins get an alert; the next start that can place it drops everything
 - a reminder after the share was taken back in the calendar's dialog: only the member still shared gets it
 - the heir of a deleted account (people without an organisation): a calendar shared through the calendar's dialog and
   one person taken back in the file store's dialog and restored through the core (GET / POST /api/obj/evcal/<id>/shares;
   fable F3: the restored person gets the News of the share, as from the dialog):
   the heir owns it, its node lives on in the heir's tree with the other member's share; a book the same way (its node kept,
   no longer dropped)
 - the import of an older organisation archive with calendars/members.json / books/members.json and no node in it: the rows
   become the shares of the imported object's node at once; the export of this version has no members.json of them
 - the calendar's trash emptied: calendar, node and shares go, nothing of the old tables is needed
usage: p2924_b_kern_calbook_test.py <datadir>"""
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, sess, su_get, until  # noqa: E402

FEAT = "cal,events,contacts,comments,collab,files"
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_API_RATE": "100000"}, prefix="P2924B")
kt.docker_logs_on_first_fail()


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


def box(code="pass"):
    """Python in the app container: `import app` is a start next to the running server (init_db with its START hooks)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code
                          + "\nc.commit()\nc.close()"], capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def ids(r):
    j = r.json() if r.ok else {}
    rows = j if isinstance(j, list) else (j.get("items") or j.get("data") or [])
    return {x.get("id") for x in rows}


def node(kind, rid):
    r = sql("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (kind, rid))
    return r[0][0] if r else None


def share(kind, rid, who):
    """(share id, role) of account who on the object's node, or None."""
    r = sql("SELECT s.id, s.role FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind=? AND n.ref_id=? "
            "AND (s.user_id=? OR s.agent_id=?) ORDER BY s.id", (kind, rid, who, who))
    return tuple(r[0]) if r else None


def table(t):
    return sql("SELECT to_regclass(?) IS NOT NULL", (t,))[0][0]


def EH(email):
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/me").json()["id"]
uid, S = {}, {}
for u in ("bob", "gina"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
    S[u] = sess(u)
    S[u].patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Bo, Gi = S["bob"], S["gina"]
BOB, GINA = uid["bob"], uid["gina"]
r = A.post(B + "/api/admin/orgs", json={"name": "Northwind Studio"})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT (org_id,user_id) DO UPDATE SET role='admin'", (ORG, ALICE), write=True)
for who in (BOB, GINA):
    mail = sql("SELECT email FROM users WHERE id=?", (who,))[0][0]
    check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": mail, "role": "member"}).ok, f"setup: {who} member of the organisation")

# ================================================================== the start step: tables and triggers gone
check(not table("ev_cal_members") and not table("book_members"), "#5069: a new database has neither ev_cal_members nor book_members")
check(not sql("SELECT 1 FROM pg_trigger WHERE tgname IN ('kalmido_kern_back','kalmido_kern_node_made','kalmido_kern_node_gone')")
      and not sql("SELECT 1 FROM pg_proc WHERE proname IN ('kalmido_kern_mirror','kalmido_kern_back','kalmido_kern_node_made','kalmido_kern_node_gone')"),
      "#5069: the sync triggers and their functions are gone")
K = A.post(B + "/api/evcals", json={"name": "Studio plan", "org_id": ORG}).json()["id"]
BK = A.post(B + "/api/books", json={"name": "Studio contacts", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/evcals/{K}/members", json={"user_id": BOB, "role": "edit"}).ok and share("evcal", K, BOB)[1] == "edit",
      "#5069: the calendar's dialog writes bob's share on its node")
check(A.put(B + f"/api/evcals/{K}/members", json={"user_id": BOB, "role": "view"}).ok and share("evcal", K, BOB)[1] == "view"
      and len(sql("SELECT 1 FROM fs_shares WHERE node_id=? AND user_id=?", (node("evcal", K), BOB))) == 1,
      "#5069: again: the same row, the role changed")
check(A.put(B + f"/api/books/{BK}/members", json={"user_id": GINA, "role": "edit"}).ok and BK in ids(Gi.get(B + "/api/books")),
      "#5069: the book's dialog: gina sees the book through the share of its node")

# an older version ran after a rollback: the old tables are there again, with a row of a calendar without a node (comes
# along) and a stale row (its calendar's node has no share of gina: the check holds the drop back)
KS = A.post(B + "/api/evcals", json={"name": "Rollback plan", "org_id": ORG}).json()["id"]
BS = A.post(B + "/api/books", json={"name": "Rollback book", "org_id": ORG}).json()["id"]
TS = "2026-11-01T00:00:00+00:00"
sql("CREATE TABLE ev_cal_members (cal_id BIGINT NOT NULL REFERENCES ev_cals(id) ON DELETE CASCADE, user_id BIGINT NOT NULL REFERENCES "
    "users(id) ON DELETE CASCADE, role TEXT NOT NULL DEFAULT 'view', hidden BIGINT NOT NULL DEFAULT 0, added_at TEXT NOT NULL, "
    "PRIMARY KEY (cal_id, user_id))", write=True)
sql("CREATE TABLE book_members (book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE, user_id BIGINT NOT NULL REFERENCES "
    "users(id) ON DELETE CASCADE, role TEXT NOT NULL DEFAULT 'view', added_at TEXT NOT NULL, PRIMARY KEY (book_id, user_id))", write=True)
sql("INSERT INTO ev_cal_members(cal_id,user_id,role,added_at) VALUES(?,?,'edit',?)", (KS, GINA, TS), write=True)
sql("INSERT INTO book_members(book_id,user_id,role,added_at) VALUES(?,?,'view',?)", (BS, BOB, TS), write=True)
sql("INSERT INTO ev_cal_members(cal_id,user_id,role,added_at) VALUES(?,?,'view',?)", (K, GINA, TS), write=True)  # stale: no share
check(node("evcal", KS) is None and node("address_book", BS) is None, "setup: old rows of a calendar / book without a node")
out = box()
# fable F1 (#5117, decided 08.11.2026): the stale row (a node without a share of that person) no longer holds the drop - it goes,
# the log names the number, the tables are dropped in the same start
check("old row(s) of" not in out, f"#5069 F1: a stale row does not hold the drop any more ({out[-300:]})")
check("1 stale row(s) of ev_cal_members deleted" in out, f"#5069 F1: the log names the number of stale rows deleted ({out[-300:]})")
check(share("evcal", KS, GINA) and share("evcal", KS, GINA)[1] == "edit" and share("address_book", BS, BOB)[1] == "view",
      "#5069: the copy before the check gave the node-less calendar / book their nodes and the rows their shares")
check(share("evcal", K, GINA) is None and K not in ids(Gi.get(B + "/api/evcals")),
      "#5069 F1: the stale row opens nothing and is not copied (the node says no)")
check("calendars / address books, stage 7b (#5069): every old row has its share in the shared core -- ev_cal_members, book_members dropped" in out,
      f"#5069: the start drops them ({out[-300:]})")
check(not table("ev_cal_members") and not table("book_members"), "#5069: both tables dropped")
check(not sql("SELECT 1 FROM pg_trigger WHERE tgname LIKE 'kalmido_kern_%'") and not sql("SELECT 1 FROM pg_proc WHERE proname='kalmido_kern_mirror'"),
      "#5069: with the triggers and the function of the old tables")
check(KS in ids(Gi.get(B + "/api/evcals")) and BS in ids(Bo.get(B + "/api/books")), "#5069: the members keep them after the drop")
out = box()
check("#5069" not in out, f"#5069: a later start does nothing ({out[-200:]})")

# fable F1: a row the copy cannot give a node (here: the node maker refuses, Denied) holds the drop -- tables and trigger stay
KN = A.post(B + "/api/evcals", json={"name": "Unplaced plan", "org_id": ORG}).json()["id"]
out = box("import kalmido.events.evkern as e\nfrom kalmido.core.errors import Denied\nfrom kalmido.notify.alerts import _AA\n"
          "def no(*a, **k):\n    raise Denied(404)\n"
          "c.execute('RESET ROLE')\n"  # the login role of the container (the pool's kalmido_app may not create tables)
          "c.execute(\"CREATE TABLE ev_cal_members (cal_id BIGINT NOT NULL REFERENCES ev_cals(id) ON DELETE CASCADE, user_id BIGINT NOT NULL "
          "REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL DEFAULT 'view', hidden BIGINT NOT NULL DEFAULT 0, added_at TEXT NOT NULL, "
          "PRIMARY KEY (cal_id, user_id))\")\n"
          "c.execute(\"CREATE OR REPLACE FUNCTION kalmido_kern_mirror() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$\")\n"
          "c.execute(\"CREATE TRIGGER kalmido_kern_mirror_cal AFTER INSERT ON ev_cal_members FOR EACH ROW EXECUTE FUNCTION kalmido_kern_mirror()\")\n"
          f"c.execute(\"INSERT INTO ev_cal_members(cal_id,user_id,role,added_at) VALUES({int(KN)},{int(BOB)},'view','{TS}')\")\n"
          "e.obj_node = no\ntry:\n    print('result', e.ev_kern_drop(c))\nexcept Exception as x:\n    print('ERR', repr(x)[:300])\n"
          "print('alert', [x[1] for x in _AA['q']])")
check("stage 7b (#5069): 1 old row(s) of ev_cal_members have no share in the shared core" in out, "#5069 F1: the start check holds the drop and the log names the row ("
      + out[-500:].replace("\n", " | ") + ")")
check("kern5069:ev_cal_members" in out, f"#5069 F1: the admins get an alert, not only a log line ({out[-300:]})")
check(table("ev_cal_members") and sql("SELECT 1 FROM pg_trigger WHERE tgname='kalmido_kern_mirror_cal'"),
      "#5069 F1: the table AND its trigger stay (no half state)")
check(KN not in ids(Bo.get(B + "/api/evcals")), "#5069: the waiting old row opens nothing (no reader reads it)")
out = box()
check("ev_cal_members dropped" in out and not table("ev_cal_members")
      and not sql("SELECT 1 FROM pg_trigger WHERE tgname='kalmido_kern_mirror_cal'") and not sql("SELECT 1 FROM pg_proc WHERE proname='kalmido_kern_mirror'"),
      f"#5069 F1: the next start places it and drops table, trigger and function ({out[-300:]})")
check(share("evcal", KN, BOB) and share("evcal", KN, BOB)[1] == "view" and KN in ids(Bo.get(B + "/api/evcals")),
      "#5069: the row became bob's share of the node")

# ================================================================== a reminder after the share was taken back
check(A.put(B + f"/api/evcals/{K}/members", json={"user_id": GINA, "role": "view"}).ok, "setup: gina shared on the calendar as well")
check(A.delete(B + f"/api/evcals/{K}/members/{GINA}").ok and share("evcal", K, GINA) is None, "#5069: gina taken back in the calendar's dialog")
check(A.delete(B + f"/api/evcals/{K}/members/{GINA}").status_code == 404, "#5069: taking back someone who is no member: 404")
st = (datetime.now(timezone.utc) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M")
en = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M")
r = A.post(B + "/api/events", json={"cal_id": K, "title": "Load-in", "start": st, "end": en, "reminders": [1440]})
check(r.ok, f"setup: an event with a due reminder {r.text[:160]}")
EV = (r.json() or {}).get("id")
check(until(lambda: sql("SELECT 1 FROM ev_reminded WHERE event_id=? AND user_id=?", (EV, BOB)), 40),
      "#5069: the reminder reaches bob (shared on the node) -- the watchdog ran")
check(not sql("SELECT 1 FROM ev_reminded WHERE event_id=? AND user_id=?", (EV, GINA)), "#5069: none for gina, taken back")

# ================================================================== the heir of a deleted account (people without an organisation)
DORA, Do = freelancer(B, A, "dora")
FIONA, Fi = freelancer(B, A, "fiona")
HANK, Ha = freelancer(B, A, "hank")
for a_, b_ in ((DORA, FIONA), (DORA, HANK)):  # an accepted connection: people without an organisation see each other
    sql("INSERT INTO conn_links(a_id,b_id,created_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (min(a_, b_), max(a_, b_), TS), write=True)
KH = Do.post(B + "/api/evcals", json={"name": "Dora's rota", "org_id": None}).json()["id"]
BH = Do.post(B + "/api/books", json={"name": "Dora's people"}).json()["id"]
for url, rid in (("evcals", KH), ("books", BH)):
    for who, role in ((HANK, "edit"), (FIONA, "view")):
        check(Do.put(B + f"/api/{url}/{rid}/members", json={"user_id": who, "role": role}).ok, f"setup: dora's {url} shared with {who}")
for kind, rid in (("evcal", KH), ("address_book", BH)):  # hank is the longest-standing one with edit: the heir
    sql("UPDATE fs_shares SET created_at='2020-01-01T00:00:00+00:00' WHERE id=?", (share(kind, rid, HANK)[0],), write=True)
# fiona's calendar share taken back in the file store's dialog and given back through the core's restore
check(Do.delete(B + f"/api/files/shares/{share('evcal', KH, FIONA)[0]}").ok and KH not in ids(Fi.get(B + "/api/evcals")),
      "setup: fiona taken back in the file store's dialog")
r = Do.get(B + f"/api/obj/evcal/{KH}/shares")
rev = [x["id"] for x in (r.json().get("revoked") or []) if x.get("user_id") == FIONA] if r.ok else []
check(len(rev) == 1, f"#5069: the calendar's shares taken back are listed for its owner ({r.status_code} {r.text[:200]})")
check(Fi.get(B + f"/api/obj/evcal/{KH}/shares").status_code == 404, "#5069: not for anyone else")
news = lambda: sql("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='evshare'", (FIONA,))[0][0]  # noqa: E731
n0 = news()
r = Do.post(B + f"/api/obj/evcal/{KH}/shares/{rev[0] if rev else 0}/restore")
check(r.ok and KH in ids(Fi.get(B + "/api/evcals")) and share("evcal", KH, FIONA)[1] == "view",
      f"#5069: the owner restores it (a share only the core wrote) ({r.status_code} {r.text[:160]})")
check(news() == n0 + 1, f"#5069 F3: fiona gets the News of the share again, as from the calendar's dialog ({n0} -> {news()})")
check(A.get(B + "/api/obj/evcal").status_code == 404, "#5069: the generic list route stays closed for the kind")
r = A.delete(B + f"/api/users/{DORA}")
check(r.ok, f"dora's account goes {r.status_code} {r.text[:160]}")
own = lambda t, rid: (sql(f"SELECT owner_id FROM {t} WHERE id=?", (rid,)) or [(None,)])[0][0]  # noqa: E731
check(own("ev_cals", KH) == HANK and own("books", BH) == HANK, f"the heir is hank ({own('ev_cals', KH)} {own('books', BH)})")
for kind, rid, url, sx in (("evcal", KH, "evcals", Fi), ("address_book", BH, "books", Fi)):
    n = sql("SELECT owner_id, org_id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (kind, rid))
    check(n == [(HANK, None)], f"#5069: {kind}: its node lives on in hank's private tree ({n})")
    check(share(kind, rid, HANK) is None, f"#5069: {kind}: the heir has no share of his own")
    check(share(kind, rid, FIONA) and share(kind, rid, FIONA)[1] == "view" and rid in ids(sx.get(B + f"/api/{url}")),
          f"#5069: {kind}: fiona keeps her share and sees it (regression: the node went with dora's tree)")

# ================================================================== the calendar's trash emptied
KT = A.post(B + "/api/evcals", json={"name": "Old season", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/evcals/{KT}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: a calendar shared with bob")
NT = node("evcal", KT)
check(A.delete(B + f"/api/evcals/{KT}").ok and KT not in ids(Bo.get(B + "/api/evcals")), "the calendar into the trash")
out = box("from kalmido.core.pg import system_ctx\nfrom kalmido.events.evkern import ev_cal_trash_purge\n"
          "with system_ctx(c):\n    print('purged', ev_cal_trash_purge(c, '9999', True))")
check("purged 1" in out, f"#5069: the trash emptied without an error ({out[-300:]})")
check(not sql("SELECT 1 FROM ev_cals WHERE id=?", (KT,)) and not sql("SELECT 1 FROM fs_nodes WHERE id=?", (NT,))
      and not sql("SELECT 1 FROM fs_shares WHERE node_id=?", (NT,)), "#5069: calendar, node and shares are gone")
check(K in ids(Bo.get(B + "/api/evcals")), "#5069: the other calendar stays")

# ================================================================== the import of an older archive with members.json
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, f"the organisation export starts {r.status_code} {r.text[:120]}")
until(lambda: A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running", 240)
st_ = A.get(B + f"/api/orgs/{ORG}/export").json()
check(st_.get("state") == "done" and st_.get("plain"), f"the export is done, a plain ZIP {st_}")
zf = zipfile.ZipFile(io.BytesIO(su_get(A, B + f"/api/orgs/{ORG}/export/file").content))
parts = {n: zf.read(n) for n in zf.namelist()}
check("calendars/members.json" not in parts and "books/members.json" not in parts, "#5069: the export has no members.json of calendars / books")
# an archive of a version before 2.566: no reference nodes of calendars / books, their members in members.json
nodes = json.loads(parts.get("store/nodes.json") or b"[]")
gone = {x["id"] for x in nodes if x.get("kind") == "ref" and x.get("ref_kind") in ("evcal", "address_book")}
parts["store/nodes.json"] = json.dumps([x for x in nodes if x["id"] not in gone]).encode()
for p_ in ("store/shares.json", "store/history.json"):
    if p_ in parts:
        parts[p_] = json.dumps([x for x in json.loads(parts[p_]) if x.get("node_id") not in gone]).encode()
parts["calendars/members.json"] = json.dumps([{"cal_id": K, "user_id": BOB, "role": "edit", "added_at": TS, "hidden": 0}]).encode()
parts["books/members.json"] = json.dumps([{"book_id": BK, "user_id": BOB, "role": "view", "added_at": TS},
                                          {"book_id": BK, "user_id": ALICE, "role": "edit", "added_at": TS}]).encode()
man = json.loads(parts.pop("manifest.json"))
man["files"] = {n: {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for n, b in parts.items()}
bio = io.BytesIO()
with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("manifest.json", json.dumps(man))
    for n, b in parts.items():
        z.writestr(n, b)
data = bio.getvalue()
r = A.post(B + "/api/admin/orgs", json={"name": "Southwind Works", "admin_id": ALICE})
check(r.status_code in (200, 201), f"setup: the empty target organisation {r.text[:120]}")
ORG2 = r.json()["id"]
check(A.put(B + f"/api/orgs/{ORG2}/members", json={"email": "bob@example.com", "role": "member"}).ok, "setup: bob member of the target")
r = A.post(B + "/api/account/import", json={"size": len(data), "name": "northwind.kalmido-export"})
assert r.ok, r.text
iid, off = r.json()["id"], 0
while off < len(data):
    part = data[off:off + (1 << 20)]
    assert A.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"}).ok
    off += len(part)


def import_state():
    j = A.get(B + f"/api/account/import/{iid}").json()
    return j if j.get("state") not in ("checking", "running", "upload") else None


j = until(import_state, 240) or {}
check(j.get("state") == "preview", f"the older archive opens {j.get('state')} {j.get('error')}")
r = A.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": ORG2, "people": {EH("bob@example.com"): {"share": True}}})
check(r.status_code == 202, f"the import runs {r.status_code} {r.text[:160]}")
time.sleep(0.3)
j = until(import_state, 240) or {}
check(j.get("state") == "done", f"the import is done {j.get('state')} {j.get('error')}")
K2 = (sql("SELECT id FROM ev_cals WHERE org_id=? AND name='Studio plan'", (ORG2,)) or [(None,)])[0][0]
BK2 = (sql("SELECT id FROM books WHERE org_id=? AND name='Studio contacts'", (ORG2,)) or [(None,)])[0][0]
check(K2 and BK2, f"the calendar and the book came along {K2} {BK2}")
check(node("evcal", K2) and share("evcal", K2, BOB) and share("evcal", K2, BOB)[1] == "edit",
      "#5069: the archive's member row is bob's share of the imported calendar's node (made at once)")
check(node("address_book", BK2) and share("address_book", BK2, BOB) and share("address_book", BK2, BOB)[1] == "view",
      "#5069: and of the imported book's node")
check(share("address_book", BK2, ALICE) is None, "#5069: the importing person (its owner) gets no share of her own")
check(K2 in ids(Bo.get(B + "/api/evcals")) and BK2 in ids(Bo.get(B + "/api/books")), "#5069: bob sees both")

sys.exit(kt.done("p2924_b_kern_calbook"))
