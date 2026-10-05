"""Task and list templates, built-in project types."""
import json
import re
from datetime import date, timedelta
from flask import jsonify

from ..core.config import app
from ..core.schema import MAX_DEPTH
from ..core.i18n import lang, N_, tr
from ..core.db import body, bump, db, err, inbox_default, iso, local_now, now_utc, uset, usettings
from ..accounts.session import me
from ..core.access import Denied, list_role, MANAGE_ROLES, my_inbox, my_max_sort, need_list, need_task
from ..core.pages import valid_url
from ..lists.lists import agent_autoshare, clean_color, clean_folder, LIST_KINDS
from ..tasks.validation import (
    clean_reminders, clean_ticket_tpl, log_act, rr_feasible, rr_norm, rr_problem, TICKET_TPL, TICKET_TYPES, valid_date,
)
from ..tasks.tasks import ms_target, one_task, set_tags
from ..personal.timetrack import BadInput


# ---------------------------------------------------------------- templates (private per user)
# A task template = {"task": node}, a list template = {"name", "color", "view", "sections": [name, ...],
# "tasks": [node + "section": index into sections | null]}. node = {title, content, priority, tags, url,
# due_offset, start_offset, due_time, duration, reminders, repeat, repeat_from, children: [node, ...]}.
# Offsets are days relative to the day the template was saved (never negative); a template used
# today puts the dates relative to today. Subtasks up to MAX_DEPTH levels; assignees are not kept.
TPL_MAX_NODES = 500
TPL_MAX_PER_USER = 200
HHMM_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


def tpl_node_from_task(c, t, base, uid, depth=0, fidx=None, order=None):
    """fidx (list templates): ({field id: index}, {field id: type}) -> the node keeps its custom field values
    as fv {index: value} (dates as days after use, people are not kept). order (2.4.0, list templates): collects
    (task id, node key) so the dependencies between the tasks can be kept (deps: [[waiting key, blocker key], ...])."""
    def off(d):
        return max(0, (date.fromisoformat(d) - base).days) if d else None
    tags = [r[0] for r in c.execute("SELECT tag FROM task_tags WHERE task_id=? AND user_id=? ORDER BY tag", (t["id"], uid))]
    kids = c.execute("SELECT * FROM tasks WHERE parent_id=? AND deleted_at IS NULL ORDER BY sort, id",
                     (t["id"],)).fetchall() if depth < MAX_DEPTH - 1 else []
    n = {"title": t["title"], "content": t["content"] or "", "priority": t["priority"] or 0, "tags": tags,
         "url": t["url"], "due_offset": off(t["due"]), "start_offset": off(t["start"]) if t["due"] else None,
         "due_time": t["due_time"] if t["due"] else None, "duration": t["duration"] if t["due_time"] else None,
         "reminders": t["reminders"] or "", "repeat": t["repeat"] or "", "repeat_from": t["repeat_from"] or "due",
         **({"ttype": t["ttype"]} if t["ttype"] else {}), **({"ms": 1} if t["ms"] and depth == 0 else {}), "children": []}
    if order is not None:
        n["k"] = f"n{len(order) + 1}"
        order.append((t["id"], n["k"]))
        if t["milestone_id"]:  # 2.18.0 (#430): resolved to the milestone's node key once the whole list is read
            n["mid"] = t["milestone_id"]
    n["children"] = [tpl_node_from_task(c, k, base, uid, depth + 1, fidx, order) for k in kids]
    if fidx:
        fv = {}
        for r in c.execute("SELECT field_id, value FROM task_field_values WHERE task_id=?", (t["id"],)):
            i, ty = fidx[0].get(r["field_id"]), fidx[1].get(r["field_id"])
            if i is None or ty == "person":
                continue
            try:
                fv[str(i)] = (date.fromisoformat(r["value"]) - base).days if ty == "date" else r["value"]
            except ValueError:
                continue
        if fv:
            n["fv"] = fv
    return n


def tpl_clean_node(n, depth, count):
    """Validates one node from the client (edited template); raises ValueError with a message."""
    from ..lists.fields import FIELD_MAX
    if not isinstance(n, dict):
        raise ValueError(tr("Invalid template"))
    count[0] += 1
    if count[0] > TPL_MAX_NODES:
        raise ValueError(tr("Template too large (at most {0} tasks)", TPL_MAX_NODES))
    title = str(n.get("title") or "").strip()[:500]
    if not title:
        raise ValueError(tr("Title missing"))

    def num(k, lo, hi):
        v = n.get(k)
        if v in (None, ""):
            return None
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise ValueError(tr("Invalid template")) from None
        return min(hi, max(lo, v))
    due_off = num("due_offset", 0, 3650)
    due_time = n.get("due_time") if isinstance(n.get("due_time"), str) and HHMM_RE.fullmatch(n.get("due_time")) else None
    rep = rr_norm(str(n.get("repeat") or ""))
    if rep and rr_problem(rep):
        rep = ""
    rems = []
    for x in str(n.get("reminders") or "").split(","):  # keeps the valid offsets
        try:
            rems.append(clean_reminders(x))
        except BadInput:
            pass
    rems = ",".join(dict.fromkeys(x for x in rems if x))
    url = str(n.get("url") or "").strip() or None
    kids = n.get("children") or []
    fv = n.get("fv") if isinstance(n.get("fv"), dict) else {}
    key = n.get("k") if isinstance(n.get("k"), str) and re.fullmatch(r"n\d{1,5}", n.get("k")) else None
    if key and len(count) > 1:  # 2.4.0: node keys (dependencies) are unique within a template
        key = None if key in count[1] else key
        if key:
            count[1].add(key)
    return {**({"k": key} if key else {}), "title": title, "content": str(n.get("content") or "")[:20000],
            **({"fv": {k: v for k, v in list(fv.items())[:FIELD_MAX] if re.fullmatch(r"\d{1,2}", str(k))
                       and isinstance(v, (str, int, float)) and not isinstance(v, bool) and len(str(v)) <= 2000}} if fv else {}),
            "priority": num("priority", 0, 5) if num("priority", 0, 5) in (0, 1, 3, 5) else 0,
            "tags": [str(x).strip().lstrip("#")[:60] for x in (n.get("tags") or []) if str(x).strip().lstrip("#")][:30]
            if isinstance(n.get("tags"), list) else [],
            "url": url if url and valid_url(url) else None,
            "due_offset": due_off, "start_offset": num("start_offset", 0, 3650) if due_off is not None else None,
            "due_time": due_time if due_off is not None else None,
            "duration": num("duration", 5, 1440) if due_time and due_off is not None else None,
            "reminders": rems if due_off is not None else "", "repeat": rep if due_off is not None else "",
            "repeat_from": "done" if n.get("repeat_from") == "done" else "due",
            **({"ttype": n["ttype"]} if n.get("ttype") in TICKET_TYPES else {}),
            # 2.18.0 (#430): a milestone (top level, without subtasks) / the node key of the milestone a task belongs to
            **({"ms": 1} if n.get("ms") and depth == 0 and not kids else {}),
            **({"mk": n["mk"]} if isinstance(n.get("mk"), str) and re.fullmatch(r"n\d{1,5}", n["mk"]) else {}),
            "children": [tpl_clean_node(k, depth + 1, count) for k in kids] if depth < MAX_DEPTH - 1 and isinstance(kids, list) else []}


def tpl_clean(kind, d):
    from ..lists.fields import tpl_clean_fields
    if not isinstance(d, dict):
        raise ValueError(tr("Invalid template"))
    count = [0, set()]
    if kind == "task":
        return {"task": tpl_clean_node(d.get("task"), 0, count)}
    secs = [str(x).strip()[:200] for x in (d.get("sections") or []) if str(x).strip()][:50]
    tasks = []
    for n in d.get("tasks") or []:
        x = tpl_clean_node(n, 0, count)
        si = n.get("section") if isinstance(n, dict) else None
        x["section"] = si if isinstance(si, int) and not isinstance(si, bool) and 0 <= si < len(secs) else None
        tasks.append(x)
    color = str(d.get("color") or "")
    # 2.4.0 (#328): dependencies between the template's tasks (by node key; unknown keys and edges closing a cycle go)
    deps, adj = [], {}

    def reaches(a, b):
        seen, todo = set(), [a]
        while todo:
            x = todo.pop()
            if x == b:
                return True
            if x not in seen:
                seen.add(x)
                todo.extend(adj.get(x, ()))
        return False
    for e in (d.get("deps") if isinstance(d.get("deps"), list) else [])[:TPL_MAX_NODES]:
        if isinstance(e, list) and len(e) == 2 and all(isinstance(x, str) and x in count[1] for x in e) and e[0] != e[1] \
                and e not in deps and not reaches(e[1], e[0]):
            deps.append(e)
            adj.setdefault(e[0], []).append(e[1])
    tt = d.get("ticket_tpl") if isinstance(d.get("ticket_tpl"), dict) else {}
    try:
        tt = json.loads(clean_ticket_tpl({k: v for k, v in tt.items() if k in TICKET_TPL}) or "{}")
    except BadInput:
        tt = {}

    def span(nodes):
        return max([0] + [max(x.get("due_offset") or 0, span(x.get("children") or [])) for x in nodes])
    return {"name": str(d.get("name") or "").strip()[:200], "color": color if re.fullmatch(r"#[0-9a-fA-F]{3,8}", color) else "",
            "view": d.get("view") if d.get("view") in ("list", "kanban", "timeline") else "list",
            # list type (D2); older templates with custom fields become projects when used
            "kind": d.get("kind") if d.get("kind") in LIST_KINDS else "project" if d.get("fields") else "list",
            # 2.7.2 (#414): "Show completed at the bottom" (older templates: kind "checklist")
            "done_at_bottom": 1 if d.get("done_at_bottom") or d.get("kind") == "checklist" else 0,
            "sections": secs, "tasks": tasks, "fields": tpl_clean_fields(d.get("fields")),
            # 2.4.0 (#328 / #340): dates relative to the project start (rel), its length in days (span), the dependencies,
            # the list's ticket types + templates and "Move dependent tasks along"
            "rel": bool(d.get("rel")), "span": span(tasks), "deps": deps, "tickets": 1 if d.get("tickets") else 0,
            "ticket_tpl": tt, "dep_shift": 1 if d.get("dep_shift") else 0}


def tpl_count(d):
    def n(x):
        return 1 + sum(n(k) for k in x.get("children") or [])
    return n(d["task"]) if "task" in d else sum(n(x) for x in d.get("tasks") or [])


def tpl_dict(r):
    d = json.loads(r["data"] or "{}")
    return {"id": r["id"], "kind": r["kind"], "name": r["name"], "data": d, "count": tpl_count(d),
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def need_template(c, tid):
    r = c.execute("SELECT * FROM templates WHERE id=? AND user_id=?", (tid, me())).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.get("/api/templates")
def templates_list():
    return jsonify(templates=[tpl_dict(r) for r in db().execute(
        "SELECT * FROM templates WHERE user_id=? ORDER BY kind DESC, name COLLATE NOCASE, id", (me(),))])


@app.post("/api/templates")
def template_create():
    """{task_id} = this task with its subtasks, {list_id} = the list's sections and open tasks (with subtasks),
    or {kind, data} as sent by the template editor. name optional (default: the task title / list name)."""
    from ..lists.fields import tpl_fields_of
    b = body()
    c = db()
    uid = me()
    if c.execute("SELECT COUNT(*) FROM templates WHERE user_id=?", (uid,)).fetchone()[0] >= TPL_MAX_PER_USER:
        return err(tr("At most {0} templates", TPL_MAX_PER_USER))
    base = local_now().date()
    try:
        if b.get("task_id"):
            tid = int(b["task_id"])
            need_task(c, tid, write=False, full=True)
            t = c.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)).fetchone()
            if not t:
                raise Denied(404)
            kind, data, name = "task", {"task": tpl_node_from_task(c, t, base, uid)}, t["title"]
        elif b.get("list_id"):
            lid = int(b["list_id"])
            if need_list(c, lid, write=False) == "participant":  # the whole list is not theirs to copy
                raise Denied(403, tr("Participants cannot save the whole list as a template"))
            lst = c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()
            secs = c.execute("SELECT id, name FROM sections WHERE list_id=? ORDER BY sort, id", (lid,)).fetchall()
            sidx = {s["id"]: i for i, s in enumerate(secs)}
            fdefs, fidx, ftypes = tpl_fields_of(c, lid)
            rel = bool(b.get("relative"))
            if rel:  # 2.4.0 (#328): the project start = the earliest start / due of its open tasks ("Start + 3 days")
                t0 = c.execute("""SELECT MIN(COALESCE(start, due)) FROM tasks WHERE list_id=? AND status=0 AND deleted_at IS NULL
                                  AND due IS NOT NULL""", (lid,)).fetchone()[0]
                base = date.fromisoformat(t0) if t0 and valid_date(t0) else base
            tasks, order = [], []
            for t in c.execute("""SELECT * FROM tasks WHERE list_id=? AND parent_id IS NULL AND status=0 AND deleted_at IS NULL
                                  ORDER BY sort, id""", (lid,)).fetchall():
                n = tpl_node_from_task(c, t, base, uid, fidx=(fidx, ftypes), order=order)
                n["section"] = sidx.get(t["section_id"])
                tasks.append(n)
            keys = dict(order)

            def mkeys(nodes):  # 2.18.0 (#430): milestone task ids -> node keys (a milestone not in the template: dropped)
                for x in nodes:
                    mid = x.pop("mid", None)
                    if mid in keys:
                        x["mk"] = keys[mid]
                    mkeys(x.get("children") or [])
            mkeys(tasks)
            deps = [[keys[r[0]], keys[r[1]]] for r in c.execute("""SELECT d.task_id, d.blocker_id FROM task_deps d JOIN tasks t ON t.id=d.task_id
                                                                           WHERE t.list_id=? ORDER BY d.rowid""", (lid,)).fetchall()
                    if r[0] in keys and r[1] in keys] if keys else []
            role = list_role(c, lid)
            name = tr("Inbox") if lst["is_inbox"] and inbox_default(lst["name"]) else lst["name"]
            kind, data = "list", {"name": name, "color": lst["color"], "kind": lst["kind"],
                                  "view": lst["view"] if role == "owner" else (c.execute(
                                      "SELECT COALESCE(view, ?) FROM list_members WHERE list_id=? AND user_id=?",
                                      (lst["view"], lid, uid)).fetchone() or ["list"])[0],
                                  "sections": [s["name"] for s in secs], "tasks": tasks, "fields": fdefs,
                                  "rel": rel, "deps": deps, "tickets": lst["tickets"], "dep_shift": lst["dep_shift"],
                                  "done_at_bottom": lst["checklist"],
                                  "ticket_tpl": json.loads(lst["ticket_tpl"] or "{}") if role == "owner" else {}}
        else:
            kind = b.get("kind") if b.get("kind") in ("task", "list") else None
            if not kind:
                return err(tr("Invalid template"))
            data = b.get("data")
            name = ""
        data = tpl_clean(kind, data)
    except (ValueError, TypeError) as e:
        return err(str(e) or tr("Invalid template"))
    name = (str(b.get("name") or "").strip() or name or (data.get("name") if kind == "list" else data["task"]["title"]))[:200]
    if not name:
        return err(tr("Name missing"))
    ts = iso(now_utc())
    cur = c.execute("INSERT INTO templates(user_id,kind,name,data,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (uid, kind, name, json.dumps(data, ensure_ascii=False), ts, ts))
    bump(c)
    c.commit()
    return jsonify(tpl_dict(c.execute("SELECT * FROM templates WHERE id=?", (cur.lastrowid,)).fetchone()))


@app.patch("/api/templates/<int:tid>")
def template_update(tid):
    b = body()
    c = db()
    r = need_template(c, tid)
    if "name" in b:
        name = str(b["name"] or "").strip()[:200]
        if not name:
            return err(tr("Name missing"))
        c.execute("UPDATE templates SET name=? WHERE id=?", (name, tid))
    if "data" in b:
        try:
            data = tpl_clean(r["kind"], b["data"])
        except (ValueError, TypeError) as e:
            return err(str(e) or tr("Invalid template"))
        c.execute("UPDATE templates SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), tid))
    c.execute("UPDATE templates SET updated_at=? WHERE id=?", (iso(now_utc()), tid))
    bump(c)
    c.commit()
    return jsonify(tpl_dict(c.execute("SELECT * FROM templates WHERE id=?", (tid,)).fetchone()))


@app.delete("/api/templates/<int:tid>")
def template_delete(tid):
    c = db()
    need_template(c, tid)
    c.execute("DELETE FROM templates WHERE id=?", (tid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


def tpl_insert(c, n, lid, sec, parent, base, sort, uid, fmap=None, scale=1.0, made=None):
    """Creates the task of one template node (and its subtasks); returns the new id. fmap (list templates):
    [new field rows by template index] for the node's custom field values (invalid ones are skipped). 2.4.0: scale
    stretches / squeezes the day offsets (a project template used with an end date), made collects {node key: new id}."""
    from ..lists.fields import field_value
    def off(k):
        return round(n[k] * scale) if n.get(k) is not None else None
    due = (base + timedelta(days=off("due_offset"))).isoformat() if n.get("due_offset") is not None else None
    start = (base + timedelta(days=off("start_offset"))).isoformat() if due and n.get("start_offset") is not None else None
    if start and start >= due:
        start = None
    tm = n.get("due_time") if due else None
    f = {"list_id": lid, "section_id": sec, "parent_id": parent, "title": n["title"], "content": n.get("content") or "",
         "priority": n.get("priority") or 0, "due": due, "due_time": tm, "start": start,
         "duration": n.get("duration") if tm else None, "reminders": n.get("reminders") or "" if due else "",
         "repeat": n.get("repeat") or "" if due else "", "repeat_from": n.get("repeat_from") or "due",
         "url": n.get("url"), "sort": sort, "created_by": uid, "ttype": n.get("ttype") if n.get("ttype") in TICKET_TYPES else "",
         "ms": 1 if n.get("ms") and parent is None else 0}
    if f["repeat"] and (rr_problem(rr_norm(f["repeat"])) or not rr_feasible(rr_norm(f["repeat"]), due)):
        f["repeat"] = ""
    ts = iso(now_utc())
    cols = list(f) + ["created_at", "updated_at"]
    tid = c.execute(f"INSERT INTO tasks({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                    [f[k] for k in f] + [ts, ts]).lastrowid
    if n.get("tags"):
        set_tags(c, tid, n["tags"], uid)
    for k, v in (n.get("fv") or {}).items() if fmap else ():
        f = fmap[int(k)] if int(k) < len(fmap) else None
        if not f:
            continue
        try:
            if f["type"] == "date":
                v = (base + timedelta(days=max(-3650, min(3650, int(v))))).isoformat()
            val = field_value(c, f, v, lid)
        except (BadInput, ValueError, TypeError):
            continue
        if val is not None:
            c.execute("INSERT OR REPLACE INTO task_field_values(task_id,field_id,value) VALUES(?,?,?)", (tid, f["id"], val))
    log_act(c, tid, "created")
    if made is not None and n.get("k"):
        made[n["k"]] = tid
    for i, k in enumerate(n.get("children") or []):
        tpl_insert(c, k, lid, sec, tid, base, i + 1, uid, fmap, scale, made)
    return tid


@app.post("/api/templates/<int:tid>/apply")
def template_apply(tid):
    """Task template: new task (+ subtasks) in {list_id, section_id} (default: inbox).
    List template: a new list of mine ({name} optional). Dates relative to today."""
    b = body()
    c = db()
    uid = me()
    r = need_template(c, tid)
    d = json.loads(r["data"] or "{}")
    base = local_now().date()
    if r["kind"] == "task":
        lid = int(b.get("list_id") or 0) or my_inbox(c)
        need_list(c, lid)
        sec = b.get("section_id")
        if sec and not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (sec, lid)).fetchone():
            sec = None
        srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
        new = tpl_insert(c, d["task"], lid, sec or None, None, base, srt, uid)
        bump(c)
        c.commit()
        return jsonify(task=one_task(c, new))
    name = str(b.get("name") or "").strip()[:200] or d.get("name") or r["name"]
    start, end = tpl_dates(b, base)
    lid = tpl_apply_list(c, uid, d, name, clean_folder(b.get("folder") or ""), start, end,
                         color=clean_color(b["color"]) if b.get("color") else None)
    bump(c)
    c.commit()
    return jsonify(list_id=lid)


def tpl_dates(b, today_):
    """{start?, end?} of a template use (2.4.0, #328): the project start (default today) and an optional end date."""
    start = b.get("start") or None
    end = b.get("end") or None
    for k, v in (("start", start), ("end", end)):
        if v is not None and not valid_date(v):
            raise BadInput(tr("Invalid value: {0}", tr("Start|date") if k == "start" else tr("End")))
    start = date.fromisoformat(start) if start else today_
    end = date.fromisoformat(end) if end else None
    if end and end < start:
        raise BadInput(tr("The end date is before the start date"))
    return start, end


def tpl_apply_list(c, uid, d, name, folder, start, end=None, color=None):
    """A new list of uid from a list template d (2.4.0: also the built-in project types). Dates relative to start;
    with end and a template span of at least one day, every offset is stretched / squeezed to fit (start .. end).
    Sections, custom fields, dependencies, ticket types. The caller commits; returns the list id."""
    lk = d.get("kind") if d.get("kind") in LIST_KINDS else "project" if d.get("fields") else "list"
    span = int(d.get("span") or 0)
    scale = (end - start).days / span if end and span > 0 else 1.0
    tt = d.get("ticket_tpl") if isinstance(d.get("ticket_tpl"), dict) else {}
    lid = c.execute("""INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,kind,checklist,tickets,ticket_tpl,dep_shift)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (name, d.get("color") or "" if color is None else color, folder, my_max_sort(c, uid) + 1, d.get("view") or "list",
                     iso(now_utc()), uid, lk, 1 if d.get("done_at_bottom") or d.get("kind") == "checklist" else 0, 1 if d.get("tickets") else 0,
                     json.dumps(tt, ensure_ascii=False) if tt else "", 1 if d.get("dep_shift") else 0)).lastrowid
    secs = [c.execute("INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, s, i)).lastrowid
            for i, s in enumerate(d.get("sections") or [])]
    fmap = []
    for i, fd in enumerate(d.get("fields") or []):
        fid = c.execute("INSERT INTO list_fields(list_id,name,type,options,pinned,sort,created_at) VALUES(?,?,?,?,?,?,?)",
                        (lid, fd["name"], fd["type"], json.dumps(fd.get("options") or {}, ensure_ascii=False), fd.get("pinned") or 0,
                         i + 1, iso(now_utc()))).lastrowid
        fmap.append(c.execute("SELECT * FROM list_fields WHERE id=?", (fid,)).fetchone())
    made = {}
    for i, n in enumerate(d.get("tasks") or []):
        si = n.get("section")
        tpl_insert(c, n, lid, secs[si] if isinstance(si, int) and 0 <= si < len(secs) else None, None, start, i, uid, fmap,
                   scale, made)
    links = []  # 2.18.0 (#430): the tasks of a milestone of the template belong to the new milestone

    def walk(nodes):
        for x in nodes:
            if x.get("mk") and x.get("k") in made and x["mk"] in made:
                links.append((made[x["mk"]], made[x["k"]]))
            walk(x.get("children") or [])
    walk(d.get("tasks") or [])
    for mid, tid_ in links:
        if ms_target(c, mid, lid, tid_) is None and not (c.execute("SELECT ms FROM tasks WHERE id=?", (tid_,)).fetchone() or [0])[0]:
            c.execute("UPDATE tasks SET milestone_id=? WHERE id=?", (mid, tid_))
    for a, b_ in d.get("deps") or []:
        if a in made and b_ in made:
            c.execute("INSERT OR IGNORE INTO task_deps(task_id,blocker_id,created_by,created_at) VALUES(?,?,?,?)",
                      (made[a], made[b_], uid, iso(now_utc())))
    agent_autoshare(c, uid, lid)  # 2.4.2 (#391): project types + templates are new lists too
    return lid


# ---- 2.4.0 (#243): project types = built-in project templates (the #328 mechanism, no tasks). English source, the section
# and field names in the language of the person creating the project. modules: switched on for that person if off
# (the time tracking of the whole instance stays the admin's switch). The client names them in the "New list" dialog,
# the setup and the welcome tour; POST /api/lists {ptype} and POST /api/v1/lists {project_type} create one.
PTYPES = {
    "agency": {"view": "list", "tickets": 0, "dep_shift": 0, "modules": ("time", "fields"),
               "sections": (N_("Request"), N_("Concept"), N_("Production"), N_("Approval"), N_("Billing")),
               "fields": ((N_("Client"), "text"), (N_("Budget h"), "number"))},
    "software": {"view": "kanban", "tickets": 1, "dep_shift": 1, "modules": ("kanban", "deps"),
                 "sections": (N_("Backlog"), N_("Next|section"), N_("In progress"), N_("Review"), N_("Done|section")), "fields": ()},
    "private": {"view": "list", "tickets": 0, "dep_shift": 0, "modules": (),
                "sections": (N_("Ideas"), N_("Planning"), N_("To do|section")), "fields": ()},
}


PTYPE_NAMES = {"agency": N_("Agency"), "software": N_("Software / AI dev"), "private": N_("Personal|project type")}


def ptype_template(k, lg):
    p = PTYPES[k]
    return {"kind": "project", "view": p["view"], "sections": [tr(x, lg=lg) for x in p["sections"]],
            "fields": [{"name": tr(n, lg=lg), "type": t, "options": {}, "pinned": 1} for n, t in p["fields"]],
            "tasks": [], "deps": [], "rel": True, "span": 0, "tickets": p["tickets"], "ticket_tpl": {}, "dep_shift": p["dep_shift"]}


def ptype_create(c, uid, k, name, folder="", color="", start=None):
    """A new project list of type k for uid; returns (list id, [modules switched on])."""
    if k not in PTYPES:
        raise BadInput(tr("Invalid value: {0}", tr("Project type")))
    lid = tpl_apply_list(c, uid, ptype_template(k, lang(c, uid)), name, folder, start or local_now().date(), color=color)
    c.execute("UPDATE lists SET ptype=? WHERE id=?", (k, lid))  # 2.18.0 (#408): the type is kept (list dialog, API)
    fs = [x for x in (usettings(c, uid).get("features") or "").split(",") if x]
    on = [m for m in PTYPES[k]["modules"] if m not in fs]
    if on:
        uset(c, uid, "features", ",".join(fs + on))
    return lid, on


def ptype_missing(c, lid, k, lg):
    """2.18.0 (#408): the sections / custom fields of project type k that list lid does not have yet (by name, ignoring
    case; in the language lg and in English). The client offers to add them; switching a type never adds or deletes them."""
    if k not in PTYPES:
        return {"sections": [], "fields": []}
    have_s = {r[0].strip().casefold() for r in c.execute("SELECT name FROM sections WHERE list_id=?", (lid,))}
    have_f = {r[0].strip().casefold() for r in c.execute("SELECT name FROM list_fields WHERE list_id=?", (lid,))}

    def lacks(x, have):
        return tr(x, lg=lg).strip().casefold() not in have and x.split("|")[0].strip().casefold() not in have
    return {"sections": [tr(x, lg=lg) for x in PTYPES[k]["sections"] if lacks(x, have_s)],
            "fields": [{"name": tr(n, lg=lg), "type": t} for n, t in PTYPES[k]["fields"] if lacks(n, have_f)]}


def list_ptype_set(c, lid, role, k, skip=()):
    """2.18.0 (#408): set the project type of list lid ('' = none). Owner / list admins (Denied 403), never the inbox.
    Switching never deletes anything: it switches on what the type needs -- type Project, ticket types (software), the
    type's view only while the list has no tasks, the type's modules for the person switching -- unless the request sets
    that field itself (skip). Returns {ptype_prev: the previous values of what it changed (for the undo), modules_on,
    ptype_missing: the type's sections / fields the list lacks (offered, not added)}."""
    k = "" if k is None else k
    if not isinstance(k, str) or (k and k not in PTYPES):
        raise BadInput(tr("Invalid value: {0}", tr("Project type")))
    if role not in MANAGE_ROLES:
        raise Denied(403)
    cur = c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()
    if cur["is_inbox"]:
        raise BadInput(tr("The inbox cannot be a project"))
    out = {"ptype_prev": {}, "modules_on": [], "ptype_missing": {"sections": [], "fields": []}}
    if (cur["ptype"] or "") == k:
        if k:
            out["ptype_missing"] = ptype_missing(c, lid, k, lang(c, me()))
        return out
    c.execute("UPDATE lists SET ptype=? WHERE id=?", (k, lid))
    if not k:
        return out
    p, prev = PTYPES[k], out["ptype_prev"]
    if cur["kind"] != "project" and "kind" not in skip:
        prev["kind"] = cur["kind"]
        c.execute("UPDATE lists SET kind='project' WHERE id=?", (lid,))
    if p["tickets"] and not cur["tickets"] and "tickets" not in skip:
        prev["tickets"] = 0  # 0 / 1 like the column: an undo sending it back passes the _prev check (_norm compares strings)
        c.execute("UPDATE lists SET tickets=1 WHERE id=?", (lid,))
    if cur["view"] != p["view"] and "view" not in skip and \
            not c.execute("SELECT 1 FROM tasks WHERE list_id=? AND deleted_at IS NULL LIMIT 1", (lid,)).fetchone():
        prev["view"] = cur["view"]
        c.execute("UPDATE lists SET view=? WHERE id=?", (p["view"], lid))
    fs = [x for x in (usettings(c, me()).get("features") or "").split(",") if x]
    out["modules_on"] = [m for m in p["modules"] if m not in fs]
    if out["modules_on"]:
        uset(c, me(), "features", ",".join(fs + out["modules_on"]))
    out["ptype_missing"] = ptype_missing(c, lid, k, lang(c, me()))
    return out
