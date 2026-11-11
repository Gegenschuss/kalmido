#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.981.0 (#5286, stage Q8b of the cross-cutting core): the read marks of the feeds' articles are rows of the core's obj_seen
(kind 'rss'), one model for private feeds and the feeds of an organisation; the team chat's read marks are rows of obj_seen
(kind 'tchat' = a room, 'tchat_thread' = a thread), muting a room and taking part in a thread rows of obj_follow. Own container, no feed server (the feeds and their
articles are written into the database; nothing is fetched). Invented names only.
 - rss_reads and rss_items.read_at are gone; the start moves rows / marks of them made again by hand (what a version before
   2.981 leaves after a rollback) into obj_seen and drops them
 - an organisation's feed: one member reads an article, the other still sees it unread; unread again; "all read"; read later
   marks it read; the counters of the feed and the space follow
 - an article deleted (trimmed) takes its marks along
 - a person without an organisation (freelancer fixture): her private feed, read / unread, the same rows
 - team chat: the unread count of a project's room follows the read mark, muting holds it out of the total, a thread taken part
   in counts its new answers until it is read; leaving a channel takes the mark and the mute along; tchat_reads /
   tchat_thread_reads made again by hand move into the core with the same unread count and mute
 - a person without an organisation: her own channel, read mark
freelancer-matrix: feeds, teamchat
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


def team(s):
    r = s.get(B + "/api/team")
    return r.json() if r.ok else {"rooms": [], "unread": -1}


def room(s, rid):
    return next((x for x in team(s)["rooms"] if x["id"] == rid), {})


def say(s, rid, text, **kw):
    r = s.post(B + f"/api/team/rooms/{rid}/messages", json={"body": text, **kw})
    check(r.status_code == 201, f"message written {r.status_code} {r.text[:200]}")
    return r.json().get("id") if r.status_code == 201 else None


def read(s, rid, **b):
    return s.post(B + f"/api/team/rooms/{rid}/read", json=b)


def seen(kind, rid, uid):
    x = dbx("SELECT seen_id FROM obj_seen WHERE kind=? AND ref_id=? AND user_id=?", (kind, rid, uid))
    return x[0][0] if x else None


def follows(kind, rid, uid):
    return sorted(r[0] for r in dbx("SELECT mode FROM obj_follow WHERE kind=? AND ref_id=? AND user_id=?", (kind, rid, uid)))


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

# ================================================================== team chat: a project's room
LID = A.post(B + "/api/lists", json={"name": "Werkstatt", "kind": "project", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{LID}/members", json={"user_id": BOB, "role": "edit"})
RID = next((x["id"] for x in team(A)["rooms"] if x.get("list_id") == LID), None)
check(bool(RID), "the project's room is there")
M1, M2 = say(A, RID, "Hallo"), say(A, RID, "Zweite Nachricht")
check(seen("tchat", RID, ALICE) == M2, f"writing moves the writer's mark (obj_seen kind tchat) {seen('tchat', RID, ALICE)}")
check(room(Bo, RID).get("unread") == 2, f"bob: two unread {room(Bo, RID)}")
r = read(Bo, RID, last_id=M1)
check(r.ok and r.json()["last_id"] == M1 and seen("tchat", RID, BOB) == M1 and room(Bo, RID)["unread"] == 1, f"bob reads up to the first {r.text[:200]}")
check(read(Bo, RID, last_id=1).json()["last_id"] == M1 and seen("tchat", RID, BOB) == M1, "an older mark never goes back")
check(read(Bo, RID).ok and room(Bo, RID)["unread"] == 0 and seen("tchat", RID, BOB) == M2, "bob reads all")
r = read(Bo, RID, muted=True)
check(r.ok and r.json()["muted"] is True and follows("tchat", RID, BOB) == ["mute"] and seen("tchat", RID, BOB) == M2,
      f"bob mutes the room: a row of obj_follow, the mark stays {r.text[:200]}")
M3 = say(A, RID, "Dritte Nachricht")
t = team(Bo)
check(room(Bo, RID)["unread"] == 1 and room(Bo, RID)["muted"] is True and t["unread"] == 0, f"muted: the room counts, the total not {t['unread']}")
r = read(Bo, RID, muted=False)
check(r.ok and follows("tchat", RID, BOB) == [] and team(Bo)["unread"] == 1, "unmuted: the row goes, the total counts it again")
check(read(Bo, RID).ok and team(Bo)["unread"] == 0, "bob reads it")

# a thread: who takes part counts its new answers
T1 = say(Bo, RID, "Ich bin dabei", thread_of=M3)
check(follows("tchat_thread", M3, BOB) == ["watch"] and seen("tchat_thread", M3, BOB) == T1, "bob answers: he takes part, read up to his answer")
check(follows("tchat_thread", M3, ALICE) == ["watch"], "the root's author takes part too")
T2 = say(A, RID, "Prima", thread_of=M3)
check(room(Bo, RID)["unread"] == 1, f"bob: the new answer counts {room(Bo, RID)}")
pg = Bo.get(B + f"/api/team/rooms/{RID}/messages").json()
rt = next((m for m in pg.get("messages", []) if m["id"] == M3), {})
check(rt.get("thread_unread") == 1 and rt.get("thread_follow") is True and rt.get("thread_count") == 2, f"the root shows it {rt}")
r = read(Bo, RID, thread=M3)
check(r.ok and r.json()["last_id"] == T2 and seen("tchat_thread", M3, BOB) == T2 and room(Bo, RID)["unread"] == 0, f"bob reads the thread {r.text[:200]}")

# leaving a channel takes the mark and the mute along
r = A.post(B + "/api/team/channels", json={"name": "Planung", "org_id": ORG, "open": False, "members": [BOB]})
check(r.status_code == 201, "a closed channel with bob " + r.text[:200])
CH = r.json().get("id")
say(A, CH, "Plan steht")
check(read(Bo, CH).ok and read(Bo, CH, muted=True).ok and seen("tchat", CH, BOB) and follows("tchat", CH, BOB) == ["mute"], "bob reads and mutes it")
check(Bo.delete(B + f"/api/team/rooms/{CH}/members/{BOB}").ok, "bob leaves the channel")
check(seen("tchat", CH, BOB) is None and follows("tchat", CH, BOB) == [], "his mark and his mute there are gone")

# a person without an organisation
r = Fr.post(B + "/api/team/channels", json={"name": "Notizen", "org_id": None})
check(r.status_code == 201, "freelancer: her own channel " + r.text[:200])
FC = r.json().get("id")
FM = say(Fr, FC, "Erste Notiz")
check(seen("tchat", FC, FID) == FM and read(Fr, FC, muted=True).ok and follows("tchat", FC, FID) == ["mute"], "freelancer: her mark and mute are rows of the core")

# ================================================================== the move of the old tables (a version before 2.981 ran)
check(read(Bo, RID, muted=True).ok, "bob mutes the project's room again")
M4 = say(A, RID, "Vierte Nachricht")
T3 = say(A, RID, "Noch was", thread_of=M3)
before = room(Bo, RID)
check(before.get("unread") == 2 and before.get("muted") is True, f"bob before the move: one in the room, one in the thread, muted {before}")
dbx("""CREATE TABLE tchat_reads (room_id BIGINT NOT NULL REFERENCES tchat_rooms(id) ON DELETE CASCADE,
       user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, last_id BIGINT NOT NULL DEFAULT 0, muted BIGINT NOT NULL DEFAULT 0,
       PRIMARY KEY (room_id, user_id))""")
dbx("""CREATE TABLE tchat_thread_reads (root_id BIGINT NOT NULL REFERENCES tchat_msgs(id) ON DELETE CASCADE,
       user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, room_id BIGINT NOT NULL REFERENCES tchat_rooms(id) ON DELETE CASCADE,
       last_id BIGINT NOT NULL DEFAULT 0, follow BIGINT NOT NULL DEFAULT 1, PRIMARY KEY (root_id, user_id))""")
dbx("INSERT INTO tchat_reads(room_id, user_id, last_id, muted) VALUES(?,?,?,1)", (RID, BOB, seen("tchat", RID, BOB)))
dbx("INSERT INTO tchat_thread_reads(root_id, user_id, room_id, last_id, follow) VALUES(?,?,?,?,1)", (M3, BOB, RID, seen("tchat_thread", M3, BOB)))
dbx("DELETE FROM obj_seen WHERE user_id=? AND kind IN ('tchat','tchat_thread')", (BOB,))
dbx("DELETE FROM obj_follow WHERE user_id=? AND kind IN ('tchat','tchat_thread')", (BOB,))
check(room(Bo, RID).get("unread") != 2, "without the core's rows the count differs (the move below brings them back)")

# the old feed table and column too

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
check(not table_there("tchat_reads") and not table_there("tchat_thread_reads"), "... and the team chat's old tables")
after = room(Bo, RID)
check(after.get("unread") == before["unread"] and after.get("muted") is True, f"bob after the move: the same unread count, still muted {after}")
check(follows("tchat", RID, BOB) == ["mute"] and follows("tchat_thread", M3, BOB) == ["watch"] and seen("tchat_thread", M3, BOB) == T2,
      "the mute, the thread taken part in and its mark moved")
check(marks(QI[0]) == [BOB] and marks(QI[1]) == [BOB] and marks(PI[0]) == [FID], f"their marks moved {marks(QI[0])} {marks(QI[1])} {marks(PI[0])}")
t = dbx("SELECT seen_at::text, seen_id FROM obj_seen WHERE kind='rss' AND ref_id=? AND user_id=?", (QI[0], BOB))
check(t and t[0][0].startswith("2026-11-03") and t[0][1] == QI[0], f"... with their time {t}")
fl = dict(dbx("SELECT key, value FROM kalmido_meta WHERE key IN ('back_floor','back_floor_how')"))
check("#5286" in (fl.get("back_floor_how") or ""), f"the move raised the back limit and names why {fl}")
check(feeds(Bo, SP)["unread"] == 1 and feeds(Fr)["unread"] == 0, "the app reads the moved marks (bob: only the article he marked unread)")

sys.exit(kt.done("p2981_c2_seen"))
