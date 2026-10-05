"""Saved filters, folders and sections (kanban columns)."""
import json
import math
from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc, uset, usettings
from ..accounts.session import me
from ..core.access import Denied, need_list
from ..lists.lists import clean_folder, FOLDER_DEPTH, FOLDER_SEP, folder_under
from ..lists.groups import grp_list_ids, grp_sync


@app.post("/api/filters")
def filter_create():
    b = body()
    name = (b.get("name") or "").strip()
    if not name:
        return err(tr("Name missing"))
    c = db()
    srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM filters WHERE user_id=?", (me(),)).fetchone()[0]
    cur = c.execute("INSERT INTO filters(name,rules,sort,created_at,user_id) VALUES(?,?,?,?,?)",
                    (name, json.dumps(b.get("rules") or {}), srt, iso(now_utc()), me()))
    bump(c)
    c.commit()
    return jsonify(id=cur.lastrowid)


def need_filter(c, fid):
    if not c.execute("SELECT 1 FROM filters WHERE id=? AND user_id=?", (fid, me())).fetchone():
        raise Denied(404)


@app.patch("/api/filters/<int:fid>")
def filter_update(fid):
    b = body()
    c = db()
    need_filter(c, fid)
    if "name" in b and (b["name"] or "").strip():
        c.execute("UPDATE filters SET name=? WHERE id=?", (b["name"].strip(), fid))
    if "rules" in b:
        c.execute("UPDATE filters SET rules=? WHERE id=?", (json.dumps(b["rules"] or {}), fid))
    if "sort" in b:
        c.execute("UPDATE filters SET sort=? WHERE id=?", (b["sort"], fid))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.delete("/api/filters/<int:fid>")
def filter_delete(fid):
    c = db()
    need_filter(c, fid)
    c.execute("DELETE FROM filters WHERE id=?", (fid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


def _folders(c):
    try:
        return json.loads(usettings(c, me()).get("folders") or "[]")
    except (TypeError, ValueError):
        return []


def _folder_paths(c, uid):
    """Every folder path of the user: the stored order plus any folder one of their lists is in."""
    used = [r[0] for r in c.execute("SELECT folder FROM lists WHERE owner_id=? AND folder!='' UNION ALL "
                                    "SELECT folder FROM list_members WHERE user_id=? AND folder!=''", (uid, uid))]
    return list(dict.fromkeys([x for x in _folders(c) if isinstance(x, str)] + used))


def _folder_move(c, uid, fn):
    """Applies fn(path) -> new path to the user's lists, member rows, folder order and closed folders."""
    for tbl, who, key in (("lists", "owner_id", "id"), ("list_members", "user_id", "list_id")):
        for r in c.execute(f"SELECT {key} AS k, folder FROM {tbl} WHERE {who}=? AND folder!=''", (uid,)).fetchall():
            nf = fn(r["folder"])
            if nf != r["folder"]:
                c.execute(f"UPDATE {tbl} SET folder=? WHERE {key}=? AND {who}=?", (nf, r["k"], uid))
    for k in ("folders", "folders_closed"):
        try:
            arr = json.loads(usettings(c, uid).get(k) or "[]")
        except (TypeError, ValueError):
            arr = []
        arr = [fn(x) for x in arr if isinstance(x, str)]
        uset(c, uid, k, json.dumps(list(dict.fromkeys(x for x in arr if x)), ensure_ascii=False))
    # 2.10.0 (#441): folder shares with groups follow a renamed / moved folder; a deleted folder's share goes
    for r in c.execute("SELECT id, folder FROM group_shares WHERE owner_id=? AND list_id IS NULL", (uid,)).fetchall():
        nf = fn(r["folder"])
        if not nf or (nf != r["folder"] and folder_under(r["folder"], nf)):  # deleted (its lists went up a level): never widen
            c.execute("DELETE FROM group_shares WHERE id=?", (r["id"],))
        elif nf != r["folder"]:
            c.execute("UPDATE group_shares SET folder=? WHERE id=?", (nf, r["id"]))
    grp_sync(c, grp_list_ids(c, owner=uid) | {r[0] for r in c.execute("SELECT list_id FROM list_members m JOIN lists l ON l.id=m.list_id "
                                                                       "WHERE m.grole IS NOT NULL AND l.owner_id=?", (uid,))})


@app.post("/api/folders/rename")
def folder_rename():
    """{old, new}: renames or moves a folder (paths, 2.4.0 #361): "A" -> "B" renames, "A/x" -> "B/x" moves a subfolder
    into another folder, "A/x" -> "x" makes it a top-level folder, "A" -> "B/A" nests a folder (only one without
    subfolders: at most FOLDER_DEPTH levels). Its lists and subfolders go along; an existing target folder is merged."""
    b = body()
    old, new = clean_folder(str(b.get("old") or ""), False), clean_folder(b.get("new") or "")
    if not old or not new:
        return err(tr("Name missing"))
    if new == old:
        return jsonify(ok=True)
    if folder_under(new, old):
        return err(tr("A folder cannot go into itself"))
    c = db()
    uid = me()
    subs = any(p != old and folder_under(p, old) for p in _folder_paths(c, uid))
    if subs and new.count(FOLDER_SEP) + 1 >= FOLDER_DEPTH:
        return err(tr("Folders nest at most {0} levels deep", FOLDER_DEPTH))
    _folder_move(c, uid, lambda p: new + p[len(old):] if folder_under(p, old) else p)
    for fp in c.execute("SELECT folder, user_id FROM folder_people WHERE owner_id=?", (uid,)).fetchall():  # 2.22.0 (#740)
        if folder_under(fp[0], old):
            c.execute("UPDATE OR REPLACE folder_people SET folder=? WHERE owner_id=? AND folder=? AND user_id=?", (new + fp[0][len(old):], uid, fp[0], fp[1]))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/folders/delete")
def folder_delete():
    """Removes the folder only: its lists and subfolders move up one level (2.4.0: a top folder's subfolders become
    top-level folders, a subfolder's lists go to its parent folder)."""
    name = clean_folder(str(body().get("name") or ""), False)
    if not name:
        return err(tr("Name missing"))
    c = db()
    uid = me()
    parent = name.rsplit(FOLDER_SEP, 1)[0] if FOLDER_SEP in name else ""

    def up(p):
        if p == name:
            return parent or "\0"  # a top folder's own lists: top level (dropped from the order below)
        if folder_under(p, name):
            rest = p[len(name) + 1:]
            return (parent + FOLDER_SEP + rest) if parent else rest
        return p
    _folder_move(c, uid, lambda p: "" if up(p) == "\0" else up(p))
    c.execute("DELETE FROM folder_people WHERE owner_id=? AND folder=?", (uid, name))  # 2.22.0 (#740): the folder is gone
    bump(c)
    c.commit()
    return jsonify(ok=True)


def need_section(c, sid):
    r = c.execute("SELECT list_id FROM sections WHERE id=?", (sid,)).fetchone()
    if not r:
        raise Denied(404)
    need_list(c, r[0])


def _sec_tasks(c, sid):
    return [r[0] for r in c.execute("SELECT id FROM tasks WHERE section_id=? AND deleted_at IS NULL ORDER BY id", (sid,))]


def _sec_sort(v):
    from ..personal.timetrack import BadInput
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "sort")) from None
    if not math.isfinite(v):
        raise BadInput(tr("Invalid value: {0}", "sort"))
    return v


@app.post("/api/sections")
def section_create():
    """{list_id, name, sort?, tasks?}. D4 (undo of a deleted section): sort = its old place, tasks = the tasks that were
    in it -- each moves back only while it is still in that list without a section (else it is reported in skipped)."""
    from ..tasks.validation import as_int, log_changes
    b = body()
    name = (b.get("name") or "").strip()
    if not name or not b.get("list_id"):
        return err(tr("Name/list missing"))
    c = db()
    lid = as_int(b["list_id"], "list_id", 1)
    need_list(c, lid)
    srt = _sec_sort(b["sort"]) if b.get("sort") is not None else \
        c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM sections WHERE list_id=?", (lid,)).fetchone()[0]
    tids = b.get("tasks") or []
    if not isinstance(tids, list) or len(tids) > 5000 or any(isinstance(i, bool) or not isinstance(i, int) for i in tids):
        return err(tr("Invalid value: {0}", "tasks"))
    cur = c.execute("INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, name[:200], srt))
    sid, moved, skipped = cur.lastrowid, [], []
    for tid in tids:
        r = c.execute("SELECT list_id, section_id, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
        if not r or r["deleted_at"] or r["list_id"] != lid or r["section_id"] is not None:
            skipped.append(tid)
            continue
        before = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        c.execute("UPDATE tasks SET section_id=?, updated_at=? WHERE id=?", (sid, iso(now_utc()), tid))
        log_changes(c, tid, before)
        moved.append(tid)
    bump(c)
    c.commit()
    return jsonify({**dict(c.execute("SELECT * FROM sections WHERE id=?", (sid,)).fetchone()), "moved": moved, "skipped": skipped})


@app.patch("/api/sections/<int:sid>")
def section_update(sid):
    """{name?, sort?, _prev?: {name}}: with _prev (undo / redo) a name changed elsewhere meanwhile stays (conflicts)."""
    b = body()
    c = db()
    need_section(c, sid)
    conflicts = []
    prev = b.get("_prev") if isinstance(b.get("_prev"), dict) else {}
    cur = c.execute("SELECT name FROM sections WHERE id=?", (sid,)).fetchone()
    if "name" in b:
        name = str(b["name"] or "").strip()[:200]
        if not name:
            return err(tr("Name missing"))
        if "name" in prev and cur["name"] != str(prev["name"] or "") and cur["name"] != name:
            conflicts.append({"field": "name", "server": cur["name"], "mine": name})
        else:
            c.execute("UPDATE sections SET name=? WHERE id=?", (name, sid))
    if "sort" in b:
        c.execute("UPDATE sections SET sort=? WHERE id=?", (_sec_sort(b["sort"]), sid))
    bump(c)
    c.commit()
    return jsonify(ok=True, conflicts=conflicts)


@app.post("/api/lists/<int:lid>/sections/order")
def sections_order(lid):
    """{ids: [...], _prev?: [...]}: the list's sections in their new order (every one exactly once), one transaction, edit
    rights. Returns the previous order (the client's undo sends it back). With _prev (undo / redo): only while the order
    is still the expected one, else nothing changes and the answer carries a conflict."""
    c = db()
    need_list(c, lid)
    b = body()
    ids, prev = b.get("ids"), b.get("_prev")
    cur = [r[0] for r in c.execute("SELECT id FROM sections WHERE list_id=? ORDER BY sort, id", (lid,))]
    bad = not isinstance(ids, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in ids)
    if prev is not None and (bad or not isinstance(prev, list) or prev != cur or sorted(ids) != sorted(cur)):
        return jsonify(ok=False, prev=cur, ids=cur, conflicts=[{"field": "order", "server": cur, "mine": ids}])
    if bad or sorted(ids) != sorted(cur):
        return err(tr("Invalid value: {0}", "ids"))
    c.executemany("UPDATE sections SET sort=? WHERE id=?", [(k, i) for k, i in enumerate(ids)])
    bump(c)
    c.commit()
    return jsonify(ok=True, prev=cur, ids=ids, conflicts=[])


@app.delete("/api/sections/<int:sid>")
def section_delete(sid):
    """Deletes a section, its tasks stay (without a section). Returns the section and the ids of its tasks (the undo
    recreates it with them). Optional body {_prev: {name, tasks}} (undo / redo): only while the section still has that
    name and exactly those tasks, else nothing happens and the answer carries a conflict."""
    c = db()
    need_section(c, sid)
    sec = dict(c.execute("SELECT id, list_id, name, sort FROM sections WHERE id=?", (sid,)).fetchone())
    tids = _sec_tasks(c, sid)
    prev = body().get("_prev")
    if isinstance(prev, dict):
        want = prev.get("tasks") if isinstance(prev.get("tasks"), list) else []
        if sec["name"] != str(prev.get("name") or "") or sorted(tids) != sorted(x for x in want if isinstance(x, int)):
            return jsonify(ok=False, section=sec, tasks=tids,
                           conflicts=[{"field": "section", "server": {"name": sec["name"], "tasks": tids}, "mine": prev}])
    c.execute("DELETE FROM sections WHERE id=?", (sid,))
    bump(c)
    c.commit()
    return jsonify(ok=True, section=sec, tasks=tids, conflicts=[])
