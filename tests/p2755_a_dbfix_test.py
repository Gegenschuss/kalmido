#!/usr/bin/env python3
# kalmido-suite: fresh now=2026-12-15T10:00:00Z
"""2.755.0 part A API tests, own container: the database clean-ups of the package. Invented names only.
 - #5265: the table paperless_links is gone after the start (migrations.d/5265_a.py), pl_conns stays
 - #5299: the indexes lists(deleted_at), fs_nodes(parent_id, deleted_at), list_activity(list_id, created_at) exist
 - #5263: a deleted comment of a video review is not in the organisation export (admin/orgexport.py ox_live), the live one is;
   the trash run (videos/review.py vdr_trash_prune, switch on) deletes a comment after the trash period, not before; the
   one-off clean-up (migrations.d/5263_a.py) removes at the next start the comments deleted before its cut-off -- of an
   organisation and of a person without one -- with their answers, and keeps the live ones and those deleted after the cut-off
   (the group's test time lies after the cut-off: every "import app" of a run in the container starts the app and so the clean-up)
The case without an organisation (freelancer fixture) runs the purge and the clean-up.
usage: p2755_a_dbfix_test.py <datadir>"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, DATA, check, dbx, done  # noqa: E402
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

import testclock  # noqa: E402
from datetime import timedelta, timezone  # noqa: E402
CUT = "2026-11-08"  # the cut-off of migrations.d/5263_a.py
NOW = testclock.now().astimezone(timezone.utc)
assert NOW.date().isoformat() > "2026-12-09", f"the suite needs a test time 31 days after the cut-off {NOW}"
OLD = (NOW - timedelta(days=31)).isoformat(timespec="seconds")  # older than the trash period, but after the cut-off
BEFORE = "2026-11-01T10:00:00+00:00"  # deleted before the cut-off


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # noqa: BLE001 - a statement without rows to read
            return []
    finally:
        c.close()


def box(code, env=()):
    """Python inside the app container (as the system: every workspace) -> its output."""
    e = [x for k in env for x in ("-e", k)]
    out = subprocess.run(["docker", "exec", *e, CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\n"
                          "from kalmido.core.pg import system_ctx\nc = connect()\nwith system_ctx(c):\n"
                          + "".join("    " + ln + "\n" for ln in code.splitlines()) + "c.commit()\nc.close()"],
                         capture_output=True, text=True)
    check(out.returncode == 0, f"the run in the container works {out.stderr[-800:]}")
    return out.stdout.strip()


def export(oid, uid):
    """The organisation export of oid as admin uid (ox_build, the ZIP before its encryption) -> {name: rows}."""
    out = box(f"""import io, json, zipfile
from kalmido.admin.orgexport import ox_build
b = io.BytesIO()
ox_build(c, {int(oid)}, b, by={{"id": {int(uid)}, "name": "Admin"}})
z = zipfile.ZipFile(b)
print("OXJSON" + json.dumps({{n: json.loads(z.read(n)) for n in z.namelist() if n.endswith(".json") and n != "manifest.json"}}, default=str))""")
    line = next((x for x in out.splitlines() if x.startswith("OXJSON")), None)
    assert line, out[-3000:]
    return json.loads(line[6:])


def exists(table, rid):
    return bool(dbx(f"SELECT 1 FROM {table} WHERE id=?", (rid,)))


# ================================================================== #5263: the lint of a one-off clean-up (static)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import check_migrations as cm  # noqa: E402
OK_SRC = "# purge-ok t: why\n"
check(cm.content_findings("f", {"AFTER": (["DELETE FROM t WHERE deleted_at IS NOT NULL AND deleted_at < '2026-11-08'"], 1)}, OK_SRC) == [],
      "#5263 lint: a DELETE with a fixed cut-off and its # purge-ok line passes")
check(cm.content_findings("f", {"AFTER": (["DELETE FROM t WHERE deleted_at IS NOT NULL"], 1)}, OK_SRC),
      "#5263 lint: a DELETE without a fixed cut-off (it would empty the trash at every start) is a finding")
check(cm.content_findings("f", {"AFTER": (["DELETE FROM t WHERE deleted_at < '2026-11-08'"], 1)}, ""),
      "#5263 lint: a DELETE without its # purge-ok line is a finding")
check(cm.content_findings("f", {"AFTER": (["DELETE FROM t WHERE deleted_at < '2999-01-01'"], 1)}, OK_SRC),
      "#5263 lint: a cut-off in the future is a finding (until then every start would empty the trash)")
# 2.755.0 (#5263, review M2): a cut-off on live rows is no clean-up of the trash
check(cm.content_findings("f", {"AFTER": (["DELETE FROM t WHERE created_at < '2026-11-08'"], 1)}, OK_SRC),
      "#5263 lint: a DELETE without a trash condition (created_at < ...: live rows) is a finding")
check(cm.content_findings("f", {"AFTER": (["DELETE FROM t WHERE deleted_at < '2026-11-08'"], 1)}, OK_SRC) == [],
      "#5263 lint: deleted_at < cut-off alone is a trash condition")
check(cm.findings() == [], f"the fragments of this tree pass the lint {cm.findings()[:3]}")

kt.fresh(prefix="P2755A")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ALICE = kt.me_id(A)
FID, Fr = freelancer(B, A)


def review(s, org=None):
    lid = s.post(B + "/api/lists", json={"name": "Cut project", "kind": "project", "org_id": org}).json()["id"]
    r = s.post(B + "/api/videos", json={"title": "Cut", "url": "https://vimeo.com/123456789", "list_id": lid})
    assert r.ok, r.text
    return r.json()["id"]


def comment(s, vid, text, **kw):
    r = s.post(B + f"/api/videos/{vid}/comments", json={"body": text, "at_sec": 3, **kw})
    check(r.ok, f"setup: comment {text} {r.text[:200]}")
    return r.json()["comment_id"]


# ================================================================== #5265: the dead table paperless_links is dropped
check(not dbx("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='paperless_links'"),
      "#5265: the start dropped the table paperless_links")
check(dbx("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='pl_conns'"),
      "#5265: the other old Paperless tables stay")

# ================================================================== #5299: three indexes
IX = {r[0]: r[1] for r in dbx("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname=current_schema() AND indexname LIKE 'ix5299_%'")}
check("lists USING btree (deleted_at)" in IX.get("ix5299_lists_deleted", ""),
      f"#5299: lists(deleted_at) {IX}")
check("fs_nodes USING btree (parent_id, deleted_at)" in IX.get("ix5299_fs_nodes_parent_deleted", ""), f"#5299: fs_nodes(parent_id, deleted_at) {IX}")
check("list_activity USING btree (list_id, created_at)" in IX.get("ix5299_list_activity_list_created", ""), f"#5299: list_activity(list_id, created_at) {IX}")

# ================================================================== #5263 (a): the organisation export
VO = review(A, ORG)
C_LIVE = comment(A, VO, "Live note p2755")
C_GONE = comment(A, VO, "Deleted note p2755")
check(A.delete(B + f"/api/videos/{VO}/comments/{C_GONE}").ok, "setup: one comment deleted")
x = export(ORG, ALICE)
bodies = {c["body"] for c in x.get("videos/comments.json", [])}
check("Live note p2755" in bodies and "Deleted note p2755" not in bodies,
      f"#5263: the organisation export holds the live comment, not the deleted one {sorted(bodies)}")

# ================================================================== #5263 (b): the trash run after the period, not before
PRUNE = "from kalmido.videos.review import vdr_trash_prune\nvdr_trash_prune(c)"
C_OLD = comment(A, VO, "Old deleted p2755")
C_YOUNG = comment(A, VO, "Young deleted p2755")
for cid in (C_OLD, C_YOUNG):
    check(A.delete(B + f"/api/videos/{VO}/comments/{cid}").ok, f"setup: comment {cid} deleted")
sql("UPDATE video_comments SET deleted_at=? WHERE id=?", (OLD, C_OLD))
box(PRUNE)
check(exists("video_comments", C_OLD), "#5263: switch off (dry run): the old deleted comment stays")
box(PRUNE, env=("KALMIDO_PURGE_TRASH=1",))
check(not exists("video_comments", C_OLD), "#5263: switch on: the comment deleted before the trash period goes")
check(exists("video_comments", C_YOUNG) and exists("video_comments", C_LIVE),
      "#5263: a comment deleted within the trash period and a live one stay")
# freelancer: a private review follows the same rule
VF = review(Fr)
F_OLD = comment(Fr, VF, "Frida old p2755")
check(Fr.delete(B + f"/api/videos/{VF}/comments/{F_OLD}").ok, "setup: frida deleted her comment")
sql("UPDATE video_comments SET deleted_at=? WHERE id=?", (OLD, F_OLD))
box(PRUNE, env=("KALMIDO_PURGE_TRASH=1",))
check(not exists("video_comments", F_OLD), "freelancer #5263: her old deleted comment goes after the trash period")

# ================================================================== #5263 (c): the one-off clean-up at the next start
C_PAR = comment(A, VO, "Parent p2755")
C_ANS = comment(A, VO, "Answer p2755", parent_id=C_PAR)
check(A.delete(B + f"/api/videos/{VO}/comments/{C_PAR}").ok, "setup: the commented comment deleted (its answer stays live)")
C_LATE = comment(A, VO, "Late p2755")
check(A.delete(B + f"/api/videos/{VO}/comments/{C_LATE}").ok, "setup: one more deleted (now: after the cut-off)")
F_DEL = comment(Fr, VF, "Frida deleted p2755")
F_LIVE = comment(Fr, VF, "Frida live p2755")
check(Fr.delete(B + f"/api/videos/{VF}/comments/{F_DEL}").ok, "setup: frida deleted one")
for cid in (C_YOUNG, C_PAR, F_DEL):  # as if deleted before the update
    sql("UPDATE video_comments SET deleted_at=? WHERE id=?", (BEFORE, cid))
check(exists("video_comments", C_YOUNG) and exists("video_comments", C_PAR) and exists("video_comments", F_DEL),
      "setup: the deleted comments lie in the trash before the start")
if kt.fresh(prefix="P2755A", keep=True):  # the next start runs the fragments' AFTER
    check(not exists("video_comments", C_YOUNG) and not exists("video_comments", C_PAR),
          "#5263: the start removed the organisation's comments deleted before the cut-off")
    check(not exists("video_comments", C_ANS), "#5263: the answer below a removed comment goes with it (as in the trash run)")
    check(not exists("video_comments", F_DEL), "freelancer #5263: her deleted comment is removed too")
    check(exists("video_comments", C_LIVE) and exists("video_comments", F_LIVE), "#5263: live comments stay")
    check(exists("video_comments", C_LATE), "#5263: a comment deleted after the cut-off keeps its trash period (and the undo)")
    A, Fr = kt.sess("alice"), kt.sess("frida")
    check(A.post(B + f"/api/videos/{VO}/comments/{C_LATE}/restore").ok, "#5263: it can still be restored")
    kt.fresh(prefix="P2755A", keep=True)
    check(exists("video_comments", C_LIVE) and exists("video_comments", C_LATE), "#5263: a second start changes nothing")

sys.exit(done("p2755_a_dbfix"))
