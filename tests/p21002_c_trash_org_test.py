#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1002.0 C (#5490, stage 5b of the core's trash): the organisation cases of bookmarks, feeds and video sign-offs on the core's
trash and its retention run (purge hook obj_on_purge, trash_prune=True), and the delete / restore of a video sign-off as a
step of the person's list "Recent steps" (core/undoweb.py undo_trash_reg, videos/vdkern.py). Invented names only.
 - bookmark of an organisation: its maker (a member) deletes it, an outsider gets 404, the admin restores it; the core's run
   deletes an old one with its stored picture (purge hook life/lfkern.py), a younger one stays
 - feed of an organisation: a member may not unfollow it (403), an outsider 404, the admin unfollows and restores it; the
   core's run deletes an old one, a younger one stays
 - video sign-off: delete -> a step "Moved to the trash: <title>" in GET /api/undo; undo brings it back, redo puts it into the
   trash again (its open customer link stops); restore is a step too; someone else's step 404; who lost the right to change
   it meanwhile (member -> guest) cannot take it back: it stays in the trash
 - video sign-off of an organisation: the core's run deletes an old one, a younger one stays
tenant-matrix: reading, feeds, videos (an outsider: 404 on the organisation's bookmark / feed / review)
freelancer-matrix: videos (frida, a person without an organisation: delete, undo, redo, restore of her own review)
usage: p21002_c_trash_org_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

fresh(prefix="P21002C")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
AID = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
FID, Fr = freelancer(B, A)
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
check(r.ok, f"setup: bob as a member {r.text[:200]}")
BID = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
OLD = "2020-01-02T03:04:05.000Z"


def row(table, rid):
    r = dbx(f"SELECT deleted_at, deleted_by FROM {table} WHERE id=?", (rid,))
    return tuple(r[0]) if r else None


def steps(s):
    return s.get(B + "/api/undo").json().get("items") or []


def run_core():
    """The core's hourly run with the switch on (core/writes.py obj_trash_tick)."""
    return in_app("""from kalmido.core import writes
writes.ret_on = lambda k: True
print("TICK", writes.obj_trash_tick(c, True))""")


# ================================================================ bookmark of the organisation
def bm_ids(s):
    return [x["id"] for x in s.get(B + "/api/bookmarks", params={"space": "all"}).json()["items"]]


def bookmark(s, url):
    r = s.post(B + "/api/bookmarks", json={"url": url, "space": f"org:{ORG}"})
    assert r.status_code == 201, r.text
    return r.json()["bookmark"]["id"]


BM = bookmark(Bo, "https://example.com/p21002c-a")
check(BM in bm_ids(A) and dbx("SELECT org_id FROM bookmarks WHERE id=?", (BM,))[0][0] == ORG,
      "org bookmark: bob's bookmark lies in the organisation, alice sees it")
check(Fr.delete(B + f"/api/bookmarks/{BM}").status_code == 404 and row("bookmarks", BM)[0] is None, "org bookmark: an outsider 404")
check(Bo.delete(B + f"/api/bookmarks/{BM}").ok and BM not in bm_ids(Bo) and BM not in bm_ids(A) and row("bookmarks", BM)[1] == BID,
      "org bookmark: its maker deleted it, gone for both, core's trash (deleted_by)")
check(Fr.post(B + f"/api/bookmarks/{BM}/restore").status_code == 404, "org bookmark: an outsider cannot restore (404)")
check(A.post(B + f"/api/bookmarks/{BM}/restore").ok and BM in bm_ids(Bo) and row("bookmarks", BM) == (None, None),
      "org bookmark: the admin restored it, bob sees it again")
BY = bookmark(Bo, "https://example.com/p21002c-b")
check(A.delete(B + f"/api/bookmarks/{BM}").ok and A.delete(B + f"/api/bookmarks/{BY}").ok, "org bookmarks into the trash for the run")
dbx("UPDATE bookmarks SET deleted_at=?, image=? WHERE id=?", (OLD, f"bookmarks/p21002c-{BM}.png", BM))
PIC = f"""import os
from kalmido.core.config import ATT_DIR
p = os.path.join(ATT_DIR, "bookmarks", "p21002c-{BM}.png")
"""
out = in_app(PIC + """os.makedirs(os.path.dirname(p), exist_ok=True)
open(p, "wb").write(b"x")
print("PIC", os.path.isfile(p))""")
check("PIC True" in out, f"setup: the old org bookmark has a stored picture {out[-200:]}")
out = run_core()
check("TICK" in out and row("bookmarks", BM) is None and row("bookmarks", BY) and row("bookmarks", BY)[0],
      f"org bookmark: the core's run deletes the old one, the younger one stays {out[-300:]}")
out = in_app(PIC + 'print("PIC", os.path.isfile(p))')
check("PIC False" in out, f"org bookmark: its stored picture went after the commit (purge hook) {out[-200:]}")

# ================================================================ feed of the organisation (inserted as the add leaves it: no fetch)
def feed_ids(s):
    return [x["id"] for x in s.get(B + "/api/feeds", params={"space": f"org:{ORG}"}).json()["feeds"]]


def feed(url):
    return dbx("INSERT INTO rss_feeds(user_id, org_id, url, title, created_at) VALUES(?,?,?,?,?) RETURNING id",
               (AID, ORG, url, "Example org feed", OLD))[0][0]


FD = feed("https://feeds.example.com/org-a.xml")
check(FD in feed_ids(Bo), f"org feed: bob reads the organisation's feed {feed_ids(Bo)}")
check(Bo.delete(B + f"/api/feeds/{FD}").status_code == 403 and row("rss_feeds", FD)[0] is None, "org feed: a member may not unfollow it (403)")
check(Fr.delete(B + f"/api/feeds/{FD}").status_code == 404 and row("rss_feeds", FD)[0] is None, "org feed: an outsider 404")
check(A.delete(B + f"/api/feeds/{FD}").ok and FD not in feed_ids(Bo) and row("rss_feeds", FD)[1] == AID,
      "org feed: the admin unfollowed it, gone for bob, core's trash (deleted_by)")
check(Bo.post(B + f"/api/feeds/{FD}/restore").status_code in (403, 404) and row("rss_feeds", FD)[0], "org feed: a member cannot restore it")
check(A.post(B + f"/api/feeds/{FD}/restore").ok and FD in feed_ids(Bo) and row("rss_feeds", FD) == (None, None),
      "org feed: the admin restored it, bob reads it again")
FY = feed("https://feeds.example.com/org-b.xml")
check(A.delete(B + f"/api/feeds/{FD}").ok and A.delete(B + f"/api/feeds/{FY}").ok, "org feeds into the trash for the run")
dbx("UPDATE rss_feeds SET deleted_at=? WHERE id=?", (OLD, FD))
out = run_core()
check("TICK" in out and row("rss_feeds", FD) is None and row("rss_feeds", FY) and row("rss_feeds", FY)[0],
      f"org feed: the core's run deletes the old one, the younger one stays {out[-300:]}")

# ================================================================ video sign-off: delete / restore are steps of the person
def vids(s, lid):
    return [x["id"] for x in s.get(B + f"/api/videos?list_id={lid}").json()["reviews"]]


def review(s, lid, title):
    r = s.post(B + "/api/videos", json={"title": title, "url": "https://vimeo.com/123456789", "list_id": lid})
    assert r.ok, r.text
    return r.json()["id"]


LF = Fr.post(B + "/api/lists", json={"name": "Example Film", "kind": "project", "org_id": None}).json()["id"]
VD = review(Fr, LF, "Example rough cut")
check(Fr.delete(B + f"/api/videos/{VD}").ok and VD not in vids(Fr, LF), "review: deleted, gone from the project")
st = steps(Fr)
g = st[0] if st else {}
check(g.get("kind") == "video_review" and g.get("ref_id") == VD and g.get("undo") is True and "Example rough cut" in (g.get("label") or ""),
      f"review: its delete is a step of the person's list, named with its title {g}")
check(A.post(B + f"/api/undo/to/{g.get('id')}").status_code == 404 and row("video_reviews", VD)[0],
      "review: someone else's step 404, it stays in the trash")
r = Fr.post(B + f"/api/undo/to/{g.get('id')}")
check(r.ok and VD in vids(Fr, LF) and row("video_reviews", VD) == (None, None),
      f"review: undo brings it back into its project {r.status_code} {r.text[:200]} {row('video_reviews', VD)}")
r = Fr.post(B + f"/api/undo/{g.get('id')}/redo")
check(r.ok and VD not in vids(Fr, LF) and row("video_reviews", VD)[1] == FID,
      f"review: redo puts it into the trash again {r.status_code} {r.text[:200]} {row('video_reviews', VD)}")
check(Fr.post(B + f"/api/videos/{VD}/restore").ok and VD in vids(Fr, LF), "review: restored through its route")
g2 = (steps(Fr) or [{}])[0]
check(g2.get("kind") == "video_review" and g2.get("ref_id") == VD and g2.get("id") != g.get("id"), f"review: the restore is a step too {g2}")
r = Fr.post(B + f"/api/undo/to/{g2.get('id')}")
check(r.ok and VD not in vids(Fr, LF) and row("video_reviews", VD)[0], f"review: undo of the restore = into the trash again {r.status_code} {r.text[:200]}")

# ---- the right of NOW: bob deletes an organisation's review, then becomes a guest -> his undo leaves it in the trash
LO = A.post(B + "/api/lists", json={"name": "Example Org Film", "kind": "project", "org_id": ORG}).json()["id"]
VO = review(Bo, LO, "Example org cut")
check(Bo.delete(B + f"/api/videos/{VO}").ok and row("video_reviews", VO)[1] == BID, "org review: bob deleted it")
gb = (steps(Bo) or [{}])[0]
check(gb.get("kind") == "video_review" and gb.get("ref_id") == VO, f"org review: bob's step {gb}")
dbx("UPDATE org_members SET role='guest' WHERE org_id=? AND user_id=?", (ORG, BID))
Bo.post(B + f"/api/undo/to/{gb.get('id')}")
check(row("video_reviews", VO)[0], f"org review: bob (a guest now) cannot take it back, it stays in the trash {row('video_reviews', VO)}")
dbx("UPDATE org_members SET role='member' WHERE org_id=? AND user_id=?", (ORG, BID))

# ---- the core's run deletes an old organisation's review, a younger one stays
VY = review(A, LO, "Example org young")
check(A.delete(B + f"/api/videos/{VY}").ok, "org review: a younger one into the trash")
dbx("UPDATE video_reviews SET deleted_at=? WHERE id=?", (OLD, VO))
out = run_core()
check("TICK" in out and row("video_reviews", VO) is None and row("video_reviews", VY) and row("video_reviews", VY)[0],
      f"org review: the core's run deletes the old one, the younger one stays {out[-300:]}")
check(not dbx("SELECT 1 FROM obj_undo WHERE kind='video_review' AND ref_id=?", (VO,)),
      "org review: its undo steps went with it (core's _purge_rows)")

sys.exit(done("p21002_c_trash_org"))
