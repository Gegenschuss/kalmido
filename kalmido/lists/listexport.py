"""2.116.0 C (#2064): a list or project as a CSV file (GET /api/lists/<id>/export.csv).

An app route (session cookie) like the time sheet's CSV; agents have /api/v1/tasks instead. The printable view is the client's
(static/js/listprint.js). Same rules as reading the list: who cannot see it gets 404, participants get only their own tasks
(tvis, the tasks they may change: no context parents), a list with the lock (end-to-end encrypted) has only ciphertext here (409; the client does not offer it).
2.145.0 C (#2431): more columns, appended after the old ones (importers / sheets of users keep working): start, deadline,
duration, tracked time, created / completed by, milestone, sprint and the checklist as one cell. Comments, attachments and the
project description stay out (the printable view has the project head, #2432)."""
import csv
import io
import json
import re

from flask import Response, request

from ..core.config import app
from ..core.i18n import dec_comma, lang, tr
from ..core.db import db, local_now
from ..core.access import Denied, list_role, tvis, vis_sql
from ..accounts.session import me
from ..personal.timetrack import _csv_cell

LEX_PRIO = {1: "Low", 3: "Medium", 5: "High"}
LEX_CB = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s*(.*)")  # a Markdown checkbox line of the notes (like renderMd)


def lex_name(c, lid):
    r = c.execute("SELECT name, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
    return tr("Basket") if r["is_inbox"] else r["name"]


def lex_value(c, f, raw, names):
    """The readable text of a custom field's stored value (select: the option name, person: the name, checkbox: Yes)."""
    if raw in (None, ""):
        return ""
    t = f["type"]
    if t == "select":
        for o in json.loads(f["options"] or "{}").get("options", []):
            if o.get("id") == raw:
                return o.get("name") or ""
        return ""
    if t == "person":
        return names.get(int(raw), "") if str(raw).isdigit() else ""
    if t == "checkbox":
        return tr("Yes") if raw == "1" else ""
    if t == "multiselect":  # 2.156.0 B (#2069): the option names, in the order of the options
        on = {o.get("id"): o.get("name") or "" for o in json.loads(f["options"] or "{}").get("options", [])}
        return ", ".join(on[x] for x in str(raw).split(",") if x in on)
    if t == "task":  # 2.156.0 B (#2069): the title, only when the person exporting may see the task
        from .fields import fd_uid
        from ..core.access import task_visible
        r = c.execute("SELECT title FROM tasks WHERE id=? AND deleted_at IS NULL", (int(raw),)).fetchone() if str(raw).isdigit() else None
        return r["title"] if r and task_visible(c, int(raw), fd_uid()) else ""
    return raw


def lex_start(r):
    """2.145.0 C (#2431): the start day (timeline), else the day plan's slot ("YYYY-MM-DD HH:MM")."""
    return r["start"] or (r["plan_start"] or "").replace("T", " ")


def lex_checklist(content, subs):
    """2.145.0 C (#2431): the checklist of a task as one cell, one point per line: the checkbox lines of its notes, then its
    subtasks ("[x] Text" done, "[ ] Text" open; won't-do subtasks are left out)."""
    out = [f"[{'x' if m.group(1) != ' ' else ' '}] {m.group(2).strip()}" for m in map(LEX_CB.match, (content or "").split("\n")) if m]
    out += [f"[{'x' if s['status'] == 2 else ' '}] {s['title']}" for s in subs if s["status"] != -1]
    return "\n".join(out)


def lex_extra(c, uid, lid, rows, ids):
    """2.145.0 C (#2431): what the new columns need, each loaded once for all rows (no query per task).
    names: creators / completers the user may see in this list (a participant: h6r_shared_people, else everyone of the list's
    tasks); ms: milestone titles the user can see; sprints: the list's sprint names; secs: tracked seconds per task like the
    task view's total (time_totals: finished entries the user may see); subs: subtasks per parent the user may change (tvis)."""
    from ..collab.comments import h6r_shared_people, user_names
    from ..personal.timetrack import evis, th_sql
    out = {"names": {}, "ms": {}, "sprints": {}, "secs": {}, "subs": {}}
    if not ids:
        return out
    q = ",".join(str(int(i)) for i in ids)
    keep = h6r_shared_people(c, lid, uid)
    people = {p for r in rows for p in (r["created_by"], r["completed_by"]) if p and (keep is None or p in keep)}
    out["names"] = user_names(c, list(people))
    mids = {int(r["milestone_id"]) for r in rows if r["milestone_id"]}
    if mids:
        out["ms"] = {r["id"]: r["title"] for r in c.execute(
            f"""SELECT id, title FROM tasks WHERE list_id=? AND ms=1 AND deleted_at IS NULL AND id IN ({','.join(str(i) for i in mids)})
                AND {tvis(c, uid)}""", (lid,))}
    if any(r["sprint_id"] for r in rows):
        out["sprints"] = {r["id"]: r["name"] or tr("Sprint {0}", r["num"]) for r in c.execute(
            "SELECT id, num, name FROM sprints WHERE list_id=?", (lid,))}
    for r in c.execute(f"""SELECT task_id, SUM(seconds) AS s FROM time_entries WHERE task_id IN ({q}) AND "end" IS NOT NULL
                             AND (user_id=? OR list_id IN {vis_sql()}) AND {evis(c, uid, "")} AND {th_sql("")} GROUP BY task_id""",
                       (uid, uid, uid)):
        out["secs"][r["task_id"]] = r["s"] or 0
    for r in c.execute(f"""SELECT parent_id, title, status FROM tasks t WHERE parent_id IN ({q}) AND deleted_at IS NULL
                             AND {tvis(c, uid, 't.', write=True)} ORDER BY sort, id"""):
        out["subs"].setdefault(r["parent_id"], []).append(r)
    return out


@app.get("/api/lists/<int:lid>/export.csv")
def lex_csv(lid):
    from ..agents.core import agent_ids
    from ..collab.comments import user_names
    from ..collab.liste2e import le2e_mode
    c = db()
    uid = me()
    if not list_role(c, lid):
        raise Denied(404)
    if uid in agent_ids(c):
        raise Denied(403)
    if le2e_mode(c, lid):
        raise Denied(409, tr("Not available in encrypted projects"))
    done = request.args.get("done", "1") != "0"
    rows = c.execute(f"""SELECT t.*, s.name AS section, p.title AS parent_title FROM tasks t
        LEFT JOIN sections s ON s.id=t.section_id LEFT JOIN tasks p ON p.id=t.parent_id
        WHERE t.list_id=? AND t.deleted_at IS NULL AND {tvis(c, uid, 't.', write=True)}{'' if done else ' AND t.status=0'}
        ORDER BY COALESCE(s.sort, -1), t.sort, t.id""", (lid,)).fetchall()
    ids = [r["id"] for r in rows]
    tags = {}
    if ids:
        q = ",".join(str(int(i)) for i in ids)
        for r in c.execute(f"SELECT task_id, tag FROM task_tags WHERE user_id=? AND task_id IN ({q}) ORDER BY tag", (uid,)):
            tags.setdefault(r[0], []).append(r[1])
    fields = [f for f in c.execute("SELECT * FROM list_fields WHERE list_id=? AND type!='formula' ORDER BY sort, id", (lid,))]
    vals = {}
    if ids and fields:
        q = ",".join(str(int(i)) for i in ids)
        for r in c.execute(f"SELECT task_id, field_id, value FROM task_field_values WHERE task_id IN ({q})"):
            vals[(r[0], r[1])] = r[2]
    names = user_names(c, [r["assignee_id"] for r in rows] + [int(v) for (t, f), v in vals.items() if str(v).isdigit()])
    x = lex_extra(c, uid, lid, rows, ids)
    de = dec_comma(lang())
    hrs = (lambda sec: f"{sec / 3600:.2f}".replace(".", "," if de else ".") if sec else "")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";" if de else ",", lineterminator="\r\n")
    w.writerow([tr("Title"), tr("Status"), tr("Due"), tr("Priority"), tr("Tags"), tr("Assignee"), tr("Section"), tr("Parent task"),
                tr("Notes"), tr("Completed"), tr("Created")] + [_csv_cell(f["name"]) for f in fields]
              + [tr("Start date"), tr("Deadline"), tr("Duration (h)"), tr("Tracked time (h)"), tr("Created by"), tr("Completed by"),
                 tr("Milestone"), tr("Sprint"), tr("Checklist")])
    for r in rows:
        due = (r["due"] or "") + (" " + r["due_time"] if r["due"] and r["due_time"] else "")
        st = tr("Done") if r["status"] == 2 else tr("Won't do") if r["status"] == -1 else tr("Open|report")  # 2.145.0 C (#2431): the state, not the verb (de "Offen")
        w.writerow([_csv_cell(r["title"]), st, due, tr(LEX_PRIO[r["priority"]]) if r["priority"] in LEX_PRIO else "",
                    _csv_cell(", ".join(tags.get(r["id"], []))), _csv_cell(names.get(r["assignee_id"], "")),
                    _csv_cell(r["section"]), _csv_cell(r["parent_title"]), _csv_cell(r["content"]),
                    (r["completed_at"] or "")[:10], (r["created_at"] or "")[:10]]
                   + [_csv_cell(lex_value(c, f, vals.get((r["id"], f["id"])), names)) for f in fields]
                   + [lex_start(r), r["due"] if r["deadline"] and r["due"] else "", hrs((r["duration"] or 0) * 60),
                      hrs(x["secs"].get(r["id"], 0)), _csv_cell(x["names"].get(r["created_by"], "")),
                      _csv_cell(x["names"].get(r["completed_by"], "") if r["status"] == 2 else ""),
                      _csv_cell(x["ms"].get(r["milestone_id"], "")), _csv_cell(x["sprints"].get(r["sprint_id"], "")),
                      _csv_cell(lex_checklist(r["content"], x["subs"].get(r["id"], [])))])
    name = re.sub(r"[^A-Za-z0-9._-]", "_", f"{lex_name(c, lid)}-{local_now().date().isoformat()}") + ".csv"
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
