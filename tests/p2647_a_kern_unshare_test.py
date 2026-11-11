#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.647.0 part A (#5046): a share of a calendar / an address book taken back IN the core (the file store's share dialog,
DELETE /api/files/shares) or run out there (expires_at in the past) ends what the old member tables ev_cal_members /
book_members still opened. Own container (no server key: the organisation export is a plain ZIP). Invented
names only.  freelancer-matrix: pim
 - a share deleted in the core (the file store's dialog) ends the membership, another person's stays; a role changed in the
   core is the role (2.924.0 #5069: the old member tables and the trigger kalmido_kern_back are gone, the node's shares decide)
 - reminders (events/model.py _wd_events): of a private calendar of a person without an organisation, shared with three
   people: the one taken back in the core and the one whose share ran out get no reminder, the one still shared does
   (regression: the old rows were read)
 - the heir of a deleted account (admin/purgeshare.py _plan, a person without an organisation): a calendar whose share
   with the longest-standing person ran out, a book whose share with her was taken back in the core: the heir is the
   other person, never the one taken back (regression)
 - the organisation export (admin/orgexport.py): 2.924.0 (#5069) no calendars/members.json / books/members.json any more
   (the shares are in store/shares.json); the import (admin/oi_team.py) of an archive that still has such files with a row
   whose node in the archive has no share of that person (doctored like an export of an older version) opens nothing to
   that person (regression), the other rows land as shares of the node
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
kt.fresh(env={"KALMIDO_API_RATE": "100000"}, prefix="P2647A")


def sql(q, args=(), write=False, quiet=False):
    """quiet: the write as an older version could leave it -- without the mirror triggers (app.kern_sync, 4712_a.py)."""
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(("SET app.kern_sync = '1'; " if quiet else "") + q, args)  # dbx: one psql per statement
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

# ================================================================== a share taken back / changed in the core
K = A.post(B + "/api/evcals", json={"name": "Studio plan", "org_id": ORG}).json()["id"]
BK = A.post(B + "/api/books", json={"name": "Studio contacts", "org_id": ORG}).json()["id"]
for url, rid in (("evcals", K), ("books", BK)):
    for who, role in ((BOB, "edit"), (GINA, "view")):
        check(A.put(B + f"/api/{url}/{rid}/members", json={"user_id": who, "role": role}).ok, f"setup: {url} {rid} shared with {who}")
check(sid("evcal", K, BOB), "setup: bob's core share")
r = A.delete(B + f"/api/files/shares/{sid('evcal', K, BOB)}")
check(r.ok, f"the calendar's share with bob taken back in the file store's dialog ({r.status_code} {r.text[:120]})")
check(sid("evcal", K, GINA), "gina's share stays")
check(K not in ids(Bo.get(B + "/api/evcals")), "bob does not see the calendar")
r = A.delete(B + f"/api/files/shares/{sid('address_book', BK, BOB)}")
check(r.ok and BK not in ids(Bo.get(B + "/api/books")), f"the book's share with bob taken back: he does not see it ({r.status_code})")
r = A.patch(B + f"/api/files/shares/{sid('evcal', K, GINA)}", json={"role": "edit"})
members = lambda: {m["user_id"]: m["role"] for c_ in A.get(B + "/api/evcals").json()["items"] if c_["id"] == K for m in c_.get("members") or []}  # noqa: E731
check(r.ok and members().get(GINA) == "edit", f"a role changed in the core is the calendar's role ({r.status_code} {members()})")
check(A.put(B + f"/api/evcals/{K}/members", json={"user_id": GINA, "role": "view"}).ok and members() == {GINA: "view"},
      "and back through the calendar's dialog: one share row, its role changed")

# ================================================================== reminders (a person without an organisation)
DORA, Do = freelancer(B, A, "dora")
FIONA, Fi = freelancer(B, A, "fiona")
HANK, Ha = freelancer(B, A, "hank")
IVY, Iv = freelancer(B, A, "ivy")
JUNO, Ju = freelancer(B, A, "juno")


def connect(a, b):  # an accepted connection request (accounts/discover.py): people without an organisation see each other
    sql("INSERT INTO conn_links(a_id,b_id,created_at) VALUES(?,?,'2026-11-01T00:00:00+00:00') ON CONFLICT DO NOTHING", (min(a, b), max(a, b)), write=True)


for owner_ in (DORA, JUNO):
    for who in (FIONA, HANK, IVY):
        connect(owner_, who)
KR = Do.post(B + "/api/evcals", json={"name": "Dora's rota", "org_id": None}).json()["id"]
for who in (FIONA, HANK, IVY):
    r = Do.put(B + f"/api/evcals/{KR}/members", json={"user_id": who, "role": "view"})
    check(r.ok, f"setup: dora's calendar shared with {who} {r.status_code} {r.text[:120]}")
r = Do.delete(B + f"/api/files/shares/{sid('evcal', KR, FIONA)}")
check(r.ok and sid("evcal", KR, FIONA) is None, f"fiona taken back in the core ({r.status_code})")
sql("UPDATE fs_shares SET expires_at='2020-01-01T00:00:00+00:00' WHERE id=?", (sid("evcal", KR, IVY),), write=True)  # ivy's ran out
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
KH = Ju.post(B + "/api/evcals", json={"name": "Juno's plan", "org_id": None}).json()["id"]
BH = Ju.post(B + "/api/books", json={"name": "Juno's people"}).json()["id"]
for url, rid in (("evcals", KH), ("books", BH)):
    for who in (FIONA, HANK):
        r = Ju.put(B + f"/api/{url}/{rid}/members", json={"user_id": who, "role": "edit"})
        check(r.ok, f"setup: juno's {url} shared with {who} {r.status_code} {r.text[:120]}")
# fiona is the longest-standing one (she would be the heir)
for kind, rid in (("evcal", KH), ("address_book", BH)):
    sql("UPDATE fs_shares SET created_at='2020-01-01T00:00:00+00:00' WHERE id=?", (sid(kind, rid, FIONA),), write=True)
sql("UPDATE fs_shares SET expires_at='2020-06-01T00:00:00+00:00' WHERE id=?", (sid("evcal", KH, FIONA),), write=True)  # ran out
check(Ju.delete(B + f"/api/files/shares/{sid('address_book', BH, FIONA)}").ok, "setup: the book's share with fiona taken back in the core")
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
check(sid("evcal", K, BOB) is None and K not in ids(Bo.get(B + "/api/evcals")) and BK not in ids(Bo.get(B + "/api/books")),
      "setup: bob has neither (taken back in the core)")
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, f"the organisation export starts {r.status_code} {r.text[:120]}")
until(lambda: A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running", 240)
st = A.get(B + f"/api/orgs/{ORG}/export").json()
check(st.get("state") == "done" and st.get("plain"), f"the export is done, a plain ZIP (no server key) {st}")
ox = su_get(A, B + f"/api/orgs/{ORG}/export/file").content
zf = zipfile.ZipFile(io.BytesIO(ox))
parts = {n: zf.read(n) for n in zf.namelist()}
check("calendars/members.json" not in parts and "books/members.json" not in parts,
      "2.924.0 (#5069): no members.json of calendars / books any more (their shares are in store/shares.json)")

# the archive of an older version (before 2.661): members.json with gina's rows and a stale row of bob (the core's shares.json
# without him)
cm = [{"cal_id": K, "user_id": GINA, "role": "view", "added_at": "2026-11-01T00:00:00+00:00", "hidden": 0},
      {"cal_id": K, "user_id": BOB, "role": "edit", "added_at": "2026-11-01T00:00:00+00:00", "hidden": 0}]
bm = [{"book_id": BK, "user_id": GINA, "role": "view", "added_at": "2026-11-01T00:00:00+00:00"},
      {"book_id": BK, "user_id": BOB, "role": "edit", "added_at": "2026-11-01T00:00:00+00:00"}]
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
check(sid("evcal", K2, GINA) and sid("address_book", BK2, GINA), "gina's shares of the calendar and the book came along")
check(len(sql("SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind='evcal' AND n.ref_id=? "
              "AND s.user_id=?", (K2, GINA))) == 1, "2.924.0 (#5069): one share of gina (members.json beside shares.json makes no second)")
check(sid("evcal", K2, BOB) is None, "#5046: the archive's stale row does not make bob a member of the imported calendar (regression)")
check(sid("address_book", BK2, BOB) is None, "#5046: nor of the imported book")
check(K2 not in ids(Bo.get(B + "/api/evcals")) and BK2 not in ids(Bo.get(B + "/api/books")), "#5046: bob sees neither")

sys.exit(kt.done("p2647_a_kern_unshare"))
