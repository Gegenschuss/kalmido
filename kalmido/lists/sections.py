"""Saved filters, folders and sections (kanban columns)."""
import json
import math
from flask import jsonify

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc, uset, usettings
from ..accounts.session import me
from ..core.access import Denied, is_project, need_list
from ..lists.lists import clean_folder, FOLDER_DEPTH, FOLDER_SEP, folder_under
from ..lists.groups import grp_list_ids, grp_sync, grp_touch
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions
from ..lists.lists import lp_folder_rename  # 2.369.5 (#2517): pulled up from functions
from ..lists.seckind import sk_clean  # 2.577.0 (#3354)
from ..tasks.validation import as_int


def view_rules(rules):
    """2.577.0 (#3356): a shared view is the view of its one project: no other project in its rules (old rules.lists, a
    project / folder condition of the dialog since 2.521.0)."""
    out = {k: v for k, v in (rules or {}).items() if k != "lists"}
    if isinstance(out.get("conds"), list):
        out["conds"] = [x for x in out["conds"] if not (isinstance(x, dict) and x.get("f") in ("list", "folder"))]
    return out


def view_plain(c, lid, name, rules):
    """2.577.0 (#3356): a view's name and text rule are stored readable: refused in a project encrypted in the browser, like a
    notepad (its text rule could not match there anyway).
    2.577.0 (#3356, review): also a text condition of the newer format (rules.conds [{f: "text", v}]), not only rules.text."""
    from ..collab.liste2e import le2a_locked_text
    r = rules if isinstance(rules, dict) else {}
    conds = r.get("conds") if isinstance(r.get("conds"), list) else []
    texts = [x.get("v") for x in conds if isinstance(x, dict) and x.get("f") == "text"]
    le2a_locked_text(c, lid, name, r.get("text"), *[v if isinstance(v, str) or v is None else json.dumps(v) for v in texts])


@app.post("/api/filters")
def filter_create():
    """2.577.0 (#3356): with list_id a shared view of that project (shared: true, the default then), for its editors."""
    b = body()
    name = (b.get("name") or "").strip()
    if not name:
        return err(tr("Name missing"))
    c = db()
    if b.get("list_id") is None:
        if b.get("shared"):
            raise BadInput(tr("Invalid value: {0}", "shared"))
        srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM filters WHERE user_id=? AND list_id IS NULL", (me(),)).fetchone()[0]
        cur_id = insert_id(c, "INSERT INTO filters(name,rules,sort,created_at,user_id) VALUES(?,?,?,?,?)",
                           (name, json.dumps(b.get("rules") or {}), srt, iso(now_utc()), me()))
    else:
        lid = as_int(b["list_id"], "list_id", 1)
        if b.get("shared") is False:
            raise BadInput(tr("Invalid value: {0}", "shared"))
        need_list(c, lid)
        view_plain(c, lid, name, b.get("rules"))
        if not is_project(c, lid):
            raise BadInput(tr("Invalid value: {0}", "list_id"))
        if not isinstance(b.get("rules") or {}, dict):
            raise BadInput(tr("Invalid value: {0}", "rules"))
        srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM filters WHERE list_id=? AND shared=1", (lid,)).fetchone()[0]
        cur_id = insert_id(c, "INSERT INTO filters(name,rules,sort,created_at,user_id,list_id,shared) VALUES(?,?,?,?,?,?,1)",
                           (name, json.dumps(view_rules(b.get("rules"))), srt, iso(now_utc()), me(), lid))
    bump(c)
    c.commit()
    return jsonify(id=cur_id)


def filter_read(c, fid):
    """2.577.0 (#3356): the filter row for whoever may read it: an own private filter, or a shared view of a project the person
    sees right now. Anything else is 404 (a filter of someone else, a project left, moved out of reach or in the trash)."""
    r = c.execute("SELECT * FROM filters WHERE id=?", (fid,)).fetchone()
    if r and r["shared"]:
        need_list(c, r["list_id"], write=False)
    elif not r or r["user_id"] != me():
        raise Denied(404)
    return r


def need_filter(c, fid):
    """Change / delete: an own private filter; a shared view for the project's editors (a reader: 403)."""
    r = filter_read(c, fid)
    if r["shared"]:
        need_list(c, r["list_id"])
    return r


@app.patch("/api/filters/<int:fid>")
def filter_update(fid):
    b = body()
    c = db()
    f = need_filter(c, fid)
    if f["shared"]:
        view_plain(c, f["list_id"], b.get("name"), b.get("rules"))
    if "name" in b and (b["name"] or "").strip():
        c.execute("UPDATE filters SET name=? WHERE id=?", (b["name"].strip(), fid))
    if "rules" in b:
        if f["shared"] and not isinstance(b["rules"] or {}, dict):
            raise BadInput(tr("Invalid value: {0}", "rules"))
        c.execute("UPDATE filters SET rules=? WHERE id=?", (json.dumps(view_rules(b["rules"]) if f["shared"] else b["rules"] or {}), fid))
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
    for k in ("folders", "folders_closed", "cal_folders_hidden"):  # 2.624.0 (#3946): the folders hidden in the calendar go along
        try:
            arr = json.loads(usettings(c, uid).get(k) or "[]")
        except (TypeError, ValueError):
            arr = []
        arr = [fn(x) for x in arr if isinstance(x, str)]
        uset(c, uid, k, json.dumps(list(dict.fromkeys(x for x in arr if x)), ensure_ascii=False))
    # 2.10.0 (#441): folder shares with groups follow a renamed / moved folder; a deleted folder's share goes. 2.958.0 (#5245): they
    # are shares of the folder's nodes, which lffolder.lf_folder_repath / lf_folder_dissolve move or remove (group_shares is gone)
    grp_sync(c, grp_list_ids(c, owner=uid) | {r[0] for r in c.execute("SELECT list_id FROM list_members m JOIN lists l ON l.id=m.list_id "
                                                                       "WHERE m.grole IS NOT NULL AND l.owner_id=?", (uid,))})


def _cal_folder_drop(c, uid, name):
    """2.624.0 (#3946): a deleted folder leaves cal_folders_hidden (its lists go up a level and show in the calendar again;
    its subfolders keep their own entry, moved up by _folder_move)."""
    try:
        arr = json.loads(usettings(c, uid).get("cal_folders_hidden") or "[]")
    except (TypeError, ValueError):
        arr = []
    if isinstance(arr, list) and name in arr:
        uset(c, uid, "cal_folders_hidden", json.dumps([x for x in arr if x != name], ensure_ascii=False))


@app.post("/api/folders/rename")
def folder_rename():
    """{old, new}: renames or moves a folder (paths, 2.4.0 #361): "A" -> "B" renames, "A/x" -> "B/x" moves a subfolder
    into another folder, "A/x" -> "x" makes it a top-level folder, "A" -> "B/A" nests a folder (only one without
    subfolders: at most FOLDER_DEPTH levels, 2.352.0: 30). Its lists and subfolders go along; an existing target folder is merged."""
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
    write_lock(c, f"usettings-{int(uid)}")  # 2.269.0 B (#3014): folder order / closed folders read-change-write like PATCH /api/settings
    # 2.352.0 A (#2748): any depth up to FOLDER_DEPTH (was: a folder with subfolders never became a subfolder)
    below = max([p.count(FOLDER_SEP) - old.count(FOLDER_SEP) for p in _folder_paths(c, uid) if folder_under(p, old)] or [0])
    if new.count(FOLDER_SEP) + 1 + below > FOLDER_DEPTH:
        return err(tr("Folders nest at most {0} levels deep", FOLDER_DEPTH))
    merged = any(p == new or folder_under(p, new) for p in _folder_paths(c, uid))  # 2.809.0 (#5476): into an existing folder
    folder_rename_do(c, uid, old, new)
    from .foldundo import fpu_add  # 2.809.0 (#5476): a step of the person's undo list (not a merge)
    ug = fpu_add(c, uid, old, new, merged)
    bump(c)
    c.commit()
    return jsonify(ok=True, **({"undo_group": ug} if ug else {}))


def folder_rename_do(c, uid, old, new):
    """Folder path old of uid becomes new: lists, member rows, folder order, shares and every setting keyed by the path go
    along. 2.352.0 A (#2748): also the folder nodes in the projects trees (lists/lffolder.py; a node moved in the tree calls
    this after the move). Caller commits."""
    from ..lists.lffolder import lf_folder_repath
    lf_folder_repath(c, uid, old, new)
    _folder_move(c, uid, lambda p: new + p[len(old):] if folder_under(p, old) else p)
    # 2.958.0 (#5245): the folder's people are the shares of its nodes (lf_folder_repath above moved them); folder_people is gone
    from ..notify.caps import folder_tpl_rename
    folder_tpl_rename(c, uid, old, new)  # 2.33.0 (#927): the folder's notification templates go along
    from ..integrations.gitfolder import gf_rename
    gf_rename(c, uid, old, new)  # 2.33.0 (#934): the folder's repositories go along
    from ..lists.playbook import pb_folder_rename
    pb_folder_rename(c, uid, old, new)  # 2.39.0 (#1168): the folder's Playbook (and its subfolders') go along
    from ..lists.foldershare import sh_folder_rename
    sh_folder_rename(c, uid, old, new)  # 2.41.0 (#1420): the folder's agents go along
    lp_folder_rename(c, uid, old, new)  # 2.53.0 (#1426): the folder's colour (and its subfolders') go along
    from ..lists.favorites import fv2_folder_rename
    fv2_folder_rename(c, uid, old, new)  # 2.57.0 (#1798): a favourite folder (and its subfolders) stays a favourite
    grp_touch(c, uid)  # 2.352.0 A (#2748): the lists' nodes where their new paths say, their roles anew


@app.post("/api/folders/delete")
def folder_delete():
    """Removes the folder only: its lists and subfolders move up one level (2.4.0: a top folder's subfolders become
    top-level folders, a subfolder's lists go to its parent folder)."""
    name = clean_folder(str(body().get("name") or ""), False)
    if not name:
        return err(tr("Name missing"))
    c = db()
    uid = me()
    write_lock(c, f"usettings-{int(uid)}")  # 2.269.0 B (#3014)
    parent = name.rsplit(FOLDER_SEP, 1)[0] if FOLDER_SEP in name else ""

    def up(p):
        if p == name:
            return parent or "\0"  # a top folder's own lists: top level (dropped from the order below)
        if folder_under(p, name):
            rest = p[len(name) + 1:]
            return (parent + FOLDER_SEP + rest) if parent else rest
        return p
    from ..lists.lffolder import lf_folder_dissolve
    lf_folder_dissolve(c, uid, name)  # 2.352.0 A (#2748): its nodes go, their content one level up (before the paths move)
    _cal_folder_drop(c, uid, name)  # 2.624.0 (#3946): before the move, so the parent does not get the folder's "hidden"
    _folder_move(c, uid, lambda p: "" if up(p) == "\0" else up(p))
    from ..integrations.gitfolder import gf_folder_removed
    gf_folder_removed(c, uid, lambda p: "" if up(p) == "\0" else up(p))  # 2.33.0 (#934): its repositories go to the parent folder
    from ..lists.playbook import pb_folder_removed
    pb_folder_removed(c, uid, name, up)  # 2.39.0 (#1168): the subfolders' Playbooks move up; the folder's own one ends empty (history kept)
    # 2.958.0 (#5245): the folder's people were the shares of its nodes (lf_folder_dissolve took them); folder_people is gone
    c.execute("DELETE FROM folder_agents WHERE owner_id=? AND folder=?", (uid, name))  # 2.41.0 (#1420)
    grp_touch(c, uid)  # 2.352.0 A (#2748)
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
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "sort")) from None
    if not math.isfinite(v):
        raise BadInput(tr("Invalid value: {0}", "sort"))
    return v


def wip_hard_clean(v):
    """2.392.0 A (#3367): the "no new agent jobs while over the limit" switch from a client value: 0 / 1."""
    if v in (None, "", 0, "0", False):
        return 0
    if v in (1, "1", True):
        return 1
    raise BadInput(tr("Invalid value: {0}", "wip_hard"))


def wip_clean(v):
    """2.60.0 (#1510): a section's WIP limit from a client value: None / '' / 0 = no limit, else 1..999."""
    if v in (None, "", 0, "0"):
        return None
    from ..tasks.validation import as_int
    return as_int(v, "wip_limit", 1, 999)


DW_KEYS = ("dwell_warn_h", "dwell_alert_h")


def dw_clean(v, what):
    """2.410.0 B (#3515): a column's time limit (hours) from a client value: None / '' / 0 = none, else 1 h .. 1 year."""
    if v in (None, "", 0, "0"):
        return None
    n = v if isinstance(v, int) and not isinstance(v, bool) else int(v) if isinstance(v, str) and v.strip().isdigit() else 0
    if not 1 <= n <= 8760:
        raise BadInput(tr("Invalid value: {0}", what))
    return n


def dw_check(warn, alert):
    """2.410.0 B (#3515): red comes after yellow (both set)."""
    if warn and alert and alert <= warn:
        raise BadInput(tr("The red limit must be above the yellow one."))


@app.post("/api/sections")
def section_create():
    """{list_id, name, sort?, tasks?}. D4 (undo of a deleted section): sort = its old place, tasks = the tasks that were
    in it -- each moves back only while it is still in that list without a section (else it is reported in skipped)."""
    from ..tasks.validation import as_int, log_changes
    b = body()
    name = (b.get("name") or "").strip()
    if not name or not b.get("list_id"):
        return err(tr("Name/project missing"))
    c = db()
    lid = as_int(b["list_id"], "list_id", 1)
    need_list(c, lid)
    from ..collab.liste2e import le2a_clean_cipher, le2e_guard, le2e_is_cipher
    if le2e_is_cipher(name):  # 2.64.1 (#1817): the encrypted name of a section in a list with the lock (never cut)
        name = le2a_clean_cipher(name, "name")
    le2e_guard(c, lid, {"section": name})
    srt = _sec_sort(b["sort"]) if b.get("sort") is not None else \
        c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM sections WHERE list_id=?", (lid,)).fetchone()[0]
    tids = b.get("tasks") or []
    if not isinstance(tids, list) or len(tids) > 5000 or any(isinstance(i, bool) or not isinstance(i, int) for i in tids):
        return err(tr("Invalid value: {0}", "tasks"))
    wip = wip_clean(b.get("wip_limit"))  # 2.60.0 (#1510): also the undo of a deleted section brings its limit back
    dw = [dw_clean(b.get(k), k) for k in DW_KEYS]  # 2.410.0 B (#3515): the same for its time limits
    dw_check(*dw)
    hard = wip_hard_clean(b.get("wip_hard")) if wip else 0  # 2.392.0 A (#3367): only with a limit
    kind = sk_clean(b.get("kind"))  # 2.577.0 (#3354): the undo of a deleted section brings its meaning back
    cur_id = insert_id(c, "INSERT INTO sections(list_id,name,sort,wip_limit,dwell_warn_h,dwell_alert_h,wip_hard,kind) VALUES(?,?,?,?,?,?,?,?)",
                       (lid, name if le2e_is_cipher(name) else name[:200], srt, wip, *dw, hard, kind))
    sid, moved, skipped = cur_id, [], []
    for tid in tids:
        r = c.execute("SELECT list_id, section_id, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
        if not r or r["deleted_at"] or r["list_id"] != lid or r["section_id"] is not None:
            skipped.append(tid)
            continue
        before = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        c.execute("UPDATE tasks SET section_id=?, updated_at=? WHERE id=?", (sid, iso(now_utc()), tid))
        log_changes(c, tid, before)
        moved.append(tid)
    from .secundo import secu_add  # 2.809.0 (#5476): a step of the person's undo list
    ug = secu_add(c, sid, "create", name, lid)
    bump(c)
    c.commit()
    return jsonify({**dict(c.execute("SELECT * FROM sections WHERE id=?", (sid,)).fetchone()), "moved": moved, "skipped": skipped,
                    **({"undo_group": ug} if ug else {})})


@app.patch("/api/sections/<int:sid>")
def section_update(sid):
    """{name?, sort?, wip_limit?, dwell_warn_h?, dwell_alert_h?, kind?, _prev?: {name, wip_limit, dwell_*, kind}}: with _prev (undo / redo)
    a name / limit changed elsewhere meanwhile stays (conflicts). 2.60.0 (#1510): wip_limit null / 0 = no limit. 2.410.0 B
    (#3515): dwell_warn_h / dwell_alert_h = hours in the column after which a card's time turns yellow / red (null / 0 = none).
    2.577.0 (#3354): kind = the column's meaning; the tasks in it stay as they are, it counts from the next move on."""
    c = db()
    conflicts = sec_apply(c, sid, body())
    bump(c)
    c.commit()
    return jsonify(ok=True, conflicts=conflicts)


SEC_UNDO = ("name", "wip_limit", "wip_hard", "dwell_warn_h", "dwell_alert_h", "kind")  # 2.774.0 (#5251): what a section's step keeps


def sec_apply(c, sid, b):
    """PATCH /api/sections/<id> without its answer (2.774.0, #5251: also the server's undo of a section step, tasks/tundo.py).
    Returns the conflicts; records the person's step (the values before / after that changed)."""
    write_lock(c, f"section-{int(sid)}")  # 2.269.0 B (#3034): the _prev check and the write see no other edit in between
    need_section(c, sid)
    conflicts = []
    prev = b.get("_prev") if isinstance(b.get("_prev"), dict) else {}
    cur = c.execute("SELECT name, wip_limit, wip_hard, dwell_warn_h, dwell_alert_h, kind FROM sections WHERE id=?", (sid,)).fetchone()
    if "name" in b:
        from ..collab.liste2e import le2a_clean_cipher, le2e_guard, le2e_is_cipher
        name = str(b["name"] or "").strip()
        name = le2a_clean_cipher(name, "name") if le2e_is_cipher(name) else name[:200]  # 2.64.1 (#1817): a ciphertext is never cut
        if not name:
            raise BadInput(tr("Name missing"))
        le2e_guard(c, c.execute("SELECT list_id FROM sections WHERE id=?", (sid,)).fetchone()[0], {"section": name}, cur={"section": cur["name"]})
        if "name" in prev and cur["name"] != str(prev["name"] or "") and cur["name"] != name:
            conflicts.append({"field": "name", "server": cur["name"], "mine": name})
        else:
            c.execute("UPDATE sections SET name=? WHERE id=?", (name, sid))
    if "sort" in b:
        c.execute("UPDATE sections SET sort=? WHERE id=?", (_sec_sort(b["sort"]), sid))
    if "wip_limit" in b:  # 2.60.0 (#1510)
        wip = wip_clean(b["wip_limit"])
        if "wip_limit" in prev and cur["wip_limit"] != wip_clean(prev["wip_limit"]) and cur["wip_limit"] != wip:
            conflicts.append({"field": "wip_limit", "server": cur["wip_limit"], "mine": wip})
        else:
            c.execute("UPDATE sections SET wip_limit=? WHERE id=?", (wip, sid))
    if "wip_hard" in b:  # 2.392.0 A (#3367): the limit stops new agent jobs (same rights and undo as wip_limit)
        hard = wip_hard_clean(b["wip_hard"])
        if "wip_hard" in prev and cur["wip_hard"] != wip_hard_clean(prev["wip_hard"]) and cur["wip_hard"] != hard:
            conflicts.append({"field": "wip_hard", "server": cur["wip_hard"], "mine": hard})
        else:
            c.execute("UPDATE sections SET wip_hard=? WHERE id=?", (hard, sid))
    if any(k in b for k in DW_KEYS):  # 2.410.0 B (#3515): both limits as one value (red stays above yellow)
        want = {k: dw_clean(b[k], k) if k in b else cur[k] for k in DW_KEYS}
        dw_check(*want.values())
        if any(k in prev for k in DW_KEYS) and any(cur[k] != dw_clean(prev.get(k), k) and cur[k] != want[k] for k in DW_KEYS):
            conflicts.append({"field": "dwell", "server": {k: cur[k] for k in DW_KEYS}, "mine": want})
        else:
            c.execute("UPDATE sections SET dwell_warn_h=?, dwell_alert_h=? WHERE id=?", (*want.values(), sid))
    if "kind" in b:  # 2.577.0 (#3354)
        kind = sk_clean(b["kind"])
        if "kind" in prev and cur["kind"] != sk_clean(prev["kind"]) and cur["kind"] != kind:
            conflicts.append({"field": "kind", "server": cur["kind"], "mine": kind})
        else:
            c.execute("UPDATE sections SET kind=? WHERE id=?", (kind, sid))
    from ..tasks.tundo import tu_section
    tu_section(c, sid, cur, SEC_UNDO)  # 2.774.0 (#5251)
    return conflicts


@app.post("/api/lists/<int:lid>/sections/order")
def sections_order(lid):
    """{ids: [...], _prev?: [...]}: the list's sections in their new order (every one exactly once), one transaction, edit
    rights. Returns the previous order (the client's undo sends it back). With _prev (undo / redo): only while the order
    is still the expected one, else nothing changes and the answer carries a conflict."""
    c = db()
    write_lock(c, f"sections-list-{int(lid)}")  # 2.269.0 B (#3034)
    need_list(c, lid)
    b = body()
    ids, prev = b.get("ids"), b.get("_prev")
    write_lock(c, f"sections:{lid}")  # 2.273.0 B (#3051): _prev checked and the order written as one step (two drags at once)
    cur = [r[0] for r in c.execute("SELECT id FROM sections WHERE list_id=? ORDER BY sort, id", (lid,))]
    bad = not isinstance(ids, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in ids)
    if prev is not None and (bad or not isinstance(prev, list) or prev != cur or sorted(ids) != sorted(cur)):
        return jsonify(ok=False, prev=cur, ids=cur, conflicts=[{"field": "order", "server": cur, "mine": ids}])
    if bad or sorted(ids) != sorted(cur):
        return err(tr("Invalid value: {0}", "ids"))
    c.executemany("UPDATE sections SET sort=? WHERE id=?", [(k, i) for k, i in enumerate(ids)])
    if ids != cur:
        from ..tasks.tundo import tu_sec_order
        tu_sec_order(c, lid, cur, ids)  # 2.774.0 (#5251)
    bump(c)
    c.commit()
    return jsonify(ok=True, prev=cur, ids=ids, conflicts=[])


@app.delete("/api/sections/<int:sid>")
def section_delete(sid):
    """Deletes a section, its tasks stay (without a section). Returns the section and the ids of its tasks; 2.567.0 A (#4707):
    a copy waits in the trash (trash: true), the undo is POST /api/sections/<id>/restore (same id, limits, tasks). Optional body {_prev: {name, tasks}} (undo / redo): only while the section still has that
    name and exactly those tasks, else nothing happens and the answer carries a conflict."""
    c = db()
    write_lock(c, f"section-{int(sid)}")  # 2.269.0 B (#3034)
    need_section(c, sid)
    sec = dict(c.execute("SELECT id, list_id, name, sort, wip_limit, wip_hard, dwell_warn_h, dwell_alert_h, kind FROM sections WHERE id=?",
                         (sid,)).fetchone())  # 2.60.0 (#1510): + limit; 2.410.0 B (#3515): + time limits; 2.577.0 (#3354): + meaning
    tids = _sec_tasks(c, sid)
    prev = body().get("_prev")
    if isinstance(prev, dict):
        want = prev.get("tasks") if isinstance(prev.get("tasks"), list) else []
        if sec["name"] != str(prev.get("name") or "") or sorted(tids) != sorted(x for x in want if isinstance(x, int)):
            return jsonify(ok=False, section=sec, tasks=tids,
                           conflicts=[{"field": "section", "server": {"name": sec["name"], "tasks": tids}, "mine": prev}])
    sec_trash(c, sid, sec["name"], me())
    from .secundo import secu_add  # 2.809.0 (#5476): a step of the person's undo list
    ug = secu_add(c, sid, "delete", sec["name"], sec["list_id"])
    bump(c)
    c.commit()
    return jsonify(ok=True, section=sec, tasks=tids, conflicts=[], trash=True, **({"undo_group": ug} if ug else {}))


def sec_trash(c, sid, name, uid):
    """2.809.0 (#5476, from section_delete): section sid into the trash -- a copy (POST /api/sections/<id>/restore), the row
    goes, its tasks stay without one. The caller checked the rights and holds the section's lock."""
    # 2.272.0 E2 (#3038): its tasks in the trash remember the section's name (restoring one puts it back, lifecycle.py restore_task)
    c.execute("UPDATE tasks SET trash_section=? WHERE section_id=? AND deleted_at IS NOT NULL", (name, sid))
    from .parttrash import lpt_section_put  # 2.567.0 A (#4707): a copy into the trash (POST /api/sections/<id>/restore)
    lpt_section_put(c, sid, uid)
    c.execute("DELETE FROM sections WHERE id=?", (sid,))
