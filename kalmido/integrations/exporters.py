"""2.142.0 C (#2148): export into other tools' formats: a ZIP with one Todoist-template CSV per list, or one Markdown checklist per
list. Same scope as GET /api/export.json (the lists I own); lists with the lock (end-to-end encrypted) are left out, the server
only holds ciphertext of them, and a note file in the ZIP says so. Completed tasks stay out of the CSV (it has no state)."""
import csv
import io
import re
import zipfile

from flask import Response

from ..core.config import app, TZ
from ..core.i18n import tr
from ..core.db import db, local_now
from ..core.serializers import csv_cell
from ..accounts.session import me

_WD = {"MO": "monday", "TU": "tuesday", "WE": "wednesday", "TH": "thursday", "FR": "friday", "SA": "saturday", "SU": "sunday"}
TD_HEAD = ["TYPE", "CONTENT", "DESCRIPTION", "PRIORITY", "INDENT", "AUTHOR", "RESPONSIBLE", "DATE", "DATE_LANG", "TIMEZONE"]
TD_PRIO = {5: "1", 3: "2", 1: "3"}  # Kalmido high / medium / low -> Todoist p1 / p2 / p3 (p4 = none)
MD_PRIO = {5: "high", 3: "medium", 1: "low"}


def ex_rr_text(rr, after=False):
    """An RRULE body -> Todoist's "every ..." text, or None when it has no simple wording."""
    p = dict(x.split("=", 1) for x in str(rr or "").split(";") if "=" in x)
    f, n = p.get("FREQ", ""), int(p["INTERVAL"]) if p.get("INTERVAL", "").isdigit() else 1
    lead = "every!" if after else "every"
    unit = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}.get(f)
    if not unit or set(p) - {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY"}:
        return None
    if f == "WEEKLY" and p.get("BYDAY"):
        days = p["BYDAY"].split(",")
        if n != 1 or not all(d in _WD for d in days):
            return None
        return f"{lead} workday" if days == ["MO", "TU", "WE", "TH", "FR"] else f"{lead} " + ", ".join(_WD[d] for d in days)
    if f == "MONTHLY" and p.get("BYMONTHDAY"):
        d = p["BYMONTHDAY"]
        return f"{lead} last day" if d == "-1" and n == 1 else f"{lead} {d}" if d.isdigit() and n == 1 else None
    if "BYDAY" in p or "BYMONTHDAY" in p:
        return None
    return f"{lead} {unit}" if n == 1 else f"{lead} {n} {unit}s"


def ex_date_text(t):
    """The DATE cell of a task: ISO date (+ time), or "every ..." (+ " at HH:MM") for a repeating one; (text, rule that has no wording)."""
    if t["repeat"]:
        w = ex_rr_text(t["repeat"], t["repeat_from"] == "done")
        if w:
            return w + (f" at {t['due_time']}" if t["due_time"] else ""), ""
    if not t["due"]:
        return "", t["repeat"] or ""
    return t["due"] + (f" {t['due_time']}" if t["due_time"] else ""), t["repeat"] or ""


def ex_file_name(name, used, ext):
    """A safe member name: no path characters, no control characters, not empty, not twice."""
    base = re.sub(r"[^\w\- .()]+", "_", str(name or ""), flags=re.U).strip(" ._")[:80] or "list"
    n, cand = 1, base
    while cand.lower() in used:
        n += 1
        cand = f"{base} ({n})"
    used.add(cand.lower())
    return cand + ext


def ex_lists(c, uid):
    """(lists to export, names of the locked ones that stay out), the scope of export.json."""
    rows = c.execute("SELECT * FROM lists WHERE owner_id=? AND (deleted_at IS NULL OR org_id IS NULL) ORDER BY is_inbox DESC, sort, id", (uid,)).fetchall()
    return [r for r in rows if not r["e2e"]], [r["name"] for r in rows if r["e2e"]]


def ex_tasks(c, uid, lid):
    """The tasks of one list in tree order: [(task, depth, tags, assignee name)], sections in their order. Not deleted;
    a child whose parent is left out (completed in the CSV) moves up."""
    secs = c.execute("SELECT id, name FROM sections WHERE list_id=? ORDER BY sort, id", (lid,)).fetchall()
    rows = c.execute("SELECT t.*, u.display_name AS who FROM tasks t LEFT JOIN users u ON u.id=t.assignee_id "
                     "WHERE t.list_id=? AND t.deleted_at IS NULL ORDER BY t.sort, t.id", (lid,)).fetchall()
    tags = {}
    for r in c.execute("SELECT task_id, tag FROM task_tags WHERE user_id=? AND task_id IN (SELECT id FROM tasks WHERE list_id=?) ORDER BY tag",
                       (uid, lid)):
        tags.setdefault(r["task_id"], []).append(r["tag"])
    return secs, rows, tags


def ex_tree(rows, keep):
    """rows -> [(row, depth)] depth-first, children below their parent; parents not kept are skipped."""
    ids = {r["id"] for r in rows if keep(r)}
    kids = {}
    for r in rows:
        if keep(r):
            p = r["parent_id"]
            kids.setdefault(p if p in ids else None, []).append(r)
    out = []

    def walk(p, d):
        for r in kids.get(p, []):
            out.append((r, d))
            walk(r["id"], d + 1)
    walk(None, 0)
    return out


def ex_sections(secs, rows):
    """[(section name | None, rows of it)]: first the ones without a section, then each section in order."""
    ids = {s["id"] for s in secs}
    out = [(None, [r for r in rows if r["section_id"] not in ids])]
    return out + [(s["name"], [r for r in rows if r["section_id"] == s["id"]]) for s in secs]


def ex_todoist_csv(c, uid, lst):
    secs, rows, tags = ex_tasks(c, uid, lst["id"])
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")  # 2.142.0 review: free text through csv_cell (no formulas in spreadsheets)
    w.writerow(TD_HEAD)
    notes = {}
    for r in c.execute("SELECT m.task_id, m.body, u.display_name FROM comments m LEFT JOIN users u ON u.id=m.user_id "
                       "WHERE m.deleted_at IS NULL AND m.task_id IN (SELECT id FROM tasks WHERE list_id=?) ORDER BY m.id", (lst["id"],)):
        notes.setdefault(r["task_id"], []).append((re.sub(r"<@\d+>", "@", r["body"] or ""), r["display_name"] or ""))
    for sec, srows in ex_sections(secs, rows):
        if sec is not None:
            w.writerow(["section", csv_cell(sec), "", "", "", "", "", "", "", ""])
        for t, d in ex_tree(srows, lambda r: r["status"] == 0):
            title = (t["title"] or "").replace("\n", " ")
            label = "".join(" @" + re.sub(r"\s+", "_", g) for g in tags.get(t["id"], []))
            date, extra = ex_date_text(t)
            desc = t["content"] or ""
            if extra:
                desc = (desc + "\n" if desc else "") + "Repeats: " + extra  # plain text, the file is for other tools
            w.writerow(["task", csv_cell(title + label), csv_cell(desc), TD_PRIO.get(t["priority"], "4"), min(d + 1, 4), "", csv_cell(t["who"]), date,
                        "en" if date else "", str(TZ.key) if date else ""])
            for body, who in notes.get(t["id"], []):
                w.writerow(["note", csv_cell(body), "", "", "", csv_cell(who), "", "", "", ""])
    return out.getvalue()


def ex_markdown(c, uid, lst):
    secs, rows, tags = ex_tasks(c, uid, lst["id"])
    out = [f"# {lst['name']}", ""]
    for sec, srows in ex_sections(secs, rows):
        if sec is not None:
            out += [f"## {sec}", ""]
        for t, d in ex_tree(srows, lambda r: True):
            date, extra = ex_date_text(t)
            bits = [x for x in (("due " + date) if date else "", MD_PRIO.get(t["priority"], "") and MD_PRIO[t["priority"]] + " priority",
                                ("repeats " + extra) if extra else "") if x]
            box = "x" if t["status"] == 2 else "-" if t["status"] == -1 else " "
            pad = "  " * d
            out.append(f"{pad}- [{box}] {(t['title'] or '').replace(chr(10), ' ')}" + (f" ({', '.join(bits)})" if bits else "") +
                       "".join(" #" + re.sub(r"\s+", "_", g) for g in tags.get(t["id"], [])))
            out += [f"{pad}  {ln}".rstrip() for ln in (t["content"] or "").splitlines()]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def ex_zip(kind):
    c = db()
    uid = me()
    lists, locked = ex_lists(c, uid)
    used, buf = set(), io.BytesIO()
    ext, fn = (".csv", ex_todoist_csv) if kind == "todoist" else (".md", ex_markdown)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for l in lists:
            z.writestr(ex_file_name("Inbox" if l["is_inbox"] else l["name"], used, ext), fn(c, uid, l))
        if locked:
            z.writestr(ex_file_name("README-locked-lists", used, ".txt"),
                       tr("These projects are locked with a password (end-to-end encrypted). The server only holds them as ciphertext, so they cannot be exported here:") +
                       "\n\n" + "\n".join("- " + n for n in locked) + "\n")
    name = f"kalmido-{'todoist' if kind == 'todoist' else 'markdown'}-{local_now():%Y-%m-%d}.zip"
    from ..admin.acctexport import umz_log_org_lists
    umz_log_org_lists(c, uid)  # 2.148.1 H (#2492): noted in the organisation's list history like export.json
    c.commit()
    return Response(buf.getvalue(), mimetype="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/export/todoist.zip")
def export_todoist():
    return ex_zip("todoist")


@app.get("/api/export/markdown.zip")
def export_markdown():
    return ex_zip("markdown")
