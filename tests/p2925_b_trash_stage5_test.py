#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.925.0 (#5367, stage 5 of the core's trash): calendars, address books, bookmarks, feeds and video sign-offs lie in the ONE
trash of the core (core/writes.py obj_trash / obj_restore / obj_trash_prune). Invented names only.
 - each area: delete -> gone from its list, in the core's trash (deleted_at, deleted_by) -> restore -> visible again
 - the calendar with its events (children of the kind evcal): they go and come back with it, one deleted on its own before
   stays in the trash; deleting it is a step of the person's list (GET /api/undo) and taken back there with its events
 - rows put into the trash the old way (deleted_at only, deleted_by empty; a calendar with its events at the same time) are
   the core's trash: their restore works
 - someone else: 404 on another person's object (delete / restore)
 - the retention run: all five are kinds of the core's run (trash_prune); obj_trash_prune deletes a calendar with its
   events, an address book with its contact (and its contact's core rows, the purge hook contacts/ctkern.py bk_purge_prep), a
   bookmark with its stored picture (purge hook life/lfkern.py), a feed, a review; a younger one stays
 - bookmarks and feeds keep their own undo step (life/bmundo.py, life/rssundo.py, #5476): taking back the delete from the
   list of steps brings the row out of the core's trash completely (deleted_at and deleted_by empty)
tenant-matrix: calendar, contacts, reading, feeds, videos (another person: 404 on a foreign object)
freelancer-matrix: calendar, contacts, reading, feeds, videos (frida, a person without an organisation, runs the whole way)
usage: p2925_b_trash_stage5_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

fresh(prefix="P2862C")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
FID, Fr = freelancer(B, A)
OLD = "2020-01-02T03:04:05.000Z"


def row(table, rid):
    r = dbx(f"SELECT deleted_at, deleted_by FROM {table} WHERE id=?", (rid,))
    return tuple(r[0]) if r else None


def evd(eid):
    """An event's deleted_at (events have no deleted_by), "gone" when the row is gone."""
    r = dbx("SELECT deleted_at FROM events WHERE id=?", (eid,))
    return r[0][0] if r else "gone"


def groups(u):
    return dbx("SELECT id FROM undo_groups WHERE user_id=? ORDER BY id", (u,))


# ================================================================ the kinds
out = in_app("""from kalmido.core.objects import OBJ
print("PRUNE", sorted(k for k in ("evcal", "rss_feed", "video_review", "bookmark_link", "address_book") if OBJ[k]["trash_prune"]))
print("KIDS", OBJ["evcal"]["children"])""")
check("PRUNE ['address_book', 'bookmark_link', 'evcal', 'rss_feed', 'video_review']" in out and "KIDS (('events', 'cal_id'),)" in out,
      f"the kinds: all five in the core's run; the events are the calendar's children {out[-300:]}")

# ================================================================ calendar with its events
def cal_ids(s):
    return [x["id"] for x in s.get(B + "/api/evcals").json()["items"]]


K = Fr.post(B + "/api/evcals", json={"name": "Example Plans"}).json()["id"]
E1 = Fr.post(B + "/api/events", json={"cal_id": K, "title": "Example meeting", "start": "2026-12-03T09:00", "end": "2026-12-03T10:00"}).json()["id"]
E2 = Fr.post(B + "/api/events", json={"cal_id": K, "title": "Example review", "start": "2026-12-04T09:00", "end": "2026-12-04T10:00"}).json()["id"]
E3 = Fr.post(B + "/api/events", json={"cal_id": K, "title": "Example gone", "start": "2026-12-05T09:00", "end": "2026-12-05T10:00"}).json()["id"]
check(Fr.delete(B + f"/api/events/{E3}").ok and evd(E3), "setup: one event deleted on its own before")
check(A.delete(B + f"/api/evcals/{K}").status_code == 404 and row("ev_cals", K)[0] is None, "someone else: 404, the calendar stays")
g0 = len(groups(FID))
check(Fr.delete(B + f"/api/evcals/{K}").ok and K not in cal_ids(Fr), "calendar: deleted, gone from the list")
d = row("ev_cals", K)
check(d and d[0] and d[1] == FID, f"calendar: in the core's trash (deleted_at, deleted_by) {d}")
check(evd(E1) == d[0] and evd(E2) == d[0] and evd(E3) != d[0],
      "calendar: its live events went with it (its time), the one deleted before keeps its own")
check(Fr.get(B + f"/api/events/{E1}").status_code == 404, "calendar: its event is not reachable in the trash")
t = {x["id"]: x for x in Fr.get(B + "/api/evcals/trash").json()["items"]}
check(K in t and t[K]["events"] == 2, f"calendar: the trash lists it with its two events {t}")
check(A.post(B + f"/api/evcals/{K}/restore").status_code == 404, "someone else: no restore (404)")
check(Fr.post(B + f"/api/evcals/{K}/restore").ok and K in cal_ids(Fr) and Fr.get(B + f"/api/events/{E1}").ok
      and Fr.get(B + f"/api/events/{E2}").ok, "calendar: restored, visible again with its events")
check(row("ev_cals", K) == (None, None) and evd(E1) is None and evd(E3),
      "calendar: out of the trash; the event deleted on its own before stays in the trash")
check(len(groups(FID)) == g0 + 2, f"calendar: delete and restore are two steps of the person {groups(FID)[g0:]}")

# ---- undo: the deletion taken back from the list of steps
check(Fr.delete(B + f"/api/evcals/{K}").ok and K not in cal_ids(Fr), "calendar: deleted again")
GT = groups(FID)[-1]["id"]
it = Fr.get(B + "/api/undo").json()["items"]
check(it and it[0]["id"] == GT and it[0]["undo"] is True and "Calendar" in it[0]["label"], f"undo: the step is listed {it[:1]}")
check(A.post(B + f"/api/undo/to/{GT}").status_code == 404 and row("ev_cals", K)[0], "undo: a foreign step 404, it stays in the trash")
r = Fr.post(B + f"/api/undo/to/{GT}")
check(r.ok and K in cal_ids(Fr) and Fr.get(B + f"/api/events/{E2}").ok and evd(E3),
      f"undo: the calendar is back with its events (not the one deleted before) {r.status_code} {r.text[:200]}")

# ---- the old way: calendar and events with the same time by hand, deleted_by empty
dbx("UPDATE ev_cals SET deleted_at=? WHERE id=?", (OLD, K))
dbx("UPDATE events SET deleted_at=? WHERE cal_id=? AND deleted_at IS NULL", (OLD, K))
check(K not in cal_ids(Fr) and Fr.post(B + f"/api/evcals/{K}/restore").ok and Fr.get(B + f"/api/events/{E1}").ok,
      "old trash row: restored with its events")

# ---- the core's run deletes it with its events
check(Fr.delete(B + f"/api/evcals/{K}").ok, "calendar: into the trash for the run")
K2 = Fr.post(B + "/api/evcals", json={"name": "Example Young"}).json()["id"]
check(Fr.delete(B + f"/api/evcals/{K2}").ok, "a younger calendar into the trash")
dbx("UPDATE ev_cals SET deleted_at=? WHERE id=?", (OLD, K))
out = in_app("""from kalmido.core.writes import obj_trash_prune
print("PURGED", obj_trash_prune(c, "evcal", purge=True))
c.commit()""")
check("PURGED 1" in out and row("ev_cals", K) is None and evd(E1) == "gone" and evd(E3) == "gone",
      f"the core's run: the old calendar gone with all its events {out[-300:]}")
check(row("ev_cals", K2) and row("ev_cals", K2)[0], "the younger calendar stays in the trash")

# ================================================================ address book
def book_ids(s, trash=False):
    return [x["id"] for x in s.get(B + "/api/books", params={"trash": 1} if trash else {}).json()["items"]]


BK = Fr.post(B + "/api/books", json={"name": "Example Contacts", "org_id": None}).json()["id"]
CT = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": "Anna Example", "emails": [{"value": "anna@example.com"}]}).json()["id"]
check(A.delete(B + f"/api/books/{BK}").status_code == 404 and row("books", BK)[0] is None, "book: someone else 404")
check(Fr.delete(B + f"/api/books/{BK}").ok and BK not in book_ids(Fr) and BK in book_ids(Fr, True), "book: deleted, in its trash")
check(row("books", BK)[1] == FID and Fr.get(B + f"/api/contacts/{CT}").status_code == 404, "book: core's trash (deleted_by), its contact hidden")
check(Fr.post(B + f"/api/books/{BK}/restore").ok and BK in book_ids(Fr) and Fr.get(B + f"/api/contacts/{CT}").ok
      and row("books", BK) == (None, None), "book: restored with its contact")
dbx("UPDATE books SET deleted_at=? WHERE id=?", (OLD, BK))
check(BK in book_ids(Fr, True) and Fr.post(B + f"/api/books/{BK}/restore").ok and BK in book_ids(Fr), "book: an old trash row restored")
BY = Fr.post(B + "/api/books", json={"name": "Example Young", "org_id": None}).json()["id"]
check(Fr.delete(B + f"/api/books/{BK}").ok and Fr.delete(B + f"/api/books/{BY}").ok, "books into the trash for the run")
dbx("UPDATE books SET deleted_at=? WHERE id=?", (OLD, BK))
dbx("INSERT INTO obj_history(org_id, kind, ref_id, user_id, action, vals_before, vals_after, agent, created_at, updated_at) "
    "VALUES(NULL, 'contact', ?, ?, 'update', '{}', '{}', 0, ?, ?)", (CT, FID, OLD, OLD))
out = in_app("""from kalmido.core.writes import obj_trash_prune
print("DRY", obj_trash_prune(c, "address_book", purge=False))
print("PURGED", obj_trash_prune(c, "address_book", purge=True))
c.commit()""")
check("DRY 1" in out and "PURGED 1" in out and row("books", BK) is None and not dbx("SELECT 1 FROM contacts WHERE id=?", (CT,)),
      f"book: the core's run deletes the old one with its contact {out[-300:]}")
check(not dbx("SELECT 1 FROM obj_history WHERE kind='contact' AND ref_id=?", (CT,)), "book: its contact's core rows went with it")
check(row("books", BY) and row("books", BY)[0], "book: the younger one stays in the trash")

# ================================================================ bookmark
def bm_ids(s):
    return [x["id"] for x in s.get(B + "/api/bookmarks").json()["items"]]


r = Fr.post(B + "/api/bookmarks", json={"url": "https://example.com/p2925-a"})
check(r.status_code == 201, f"setup: a bookmark {r.status_code} {r.text[:150]}")
BM = r.json()["bookmark"]["id"]
check(A.delete(B + f"/api/bookmarks/{BM}").status_code == 404 and row("bookmarks", BM)[0] is None, "bookmark: someone else 404")
check(Fr.delete(B + f"/api/bookmarks/{BM}").ok and BM not in bm_ids(Fr) and row("bookmarks", BM)[1] == FID,
      "bookmark: deleted, gone from the list, core's trash (deleted_by)")
check(A.post(B + f"/api/bookmarks/{BM}/restore").status_code == 404, "bookmark: someone else cannot restore")
check(Fr.post(B + f"/api/bookmarks/{BM}/restore").ok and BM in bm_ids(Fr) and row("bookmarks", BM) == (None, None), "bookmark: restored")
dbx("UPDATE bookmarks SET deleted_at=? WHERE id=?", (OLD, BM))
check(BM not in bm_ids(Fr) and Fr.post(B + f"/api/bookmarks/{BM}/restore").ok and BM in bm_ids(Fr), "bookmark: an old trash row restored")
BY = Fr.post(B + "/api/bookmarks", json={"url": "https://example.com/p2925-b"}).json()["bookmark"]["id"]
check(Fr.delete(B + f"/api/bookmarks/{BM}").ok and Fr.delete(B + f"/api/bookmarks/{BY}").ok, "bookmarks into the trash for the run")
dbx("UPDATE bookmarks SET deleted_at=?, image=? WHERE id=?", (OLD, f"bookmarks/p2925b-{BM}.png", BM))
PIC = f"""import os
from kalmido.core.config import ATT_DIR
p = os.path.join(ATT_DIR, "bookmarks", "p2925b-{BM}.png")
"""
out = in_app(PIC + """os.makedirs(os.path.dirname(p), exist_ok=True)
open(p, "wb").write(b"x")
print("PIC", os.path.isfile(p))""")
check("PIC True" in out, f"setup: the old bookmark has a stored picture {out[-200:]}")
out = in_app("""from kalmido.core.writes import obj_trash_tick
print("TICK", obj_trash_tick(c, True))""")
check("TICK" in out and row("bookmarks", BM) and row("bookmarks", BM)[0], f"bookmark: switch off - the core's run only counts {out[-300:]}")
out = in_app("""from kalmido.core import writes
writes.ret_on = lambda k: True
print("TICK", writes.obj_trash_tick(c, True))""")
check("TICK" in out and row("bookmarks", BM) is None and row("bookmarks", BY) and row("bookmarks", BY)[0],
      f"bookmark: the core's run deletes the old one, the younger one stays {out[-300:]}")
out = in_app(PIC + 'print("PIC", os.path.isfile(p))')
check("PIC False" in out, f"bookmark: its stored picture went after the commit (the purge hook) {out[-200:]}")

# ---- bookmark: its own undo step (life/bmundo.py) takes the delete back out of the core's trash completely
BU = Fr.post(B + "/api/bookmarks", json={"url": "https://example.com/p2925-undo"}).json()["bookmark"]["id"]
check(Fr.delete(B + f"/api/bookmarks/{BU}").ok and row("bookmarks", BU)[1] == FID, "bookmark: deleted for the undo")
g = (Fr.get(B + "/api/undo").json().get("items") or [{}])[0]
check(g.get("kind") == "bookmark" and g.get("ref_id") == BU, f"bookmark: its delete is the bookmarks' own step {g}")
r = Fr.post(B + f"/api/undo/to/{g.get('id')}")
check(r.ok and BU in bm_ids(Fr) and row("bookmarks", BU) == (None, None),
      f"bookmark: undo brings it back, deleted_at and deleted_by empty {r.status_code} {row('bookmarks', BU)}")

# ================================================================ feed (inserted as the add leaves it: no fetch in the test)
def feed_ids(s):
    return [x["id"] for x in s.get(B + "/api/feeds").json()["feeds"]]


def feed(url):
    return dbx("INSERT INTO rss_feeds(user_id, org_id, url, title, created_at) VALUES(?,?,?,?,?) RETURNING id", (FID, None, url, "Example feed", OLD))[0][0]


FD = feed("https://feeds.example.com/a.xml")
check(FD in feed_ids(Fr) and A.delete(B + f"/api/feeds/{FD}").status_code == 404, "feed: in the list; someone else 404")
check(Fr.delete(B + f"/api/feeds/{FD}").ok and FD not in feed_ids(Fr) and row("rss_feeds", FD)[1] == FID, "feed: deleted, core's trash")
check(Fr.post(B + f"/api/feeds/{FD}/restore").ok and FD in feed_ids(Fr) and row("rss_feeds", FD) == (None, None), "feed: restored")
dbx("UPDATE rss_feeds SET deleted_at=? WHERE id=?", (OLD, FD))
check(FD not in feed_ids(Fr) and Fr.post(B + f"/api/feeds/{FD}/restore").ok and FD in feed_ids(Fr), "feed: an old trash row restored")
FY = feed("https://feeds.example.com/b.xml")
check(Fr.delete(B + f"/api/feeds/{FD}").ok and Fr.delete(B + f"/api/feeds/{FY}").ok, "feeds into the trash for the run")
dbx("UPDATE rss_feeds SET deleted_at=? WHERE id=?", (OLD, FD))
out = in_app("""from kalmido.core.writes import obj_trash_prune
print("PURGED", obj_trash_prune(c, "rss_feed", purge=True))
c.commit()""")
check("PURGED 1" in out and row("rss_feeds", FD) is None and row("rss_feeds", FY)[0], f"feed: the core's run, the younger one stays {out[-300:]}")

# ---- feed: its own undo step (life/rssundo.py) takes the unfollow back out of the core's trash completely
FU = feed("https://feeds.example.com/undo.xml")
check(Fr.delete(B + f"/api/feeds/{FU}").ok and row("rss_feeds", FU)[1] == FID, "feed: unfollowed for the undo")
g = (Fr.get(B + "/api/undo").json().get("items") or [{}])[0]
check(g.get("kind") == "feed" and g.get("ref_id") == FU, f"feed: its unfollow is the feeds' own step {g}")
r = Fr.post(B + f"/api/undo/to/{g.get('id')}")
check(r.ok and FU in feed_ids(Fr) and row("rss_feeds", FU) == (None, None),
      f"feed: undo brings it back, deleted_at and deleted_by empty {r.status_code} {row('rss_feeds', FU)}")

# ================================================================ video sign-off
LF = Fr.post(B + "/api/lists", json={"name": "Example Film", "kind": "project", "org_id": None}).json()["id"]


def vids(s):
    return [x["id"] for x in s.get(B + f"/api/videos?list_id={LF}").json()["reviews"]]


def review():
    r = Fr.post(B + "/api/videos", json={"title": "Example cut", "url": "https://vimeo.com/123456789", "list_id": LF})
    assert r.ok, r.text
    return r.json()["id"]


VD = review()
check(A.delete(B + f"/api/videos/{VD}").status_code == 404 and row("video_reviews", VD)[0] is None, "review: someone else 404")
check(Fr.delete(B + f"/api/videos/{VD}").ok and VD not in vids(Fr) and row("video_reviews", VD)[1] == FID, "review: deleted, core's trash")
check(VD in [x["id"] for x in Fr.get(B + "/api/videos/trash").json()["reviews"]], "review: in the video trash")
check(Fr.post(B + f"/api/videos/{VD}/restore").ok and VD in vids(Fr) and row("video_reviews", VD) == (None, None), "review: restored")
dbx("UPDATE video_reviews SET deleted_at=? WHERE id=?", (OLD, VD))
check(VD not in vids(Fr) and Fr.post(B + f"/api/videos/{VD}/restore").ok and VD in vids(Fr), "review: an old trash row restored")
VY = review()
check(Fr.delete(B + f"/api/videos/{VD}").ok and Fr.delete(B + f"/api/videos/{VY}").ok, "reviews into the trash for the run")
dbx("UPDATE video_reviews SET deleted_at=? WHERE id=?", (OLD, VD))
out = in_app("""from kalmido.core.writes import obj_trash_prune
print("PURGED", obj_trash_prune(c, "video_review", purge=True))
c.commit()""")
check("PURGED 1" in out and row("video_reviews", VD) is None and row("video_reviews", VY)[0],
      f"review: the core's run, the younger one stays {out[-300:]}")

sys.exit(done("p2925_b_trash_stage5"))
