#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.981.0 (#5286, stage Q8b of the cross-cutting core): the read marks of the feeds' articles are rows of the core's obj_seen
(kind 'rss'), one model for private feeds and the feeds of an organisation. Own container, no feed server (the feeds and their
articles are written into the database; nothing is fetched). Invented names only.
 - rss_reads and rss_items.read_at are gone; the start moves rows / marks of them made again by hand (what a version before
   2.981 leaves after a rollback) into obj_seen and drops them
 - an organisation's feed: one member reads an article, the other still sees it unread; unread again; "all read"; read later
   marks it read; the counters of the feed and the space follow
 - an article deleted (trimmed) takes its marks along
 - a person without an organisation (freelancer fixture): her private feed, read / unread, the same rows
freelancer-matrix: feeds
usage: p2981_c2_seen_test.py <datadir>"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, dbx  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

TS = "2026-11-01T08:00:00+00:00"


def table_there(t):
    return bool(dbx("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?", (t,)))


def column_there(t, col):
    return bool(dbx("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? AND column_name=?", (t, col)))


def mk_feed(owner, org, title, n):
    """A feed of owner (org None = private) with n articles, written directly (nothing is fetched) -> (feed id, [article ids])."""
    fid = dbx("INSERT INTO rss_feeds(user_id, org_id, url, title, created_at, last_fetch, last_ok) VALUES(?,?,?,?,?,?,?) RETURNING id",
              (owner, org, f"https://example.com/{title.lower()}.xml", title, TS, TS, TS))[0][0]
    ids = []
    for i in range(n):
        ids.append(dbx("INSERT INTO rss_items(feed_id, user_id, guid, url, title, summary, published, fetched_at) "
                       "VALUES(?,?,?,?,?,?,?,?) RETURNING id",
                       (fid, owner, f"{title}-{i}", f"https://example.com/{title.lower()}/{i}", f"{title} {i}", "", f"2026-11-0{i + 1}T09:00:00+00:00", TS))[0][0])
    return fid, ids


def feeds(s, sp=None):
    return s.get(B + "/api/feeds" + (f"?space={sp}" if sp else "")).json()


def items(s, sp=None, unread=False):
    q = "&".join(([f"space={sp}"] if sp else []) + (["unread=1"] if unread else []))
    return s.get(B + "/api/feeds/items" + (f"?{q}" if q else "")).json()


def mark(s, **b):
    return s.post(B + "/api/feeds/read", json=b)


def marks(iid):
    return sorted(r[0] for r in dbx("SELECT user_id FROM obj_seen WHERE kind='rss' AND ref_id=?", (iid,)))


kt.fresh(prefix="P2981C2")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
org_join(B, "bob", ORG)
Bo = kt.sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
BOB = kt.me_id(Bo)

# ================================================================== the old table and column are gone
check(not table_there("rss_reads") and not column_there("rss_items", "read_at"), "rss_reads and rss_items.read_at are gone")

# ================================================================== an organisation's feed: the mark is per person
OF, OI = mk_feed(ALICE, ORG, "Teamblog", 3)
check(feeds(Bo, SP)["unread"] == 3 and feeds(A, SP)["unread"] == 3, "three unread articles for both")
r = mark(Bo, ids=[OI[0]], read=True, space=SP)
check(r.ok and r.json()["ids"] == [OI[0]], f"bob reads one {r.status_code} {r.text[:200]}")
check(marks(OI[0]) == [BOB], f"a row of obj_seen kind rss for bob {marks(OI[0])}")
check(feeds(Bo, SP)["unread"] == 2 and feeds(A, SP)["unread"] == 3, "the mark is bob's own")
it = {x["id"]: x["read"] for x in items(Bo, SP)["items"]}
check(it.get(OI[0]) is True and it.get(OI[1]) is False, f"the list shows it read for bob {it}")
check([x["id"] for x in items(Bo, SP, unread=True)["items"]] == sorted(OI[1:], reverse=True), "only unread: the two others")
check(mark(Bo, ids=[OI[0]], read=True, space=SP).json()["ids"] == [], "read again: nothing changes")
r = mark(Bo, ids=[OI[0]], read=False, space=SP)
check(r.ok and r.json()["ids"] == [OI[0]] and marks(OI[0]) == [], f"unread again: the row goes {r.text[:200]}")
r = mark(A, read=True, space=SP, feed_id=OF)
check(r.ok and sorted(r.json()["ids"]) == sorted(OI) and feeds(A, SP)["unread"] == 0 and feeds(Bo, SP)["unread"] == 3,
      f"alice: all of the feed read, bob still has three {r.text[:200]}")
r = mark(A, ids=OI, read=True)
check(r.ok and r.json()["ids"] == [], "the organisation's articles cannot be marked in the private space")
r = Bo.post(B + f"/api/feeds/items/{OI[1]}/later")
check(r.status_code == 201 and marks(OI[1]) == sorted([ALICE, BOB]), f"read later marks it read for bob {r.status_code} {marks(OI[1])}")

# ================================================================== an article deleted takes its marks along
dbx("DELETE FROM rss_items WHERE id=?", (OI[2],))
check(marks(OI[2]) == [], "a trimmed article takes its marks along")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
PF, PI = mk_feed(FID, None, "Eigenblog", 2)
check(feeds(Fr)["unread"] == 2, "freelancer: two unread in her private feed")
r = mark(Fr, read=True)
check(r.ok and sorted(r.json()["ids"]) == sorted(PI) and feeds(Fr)["unread"] == 0, f"freelancer: all read {r.text[:200]}")
check(all(marks(i) == [FID] for i in PI), "freelancer: her marks are rows of obj_seen")
check(mark(Fr, ids=[PI[0]], read=False).json()["ids"] == [PI[0]] and feeds(Fr)["unread"] == 1, "freelancer: one unread again")
check(mark(Bo, ids=PI, read=True).json()["ids"] == [], "bob cannot mark her private articles")

# ================================================================== the move of the old table and column (a version before 2.981 ran)
dbx("ALTER TABLE rss_items ADD COLUMN read_at TEXT")
dbx("""CREATE TABLE rss_reads (item_id BIGINT NOT NULL REFERENCES rss_items(id) ON DELETE CASCADE,
       user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, read_at TEXT NOT NULL, PRIMARY KEY (item_id, user_id))""")
QF, QI = mk_feed(ALICE, ORG, "Altblog", 2)
dbx("INSERT INTO rss_reads(item_id, user_id, read_at) VALUES(?,?,?)", (QI[0], BOB, "2026-11-03T10:00:00+00:00"))
dbx("INSERT INTO rss_reads(item_id, user_id, read_at) VALUES(?,?,'not a time')", (QI[1], BOB))
dbx("UPDATE rss_items SET read_at=? WHERE id=?", ("2026-11-04T10:00:00+00:00", PI[0]))  # the private feed's own mark
out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app"], capture_output=True, text=True)
check(out.returncode == 0, f"the next start of the app {out.stderr[-600:]}")
check(not table_there("rss_reads") and not column_there("rss_items", "read_at"), "the start dropped the table and the column made again")
check(marks(QI[0]) == [BOB] and marks(QI[1]) == [BOB] and marks(PI[0]) == [FID], f"their marks moved {marks(QI[0])} {marks(QI[1])} {marks(PI[0])}")
t = dbx("SELECT seen_at::text, seen_id FROM obj_seen WHERE kind='rss' AND ref_id=? AND user_id=?", (QI[0], BOB))
check(t and t[0][0].startswith("2026-11-03") and t[0][1] == QI[0], f"... with their time {t}")
fl = dict(dbx("SELECT key, value FROM kalmido_meta WHERE key IN ('back_floor','back_floor_how')"))
check("#5286" in (fl.get("back_floor_how") or ""), f"the move raised the back limit and names why {fl}")
check(feeds(Bo, SP)["unread"] == 1 and feeds(Fr)["unread"] == 0, "the app reads the moved marks (bob: only the article he marked unread)")

sys.exit(kt.done("p2981_c2_seen"))
