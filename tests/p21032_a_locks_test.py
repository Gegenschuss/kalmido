#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1032.0 (#5788): the last rare deadlock windows of the review of 2.1017 and the address path of a folder share. Own
container, invented names only.  freelancer-matrix: lists
 - (F2) admin/purgeshare.py _books: the hand-on of a deleted person's address books writes every book's row first and only
   then the shares on their nodes -- while it waits for the row of book 2 (the members dialog of book 2 holds it), the share
   bucket of book 1's new member is free (before: held, and the dialog waited for it: deadlock)
 - (F3) lists member_set takes the share's bucket BEFORE it writes the list_members row (the order of lffolder.lf_folder_share:
   buckets, then list_members): while another writer holds the bucket, the member row is free
 - (F4) a retired organisation (accounts/orgretain.py odl_retire): the calendars' events / the books' contacts are locked
   before the calendar's / book's row (the org_id trigger writes the children after the object): while an event's / a
   contact's save holds its row, the calendar's / book's row is free
 - (F4) a knowledge page moved into a private space (wiki/wkmove.py wkm_place): its files before the page's row
 - folder share by e-mail address (PUT /api/folders/people): an account outside the organisation of a list in the folder
   (archived too) gets the neutral answer and no share (before: the share was written and GET /api/folders/people showed its name)
 - review: the other writers of a member row (here a folder's share reaching a list) take the bucket before the row too
 - a person without an organisation: the folder share by address works (shown in the folder's people), the member dialog's
   order as above on her own list
The deadlock itself is not forced; the tests show the order (the row the other side would need is free while one waits).
usage: p21032_a_locks_test.py <datadir>"""
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
kt.fresh(prefix="P21032A")


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


def free(table, where, args):
    """True when the row(s) can be locked at once (nobody holds them), else the error text."""
    try:
        sql(f"SELECT 1 FROM {table} WHERE {where} FOR UPDATE NOWAIT", args)
        return True
    except dbxm.DbError as ex:
        return f"locked: {str(ex)[:120]}"


def bucket_free(nd, who):
    """True when the share bucket of (node nd, person who) is free (core/objects.py obj_share_lock; the probe's transaction
    ends with its connection)."""
    return sql("SELECT pg_try_advisory_xact_lock(hashtext(?))", (f"kalmido-fsshare-{(int(nd) * 7919 + int(who)) % 256}",)) == [(True,)]


def proc(*lines, hold=True):
    """A transaction of the app in the container (system context, a request context): runs lines, prints 'held' and keeps
    its locks until a line on stdin (hold=True), then commits and prints 'done'."""
    code = ("import os, sys; os.environ['TASKS_WATCHDOG']='0'\nimport app\nfrom flask import g\nfrom kalmido.core.pg import system_ctx\n"
            "from kalmido.core.config import app as fl\nc=app.connect()\nwith fl.test_request_context('/p21032a'):\n"
            "  g.db = c\n  with system_ctx(c):\n" + "".join("    " + x + "\n" for x in lines) +
            "  print('held', flush=True)\n" + ("  sys.stdin.readline()\n" if hold else "") + "  c.commit()\nprint('done', flush=True)")
    return subprocess.Popen(["docker", "exec", "-i", CT, "python", "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def run(*lines):
    """lines in one transaction of the app, committed -> (stdout, stderr)."""
    return proc(*lines, hold=False).communicate(timeout=120)


def waits_for(pattern):
    r = sql("SELECT query FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE ? AND query NOT LIKE '%pg_stat_activity%'",
            (pattern,))
    return r[0][0] if r else None


def race(hold, call, pattern, probe):
    """hold keeps its transaction open; call() runs in a thread. Waits for a real state: the call's backend waits on a lock
    matching pattern (or the call is over). probe() runs while it waits. -> (waited query, probe's result, call's result)."""
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
    th.join(90)
    check(held_ == "held" and "done" in out_[0], f"setup: the holding side held its transaction and committed {held_} {out_}")
    return wq, pr, res.get("r")


def node_of(kind, rid):
    r = sql("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (kind, rid))
    return r[0][0] if r else None


def rows_of(nd, who):
    return sql("SELECT COUNT(*) FROM fs_shares WHERE node_id=? AND (user_id=? OR agent_id=?)", (nd, who, who))[0][0]


def made(r, what):
    check(r.ok, f"setup: {what} {r.status_code} {r.text[:160]}")
    return r.json() if r.ok else {}


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,events,contacts,comments,collab,files,wiki", "tour": "done"})
ALICE = kt.me_id(A)
BOB, _bo = freelancer(B, A, "bob")
FID, Fr = freelancer(B, A, "frida", features="cal,events,contacts,comments,collab,files,wiki")
sql("UPDATE users SET email_proved=email WHERE id IN (?, ?)", (BOB, FID), write=True)  # addresses proved (addr_account)


def org(name):
    return made(A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": ALICE}), f"organisation {name}")["id"]


# ================================================================== (F2) the books' rows first, then the share buckets
B1 = made(A.post(B + "/api/books", json={"name": "Hand-on one", "org_id": None}), "book 1").get("id")
B2 = made(A.post(B + "/api/books", json={"name": "Hand-on two", "org_id": None}), "book 2").get("id")
check(A.put(B + f"/api/books/{B1}/members", json={"user_id": FID, "role": "view"}).ok, "(F2) setup: book 1's node (shared with frida)")
NB1 = node_of("address_book", B1)
check(NB1 is not None and rows_of(NB1, BOB) == 0, f"(F2) setup: book 1's node without bob {NB1}")
hold = proc(f"c.execute('SELECT id FROM books WHERE id=? FOR NO KEY UPDATE', ({B2},)).fetchall()")  # book 2's members dialog
wq, fr, out = race(hold, lambda: run("from kalmido.admin.purgeshare import _books",
                                     f"_books(c, [{{'id': {B1}, 'heir': {ALICE}, 'others': {{{BOB}: 'view'}}}}, "
                                     f"{{'id': {B2}, 'heir': {ALICE}, 'others': {{}}}}])"),
                   "%UPDATE books SET owner_id%", lambda: bucket_free(NB1, BOB))
check(wq is not None and fr is True,
      f"(F2) the hand-on waits for book 2's row while book 1's share bucket is free waiting={(wq or '')[:80]!r} bucket_free={fr}")
check(out is not None and "done" in out[0] and rows_of(NB1, BOB) == 1,
      f"(F2) afterwards bob keeps his role on book 1 (one share) {rows_of(NB1, BOB)} {out}")


# ================================================================== (F3) member_set: the share's bucket before the member row
def member_order(s, who, other):
    lid = made(s.post(B + "/api/lists", json={"name": f"Order {who}", "org_id": None}), f"(F3) {who}'s list").get("id")
    check(s.put(B + f"/api/lists/{lid}/members", json={"user_id": other, "role": "view"}).ok, f"(F3) {who} setup: shared (view)")
    nd = node_of("list", lid)
    check(nd is not None, f"(F3) {who} setup: the list's node {nd}")
    hold = proc("from kalmido.core.objects import obj_share_lock", f"obj_share_lock(c, {nd}, {other})")  # lf_folder_share holds it
    wq, fr, r = race(hold, lambda: s.put(B + f"/api/lists/{lid}/members", json={"user_id": other, "role": "edit"}),
                     "%pg_advisory_xact_lock%", lambda: free("list_members", "list_id=? AND user_id=?", (lid, other)))
    check(wq is not None and fr is True,
          f"(F3) {who}: the member dialog waits for the share's bucket before it wrote the member row waiting={wq is not None} row_free={fr}")
    check(r is not None and r.ok and sql("SELECT own_role FROM list_members WHERE list_id=? AND user_id=?", (lid, other)) == [("edit",)],
          f"(F3) {who}: afterwards the role is edit {r.status_code if r is not None else None} {r.text[:160] if r is not None else ''}")


member_order(A, "alice", FID)
member_order(Fr, "frida", ALICE)


# review of 2.1032: every other writer of a member row takes the bucket first too (else member_set and it would cross on the
# same bucket): the share of a folder reaching a list (_folder_member_add) waits for the bucket before it inserts the row
def member_rows_written():
    return sql("SELECT COUNT(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid WHERE l.relation='list_members'::regclass "
               "AND l.mode='RowExclusiveLock' AND a.wait_event_type='Lock'")[0][0]


L0 = made(A.post(B + "/api/lists", json={"name": "Writer order", "org_id": None}), "(F3) a list").get("id")
check(A.put(B + f"/api/lists/{L0}/members", json={"user_id": FID, "role": "view"}).ok, "(F3) writers setup: shared with frida (its node)")
N0 = node_of("list", L0)
hold = proc("from kalmido.core.objects import obj_share_lock", f"obj_share_lock(c, {N0}, {BOB})")
wq, fr, out = race(hold, lambda: run("from kalmido.lists.lists import _folder_member_add", f"_folder_member_add(c, {L0}, {BOB}, 'view', {ALICE})"),
                   "%pg_advisory_xact_lock%", member_rows_written)
check(wq is not None and fr == 0,
      f"(F3) a folder's share waits for the bucket before it wrote the member row waiting={wq is not None} writers_with_rows={fr}")
check(out is not None and "done" in out[0] and sql("SELECT COUNT(*) FROM list_members WHERE list_id=? AND user_id=?", (L0, BOB))[0][0] == 1,
      f"(F3) afterwards bob is a member {out}")


# ================================================================== (F4) a retired organisation: children before the object
OC = org("Retire calendar")
K = made(A.post(B + "/api/evcals", json={"name": "Studio bookings", "org_id": OC}), "(F4) the organisation's calendar").get("id")
E = made(A.post(B + "/api/events", json={"cal_id": K, "title": "Held", "start": f"{D}T09:00", "end": f"{D}T10:00"}), "(F4) its event").get("id")
check(sql("SELECT org_id FROM events WHERE id=?", (E,)) == [(OC,)], "(F4) setup: the event carries the organisation")
hold = proc(f"c.execute('SELECT id FROM events WHERE id=? FOR NO KEY UPDATE', ({E},)).fetchall()")  # an event's save holds it
wq, fr, out = race(hold, lambda: run("from kalmido.accounts.orgretain import odl_retire", f"odl_retire(c, {OC}, '2035-12-31')"),
                   "%FROM \"events\"%", lambda: free("ev_cals", "id=?", (K,)))
check(wq is not None and fr is True,
      f"(F4) the retirement waits for the event before it wrote the calendar's row waiting={(wq or '')[:80]!r} ev_cals={fr}")
check(out is not None and "done" in out[0] and sql("SELECT org_id FROM ev_cals WHERE id=?", (K,)) == [(None,)]
      and sql("SELECT org_id FROM events WHERE id=?", (E,)) == [(None,)],
      f"(F4) afterwards the calendar and its event are private {out}")

OB = org("Retire book")
BK = made(A.post(B + "/api/books", json={"name": "Studio contacts", "org_id": OB}), "(F4) the organisation's book").get("id")
CO = made(A.post(B + "/api/contacts", json={"book_id": BK, "fn": "Person Example"}), "(F4) its contact").get("id")
hold = proc(f"c.execute('SELECT id FROM contacts WHERE id=? FOR NO KEY UPDATE', ({CO},)).fetchall()")  # a contact's save holds it
wq, fr, out = race(hold, lambda: run("from kalmido.accounts.orgretain import odl_retire", f"odl_retire(c, {OB}, '2035-12-31')"),
                   "%contacts%", lambda: free("books", "id=?", (BK,)))
check(wq is not None and fr is True,
      f"(F4) the retirement waits for the contact before it wrote the book's row waiting={(wq or '')[:80]!r} books={fr}")
check(out is not None and "done" in out[0] and sql("SELECT org_id FROM books WHERE id=?", (BK,)) == [(None,)],
      f"(F4) afterwards the book is private {out}")


# ================================================================== (F4) a knowledge page moved: its files before the page
W = made(A.post(B + "/api/wiki/pages", json={"space": "private", "path": "Moved/Page", "body": "text"}), "(F4) a page").get("id")
sql("INSERT INTO wiki_files(page_id, owner_id, name, mime, size, path, created_by, created_at) VALUES(?,?,'a.txt','text/plain',0,"
    "'p21032a-none.txt',?,'2026-11-12T08:00:00Z')", (W, ALICE, ALICE), write=True)
WF = sql("SELECT MAX(id) FROM wiki_files WHERE page_id=?", (W,))[0][0]
check(WF is not None, f"(F4) setup: the page's file {WF}")
hold = proc(f"c.execute('SELECT id FROM wiki_files WHERE id=? FOR NO KEY UPDATE', ({WF},)).fetchall()")
wq, fr, out = race(hold, lambda: run("from kalmido.wiki.wkmove import wkm_place",
                                     f"wkm_place(c, None, {ALICE}, {ALICE}, c.execute('SELECT * FROM wiki_pages WHERE id=?', ({W},)).fetchall(), "
                                     "{}, {}, strict=False)"),
                   "%wiki_files%", lambda: free("wiki_pages", "id=?", (W,)))
check(wq is not None and fr is True,
      f"(F4) the move waits for the page's file before it wrote the page's row waiting={(wq or '')[:80]!r} wiki_pages={fr}")
check(out is not None and "done" in out[0], f"(F4) the move ends after the file's save {out}")


# ================================================================== the folder share by address checks the workspace
OF = org("Folder workspace")
L1 = made(A.post(B + "/api/lists", json={"name": "Client project", "org_id": OF}), "a list of the organisation").get("id")
check(A.patch(B + f"/api/lists/{L1}", json={"folder": "Clients"}).ok, "setup: the list in folder Clients")


def people(s, f):
    r = s.get(B + "/api/folders/people", params={"folder": f})
    return {p["user_id"]: p["name"] for p in r.json().get("people", [])} if r.ok else {"error": r.status_code}


r = A.put(B + "/api/folders/people", json={"folder": "Clients", "email": "bob@example.com", "role": "view"})
check(r.ok and r.json() == {"shared": 0, "updated": 0, "by_email": True}, f"by address: the neutral answer {r.status_code} {r.text[:160]}")
check(BOB not in people(A, "Clients") and sql("SELECT COUNT(*) FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='folder' AND s.user_id=?", (BOB,))[0][0] == 0,
      f"by address: an account outside the folder's organisation gets no share and is not shown {people(A, 'Clients')}")
r = A.put(B + "/api/folders/people", json={"folder": "Clients", "email": "nobody-p21032@example.com", "role": "view"})
check(r.ok and r.json() == {"shared": 0, "updated": 0, "by_email": True}, f"by address: an unknown address answers the same {r.text[:160]}")

# review of 2.1032: an archived list of the organisation in the folder counts too (the folder's share reaches it)
L3 = made(A.post(B + "/api/lists", json={"name": "Old client", "org_id": OF}), "an archived list of the organisation").get("id")
check(A.patch(B + f"/api/lists/{L3}", json={"folder": "Archive", "archived": True}).ok, "setup: archived, in folder Archive")
check(sql("SELECT archived FROM lists WHERE id=?", (L3,)) == [(1,)], "setup: the list is archived")
r = A.put(B + "/api/folders/people", json={"folder": "Archive", "email": "bob@example.com", "role": "view"})
check(r.ok and r.json() == {"shared": 0, "updated": 0, "by_email": True} and BOB not in people(A, "Archive"),
      f"by address: an archived list of the organisation keeps the account out too {r.text[:120]} {people(A, 'Archive')}")

# a person without an organisation shares her private folder by address: it works and the folder shows bob
L2 = made(Fr.post(B + "/api/lists", json={"name": "Garden plan", "org_id": None}), "frida's list").get("id")
check(Fr.patch(B + f"/api/lists/{L2}", json={"folder": "Home"}).ok, "setup: frida's list in folder Home")
r = Fr.put(B + "/api/folders/people", json={"folder": "Home", "email": "bob@example.com", "role": "view"})
check(r.ok and r.json().get("by_email") is True, f"frida by address: the answer {r.status_code} {r.text[:160]}")
check(people(Fr, "Home").get(BOB) == "Bob", f"frida by address: the folder is shared with bob {people(Fr, 'Home')}")
check(sql("SELECT COUNT(*) FROM list_members WHERE list_id=? AND user_id=?", (L2, BOB))[0][0] == 1,
      "frida by address: the folder's share reaches bob in the garden plan")

sys.exit(kt.done("p21032_a_locks"))
