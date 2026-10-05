"""Project lists: status, progress, the overview (description, links, files, Paperless), milestone reports."""
import mimetypes
import os
import uuid
from datetime import date, timedelta
from flask import jsonify, request, send_file

from ..core.config import app, ATT_DIR, INLINE_TYPES, MAX_FILE_MB, TZ
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, iso_ms, local_now, now_utc, parse_iso
from ..accounts.session import me
from ..accounts.pictures import list_icon_drop_file
from ..core.access import (
    collab_all, Denied, list_people, list_role, need_collab, need_list, need_project, need_task, pvis, time_all, tvis,
    WRITE_ROLES,
)
from ..core.serializers import unlink_files
from ..core.pages import url_title, valid_url
from ..tasks.validation import TITLE_MAX, valid_date
from ..tasks.tasks import task_create, task_update
from ..tasks.lifecycle import task_complete, task_delete, task_reopen
from ..tasks.attachments import safe_name
from ..integrations.paperless import need_paperless, pl_conn_arg, pl_doc, pl_usable_ids
from ..collab.comments import collab_user, user_names
from ..collab.news import bell_custom_clean, BELL_MODES, list_bell, list_push, news_add
from ..personal.timetrack import BadInput, time_day_h, time_list_totals, web_fields


# ---------------------------------------------------------------- project status + progress, package 3
# Status of a list (owner or edit members set it, with a short note; history in list_status) and a
# News item "status" for the other list members (collab). Progress (in /api/state per list): main tasks
# (subtasks too with the user setting progress_subtasks), all time, done vs. open, won't do and the trash
# left out; done copies of recurring tasks are not counted (a recurring task counts once, as open).
LIST_STATUSES = ("on_track", "at_risk", "off_track", "on_hold", "complete")
LIST_STATUS_NAMES = {"on_track": N_("On track"), "at_risk": N_("At risk"), "off_track": N_("Off track"),
                     "on_hold": N_("On hold"), "complete": N_("Complete|status")}  # 2.1.0: status pushes
STATUS_NOTE_MAX = 500


def list_progress(c, ids, subtasks, uid=None):
    """Progress per list; with uid only over the tasks uid sees (a participant counts their own tasks only)."""
    if not ids:
        return {}
    t0 = local_now().date().isoformat()
    q = ",".join("?" * len(ids))
    sub = "" if subtasks else "AND t.parent_id IS NULL"
    out = {}
    for r in c.execute(f"""SELECT t.list_id, SUM(t.status=0) AS open, SUM(t.status=2) AS done,
                                  SUM(t.status=0 AND t.due IS NOT NULL AND t.due<?) AS overdue,
                                  MIN(CASE WHEN t.status=0 AND t.due>=? THEN t.due END) AS next_due
                           FROM tasks t WHERE t.list_id IN ({q}) AND t.deleted_at IS NULL AND t.status IN (0, 2) {sub}
                             AND {tvis(c, uid, "t.", write=True) if uid else "1"} AND NOT (t.status=2 AND EXISTS (SELECT 1 FROM tasks o WHERE o.list_id=t.list_id AND o.id<t.id
                                      AND o.created_at=t.created_at AND o.title=t.title))
                           GROUP BY t.list_id""", (t0, t0, *ids)):
        out[r["list_id"]] = {"done": r["done"] or 0, "total": (r["open"] or 0) + (r["done"] or 0),
                             "overdue": r["overdue"] or 0, "next_due": r["next_due"]}
    return out


@app.put("/api/lists/<int:lid>/bell")
def list_bell_set(lid):
    """2.1.0 (#317): {mode: all | default | mute | custom, custom?: {event: {news?, push?}}} -- my notifications about this
    list (only mine). 2.6.1 (#404): custom = my own choice per event (BELL_CUSTOM_ROWS); without "custom" the stored
    choice stays."""
    c = db()
    if not list_role(c, lid, me()):
        raise Denied(404)
    b = body()
    mode = b.get("mode")
    if mode not in BELL_MODES:
        return err(tr("Invalid value: {0}", "mode"))
    cust = bell_custom_clean(b["custom"]) if mode == "custom" and "custom" in b else None
    bell_store(c, me(), lid, mode, cust)
    bump(c)
    c.commit()
    return jsonify(ok=True, mode=mode, custom=list_bell(c, me(), lid)[1])


def bell_store(c, uid, lid, mode, custom=None):
    """custom (stored json) only replaces the choice when given; it is kept while another mode is set, so switching
    back to "custom" brings it back."""
    if mode == "default":
        c.execute("UPDATE list_bell SET mode='default' WHERE user_id=? AND list_id=? AND custom IS NOT NULL AND custom!='{}'", (uid, lid))
        c.execute("DELETE FROM list_bell WHERE user_id=? AND list_id=? AND mode!='default'", (uid, lid))
    else:
        c.execute("INSERT INTO list_bell(user_id,list_id,mode,custom) VALUES(?,?,?,?) ON CONFLICT(user_id,list_id) "
                  "DO UPDATE SET mode=excluded.mode, custom=COALESCE(?, custom)", (uid, lid, mode, custom, custom))


@app.post("/api/lists/<int:lid>/status")
def list_status_set(lid):
    """{status: on_track|at_risk|off_track|on_hold|complete|'' (none), note}: owner or edit member."""
    need_collab()
    b = body()
    c = db()
    need_list(c, lid)
    lst = c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()
    if lst["is_inbox"]:
        return err(tr("The inbox has no project status"))
    need_project(c, lid, "status")
    st = b.get("status") or ""
    if st not in LIST_STATUSES + ("",):
        return err(tr("Unknown status"))
    note = str(b.get("note") or "").strip()[:STATUS_NOTE_MAX] if st else ""
    ts = iso_ms(now_utc())
    c.execute("UPDATE lists SET status=?, status_note=?, status_by=?, status_at=? WHERE id=?", (st, note, me(), ts, lid))
    c.execute("INSERT INTO list_status(list_id,user_id,status,note,created_at) VALUES(?,?,?,?,?)", (lid, me(), st, note, ts))
    for uid in sorted(list_people(c, lid)):
        if uid != me() and collab_user(c, uid, lid):
            news_add(c, uid, "status", list_id=lid, data={"status": st, "note": note, "name": lst["name"]})
            list_push(c, uid, "status", lid, lambda lg: tr("Project status: {0}", lst["name"], lg=lg),
                      lambda lg: tr(LIST_STATUS_NAMES.get(st, "No status"), lg=lg) + (" · " + note if note else ""))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.get("/api/lists/<int:lid>/status")
def list_status_history(lid):
    """The last status updates of a list (newest first)."""
    need_collab()
    c = db()
    need_list(c, lid, write=False)
    rows = c.execute("SELECT * FROM list_status WHERE list_id=? ORDER BY id DESC LIMIT 30", (lid,)).fetchall()
    names = user_names(c, [r["user_id"] for r in rows])
    return jsonify(items=[{"id": r["id"], "user_id": r["user_id"], "name": names.get(r["user_id"], ""), "status": r["status"],
                           "note": r["note"], "created_at": r["created_at"]} for r in rows])


# ---------------------------------------------------------------- 2.7.1 (#410): the overview of a project list
# Every project list has an overview next to List / Kanban / Timeline: a description (Markdown), key links (title + URL,
# in an order the editors choose), milestones (name + local day + done; also markers in the timeline), project files
# (uploaded on the list itself: the same size limit, file names and download rules as task files, stored below
# ATT_DIR/lists/<list id>/), Paperless documents linked to the list, and read-only: the files of the list's tasks (each
# with its task), Paperless documents of its tasks, members + roles, the status history and the tracked time.
# Reading: everyone who sees the list (a participant: the task files of the tasks they fully see only). Changing: owner,
# list admins and members (edit); viewers and participants read only. Only lists of the type "project".
OV_DESC_MAX = 20000      # characters of the description
OV_LINKS_MAX = 50        # key links per list
OV_MS_MAX = 100          # milestones per list
OV_FILES_MAX = 200       # project files per list
OV_TASK_FILES_MAX = 300  # task files shown in the overview (newest first)
OV_TITLE_MAX = 120
LIST_FILES_SUB = "lists"  # below ATT_DIR


def need_overview(c, lid, write=False):
    role = need_list(c, lid, write=write)
    need_project(c, lid, "overview")
    return role


def ov_day(v):
    try:
        return date.fromisoformat(str(v or "")[:10]).isoformat() if len(str(v or "")) == 10 else None
    except ValueError:
        return None


def ov_link_dict(r):
    return {"id": r["id"], "title": r["title"], "url": r["url"], "sort": r["sort"]}


def ov_file_dict(r, names=None):
    return {"id": r["id"], "name": r["name"], "mime": r["mime"], "size": r["size"], "created_at": r["created_at"],
            "user_id": r["user_id"], "user_name": (names or {}).get(r["user_id"], "")}


def ms_migrate(c):
    """2.18.0 (#430): every list_milestones row -> a milestone task in its list (title = name, due = day, done -> status 2,
    created_by = its creator or the list owner, at the end of the list, no section), then the row goes. The table itself
    stays (old backups restore into it). Returns the number migrated; the caller commits."""
    rows = c.execute("""SELECT m.*, l.owner_id FROM list_milestones m JOIN lists l ON l.id=m.list_id ORDER BY m.list_id, m.day, m.id""").fetchall()
    for r in rows:
        srt = c.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (r["list_id"],)).fetchone()[0]
        who = r["created_by"] if r["created_by"] and c.execute("SELECT 1 FROM users WHERE id=?", (r["created_by"],)).fetchone() \
            else r["owner_id"]
        ts, done = r["created_at"] or iso(now_utc()), 2 if r["done"] else 0
        day = r["day"] if valid_date(r["day"]) else None
        tid = c.execute("""INSERT INTO tasks(list_id,title,due,status,ms,sort,created_by,completed_by,completed_at,created_at,updated_at)
                           VALUES(?,?,?,?,1,?,?,?,?,?,?)""",
                        (r["list_id"], (r["name"] or "?")[:TITLE_MAX], day, done, srt, who, who if done else None,
                         iso(now_utc()) if done else None, ts, iso(now_utc()))).lastrowid
        c.execute("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
                  (tid, who, "created", "{}", ts))
    c.execute("DELETE FROM list_milestones")  # also orphan rows of lists that no longer exist
    return len(rows)


def ms_rows(c, ids):
    """The milestone tasks (not in the trash) of the given lists, by date (undated last), then id."""
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    return c.execute(f"""SELECT id, list_id, title, due, status FROM tasks WHERE ms=1 AND deleted_at IS NULL AND list_id IN ({q})
                         ORDER BY due IS NULL, due, id""", list(ids)).fetchall()


def ms_compat(r):
    """2.18.0 (#430): a milestone task in the shape of the 2.7.1 overview milestones (ids are task ids now)."""
    return {"id": r["id"], "name": r["title"], "day": r["due"], "done": r["status"] != 0}


def milestones_of_lists(c, ids):
    """{list id: [milestones by day]} of the given (project) lists, for /api/state (timeline markers, offline). 2.18.0: from
    the milestone tasks; only dated ones (the markers and "next milestone" need a day)."""
    out = {}
    for r in ms_rows(c, ids):
        if r["due"]:
            out.setdefault(r["list_id"], []).append(ms_compat(r))
    return out


def list_paperless_dicts(c, lid, uid):
    pl_ok = pl_usable_ids(c, uid)
    out = []
    for p in c.execute("SELECT * FROM list_paperless WHERE list_id=? ORDER BY id", (lid,)):
        d = {"id": p["id"], "doc_id": p["doc_id"], "title": p["title"], "correspondent": p["correspondent"], "created": p["created"],
             "conn": p["conn_id"] or 0, "added_at": p["added_at"]}
        if d["conn"] not in pl_ok:  # a connection the viewer cannot use: only that there is a document
            d.update(doc_id=None, title=tr("Paperless document"), correspondent="", created="", hidden=True, conn=None)
        out.append(d)
    return out


def overview_build(c, lid, uid):
    """Everything of the overview of list lid as uid sees it (the caller checked need_overview)."""
    from ..agents.core import agent_ids
    role = list_role(c, lid, uid)
    lst = c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()
    links = [ov_link_dict(r) for r in c.execute("SELECT * FROM list_links WHERE list_id=? ORDER BY sort, id", (lid,))]
    ms = [ms_compat(r) for r in ms_rows(c, [lid])]  # 2.18.0 (#430): milestone tasks (undated ones too, day null)
    frows = c.execute("SELECT * FROM list_files WHERE list_id=? ORDER BY id DESC", (lid,)).fetchall()
    names = user_names(c, [r["user_id"] for r in frows] + [lst["owner_id"]])
    # the files of the list's tasks (not in the trash; not files of comments): a participant only those of the tasks they
    # fully see (never the parent chain they get as context)
    cond, args = "", [lid]
    if role == "participant":
        _, wr, _ = pvis(c, uid, lid)
        cond = f" AND t.id IN ({','.join(str(int(x)) for x in wr) or '0'})"
    tfiles = [{"id": r["id"], "name": r["name"], "mime": r["mime"], "size": r["size"], "created_at": r["created_at"],
               "task_id": r["task_id"], "task_title": r["title"]}
              for r in c.execute(f"""SELECT a.id, a.name, a.mime, a.size, a.created_at, a.task_id, t.title FROM attachments a
                                     JOIN tasks t ON t.id=a.task_id WHERE t.list_id=? AND t.deleted_at IS NULL
                                     AND a.comment_id IS NULL{cond} ORDER BY a.id DESC LIMIT {OV_TASK_FILES_MAX}""", args)]
    pl_ok = pl_usable_ids(c, uid)
    tpl = []
    for p in c.execute(f"""SELECT p.id, p.doc_id, p.title, p.correspondent, p.created, p.conn_id, p.task_id, t.title AS task_title
                           FROM paperless_links p JOIN tasks t ON t.id=p.task_id WHERE t.list_id=? AND t.deleted_at IS NULL
                           AND p.status='ok'{cond} ORDER BY p.id DESC LIMIT {OV_TASK_FILES_MAX}""", args):
        d = {"id": p["id"], "doc_id": p["doc_id"], "title": p["title"], "correspondent": p["correspondent"], "created": p["created"],
             "conn": p["conn_id"] or 0, "task_id": p["task_id"], "task_title": p["task_title"]}
        if d["conn"] not in pl_ok:
            d.update(doc_id=None, title=tr("Paperless document"), correspondent="", created="", hidden=True, conn=None)
        tpl.append(d)
    members = []
    if collab_all():
        members = [{"user_id": lst["owner_id"], "name": names.get(lst["owner_id"], ""), "role": "owner"}]
        ag = agent_ids(c)
        for m in c.execute("""SELECT m.user_id, m.role, u.username, u.display_name FROM list_members m JOIN users u ON u.id=m.user_id
                              WHERE m.list_id=? ORDER BY m.added_at, u.id""", (lid,)):
            members.append({"user_id": m["user_id"], "name": m["display_name"] or m["username"], "role": m["role"],
                            **({"agent": True} if m["user_id"] in ag else {})})
    status = []
    if collab_all():
        srows = c.execute("SELECT * FROM list_status WHERE list_id=? ORDER BY id DESC LIMIT 10", (lid,)).fetchall()
        sn = user_names(c, [r["user_id"] for r in srows])
        status = [{"id": r["id"], "user_id": r["user_id"], "name": sn.get(r["user_id"], ""), "status": r["status"], "note": r["note"],
                   "created_at": r["created_at"]} for r in srows]
    out = {"list_id": lid, "name": lst["name"], "role": role, "can_edit": role in WRITE_ROLES,
           "description": lst["description"] or "", "links": links, "milestones": ms,
           "files": [ov_file_dict(r, names) for r in frows], "paperless": list_paperless_dicts(c, lid, uid),
           "task_files": tfiles, "task_paperless": tpl, "members": members,
           "status": {"current": lst["status"] or None, "note": lst["status_note"] or "", "at": lst["status_at"], "history": status},
           "time": None}
    if time_all():
        t = time_list_totals(c, uid).get(lid) or {"s": 0, "b": None}
        dh = lst["day_hours"] or time_day_h(c)
        out["time"] = {"seconds": t["s"] or 0, "budget_h": t["b"], "day_hours": dh}
    return out


@app.get("/api/lists/<int:lid>/overview")
def overview_get(lid):
    c = db()
    need_overview(c, lid)
    return jsonify(overview_build(c, lid, me()))


@app.patch("/api/lists/<int:lid>/overview")
def overview_patch(lid):
    """{description}: Markdown, at most OV_DESC_MAX characters."""
    b = web_fields(body(), {"description"}, "PATCH /api/lists/{lid}/overview")
    c = db()
    need_overview(c, lid, write=True)
    if "description" in b:
        d = b["description"]
        if d is None:
            d = ""
        if not isinstance(d, str):
            raise BadInput(tr("Invalid value: {0}", "description"))
        d = d.replace("\r\n", "\n").strip()
        if len(d) > OV_DESC_MAX:
            raise BadInput(tr("The description is too long (at most {0} characters)", OV_DESC_MAX))
        c.execute("UPDATE lists SET description=? WHERE id=?", (d, lid))
        bump(c)
        c.commit()
    return jsonify(overview_build(c, lid, me()))


def ov_link_clean(b, old=None):
    url = str(b.get("url", old["url"] if old else "") or "").strip()
    if not valid_url(url):
        raise BadInput(tr("Link: an address starting with http:// or https://"))
    title = str(b.get("title", old["title"] if old else "") or "").strip()[:OV_TITLE_MAX] or url_title(url)
    return title, url


@app.post("/api/lists/<int:lid>/links")
def ov_link_add(lid):
    """{title?, url}: a key link at the end (title: the address' domain + path when empty)."""
    b = web_fields(body(), {"title", "url"}, "POST /api/lists/{lid}/links")
    c = db()
    need_overview(c, lid, write=True)
    title, url = ov_link_clean(b)
    if c.execute("SELECT COUNT(*) FROM list_links WHERE list_id=?", (lid,)).fetchone()[0] >= OV_LINKS_MAX:
        return err(tr("At most {0} links", OV_LINKS_MAX), 409)
    srt = c.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM list_links WHERE list_id=?", (lid,)).fetchone()[0]
    nid = c.execute("INSERT INTO list_links(list_id,title,url,sort,created_by,created_at) VALUES(?,?,?,?,?,?)",
                    (lid, title, url, srt, me(), iso(now_utc()))).lastrowid
    bump(c)
    c.commit()
    return jsonify(ov_link_dict(c.execute("SELECT * FROM list_links WHERE id=?", (nid,)).fetchone()))


def need_ov_row(c, table, lid, rid):
    r = c.execute(f"SELECT * FROM {table} WHERE id=? AND list_id=?", (rid, lid)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.patch("/api/lists/<int:lid>/links/<int:rid>")
def ov_link_update(lid, rid):
    b = web_fields(body(), {"title", "url"}, "PATCH /api/lists/{lid}/links/{id}")
    c = db()
    need_overview(c, lid, write=True)
    old = need_ov_row(c, "list_links", lid, rid)
    title, url = ov_link_clean(b, old)
    c.execute("UPDATE list_links SET title=?, url=? WHERE id=?", (title, url, rid))
    bump(c)
    c.commit()
    return jsonify(ov_link_dict(c.execute("SELECT * FROM list_links WHERE id=?", (rid,)).fetchone()))


@app.delete("/api/lists/<int:lid>/links/<int:rid>")
def ov_link_delete(lid, rid):
    c = db()
    need_overview(c, lid, write=True)
    need_ov_row(c, "list_links", lid, rid)
    c.execute("DELETE FROM list_links WHERE id=?", (rid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.put("/api/lists/<int:lid>/links/order")
def ov_link_order(lid):
    """{ids: [link ids in the new order]}: every link of the list exactly once."""
    b = web_fields(body(), {"ids"}, "PUT /api/lists/{lid}/links/order")
    c = db()
    need_overview(c, lid, write=True)
    ids = b.get("ids")
    have = [r[0] for r in c.execute("SELECT id FROM list_links WHERE list_id=?", (lid,))]
    if not isinstance(ids, list) or any(not isinstance(x, int) or isinstance(x, bool) for x in ids) or sorted(ids) != sorted(have):
        raise BadInput(tr("Invalid value: {0}", "ids"))
    for i, x in enumerate(ids):
        c.execute("UPDATE list_links SET sort=? WHERE id=?", (i + 1, x))
    bump(c)
    c.commit()
    return jsonify(data=[ov_link_dict(r) for r in c.execute("SELECT * FROM list_links WHERE list_id=? ORDER BY sort, id", (lid,))])


def ov_ms_clean(b, old=None):
    name = str(b.get("name", old["name"] if old else "") or "").strip()[:OV_TITLE_MAX]
    if not name:
        raise BadInput(tr("Name missing"))
    day = ov_day(b.get("day", old["day"] if old else None))
    if not day and (old is None or old["day"] or "day" in b):  # 2.18.0: an undated milestone task may stay undated
        raise BadInput(tr("Date: YYYY-MM-DD"))
    done = b.get("done", bool(old["done"]) if old else False)
    if not isinstance(done, bool):
        raise BadInput(tr("Invalid value: {0}", "done"))
    return name, day, int(done)


# 2.18.0 (#430): the overview's milestone routes (web + API v1) stay as a compatibility layer on top of the milestone tasks:
# the ids are task ids since 2.18.0, POST creates a milestone task at the end of the list, PATCH changes its title / due date
# / done state through the normal task endpoints (history, events, webhooks), DELETE moves it to the trash.
def need_ms_task(c, lid, rid):
    r = c.execute("SELECT * FROM tasks WHERE id=? AND list_id=? AND ms=1 AND deleted_at IS NULL", (rid, lid)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.post("/api/lists/<int:lid>/milestones")
def ov_ms_add(lid):
    """{name, day: YYYY-MM-DD, done?}"""
    from ..api.v1 import v1_call
    b = web_fields(body(), {"name", "day", "done"}, "POST /api/lists/{lid}/milestones")
    c = db()
    need_overview(c, lid, write=True)
    name, day, done = ov_ms_clean(b)
    if c.execute("SELECT COUNT(*) FROM tasks WHERE list_id=? AND ms=1 AND deleted_at IS NULL", (lid,)).fetchone()[0] >= OV_MS_MAX:
        return err(tr("At most {0} milestones", OV_MS_MAX), 409)
    srt = c.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    nid = v1_call(task_create, body={"title": name, "due": day, "list_id": lid, "ms": 1, "sort": srt})["id"]
    if done:
        v1_call(task_complete, nid, body={})
    return jsonify(ms_compat(db().execute("SELECT * FROM tasks WHERE id=?", (nid,)).fetchone()))


@app.patch("/api/lists/<int:lid>/milestones/<int:rid>")
def ov_ms_update(lid, rid):
    from ..api.v1 import v1_call
    b = web_fields(body(), {"name", "day", "done"}, "PATCH /api/lists/{lid}/milestones/{id}")
    c = db()
    need_overview(c, lid, write=True)
    old = ms_compat(need_ms_task(c, lid, rid))
    name, day, done = ov_ms_clean(b, old)
    ch = {k: v for k, v in (("title", name), ("due", day)) if v != old["name" if k == "title" else "day"]}
    if ch:
        v1_call(task_update, rid, body=ch)
    if bool(done) != old["done"]:
        v1_call(task_complete if done else task_reopen, rid, body={})
    return jsonify(ms_compat(db().execute("SELECT * FROM tasks WHERE id=?", (rid,)).fetchone()))


@app.delete("/api/lists/<int:lid>/milestones/<int:rid>")
def ov_ms_delete(lid, rid):
    from ..api.v1 import v1_call
    c = db()
    need_overview(c, lid, write=True)
    need_ms_task(c, lid, rid)
    v1_call(task_delete, rid, body={})
    return jsonify(ok=True)


# ---- 2.18.0 (#430, "Software 2" B + D): what a milestone holds. Progress (closed / all of its tasks), its tasks (open first),
# a burndown (open tasks per day from the first task's creation, or 14 days before the due date, up to today; the ideal
# line from all tasks on the first day to 0 on the due date) and release notes (Markdown from its completed tasks, grouped by
# ticket type). Participants only count and see the tasks they fully see.
MS_BURN_MAX = 180  # days in a burndown (the newest ones)



def ms_report(c, tid, uid, lg=None):
    from ..core.db import local_day as _local_day  # 2.21.0 (#671): the one tolerant version
    from ..api.v1 import STATUS_NAMES
    m = c.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)).fetchone()
    if not m or not m["ms"]:
        raise Denied(404, tr("Not a milestone"))
    rows = c.execute("SELECT * FROM tasks WHERE milestone_id=? AND deleted_at IS NULL ORDER BY status!=0, sort, id", (tid,)).fetchall()
    if list_role(c, m["list_id"], uid) == "participant":
        _, wr, _ = pvis(c, uid, m["list_id"])
        rows = [r for r in rows if r["id"] in wr]
    total, closed = len(rows), sum(1 for r in rows if r["status"] != 0)
    today_ = local_now().date()
    due = date.fromisoformat(m["due"]) if m["due"] and valid_date(m["due"]) else None
    made = [d for d in (_local_day(r["created_at"]) for r in rows) if d]
    start = min(made) if made else (due - timedelta(days=14) if due else today_ - timedelta(days=14))
    if due and not made:
        start = min(start, due - timedelta(days=14))
    end = today_  # the actual line ends today; the ideal line runs on to the due date
    start = max(min(start, end), end - timedelta(days=MS_BURN_MAX - 1))
    spans = [(_local_day(r["created_at"]) or start, _local_day(r["completed_at"]) if r["status"] != 0 else None) for r in rows]
    days, d = [], start
    while d <= end:
        days.append({"day": d.isoformat(), "open": sum(1 for a, z in spans if a <= d and not (z and z <= d))})
        d += timedelta(days=1)
    ideal = [{"day": start.isoformat(), "open": total}, {"day": due.isoformat(), "open": 0}] if total and due and due >= start else []
    # release notes: completed tasks only (not "won't do"), by ticket type; without any types one plain list
    done = [r for r in rows if r["status"] == 2]
    head = f"## {m['title']}" + (f" ({m['due']})" if m["due"] else "")
    lines = [head, ""]
    if not done:
        lines.append(tr("No completed tasks yet.", lg=lg))
    elif not any(r["ttype"] for r in done):
        lines += [f"- #{r['id']} {r['title']}" for r in done]
    else:
        for name, keys in ((N_("Features"), ("feature",)), (N_("Fixes"), ("bug",)), (N_("Other|release notes"), ("task", ""))):
            part = [r for r in done if (r["ttype"] or "") in keys]
            if part:
                lines += [f"### {tr(name, lg=lg)}", "", *[f"- #{r['id']} {r['title']}" for r in part], ""]
    return {"milestone": {"id": m["id"], "title": m["title"], "list_id": m["list_id"], "due": m["due"],
                          "status": STATUS_NAMES.get(m["status"], "open")},
            "progress": {"done": closed, "total": total, "percent": round(100 * closed / total) if total else 0},
            "tasks": [{"id": r["id"], "title": r["title"], "status": STATUS_NAMES.get(r["status"], "open"),
                       "type": r["ttype"] or None, "due": r["due"], "assignee_id": r["assignee_id"],
                       "completed_at": r["completed_at"]} for r in rows],
            "burndown": {"start": start.isoformat(), "end": end.isoformat(), "due": m["due"], "days": days, "ideal": ideal},
            "release_notes": "\n".join(lines).rstrip() + "\n"}


@app.get("/api/tasks/<int:tid>/milestone")
def task_milestone(tid):
    c = db()
    need_task(c, tid, write=False, full=True)
    return jsonify(ms_report(c, tid, me()))


# ---- project files: same rules as task files (size limit, safe file names, download unless a harmless type)
@app.post("/api/lists/<int:lid>/files")
def list_file_upload(lid):
    from ..notify.alerts import aa_count, aa_oserr
    c = db()
    need_overview(c, lid, write=True)
    files = request.files.getlist("file")
    if not files:
        return err(tr("File missing"))
    if c.execute("SELECT COUNT(*) FROM list_files WHERE list_id=?", (lid,)).fetchone()[0] + len(files) > OV_FILES_MAX:
        return err(tr("At most {0} files per project", OV_FILES_MAX), 409)
    try:
        os.makedirs(os.path.join(ATT_DIR, LIST_FILES_SUB, str(lid)), exist_ok=True)
    except OSError as e:
        aa_count("storage", "attachments", aa_oserr(e))
        raise
    ts, saved = iso(now_utc()), []
    for f in files:
        name = safe_name(f.filename)
        rel = os.path.join(LIST_FILES_SUB, str(lid), f"{uuid.uuid4().hex[:12]}-{name}")
        full = os.path.join(ATT_DIR, rel)
        try:
            f.save(full)
        except OSError as e:
            aa_count("storage", "attachments", aa_oserr(e))
            c.rollback()
            unlink_files(saved)
            raise
        saved.append(rel)
        size = os.path.getsize(full)
        if size > MAX_FILE_MB * 1024 * 1024:
            c.rollback()
            unlink_files(saved)
            return err(tr("{0}: larger than {1} MB", name, MAX_FILE_MB))
        if not size:  # 2.13.2 (#478 N6)
            c.rollback()
            unlink_files(saved)
            return err(tr("{0}: the file is empty and was not uploaded", name))
        mime = (f.mimetype if f.mimetype and f.mimetype != "application/octet-stream" else None) \
            or mimetypes.guess_type(name)[0] or "application/octet-stream"
        c.execute("INSERT INTO list_files(list_id,name,mime,size,path,user_id,created_at) VALUES(?,?,?,?,?,?,?)",
                  (lid, name, mime, size, rel, me(), ts))
    bump(c)
    c.commit()
    return jsonify(overview_build(c, lid, me()))


def need_list_file(c, fid, write):
    r = c.execute("SELECT * FROM list_files WHERE id=?", (fid,)).fetchone()
    if not r:
        raise Denied(404)
    need_overview(c, r["list_id"], write=write)
    return r


@app.get("/api/list-files/<int:fid>")
def list_file_get(fid):
    a = need_list_file(db(), fid, False)
    full = os.path.join(ATT_DIR, a["path"])
    if not os.path.isfile(full) or (a["size"] and os.path.getsize(full) != a["size"]):  # 2.13.0: also empty / cut off
        if os.path.isfile(full):
            print(f"WARNING file {a['id']}: {os.path.getsize(full)} bytes on disk, {a['size']} recorded", flush=True)
        e = err(tr("File damaged or missing"), 410 if os.path.isfile(full) else 404)
        e[0].headers["Cache-Control"] = "no-store"  # never cache a broken answer
        return e
    inline = a["mime"] in INLINE_TYPES and request.args.get("dl") != "1"
    resp = send_file(full, mimetype=a["mime"] if inline else "application/octet-stream",
                     as_attachment=not inline, download_name=a["name"], conditional=True, max_age=0)
    if a["mime"] != "application/pdf":  # the browser pdf viewer does not run inside a sandboxed CSP
        resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


@app.delete("/api/list-files/<int:fid>")
def list_file_delete(fid):
    c = db()
    a = need_list_file(c, fid, True)
    c.execute("DELETE FROM list_files WHERE id=?", (fid,))
    bump(c)
    c.commit()
    unlink_files([a["path"]])
    return jsonify(ok=True)


def list_files_drop(paths):
    """The files of a list deleted for good (after its rows are gone)."""
    unlink_files(paths)


def list_row_purge(c, lid, gone):
    """2.7.2: deletes the row of list lid (cascades) and remembers its project files + own icon in gone (a list) so the
    caller removes them from disk after the commit (list_purge_files). Returns the number of rows deleted."""
    r = c.execute("SELECT icon FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        return 0
    paths = [x[0] for x in c.execute("SELECT path FROM list_files WHERE list_id=?", (lid,))]
    n = c.execute("DELETE FROM lists WHERE id=?", (lid,)).rowcount
    gone.append((lid, r["icon"], paths))
    return n


def list_purge_files(gone):
    for lid, icon, paths in gone:
        list_icon_drop_file(lid, icon)
        list_files_drop(paths)


# ---- Paperless documents of the list (same connections + rules as on tasks)
@app.post("/api/lists/<int:lid>/paperless")
def list_paperless_link(lid):
    c = db()
    need_overview(c, lid, write=True)
    b = body()
    cid = pl_conn_arg(b.get("conn"))
    cn = need_paperless(c, cid)
    try:
        doc_id = int(b.get("doc_id") or 0)
    except (TypeError, ValueError):
        return err(tr("unknown"))
    if not c.execute("SELECT 1 FROM list_paperless WHERE list_id=? AND doc_id=? AND COALESCE(conn_id,0)=?", (lid, doc_id, cid)).fetchone():
        d = pl_doc(cn, doc_id)
        c.execute("""INSERT INTO list_paperless(list_id,conn_id,doc_id,title,correspondent,created,added_by,added_at)
                     VALUES(?,?,?,?,?,?,?,?)""", (lid, cid or None, d["doc_id"], d["title"], d["correspondent"], d["created"],
                                                  me(), iso(now_utc())))
        bump(c)
        c.commit()
    return jsonify(overview_build(c, lid, me()))


@app.delete("/api/lists/<int:lid>/paperless/<int:rid>")
def list_paperless_unlink(lid, rid):
    c = db()
    need_overview(c, lid, write=True)
    r = need_ov_row(c, "list_paperless", lid, rid)
    need_paperless(c, r["conn_id"] or 0)
    c.execute("DELETE FROM list_paperless WHERE id=?", (rid,))
    bump(c)
    c.commit()
    return jsonify(overview_build(c, lid, me()))
