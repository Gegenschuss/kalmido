#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1097.0 (#5949, rest of stage Q11 #5289): the account export's queries of the core's tables, the export of single documents
(a personal office's documents/notes.json) and the import's list of what stays behind (UMZ_LEFT) read the export register
(kalmido/core/objexport.py acct / acct_more / nodes). Invented names only (example.com).
 - before / after: the parts, queries and arguments the register gives are exactly the hand queries of 2.1096 (frozen below with
   the helpers they used), the node clause is the old one, UMZ_LEFT holds the same names with the same parts; a query without
   its person, a node clause without its nodes or without an archive of the table are refused
 - freelancer-matrix: a person without an organisation: the account export carries the own comment, personal tag, watch and
   the project's notification setting in the old files and columns; GET /api/export.json the same; the import's preview names
   the parts the register calls "Notifications" / "Reactions"
Starts its OWN container (workspaces mode). usage: p21097_a_export_register_rest_test.py <datadir>"""
# freelancer-matrix: tasks
import io
import json
import subprocess
import sys
import zipfile

import kt
from freelancer_fixture import freelancer
from kt import B, check, dbx, su_get

kt.fresh(prefix="P21097A", env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_API_RATE": "100000"})
kt.docker_logs_on_first_fail()
TS = "2026-11-10T10:00:00+00:00"


def ok(r, what):
    check(r.status_code in (200, 201, 202, 204), f"{what} {r.status_code} {r.text[:200]}")
    try:
        return r.json()
    except ValueError:
        return {}


def in_app(code):
    r = subprocess.run(["docker", "exec", kt.CT, "python", "-c", code], capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ERR " + r.stderr[-600:]


# ================================================================== before / after (in the app, no data)
# the hand queries as they stood in 2.1096 (accounts/settings.py umz_export_queries, admin/acctexport.py umz_extra_queries /
# umz_mine_queries), admin/orgexport.py ox_pb_store's notes clause and admin/acctimport.py UMZ_LEFT's entries of these parts
SNAP = r'''
import json
import app  # noqa: F401 (every module registered)
from kalmido.accounts.settings import umz_export_queries
from kalmido.admin.acctexport import umz_extra_queries, umz_mine_queries
from kalmido.admin.acctimport import UMZ_LEFT, UMZ_LEFT_OWN
from kalmido.core.access import acx_lists_sql, live_sql, otr_live
from kalmido.core.objcomments import OCM_TS, ocm_old_cols, ocm_video_cols
from kalmido.core.objexport import obj_export, oex_nodes
uid = 7
own = f"(SELECT id FROM lists WHERE owner_id=? AND ({otr_live('')} OR org_id IS NULL))"
task_ids = f"(SELECT id FROM tasks WHERE list_id IN {own})"
shared = "(SELECT m.list_id FROM list_members m JOIN lists l ON l.id=m.list_id WHERE m.user_id=? AND l.owner_id!=?)"
vis = acx_lists_sql(req=False)
OLD = {
    "task_tags": ("""SELECT k.obj_id AS task_id, CAST(ot.scope_id AS BIGINT) AS user_id, ot.name AS tag FROM obj_tag_links k
                         JOIN obj_tags ot ON ot.id=k.tag_id AND ot.scope_kind='user' AND ot.scope_id=CAST(CAST(? AS BIGINT) AS TEXT)
                         WHERE k.kind='task' ORDER BY k.obj_id, ot.name""", (uid,)),
    "comments": (f"SELECT {ocm_old_cols()} FROM obj_comments WHERE kind='task' AND ref_id IN {task_ids} AND deleted_at IS NULL", (uid,)),
    "list_notif": (f"SELECT ref_id AS list_id, user_id, tpl, custom::text AS custom, updated_at FROM obj_notif_cap "
                   f"WHERE kind='list' AND ref_id IN {own}", (uid,)),
    "folder_notif": ("SELECT ref_id AS owner_id, path AS folder, user_id, tpl, custom::text AS custom, updated_at FROM obj_notif_cap "
                     "WHERE kind='folder' AND ref_id=?", (uid,)),
    "task_bell": ("SELECT ref_id AS task_id, mode AS level, until::text AS until, set_by, created_at, updated_at FROM obj_follow "
                  "WHERE user_id=? AND kind='task' AND mode<>'watch'", (uid,)),
    "task_watchers": ("SELECT ref_id AS task_id, created_at FROM obj_follow WHERE user_id=? AND kind='task' AND mode='watch'", (uid,)),
}
OLD_MORE = {
    "list_tags": (f"""SELECT id, CAST(scope_id AS BIGINT) AS list_id, name, color, sort, created_at FROM obj_tags
                          WHERE scope_kind='list' AND scope_id IN (SELECT CAST(x.id AS TEXT) FROM lists x WHERE x.id IN {own})""", (uid,)),
    "task_list_tags": (f"""SELECT k.obj_id AS task_id, k.tag_id FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id AND ot.scope_kind='list'
                               WHERE k.kind='task' AND k.obj_id IN (SELECT id FROM tasks WHERE list_id IN {own})""", (uid,)),
    "shared_comments": (f"""SELECT c.id, c.ref_id AS task_id, t.title AS task_title, t.list_id, c.body,
                                to_char(c.created_at AT TIME ZONE 'UTC', '{OCM_TS}') AS created_at,
                                to_char(c.edited_at AT TIME ZONE 'UTC', '{OCM_TS}') AS edited_at FROM obj_comments c
                                JOIN tasks t ON t.id=c.ref_id AND c.kind='task' WHERE c.user_id=? AND c.deleted_at IS NULL AND t.list_id IN {shared}""",
                        (uid, uid, uid)),
    "video_comments": (f"SELECT {ocm_video_cols('k')} FROM obj_comments k WHERE k.kind='video' AND k.ref_id IN (SELECT id FROM video_reviews "
                       "WHERE owner_id=? AND org_id IS NULL) AND k.deleted_at IS NULL", (uid,)),
    "written_comments": (f"""SELECT c.id, c.ref_id AS task_id, CASE WHEN t.list_id IN {vis} THEN t.title END AS task_title,
                                 CASE WHEN t.list_id IN {vis} THEN t.list_id END AS list_id, c.body,
                                 to_char(c.created_at AT TIME ZONE 'UTC', '{OCM_TS}') AS created_at,
                                 to_char(c.edited_at AT TIME ZONE 'UTC', '{OCM_TS}') AS edited_at
                                 FROM obj_comments c JOIN tasks t ON t.id=c.ref_id AND c.kind='task' WHERE c.user_id=? AND c.deleted_at IS NULL
                                 AND t.list_id NOT IN {own} AND t.list_id NOT IN {shared} ORDER BY c.id""",
                         (uid, uid, uid, uid, uid, uid, uid, uid)),
    "reactions": ("""SELECT CASE target_kind WHEN 'tchat' THEN 'message' ELSE target_kind END AS kind, target_id, emoji,
                         to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"+00:00"') AS created_at
                         FROM obj_reactions WHERE user_id=? ORDER BY obj_reactions.created_at, target_kind, target_id""", (uid,)),
}
norm = lambda q: " ".join(q.split())  # the register's literals are indented differently, the SQL is the same
same = lambda d, old: {p: (norm(d[p][0]), tuple(d[p][1])) == (norm(s), a) for p, (s, a) in old.items() if p in d}
mine = umz_mine_queries(uid)
out = {"acct": same(umz_export_queries(uid), OLD), "more": same(umz_extra_queries(uid), OLD_MORE),
       "missing": sorted(set(OLD) - set(umz_export_queries(uid)) | set(OLD_MORE) - set(umz_extra_queries(uid))),
       "mine_hand": sorted(set(OLD_MORE) & set(mine))}
OLD_LEFT = {"Shared with me": ("shared_lists", "shared_comments"), "Notifications": ("list_notif", "folder_notif"),
            "Comments in other projects": ("written_comments",), "Reactions": ("reactions",)}
left = dict(UMZ_LEFT)
out["left"] = {w: left.get(w) == ps for w, ps in OLD_LEFT.items()}
out["left_rest"] = [e for e in UMZ_LEFT if e[0] not in OLD_LEFT] == [e for e in UMZ_LEFT_OWN if e[0] not in OLD_LEFT]
out["left_own"] = sorted(p for _w, ps in UMZ_LEFT_OWN for p in ps if p in {x for v in OLD_LEFT.values() for x in v} - {"shared_lists"})
out["nodes"] = oex_nodes({"NODES": "11,12", "LIVE": live_sql()}) == (("documents/notes.json", "obj_comments", f"kind='doc_note' AND ref_id IN (11,12) AND {live_sql()}"),)


def refused(**kw):
    try:
        obj_export("obj_zz_" + str(len(out)), by="kind zz" + str(len(out)), **kw)
        return "accepted"
    except ValueError as e:
        return str(e)


out["no_person"] = refused(acct=(("zz_all", "SELECT * FROM obj_comments"),))
out["no_select"] = refused(acct_more=(("zz_del", "DELETE FROM obj_comments WHERE user_id=?"),))
out["no_nodes"] = refused(org=(("zz/a.json", "org_id=?"),), nodes=(("zz/a.json", "kind='x'"),))
out["no_archive"] = refused(org=(("zz/a.json", "org_id=?"),), nodes=(("zz/b.json", "ref_id IN ({NODES})"),))
print(json.dumps(out, sort_keys=True))
'''
r = in_app(SNAP)
try:
    snap = json.loads(r)
except ValueError:
    snap = {}
check(snap.get("acct") and all(snap["acct"].values()) and len(snap["acct"]) == 6,
      f"before / after: the parts of my data (task_tags, comments, list_notif, folder_notif, task_bell, task_watchers) are the old queries {r[:400]}")
check(snap.get("more") and all(snap["more"].values()) and len(snap["more"]) == 6,
      f"before / after: the account export's parts (list_tags, task_list_tags, shared/video/written comments, reactions) are the old ones {snap.get('more')}")
check(snap.get("missing") == [] and snap.get("mine_hand") == [], f"every part is there once, none left by hand {snap.get('missing')} {snap.get('mine_hand')}")
check(snap.get("left") and all(snap["left"].values()), f"UMZ_LEFT: the register's parts under their old names and groups {snap.get('left')}")
check(snap.get("left_rest") is True and snap.get("left_own") == [], f"UMZ_LEFT: the other entries unchanged, no register part by hand {snap.get('left_own')}")
check(snap.get("nodes") is True, "the notes of single documents: the old clause from the register")
check("names its person" in str(snap.get("no_person")), f"an account query without its person is refused {snap.get('no_person')}")
check("names its person" in str(snap.get("no_select")), f"an account query that is no SELECT is refused {snap.get('no_select')}")
check("names its nodes" in str(snap.get("no_nodes")), f"a node clause without its nodes is refused {snap.get('no_nodes')}")
check("names its nodes" in str(snap.get("no_archive")), f"a node clause without an archive of org is refused {snap.get('no_archive')}")

# ================================================================== freelancer-matrix: a person without an organisation
A = kt.setup()
kt.proved()
FID, Fr = freelancer(B, A)
FL = ok(Fr.post(B + "/api/lists", json={"name": "Frei Projekt"}), "freelancer: own list").get("id")
FT = ok(Fr.post(B + "/api/tasks", json={"title": "Frei Aufgabe", "list_id": FL}), "freelancer: own task").get("id")
ok(Fr.post(B + f"/api/tasks/{FT}/comments", json={"body": "Frei Kommentar"}), "freelancer: own comment")
# the core's rows directly where this suite does not check the area's route: a personal tag, a watch, a project's notification setting
dbx("INSERT INTO obj_tags(scope_kind, scope_id, name) VALUES('user', ?, 'frei-tag')", (str(FID),))
tg = dbx("SELECT id FROM obj_tags WHERE scope_kind='user' AND scope_id=? AND name='frei-tag'", (str(FID),))
dbx("INSERT INTO obj_tag_links(tag_id, kind, obj_id) VALUES(?, 'task', ?)", (tg[0][0] if tg else 0, FT))
dbx("INSERT INTO obj_follow(kind, ref_id, user_id, mode, created_at) VALUES('task',?,?,'watch',?)", (FT, FID, TS))
dbx("INSERT INTO obj_notif_cap(kind, ref_id, user_id, tpl) VALUES('list', ?, 0, 'work')", (FL,))

ej = ok(Fr.get(B + "/api/export.json"), "freelancer: export.json")
check([c.get("body") for c in ej.get("comments") or []] == ["Frei Kommentar"], f"export.json: the own comment {ej.get('comments')}")
check([t.get("tag") for t in ej.get("task_tags") or []] == ["frei-tag"], f"export.json: the personal tag in task_tags' columns {ej.get('task_tags')}")
check([(n.get("list_id"), n.get("tpl")) for n in ej.get("list_notif") or []] == [(FL, "work")], f"export.json: the project's notification setting {ej.get('list_notif')}")
check([w.get("task_id") for w in ej.get("task_watchers") or []] == [FT], f"export.json: the watch {ej.get('task_watchers')}")

ok(Fr.post(B + "/api/account/export", json={}), "freelancer: account export starts")
kt.until(lambda: Fr.get(B + "/api/account/export").json().get("state") != "running", timeout=240)
check(Fr.get(B + "/api/account/export").json().get("state") == "done", "freelancer: account export done")
raw = su_get(Fr, B + "/api/account/export/file").content
try:
    fz = zipfile.ZipFile(io.BytesIO(raw))
except zipfile.BadZipFile:
    fz = None
check(fz is not None, "freelancer: the account export is a ZIP")
fn = set(fz.namelist()) if fz else set()


def part(p):
    if f"data/{p}.json" not in fn:
        return []
    t = fz.read(f"data/{p}.json").decode()
    try:
        v = json.loads(t)
    except ValueError:
        v = [json.loads(x) for x in t.splitlines() if x.strip()]
    return v if isinstance(v, list) else []


check([c.get("body") for c in part("comments")] == ["Frei Kommentar"], f"account export: data/comments.json {part('comments')}")
check([(t.get("task_id"), t.get("tag")) for t in part("task_tags")] == [(FT, "frei-tag")], f"account export: data/task_tags.json {part('task_tags')}")
check([t.get("task_id") for t in part("task_watchers")] == [FT], f"account export: data/task_watchers.json {part('task_watchers')}")
check([n.get("tpl") for n in part("list_notif")] == ["work"], f"account export: data/list_notif.json {part('list_notif')}")
check({"list_tags", "reactions", "written_comments", "shared_comments"} <= {p[5:-5] for p in fn if p.startswith("data/")},
      f"account export: the account-only parts of the register are in the file {sorted(fn)[:12]}")

# the import's preview: what stays behind is named by the register (UMZ_LEFT)
r = in_app("import json, app\nfrom kalmido.admin.acctimport import umz_left\n"
           "print(json.dumps(umz_left({'list_notif': [{}], 'folder_notif': [{}, {}], 'reactions': [{}], 'shared_lists': [], 'shared_comments': [{}]})))")
try:
    left = {x["what"]: x["count"] for x in json.loads(r)}
except (ValueError, KeyError, TypeError):
    left = {}
check(left == {"Notifications": 1, "Reactions": 1, "Shared with me": 1},
      f"the import names the register's parts as before (first part counts, the next only when it is empty) {r[:300]}")

sys.exit(kt.done("p21097_a_export_register_rest"))
