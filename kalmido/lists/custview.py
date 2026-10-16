"""2.50.0 (#329): the customer view of a public list link - what the owner lets the customer see (public_links.cv_show, JSON).
Everything is filtered on the server (lists/public.py renders only what is switched on): progress bar, section headings,
due dates, assignee (display name only), the list's tags, single custom fields, task files (download only through the
token) and the organisation's name / logo in the header; optional "only tasks with tag ...". An empty cv_show is the 2.49
view (sections + due dates, nothing else): no link shows more than before unless its owner switches it on."""
import json
import os

from ..core.config import ATT_DIR, OFFICE_DIR
from ..core.i18n import tr
from ..personal.timetrack import BadInput

CV_FLAGS = ("progress", "sections", "due", "assignees", "tags", "files", "brand", "feedback")
CV_DEFAULT = {"progress": False, "sections": True, "due": True, "assignees": False, "tags": False, "files": False, "brand": False,
              "feedback": False, "fields": [], "tag": None}
CV_MAX_FIELDS = 20
CV_FILE_RATE = 30          # file downloads per client address and minute
CV_FILE_MAX = 25 << 20     # larger task files are listed without a download
CV_FB_RATE, CV_FB_HOUR = 5, 30   # customer comments per client address and minute / per link and hour
CV_FB_NAME, CV_FB_TEXT = 80, 2000


def cv_show(link):
    """The stored choice of a link -> a full dict (defaults filled in; anything odd = the default)."""
    out = dict(CV_DEFAULT, fields=[])
    try:
        v = json.loads(link["cv_show"] or "{}") if "cv_show" in link.keys() else {}
    except (TypeError, ValueError):
        v = {}
    if not isinstance(v, dict):
        return out
    for k in CV_FLAGS:
        if isinstance(v.get(k), bool):
            out[k] = v[k]
    out["fields"] = [int(x) for x in v.get("fields") or [] if isinstance(x, int) and not isinstance(x, bool)][:CV_MAX_FIELDS]
    out["tag"] = v["tag"] if isinstance(v.get("tag"), int) and not isinstance(v.get("tag"), bool) else None
    return out


def cv_clean(c, lid, v, cur):
    """A PUT body's "show" (partial dict) -> the JSON to store. Field and tag ids must belong to the list."""
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid value: {0}", "show"))
    out = dict(cur)
    for k in CV_FLAGS:
        if k in v:
            if not isinstance(v[k], bool):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v[k]
    if "fields" in v:
        f = v["fields"]
        if not isinstance(f, list) or len(f) > CV_MAX_FIELDS or any(not isinstance(x, int) or isinstance(x, bool) for x in f):
            raise BadInput(tr("Invalid value: {0}", "fields"))
        have = {r[0] for r in c.execute("SELECT id FROM list_fields WHERE list_id=? AND type!='formula'", (lid,))}
        if any(x not in have for x in f):
            raise BadInput(tr("Invalid value: {0}", "fields"))
        out["fields"] = list(dict.fromkeys(f))
    if "tag" in v:
        t = v["tag"]
        if t is not None and (not isinstance(t, int) or isinstance(t, bool)
                              or not c.execute("SELECT 1 FROM list_tags WHERE id=? AND list_id=?", (t, lid)).fetchone()):
            raise BadInput(tr("Invalid value: {0}", "tag"))
        out["tag"] = t
    return json.dumps(out, separators=(",", ":"))


def cv_options(c, lid):
    """What the share dialog offers: the list's tags and custom fields."""
    return {"tags": [{"id": r["id"], "name": r["name"]} for r in c.execute("SELECT id, name FROM list_tags WHERE list_id=? ORDER BY sort, id", (lid,))],
            "fields": [{"id": r["id"], "name": r["name"], "type": r["type"]}
                       for r in c.execute("SELECT id, name, type FROM list_fields WHERE list_id=? AND type!='formula' ORDER BY sort, id", (lid,))]}


def cv_tag_sql(show):
    """SQL + args that keep only the tasks with the chosen tag (and the subtasks of such tasks)."""
    if not show["tag"]:
        return "", ()
    return (" AND (id IN (SELECT task_id FROM task_list_tags WHERE tag_id=?) OR parent_id IN (SELECT task_id FROM task_list_tags WHERE tag_id=?))",
            (show["tag"], show["tag"]))


def cv_progress(c, link, show):
    """(done, total) of the list's top-level tasks the link shows (won't-do items are left out)."""
    tsql, targs = (" AND id IN (SELECT task_id FROM task_list_tags WHERE tag_id=?)", (show["tag"],)) if show["tag"] else ("", ())
    r = c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN status=2 THEN 1 ELSE 0 END), 0) AS d FROM tasks "
                  "WHERE list_id=? AND deleted_at IS NULL AND parent_id IS NULL AND status <> -1" + tsql, (link["list_id"], *targs)).fetchone()
    return int(r["d"]), int(r["n"])


def _field_text(f, val, lg, names, day):
    if val in (None, ""):
        return ""
    t = f["type"]
    if t == "checkbox":
        return tr("yes", lg=lg) if val in ("1", "true") else ""
    if t == "select":
        try:
            opts = (json.loads(f["options"] or "{}") or {}).get("options") or []
        except ValueError:
            opts = []
        ids = [x for x in str(val).split(",") if x]
        return ", ".join(o.get("name") or "" for o in opts if isinstance(o, dict) and str(o.get("id")) in ids)
    if t == "person":
        try:
            return names.get(int(val), "")
        except ValueError:
            return ""
    if t == "date":
        try:
            return day(val[:10], lg)
        except ValueError:
            return ""
    if t == "number":
        try:
            unit = (json.loads(f["options"] or "{}") or {}).get("unit") or ""
        except ValueError:
            unit = ""
        return f"{val} {unit}".strip()
    return str(val)[:300]


def cv_extras(c, link, tasks, show, lg, day):
    """{task id: {"who": name, "tags": [(name, colour)], "fields": [(name, text)], "files": [(id, name, size, ok)]}} for the
    visible tasks, only with what the link shows."""
    ids = [t["id"] for t in tasks]
    out = {i: {"who": "", "tags": [], "fields": [], "files": []} for i in ids}
    if not ids:
        return out
    ph = ",".join("?" * len(ids))
    uids = set()
    if show["assignees"]:
        uids |= {t["assignee_id"] for t in tasks if t.get("assignee_id")}
    flds = []
    if show["fields"]:
        flds = [dict(r) for r in c.execute("SELECT id, name, type, options FROM list_fields WHERE list_id=? ORDER BY sort, id", (link["list_id"],))
                if r["id"] in show["fields"]]
    vals = {}
    if flds:
        fph = ",".join("?" * len(flds))
        for r in c.execute(f"SELECT task_id, field_id, value FROM task_field_values WHERE task_id IN ({ph}) AND field_id IN ({fph})",
                           (*ids, *[f["id"] for f in flds])):
            vals[(r["task_id"], r["field_id"])] = r["value"]
            if any(f["id"] == r["field_id"] and f["type"] == "person" for f in flds):
                try:
                    uids.add(int(r["value"]))
                except (TypeError, ValueError):
                    pass
    names = {}
    if uids:
        uph = ",".join("?" * len(uids))
        names = {r["id"]: r["display_name"] or r["username"] for r in c.execute(f"SELECT id, display_name, username FROM users WHERE id IN ({uph})", tuple(uids))}
    for t in tasks:
        o = out[t["id"]]
        if show["assignees"] and t.get("assignee_id"):
            o["who"] = names.get(t["assignee_id"], "")
        for f in flds:
            txt = _field_text(f, vals.get((t["id"], f["id"])), lg, names, day)
            if txt:
                o["fields"].append((f["name"], txt))
    if show["tags"]:
        for r in c.execute(f"SELECT tt.task_id, lt.name, lt.color FROM task_list_tags tt JOIN list_tags lt ON lt.id=tt.tag_id "
                           f"WHERE tt.task_id IN ({ph}) AND lt.list_id=? ORDER BY lt.sort, lt.id", (*ids, link["list_id"])):
            out[r["task_id"]]["tags"].append((r["name"], r["color"]))
    if show["files"]:  # 2.61.0 review: browser-encrypted files (e2e) never go out through a link
        for r in c.execute(f"SELECT id, task_id, name, size FROM attachments WHERE task_id IN ({ph}) AND comment_id IS NULL AND COALESCE(enc, 0)=0 ORDER BY id", tuple(ids)):
            out[r["task_id"]]["files"].append((r["id"], r["name"], r["size"], (r["size"] or 0) <= CV_FILE_MAX))
    return out


def cv_file(c, link, show, visible_ids, aid):
    """The attachment row a link may hand out (a task file of a visible task, files switched on), or None."""
    if not show["files"] or not visible_ids:
        return None
    r = c.execute("SELECT * FROM attachments WHERE id=? AND comment_id IS NULL AND COALESCE(enc, 0)=0", (aid,)).fetchone()
    if not r or r["task_id"] not in visible_ids or (r["size"] or 0) > CV_FILE_MAX:
        return None
    from ..files.scan import sc_locked
    if sc_locked(c, "att", aid):  # 2.61.0 (#1818): a file found infected later is never handed out
        return None
    full = os.path.join(ATT_DIR, r["path"])
    return (r, full) if os.path.isfile(full) else None


def cv_brand(c, link):
    """(name, logo path or None) of the list's organisation for the page header: the office's company name and logo when
    the organisation has them, otherwise the organisation's name. Private lists: (None, None)."""
    oid = link["l_org"]
    if not oid:
        return None, None
    o = c.execute("SELECT name, personal_of FROM orgs WHERE id=?", (oid,)).fetchone()
    if not o:
        return None, None
    name, logo = (o["name"] if not o["personal_of"] else ""), None
    try:
        from ..office.model import office_settings
        s = office_settings(c, oid)
        name = ((s.get("company") or {}).get("name") or "").strip() or name
        if s.get("logo"):
            p = os.path.join(OFFICE_DIR, str(int(oid)), os.path.basename(s["logo"]))
            logo = p if os.path.isfile(p) else None
    except Exception:  # the office module is optional: the organisation's name is enough
        pass
    return (name or None), logo


def cv_size(n, lg):
    n = n or 0
    if n < 1024:
        return f"{n} B"
    if n < 1 << 20:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1 << 20):.1f} MB".replace(".", "," if lg == "de" else ".")
