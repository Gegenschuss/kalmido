#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.647.0 part A (#5046): a share of a calendar / an address book taken back IN the core (the file store's share dialog,
DELETE /api/files/shares) or run out there (expires_at in the past) ends what the old member tables ev_cal_members /
book_members still opened. Own container (mode workspaces, no server key: the organisation export is a plain ZIP). Invented
names only.  freelancer-matrix: pim
 - the trigger kalmido_kern_back (core -> old): a share deleted in the core takes the old member row with it, another
   person's row stays; a role changed in the core gives the old row the same role (regression: the row stood)
 - reminders (events/model.py _wd_events): of a private calendar of a person without an organisation, shared with three
   people: the one taken back in the core and the one whose share ran out get no reminder, the one still shared does
   (regression: the old rows were read)
 - the heir of a deleted account (admin/purgeshare.py _plan, a person without an organisation): a calendar whose share
   with the longest-standing person ran out, a book whose share with her was taken back in the core: the heir is the
   other person, never the one taken back (regression)
 - the organisation export (admin/orgexport.py): members.json of a calendar / book with a node names only the people with a
   live share on it, also when an old row stood left behind (as before 2.647); the import (admin/oi_team.py) of an archive
   that still has such a row (doctored like an export of an older version) opens nothing to that person (regression)
usage: p2647_a_kern_unshare_test.py <datadir>"""
import hashlib
import io
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, check, sess, su_get, until  # noqa: E402

FEAT = "cal,events,contacts,comments,collab,files"
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_API_RATE": "100000"}, prefix="P2647A")


def sql(q, args=(), write=False, quiet=False):
    """quiet: the write as an older version could leave it -- without the mirror triggers (app.kern_sync, 4712_a.py)."""
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        if quiet:
            c.execute("SELECT set_config('app.kern_sync', '1', true)")
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def ids(r):
    j = r.json() if r.ok else {}
    rows = j if isinstance(j, list) else (j.get("items") or j.get("data") or [])
    return {x.get("id") for x in rows}


def node(kind, rid):
    r = sql("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (kind, rid))
    return r[0][0] if r else None


def sid(kind, rid, who):
    r = sql("SELECT s.id FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind=? AND n.ref_id=? "
            "AND (s.user_id=? OR s.agent_id=?)", (kind, rid, who, who))
    return r[0][0] if r else None


def old_row(table, col, rid, who):
    r = sql(f"SELECT role FROM {table} WHERE {col}=? AND user_id=?", (rid, who))
    return r[0][0] if r else None


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
    r = A.put(B + f"/api/orgs/{ORG}/members", json={"email": mail, "role": "member"})
    check(r.ok, f"setup: {who} member of the organisation {r.text[:160]}")

# ================================================================== the trigger: core -> old member rows
K = A.post(B + "/api/evcals", json={"name": "Studio plan", "org_id": ORG}).json()["id"]
BK = A.post(B + "/api/books", json={"name": "Studio contacts", "org_id": ORG}).json()["id"]
for url, rid in (("evcals", K), ("books", BK)):
    for who, role in ((BOB, "edit"), (GINA, "view")):
        check(A.put(B + f"/api/{url}/{rid}/members", json={"user_id": who, "role": role}).ok, f"setup: {url} {rid} shared with {who}")
check(old_row("ev_cal_members", "cal_id", K, BOB) == "edit" and sid("evcal", K, BOB), "setup: bob's old row and his core share")
r = A.delete(B + f"/api/files/shares/{sid('evcal', K, BOB)}")
check(r.ok, f"the calendar's share with bob taken back in the file store's dialog ({r.status_code} {r.text[:120]})")
check(old_row("ev_cal_members", "cal_id", K, BOB) is None, "#5046: bob's old member row of the calendar goes with it (regression: it stood)")
check(old_row("ev_cal_members", "cal_id", K, GINA) == "view" and sid("evcal", K, GINA), "gina's row and share stay")
check(K not in ids(Bo.get(B + "/api/evcals")), "bob does not see the calendar")
r = A.delete(B + f"/api/files/shares/{sid('address_book', BK, BOB)}")
check(r.ok and old_row("book_members", "book_id", BK, BOB) is None, f"#5046: the book's share with bob taken back: his old row goes too ({r.status_code})")
r = A.patch(B + f"/api/files/shares/{sid('evcal', K, GINA)}", json={"role": "edit"})
check(r.ok and old_row("ev_cal_members", "cal_id", K, GINA) == "edit", f"#5046: a role changed in the core: the old row follows ({r.status_code})")
check(A.put(B + f"/api/evcals/{K}/members", json={"user_id": GINA, "role": "view"}).ok and sid("evcal", K, GINA)
      and old_row("ev_cal_members", "cal_id", K, GINA) == "view", "and back through the calendar's dialog (old -> core, no loop)")

# ================================================================== reminders (a person without an organisation)
DORA, Do = freelancer(B, A, "dora")
FIONA, Fi = freelancer(B, A, "fiona")
HANK, Ha = freelancer(B, A, "hank")
IVY, Iv = freelancer(B, A, "ivy")
KR = Do.post(B + "/api/evcals", json={"name": "Dora's rota", "org_id": None}).json()["id"]
for who in (FIONA, HANK, IVY):
    check(Do.put(B + f"/api/evcals/{KR}/members", json={"user_id": who, "role": "view"}).ok, f"setup: dora's calendar shared with {who}")
r = Do.delete(B + f"/api/files/shares/{sid('evcal', KR, FIONA)}")
check(r.ok and old_row("ev_cal_members", "cal_id", KR, FIONA) is None, f"fiona taken back in the core ({r.status_code})")
sql("UPDATE fs_shares SET expires_at='2020-01-01T00:00:00+00:00' WHERE id=?", (sid("evcal", KR, IVY),), write=True)  # ivy's ran out
check(old_row("ev_cal_members", "cal_id", KR, IVY) == "view", "setup: ivy's old row stands (an expiry is no event of the database)")
check(KR not in ids(Iv.get(B + "/api/evcals")) and KR not in ids(Fi.get(B + "/api/evcals")) and KR in ids(Ha.get(B + "/api/evcals")),
      "fiona and ivy no longer see the calendar, hank does")
# a reminder that is due whatever the server's clock zone: a day before, the start six hours from now (UTC)
st = (datetime.now(timezone.utc) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M")
en = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M")
r = Do.post(B + "/api/events", json={"cal_id": KR, "title": "Load-in", "start": st, "end": en, "reminders": [1440]})
check(r.ok, f"setup: an event with a due reminder {r.text[:160]}")
EV = (r.json() or {}).get("id")
check(until(lambda: sql("SELECT 1 FROM ev_reminded WHERE event_id=? AND user_id=?", (EV, HANK)), 30),
      "the reminder reaches hank (still shared) -- the watchdog ran")
check(until(lambda: sql("SELECT 1 FROM ev_reminded WHERE event_id=? AND user_id=?", (EV, DORA)), 10), "and dora, the owner")
check(not sql("SELECT 1 FROM ev_reminded WHERE event_id=? AND user_id=?", (EV, FIONA)),
      "#5046: no reminder for fiona, taken back in the core (regression)")
check(not sql("SELECT 1 FROM ev_reminded WHERE event_id=? AND user_id=?", (EV, IVY)),
      "#5046: no reminder for ivy, whose share ran out (regression: her old row was read)")

# ================================================================== the heir of a deleted account (people without an organisation)
JUNO, Ju = freelancer(B, A, "juno")
KH = Ju.post(B + "/api/evcals", json={"name": "Juno's plan", "org_id": None}).json()["id"]
BH = Ju.post(B + "/api/books", json={"name": "Juno's people"}).json()["id"]
for url, rid in (("evcals", KH), ("books", BH)):
    for who in (FIONA, HANK):
        check(Ju.put(B + f"/api/{url}/{rid}/members", json={"user_id": who, "role": "edit"}).ok, f"setup: juno's {url} shared with {who}")
# fiona is the longest-standing one (she would be the heir)
for kind, rid, t, col in (("evcal", KH, "ev_cal_members", "cal_id"), ("address_book", BH, "book_members", "book_id")):
    sql("UPDATE fs_shares SET created_at='2020-01-01T00:00:00+00:00' WHERE id=?", (sid(kind, rid, FIONA),), write=True)
    sql(f"UPDATE {t} SET added_at='2020-01-01T00:00:00+00:00' WHERE {col}=? AND user_id=?", (rid, FIONA), write=True)
sql("UPDATE fs_shares SET expires_at='2020-06-01T00:00:00+00:00' WHERE id=?", (sid("evcal", KH, FIONA),), write=True)  # ran out
check(Ju.delete(B + f"/api/files/shares/{sid('address_book', BH, FIONA)}").ok, "setup: the book's share with fiona taken back in the core")
sql("INSERT INTO book_members(book_id,user_id,role,added_at) VALUES(?,?,'edit','2020-01-01T00:00:00+00:00') ON CONFLICT DO NOTHING",
    (BH, FIONA), write=True, quiet=True)  # a row left behind by a version before 2.647 (no mirror)
check(old_row("book_members", "book_id", BH, FIONA) == "edit" and sid("address_book", BH, FIONA) is None, "setup: fiona's stale book row")
d = A.get(B + f"/api/users/{JUNO}/delete-info").json()
names = set((d.get("purge") or {}).get("shared", {}).get("names") or [])
check(names == {"Hank"}, f"#5046: the delete dialog names hank as the heir, not fiona ({names})")
r = A.delete(B + f"/api/users/{JUNO}")
check(r.ok, f"juno's account goes {r.status_code} {r.text[:160]}")
own = lambda t, rid: (sql(f"SELECT owner_id FROM {t} WHERE id=?", (rid,)) or [(None,)])[0][0]  # noqa: E731
check(own("ev_cals", KH) == HANK, f"#5046: the calendar goes to hank, not to fiona whose share ran out (regression) ({own('ev_cals', KH)})")
check(own("books", BH) == HANK, f"#5046: the book goes to hank, not to fiona taken back in the core (regression) ({own('books', BH)})")
check(KH not in ids(Fi.get(B + "/api/evcals")) and BH not in ids(Fi.get(B + "/api/books")), "fiona sees neither")

# ================================================================== the organisation export and its import
# a row left behind by a version before 2.647: bob's old rows stand again beside the core, which took him back
sql("INSERT INTO ev_cal_members(cal_id,user_id,role,added_at) VALUES(?,?,'edit','2026-11-01T00:00:00+00:00') ON CONFLICT DO NOTHING",
    (K, BOB), write=True, quiet=True)
sql("INSERT INTO book_members(book_id,user_id,role,added_at) VALUES(?,?,'edit','2026-11-01T00:00:00+00:00') ON CONFLICT DO NOTHING",
    (BK, BOB), write=True, quiet=True)
check(old_row("ev_cal_members", "cal_id", K, BOB) == "edit" and sid("evcal", K, BOB) is None, "setup: bob's stale calendar row, no core share")
check(K not in ids(Bo.get(B + "/api/evcals")) and BK not in ids(Bo.get(B + "/api/books")), "the stale rows open nothing to bob")
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, f"the organisation export starts {r.status_code} {r.text[:120]}")
until(lambda: A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running", 240)
st = A.get(B + f"/api/orgs/{ORG}/export").json()
check(st.get("state") == "done" and st.get("plain"), f"the export is done, a plain ZIP (no server key) {st}")
ox = su_get(A, B + f"/api/orgs/{ORG}/export/file").content
zf = zipfile.ZipFile(io.BytesIO(ox))
parts = {n: zf.read(n) for n in zf.namelist()}
cm = json.loads(parts.get("calendars/members.json") or b"[]")
bm = json.loads(parts.get("books/members.json") or b"[]")
check({(x.get("cal_id"), x.get("user_id")) for x in cm} == {(K, GINA)}, f"#5046: calendars/members.json names gina only, not bob's stale row (regression) {cm}")
check({(x.get("book_id"), x.get("user_id")) for x in bm} == {(BK, GINA)}, f"#5046: books/members.json names gina only {bm}")

# the archive of an older version: bob's rows still in it (the core's shares.json without him)
cm.append({"cal_id": K, "user_id": BOB, "role": "edit", "added_at": "2026-11-01T00:00:00+00:00", "hidden": 0})
bm.append({"book_id": BK, "user_id": BOB, "role": "edit", "added_at": "2026-11-01T00:00:00+00:00"})
parts["calendars/members.json"], parts["books/members.json"] = json.dumps(cm).encode(), json.dumps(bm).encode()
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
for who in (BOB, GINA):
    mail = sql("SELECT email FROM users WHERE id=?", (who,))[0][0]
    check(A.put(B + f"/api/orgs/{ORG2}/members", json={"email": mail, "role": "member"}).ok, f"setup: {who} member of the target")
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
check(j.get("state") == "preview", f"the doctored archive opens {j.get('state')} {j.get('error')}")
r = A.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": ORG2, "people": {
    EH("bob@example.com"): {"share": True}, EH("gina@example.com"): {"share": True}}})
check(r.status_code == 202, f"the import runs {r.status_code} {r.text[:160]}")
time.sleep(0.3)
j = until(import_state, 240) or {}
check(j.get("state") == "done", f"the import is done {j.get('state')} {j.get('error')}")
K2 = (sql("SELECT id FROM ev_cals WHERE org_id=? AND name='Studio plan'", (ORG2,)) or [(None,)])[0][0]
BK2 = (sql("SELECT id FROM books WHERE org_id=? AND name='Studio contacts'", (ORG2,)) or [(None,)])[0][0]
check(K2 and BK2, f"the calendar and the book came along {K2} {BK2}")
check(old_row("ev_cal_members", "cal_id", K2, GINA) == "view" or sid("evcal", K2, GINA), "gina's share of the calendar came along")
check(old_row("ev_cal_members", "cal_id", K2, BOB) is None and sid("evcal", K2, BOB) is None,
      "#5046: the archive's stale row does not make bob a member of the imported calendar (regression)")
check(old_row("book_members", "book_id", BK2, BOB) is None and sid("address_book", BK2, BOB) is None,
      "#5046: nor of the imported book")
check(K2 not in ids(Bo.get(B + "/api/evcals")) and BK2 not in ids(Bo.get(B + "/api/books")), "#5046: bob sees neither")

sys.exit(kt.done("p2647_a_kern_unshare"))
