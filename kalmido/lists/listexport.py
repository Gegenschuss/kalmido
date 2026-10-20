"""2.116.0 C (#2064): a list or project as a CSV file (GET /api/lists/<id>/export.csv).

An app route (session cookie) like the time sheet's CSV; agents have /api/v1/tasks instead. The printable view is the client's
(static/js/listprint.js). Same rules as reading the list: who cannot see it gets 404, participants get only their own tasks
(tvis, the tasks they may change: no context parents), a list with the lock (end-to-end encrypted) has only ciphertext here (409; the client does not offer it)."""
import csv
import io
import json
import re

from flask import Response, request

from ..core.config import app
from ..core.i18n import dec_comma, lang, tr
from ..core.db import db, local_now
from ..core.access import Denied, list_role, tvis
from ..accounts.session import me
from ..personal.timetrack import _csv_cell

LEX_PRIO = {1: "Low", 3: "Medium", 5: "High"}


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
    return raw


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
        raise Denied(409, tr("Not available in encrypted lists"))
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
    de = dec_comma(lang())
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";" if de else ",", lineterminator="\r\n")
    w.writerow([tr("Title"), tr("Status"), tr("Due"), tr("Priority"), tr("Tags"), tr("Assignee"), tr("Section"), tr("Parent task"),
                tr("Notes"), tr("Completed"), tr("Created")] + [_csv_cell(f["name"]) for f in fields])
    for r in rows:
        due = (r["due"] or "") + (" " + r["due_time"] if r["due"] and r["due_time"] else "")
        st = tr("Done") if r["status"] == 2 else tr("Won't do") if r["status"] == -1 else tr("Open")
        w.writerow([_csv_cell(r["title"]), st, due, tr(LEX_PRIO[r["priority"]]) if r["priority"] in LEX_PRIO else "",
                    _csv_cell(", ".join(tags.get(r["id"], []))), _csv_cell(names.get(r["assignee_id"], "")),
                    _csv_cell(r["section"]), _csv_cell(r["parent_title"]), _csv_cell(r["content"]),
                    (r["completed_at"] or "")[:10], (r["created_at"] or "")[:10]]
                   + [_csv_cell(lex_value(c, f, vals.get((r["id"], f["id"])), names)) for f in fields])
    name = re.sub(r"[^A-Za-z0-9._-]", "_", f"{lex_name(c, lid)}-{local_now().date().isoformat()}") + ".csv"
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
