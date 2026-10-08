"""Lists: create, change, share (people + agents), members, sidebar order."""
import json
import math
import re
from flask import g, has_request_context, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc, uset, usettings
from ..accounts.session import me
from ..accounts.pictures import list_icon_drop_file
from ..core.access import collab_all, Denied, MANAGE_ROLES, my_inbox, my_max_sort, need_collab, need_list, ROLES
from ..core.state import visible_lists


# ---------------------------------------------------------------- lists / sections

LIST_FIELDS = ("name", "color", "folder", "sort", "view", "archived", "checklist", "dep_shift", "kind", "tickets", "nag",
               "family",  # 2.19.0 (#653): '' | shopping | meals | birthdays | household | packing
               "life", "trip")  # 2.22.0 (#663): '' | contracts | home | health | travel | reading; {from, to, where} of a trip
LIST_KINDS = ("list", "project")
# 2.7.2 (#414): the type "checklist" (2.7.0 "Shopping & packing list") is gone. Every list has the display option "Show
# completed at the bottom" instead (column lists.checklist, API field done_at_bottom); kind "checklist" is still accepted
# as a deprecated alias (= kind list + the option on), the boolean "checklist" as an alias of done_at_bottom.
LIST_KIND_ALIASES = {"checklist": "list"}
MEMBER_LIST_FIELDS = ("folder", "sort", "view")  # a member's own sidebar placement / view
LIST_SORTS = ("", "prio", "custom", "date", "title", "creator", "flow", "created", "created_asc")  # 2.27.0 (#988): lists.sort_mode
# 2.31.0 (#354): the sorts of a click on a column title (the other direction, the columns without a menu entry)
LIST_SORTS += ("date_desc", "prio_asc")
LIST_SORT_RE = r"cf:\d{1,9}(_desc)?|col:(who|tags|time|progress|deps)(_desc)?"
LIST_VIEWS = ("list", "kanban", "timeline")
LIST_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
LIST_NAME_MAX, FOLDER_MAX = 200, 100


def clean_color(v):
    from ..personal.timetrack import BadInput
    v = v.strip() if isinstance(v, str) else v
    if v in ("", None):
        return ""
    if not isinstance(v, str) or not LIST_COLOR_RE.fullmatch(v):
        raise BadInput(tr("Invalid value: {0}", tr("Color")))
    return v


# 2.4.0 (#361): a folder is a path of at most FOLDER_DEPTH names joined by FOLDER_SEP ("Clients/Company X"), per user as
# before (lists.folder for the owner, list_members.folder for a member; the order in the user setting "folders"). A name
# itself can never hold the separator (folder_seg turns it into the look-alike U+2215).
FOLDER_SEP, FOLDER_DEPTH = "/", 2


def folder_seg(v):
    """One folder name (imports, legacy names): control characters out, a "/" becomes U+2215 (it would nest)."""
    return re.sub(r"[\x00-\x1f]", "", str(v or "")).replace(FOLDER_SEP, "\u2215").strip()[:FOLDER_MAX]


def clean_folder(v, strict=True):
    """A folder path from a client: every name trimmed (at most FOLDER_MAX characters), empty names dropped. Deeper than
    FOLDER_DEPTH: BadInput (strict) or cut to FOLDER_DEPTH (repairs, stored data)."""
    from ..personal.timetrack import BadInput
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", tr("Folder")))
    parts = [x for x in (re.sub(r"[\x00-\x1f]", "", p).strip()[:FOLDER_MAX] for p in v.split(FOLDER_SEP)) if x]
    if len(parts) > FOLDER_DEPTH:
        if strict:
            raise BadInput(tr("Folders nest at most {0} levels deep", FOLDER_DEPTH))
        parts = parts[:FOLDER_DEPTH]
    return FOLDER_SEP.join(parts)


def folder_under(p, top):
    """True if the path p is the folder top or inside it."""
    return bool(top) and (p == top or p.startswith(top + FOLDER_SEP))


def folder_path_migration(c):
    """2.4.0, once: a "/" in a stored folder name becomes U+2215 (lists, member rows, every user's folder order)."""
    n = 0
    for tbl, key in (("lists", "id"), ("list_members", "rowid")):
        for r in c.execute(f"SELECT {key} AS k, folder FROM {tbl} WHERE folder LIKE '%/%'").fetchall():
            c.execute(f"UPDATE {tbl} SET folder=? WHERE {key}=?", (folder_seg(r["folder"]), r["k"]))
            n += 1
    for r in c.execute("SELECT user_id, value FROM user_settings WHERE key='folders' AND value LIKE '%/%'").fetchall():
        try:
            arr = json.loads(r["value"] or "[]")
        except ValueError:
            continue
        if isinstance(arr, list):
            arr = list(dict.fromkeys(folder_seg(x) for x in arr if isinstance(x, str) and folder_seg(x)))
            c.execute("UPDATE user_settings SET value=? WHERE user_id=? AND key='folders'",
                      (json.dumps(arr, ensure_ascii=False), r["user_id"]))
    return n


# 2.14.0 (#425): list columns. One setting per list for every member (owner / list admins change it): which columns the
# rows show and in which order. Keys: COL_KEYS plus "f:<field id>" for the list's custom fields; "id" is the task number in
# front of the title. NULL (API null) = the default layout (date, assignee, time; fields as chips).
COL_KEYS = ("id", "due", "prio", "who", "tags", "time", "progress", "deps", "created")
COL_MAX = 40
COL_DOC = ("2.14.0 (#425): the columns of the list's rows in order, the same for every member: id (task number in front of the "
           "title), due, prio, who (assignee), tags, time (tracked), progress (subtasks), deps (dependencies), created, and "
           "f:<field id> for custom fields. Not listed = not shown in the rows. null = the default layout.")


def clean_columns(c, lid, v):
    """The columns of list lid from a client -> the JSON text to store (None = default). BadInput on anything odd."""
    from ..personal.timetrack import BadInput
    if v is None:
        return None
    if not isinstance(v, list) or len(v) > COL_MAX:
        raise BadInput(tr("Invalid value: {0}", "columns"))
    fids = {r[0] for r in c.execute("SELECT id FROM list_fields WHERE list_id=?", (lid,))}
    out = []
    for k in v:
        if not isinstance(k, str):
            raise BadInput(tr("Invalid value: {0}", "columns"))
        m = re.fullmatch(r"f:(\d{1,12})", k)
        if not (k in COL_KEYS or (m and int(m.group(1)) in fids)):
            raise BadInput(tr("Unknown column: {0}", k[:40]))
        if k not in out:
            out.append(k)
    return json.dumps(out)


def columns_out(raw, fids):
    """Stored columns -> the API value: a list of keys (fields that no longer exist dropped) or None (default)."""
    if raw in (None, ""):
        return None
    try:
        v = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(v, list):
        return None
    return [k for k in v if isinstance(k, str) and (k in COL_KEYS or (k.startswith("f:") and k[2:].isdigit() and int(k[2:]) in fids))]


def clean_list_value(k, v, member=False):
    """One list column from the client, validated (BadInput)."""
    from ..tasks.validation import NAG_VALUES
    from ..personal.timetrack import BadInput
    from ..family.family import FAM_LIST_KINDS
    if k == "name":
        if not isinstance(v, str) or not v.strip():
            raise BadInput(tr("Name missing"))
        return v.strip()[:LIST_NAME_MAX]
    if k == "color":
        return clean_color(v)
    if k == "folder":
        return clean_folder(v)
    if k == "view":
        if member and v in (None, ""):
            return None  # member: back to the owner's view
        if v not in LIST_VIEWS:
            raise BadInput(tr("Invalid value: {0}", tr("View")))
        return v
    if k == "sort":
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "sort")) from None
        if not math.isfinite(v):
            raise BadInput(tr("Invalid value: {0}", "sort"))
        return v
    if k in ("archived", "checklist", "dep_shift", "tickets"):
        return 1 if v else 0
    if k == "kind":
        if v not in LIST_KINDS and v not in LIST_KIND_ALIASES:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        return LIST_KIND_ALIASES.get(v, v)
    if k == "nag":  # 2.7.0 (#413): the list's default for nags ('' / 'off' = none)
        v = "" if v in (None, "off") else v
        if v not in NAG_VALUES:
            raise BadInput(tr("Invalid value: {0}", tr("Repeat reminder")))
        return v
    if k == "family":  # 2.19.0 (#653)
        v = v or ""
        if v not in FAM_LIST_KINDS:
            raise BadInput(tr("Invalid value: {0}", "family"))
        return v
    if k == "life":  # 2.22.0 (#663)
        from ..life.model import LIFE_LIST_KINDS
        v = v or ""
        if v not in LIFE_LIST_KINDS:
            raise BadInput(tr("Invalid value: {0}", "life"))
        return v
    if k == "trip":
        from ..life.model import _dump, clean_trip
        t = clean_trip(v)
        return _dump(t) if t else ""
    return v


@app.post("/api/lists")
def list_create():
    from ..lists.groups import grp_touch
    from ..tasks.tasks import WEB_LIST_NEW
    from ..personal.timetrack import web_fields
    from ..lists.templates import ptype_create
    from ..family.family import fam_list_create
    b = web_fields(body(), WEB_LIST_NEW, "POST /api/lists")
    name = clean_list_value("name", b.get("name"))
    color, folder = clean_color(b.get("color", "")), clean_folder(b.get("folder", ""))
    if b.get("ptype"):  # 2.4.0 (#243): a project of a built-in type (sections, fields, view, ticket types, modules)
        c = db()
        if "sections" in b and not isinstance(b["sections"], bool):
            return err(tr("Invalid value: {0}", "sections"))
        from ..accounts.orgs import clean_org_id, ws_default_org
        oid = clean_org_id(c, b["org_id"], me()) if "org_id" in b else ws_default_org(c, me(), folder)  # 2.28.0 (#935)
        lid, on = ptype_create(c, me(), b["ptype"], name, folder, color, sections=b.get("sections") is True, org_id=oid)  # 2.27.0 (#972)
        bump(c)
        c.commit()
        return jsonify({**dict(c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()), "modules_on": on})
    view = clean_list_value("view", b.get("view") or "list")
    kind = clean_list_value("kind", b["kind"]) if b.get("kind") else "list"
    fam = clean_list_value("family", b.get("family"))  # 2.19.0 (#653)
    if fam and kind == "project":  # 2.26.0: a project is never a family list
        return err(tr("A project cannot be a family list"))
    if fam:
        c = db()
        lid = fam_list_create(c, me(), fam, name, folder)
        if color:
            c.execute("UPDATE lists SET color=? WHERE id=?", (color, lid))
        bump(c)
        c.commit()
        return jsonify(dict(c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()))
    # 2.7.2 (#414): "Show completed at the bottom" (done_at_bottom; the old checklist flag / kind "checklist" are aliases)
    dab = 1 if b.get("done_at_bottom", b.get("checklist")) or b.get("kind") == "checklist" else 0
    c = db()
    uid = me()
    srt = my_max_sort(c, uid) + 1
    from ..accounts.orgs import clean_org_id, ws_default_org
    oid = clean_org_id(c, b["org_id"], uid) if "org_id" in b else ws_default_org(c, uid, folder)  # 2.28.0 (#935): the workspace
    g.list_keep = ("org_id",) if "org_id" in b else ()  # 2.29.0 (#1030): an explicit workspace beats the folder's default
    # 2.2.1 (#359): dep_shift ("Move dependent tasks along") is taken at creation too (before, only PATCH set it)
    cur = c.execute("INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,checklist,kind,dep_shift,tickets,org_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (name, color, folder, srt, view, iso(now_utc()), uid, dab, kind,
                     clean_list_value("dep_shift", b.get("dep_shift")), clean_list_value("tickets", b.get("tickets")), oid))
    list_created(c, uid, cur.lastrowid)  # 2.4.2 (#391) agents, 2.10.0 (#441) groups, 2.22.0 (#740) / 2.25.0 (#931) folder people
    bump(c)
    c.commit()
    return jsonify(dict(c.execute("SELECT * FROM lists WHERE id=?", (cur.lastrowid,)).fetchone()))


@app.patch("/api/lists/<int:lid>")
def list_update(lid):
    from ..lists.groups import grp_touch
    from ..tasks.validation import clean_ticket_tpl
    from ..tasks.tasks import WEB_LIST_EDIT
    from ..tasks.lifecycle import _norm
    from ..personal.timetrack import BadInput, clean_day_hours, web_fields
    from ..lists.templates import list_ptype_set
    from ..agents.core import list_listen_update
    from ..collab.reactions import list_tidy_update
    from ..lists.folders import folder_list_arrived, list_own_mark
    b = web_fields(body(), WEB_LIST_EDIT, "PATCH /api/lists/{lid}")
    c = db()
    role = need_list(c, lid, write=False)
    given = set(b)  # 2.29.0 (#1030): what this request sets on its own (kept when the list moves into a folder)
    tidy0 = c.execute("SELECT agent_tidy, agent_members, agent_peers, folder FROM lists WHERE id=?", (lid,)).fetchone()
    if "agent_tidy" in b or "tidy_agent_id" in b:  # 2.0.0: "Agent may tidy up entries" (own permission rule, see
        # list_tidy_update); 2.4.1 (#379): "Tidy up by" (the one agent)
        e = list_tidy_update(c, lid, b.get("agent_tidy"), b.get("tidy_agent_id"), "tidy_agent_id" in b)
        if e:
            return err(e, 409)
        b = {k: v for k, v in b.items() if k not in ("agent_tidy", "tidy_agent_id")}
    if "listen_agent_ids" in b:  # 2.13.1 (#471)
        try:
            list_listen_update(c, lid, b["listen_agent_ids"])
        except BadInput as e:
            return err(str(e))
        b = {k: v for k, v in b.items() if k != "listen_agent_ids"}
    if b.get("family"):  # 2.26.0: a project is never a family list (an existing value stays untouched)
        knd = b.get("kind") or c.execute("SELECT kind FROM lists WHERE id=?", (lid,)).fetchone()[0]
        if knd == "project":
            return err(tr("A project cannot be a family list"))
    if "agent_members" in b or "agent_peers" in b:  # 2.26.0 (#928)
        from ..agents.core import list_agent_access_update
        try:
            list_agent_access_update(c, lid, b)
        except BadInput as e:
            return err(str(e))
        b = {k: v for k, v in b.items() if k not in ("agent_members", "agent_peers")}
    if "client_id" in b:  # 2.23.0 (#463): the client of the list (owner / list admins, a client they see)
        from ..team.clients import list_client_set
        try:
            list_client_set(c, lid, b["client_id"])
        except BadInput as e:
            return err(str(e))
        b = {k: v for k, v in b.items() if k != "client_id"}
    if "org_id" in b:  # 2.28.0 (#935): the workspace of the list (owner only; members / agents must fit)
        from ..accounts.orgs import list_org_set
        if list_org_set(c, lid, b["org_id"]):  # Denied 403 / 409
            list_own_mark(c, lid, "org_id")  # 2.29.0 (#1030): differs from its folder from now on
        b = {k: v for k, v in b.items() if k != "org_id"}
    if "sort_mode" in b:  # 2.27.0 (#988): the list's sort, the same for every member (owner / list admins)
        if role not in MANAGE_ROLES:
            return err(tr("Only the owner and list admins can change the sort of this list"), 403)
        sm = b["sort_mode"]
        if not isinstance(sm, str) or not (sm in LIST_SORTS or re.fullmatch(LIST_SORT_RE, sm)):
            return err(tr("Invalid value: {0}", "sort_mode"))
        c.execute("UPDATE lists SET sort_mode=? WHERE id=?", (sm, lid))
        b = {k: v for k, v in b.items() if k != "sort_mode"}
    if "columns" in b:  # 2.14.0 (#425): the list's columns, the same for every member (owner / list admins)
        if role not in MANAGE_ROLES:
            return err(tr("Only the owner and list admins can change the shown fields"), 403)
        try:
            c.execute("UPDATE lists SET col_cfg=? WHERE id=?", (clean_columns(c, lid, b["columns"]), lid))
        except BadInput as e:
            return err(str(e))
        b = {k: v for k, v in b.items() if k != "columns"}
    conflicts = []
    prev = b.get("_prev") if isinstance(b.get("_prev"), dict) else None
    if prev:  # D4 undo / redo: a setting changed elsewhere meanwhile stays (reported in conflicts)
        cur = dict(c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone())
        if role != "owner":
            m = c.execute("SELECT folder, sort, view FROM list_members WHERE list_id=? AND user_id=?", (lid, me())).fetchone()
            if m:
                cur.update(folder=m["folder"], sort=m["sort"], view=m["view"] or cur["view"])
        b = dict(b)
        for k, old in prev.items():
            if k in b and k in (*LIST_FIELDS, "rate", "ptype") and _norm(cur.get(k)) != _norm(old) and _norm(cur.get(k)) != _norm(b[k]):
                conflicts.append({"field": k, "server": cur.get(k), "mine": b[k]})
                del b[k]
    pt_out = {}
    if "ptype" in b:  # 2.18.0 (#408): the project type of an existing list (owner / list admins), see list_ptype_set
        try:
            pt_out = list_ptype_set(c, lid, role, b["ptype"], skip=set(b) | (given & {"listen_agent_ids"}))
        except BadInput as e:
            return err(str(e))
        except Denied as e:
            return err(tr("Only the owner and list admins can change the project type"), e.code)
        b = {k: v for k, v in b.items() if k != "ptype"}
    if "done_at_bottom" in b:  # 2.7.2 (#414): the API name of the display option (column checklist)
        b = {**{k: v for k, v in b.items() if k != "done_at_bottom"}, "checklist": b["done_at_bottom"]}
    vals = {k: clean_list_value(k, b[k], member=role != "owner") for k in LIST_FIELDS if k in b}  # BadInput: 400
    if b.get("kind") == "checklist" and "checklist" not in vals:  # deprecated alias: a plain list with the option on
        vals["checklist"] = 1
    if role == "owner":
        if vals.get("family") or vals.get("life"):  # 2.28.0 (#935): "Used for" / Home & life make the list private (409 with an organisation agent in it)
            from ..accounts.orgs import ws_private_for
            ws_private_for(c, lid)
        if "archived" in vals:  # 1.6.1: archived_at follows the flag (set on the change to archived, cleared on restore)
            c.execute("UPDATE lists SET archived_at=CASE WHEN ?=0 THEN NULL WHEN archived=0 THEN ? ELSE archived_at END "
                      "WHERE id=?", (vals["archived"], iso(now_utc()), lid))
        for k in LIST_FIELDS:
            if k in vals:
                c.execute(f"UPDATE lists SET {k}=? WHERE id=?", (vals[k], lid))
        if vals.get("life") == "health":  # 2.22.0 (#663): a health list is never shared with an agent
            c.execute("DELETE FROM list_members WHERE list_id=? AND user_id IN (SELECT id FROM users WHERE kind='agent')", (lid,))
        # 2.22.0 (#747): a list that becomes a shopping list gets no shop areas by itself any more ("Add shop areas")
        if "rate" in b:  # hourly rate for the time reports (None / '' = none)
            try:
                rate = None if b["rate"] in (None, "") else round(float(str(b["rate"]).replace(",", ".")), 2)
            except ValueError:
                return err(tr("Hourly rate: number expected"))
            if rate is not None and not 0 <= rate <= 1e6:
                return err(tr("Hourly rate: number expected"))
            c.execute("UPDATE lists SET rate=? WHERE id=?", (rate, lid))
        if "ticket_tpl" in b:  # 2.4.0 (#340): {bug?, feature?} note templates of new tickets ('' / missing = built-in)
            c.execute("UPDATE lists SET ticket_tpl=? WHERE id=?", (clean_ticket_tpl(b["ticket_tpl"]), lid))
        if "day_hours" in b:  # 2.7.0 (#407): hours per day / shift of this list (None / '' = the instance's value)
            dh = clean_day_hours(b["day_hours"])
            if dh is False:
                return err(tr("Hours per day: a number from 1 to 24"))
            c.execute("UPDATE lists SET day_hours=? WHERE id=?", (dh, lid))
        if "folder" in vals:
            grp_touch(c, me())  # 2.10.0 (#441): moved into / out of a folder shared with a group
            folder_autoshare(c, lid)  # 2.22.0 (#740): moved into a folder shared with people
            if vals["folder"] != (tidy0["folder"] if tidy0 else None):  # really moved (the dialog sends the folder with every save)
                folder_list_arrived(c, lid, keep=tuple(k for k in ("org_id", "agent_tidy", "agent_members", "agent_peers") if k in given)
                                    + (("agent_listen",) if "listen_agent_ids" in given else ()))
    else:
        if "rate" in b or "ticket_tpl" in b or "day_hours" in b or any(k in b for k in LIST_FIELDS if k not in MEMBER_LIST_FIELDS):
            return err(tr("Only the owner can change this list"), 403)
        for k in MEMBER_LIST_FIELDS:
            if k in vals:
                c.execute(f"UPDATE list_members SET {k}=? WHERE list_id=? AND user_id=?", (vals[k], lid, me()))
    if tidy0:  # 2.29.0 (#1030): a tidy / agent access setting changed on its own differs from its folder from now on
        now = c.execute("SELECT agent_tidy, agent_members, agent_peers FROM lists WHERE id=?", (lid,)).fetchone()
        for k in ("agent_tidy", "agent_members", "agent_peers"):
            if k in given and (now[k] or 0) != (tidy0[k] or 0) and vals.get("folder", tidy0["folder"]) == tidy0["folder"]:
                list_own_mark(c, lid, k)
        if "listen_agent_ids" in given and vals.get("folder", tidy0["folder"]) == tidy0["folder"]:  # 2.30.0 (#1034)
            list_own_mark(c, lid, "agent_listen")
    bump(c)
    c.commit()
    return jsonify(ok=True, conflicts=conflicts, **pt_out)


@app.post("/api/lists/reorder")
def list_reorder():
    """{ids: [...], folder?: {id: name}, _prev?: {ids, folder}} -- sidebar order after a drag / arrow move (per user).
    D4 undo / redo: with _prev the order is only applied while it is still _prev.ids, and a list's folder only while it is
    still _prev.folder[id]; what changed elsewhere meanwhile stays and is reported in conflicts."""
    from ..lists.groups import grp_touch
    b = body()
    c = db()
    uid = me()
    conflicts = []
    prev = b.get("_prev") if isinstance(b.get("_prev"), dict) else None
    if prev:
        mine = sorted((d for d in visible_lists(c, uid) if not d["is_inbox"]), key=lambda d: (d["sort"] or 0, d["id"]))
        folders = {str(d["id"]): d["folder"] or "" for d in mine}
        try:
            want = [int(x) for x in prev.get("ids") or []]
            order = [int(x) for x in b.get("ids") or []]
        except (TypeError, ValueError):
            return err(tr("Invalid data"))
        now_ids = [d["id"] for d in mine if d["id"] in set(want)]
        if "ids" in prev and (now_ids != want or sorted(order) != sorted(want)):
            conflicts.append({"field": "order", "server": now_ids, "mine": order})
            b = {k: v for k, v in b.items() if k != "ids"}
        pf = prev.get("folder") if isinstance(prev.get("folder"), dict) else {}
        fm = dict(b.get("folder") or {}) if isinstance(b.get("folder"), dict) else b.get("folder")
        if isinstance(fm, dict):
            for k in list(fm):
                if str(k) in pf and folders.get(str(k)) != (pf[str(k)] or "") and folders.get(str(k)) != (fm[k] or ""):
                    conflicts.append({"field": "folder", "id": int(k), "server": folders.get(str(k)), "mine": fm[k]})
                    del fm[k]
            b = {**b, "folder": fm}
    for i, lid in enumerate(b.get("ids", [])):
        c.execute("UPDATE lists SET sort=? WHERE id=? AND is_inbox=0 AND owner_id=?", (i, int(lid), uid))
        c.execute("UPDATE list_members SET sort=? WHERE list_id=? AND user_id=?", (i, int(lid), uid))
    fmap = b.get("folder") or {}
    if not isinstance(fmap, dict):
        return err(tr("Invalid value: {0}", tr("Folder")))
    moved = []
    for lid, folder in fmap.items():
        folder = clean_folder(folder)
        if c.execute("UPDATE lists SET folder=? WHERE id=? AND owner_id=? AND folder!=?", (folder, int(lid), uid, folder)).rowcount:
            moved.append(int(lid))
        c.execute("UPDATE list_members SET folder=? WHERE list_id=? AND user_id=?", (folder, int(lid), uid))
    if fmap:
        grp_touch(c, uid)  # 2.10.0 (#441)
    if moved:  # 2.29.0 (#1030 / #929): dragged into a folder: its people (as the list dialog did) and its defaults
        from ..lists.folders import folder_list_arrived
        for lid in moved:
            folder_autoshare(c, lid)
            folder_list_arrived(c, lid)
    bump(c)
    c.commit()
    return jsonify(ok=True, conflicts=conflicts)


@app.delete("/api/lists/<int:lid>")
def list_delete(lid):
    from ..lists.projects import list_files_drop
    c = db()
    need_list(c, lid, owner=True)
    r = c.execute("SELECT is_inbox, archived FROM lists WHERE id=?", (lid,)).fetchone()
    if r["is_inbox"]:
        return err(tr("The inbox cannot be deleted"))
    # 1.5 (UX1): deleting for good only from the archive; "Delete" in the app archives (undoable) first
    if not r["archived"]:
        return err(tr("Archive the list first: only archived lists can be deleted for good"), 409)
    # tasks go to the trash inside the owner's inbox so they stay restorable
    inbox = my_inbox(c)
    ts = iso(now_utc())
    c.execute("UPDATE tasks SET deleted_at=COALESCE(deleted_at,?), list_id=?, section_id=NULL, assignee_id=NULL WHERE list_id=?",
              (ts, inbox, lid))
    icon = c.execute("SELECT icon FROM lists WHERE id=?", (lid,)).fetchone()[0]
    lfiles = [r[0] for r in c.execute("SELECT path FROM list_files WHERE list_id=?", (lid,))]  # 2.7.1 (#410)
    c.execute("DELETE FROM lists WHERE id=?", (lid,))
    bump(c)
    c.commit()
    list_icon_drop_file(lid, icon)
    list_files_drop(lfiles)
    return jsonify(ok=True)


def _agent_bridge_blocks(c, lid, uid):
    from ..agents.safety import bridge_blocks
    return bridge_blocks(c, lid, uid)


@app.put("/api/lists/<int:lid>/members")
def member_set(lid):
    """{user_id, role: admin|edit|participant|view} -- the owner or a list admin shares the list (or changes a member's
    role). The owner is no member row: nobody can change or remove the owner."""
    from ..lists.groups import role_max
    from ..collab.comments import user_names
    from ..collab.news import list_push, news_add
    from ..integrations.webhooks import wh_note_list
    from ..agents.admin import personal_agent_foreign
    from ..family.family import is_kid
    need_collab()
    b = body()
    c = db()
    need_list(c, lid, write=False, manage=True)
    if c.execute("SELECT is_inbox FROM lists WHERE id=?", (lid,)).fetchone()[0]:
        return err(tr("The inbox cannot be shared"))
    role = b.get("role", "edit")
    if role not in ROLES:
        return err(tr("Role must be admin, edit, participant or view"))
    if role == "admin" and c.execute("SELECT 1 FROM users WHERE id=? AND kind='agent'", (b.get("user_id"),)).fetchone():
        return err(tr("An agent cannot be a list admin"))
    if c.execute("SELECT 1 FROM users WHERE id=? AND kind='agent'", (b.get("user_id"),)).fetchone() and \
            c.execute("SELECT 1 FROM lists WHERE id=? AND life='health'", (lid,)).fetchone():  # 2.22.0 (#663)
        return err(tr("A health list is private: it cannot be shared with an agent"), 409)
    try:
        uid = int(b.get("user_id") or 0)
    except (TypeError, ValueError):
        uid = 0
    from ..accounts.orgs import may_see
    if b.get("email") and not uid:  # 2.22.0 (#752): share by e-mail address (mode "own contacts": no directory). The answer
        # never says whether the address has an account
        em = str(b["email"]).strip().lower()[:200]
        r = c.execute("SELECT id FROM users WHERE lower(email)=? AND disabled=0 AND COALESCE(kind,'user')!='agent'", (em,)).fetchone()
        from ..accounts.orgs import ws_member_problem
        if not r or r[0] == me() or r[0] == c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()[0] or \
                c.execute("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (lid, r[0])).fetchone() or \
                ws_member_problem(c, lid, r[0]) or _agent_bridge_blocks(c, lid, r[0]):  # 2.28.0 (#935): not of the list's workspace;
            # 2.30.0 (#919): would connect lists with different people through the list's agent -> nothing happens, nothing is revealed
            return jsonify(ok=True, by_email=True)
        uid = r[0]
    elif not may_see(c, me(), uid):
        return err(tr("unknown user"), 404)
    u = c.execute("SELECT id FROM users WHERE id=? AND disabled=0", (uid,)).fetchone()
    if not u or uid == me() or personal_agent_foreign(c, uid, me()):  # 2.7.2 (#420): only the owner shares with a personal agent
        return err(tr("unknown user"), 404)
    if uid == c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()[0]:
        return err(tr("The owner's role cannot be changed"), 403)
    from ..accounts.orgs import ws_check_member
    ws_check_member(c, lid, uid)  # 2.28.0 (#935): an organisation's list only inside it, agents only in their workspace (409)
    if not (b.get("email") and not b.get("user_id")):  # 2.30.0 (#919): no agent bridge between lists with different people
        from ..agents.safety import bridge_check  # (by e-mail address: skipped silently above, it must not reveal an account)
        bridge_check(c, lid, uid, ok=b.get("bridge_ok") is True)
    if is_kid(c, uid):  # 2.19.0 (#653): a kid only ever takes part (sees what is assigned to it / where it comes along)
        role = "participant"
    lname = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0]
    old = c.execute("SELECT role, grole FROM list_members WHERE list_id=? AND user_id=?", (lid, uid)).fetchone()
    if old:  # 2.10.0 (#441): the personal role; the effective one is the higher of it and the role via groups
        eff = role_max(role, old["grole"])
        c.execute("UPDATE list_members SET role=?, own_role=? WHERE list_id=? AND user_id=?", (eff, role, lid, uid))
        if old[0] != eff:
            news_add(c, uid, "role", list_id=lid, data={"role": eff, "old": old[0], "name": lname})
    else:
        from ..core.access import ONE_AGENT_MSG, list_other_agent
        if list_other_agent(c, lid, uid):  # 2.26.0: one agent per list
            return err(tr(ONE_AGENT_MSG), 409)
        c.execute("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,?,?)",
                  (lid, uid, role, role, my_max_sort(c, uid) + 1, iso(now_utc())))
        member_folder_adopt(c, lid, uid)  # 2.22.0 (#740)
        news_add(c, uid, "share", list_id=lid, data={"role": role, "name": lname})
        agent_share_skip(c, lid, uid, False)  # 2.4.2 (#391): shared again by hand -> "Share all" includes it again
        who = user_names(c, [me()]).get(me(), "?")
        list_push(c, uid, "share", lid, lambda lg: tr("{0} shared a list with you", who, lg=lg), lambda lg: lname)
        wh_note_list(lid, "list.shared", {"member_id": uid, "role": role})
        if c.execute("SELECT 1 FROM users WHERE id=? AND kind='agent'", (uid,)).fetchone():
            from ..admin.hosting import agent_joined_notice
            agent_joined_notice(c, lid, uid, me())  # 2.24.0 (#896)
    bump(c)
    c.commit()
    return jsonify(ok=True, **({"by_email": True} if b.get("email") and not b.get("user_id") else {}))


# ---- 2.22.0 (#740): a shared list lands with the other person in a folder of the same name as with its owner (created
# in their folder order when missing); they can move it freely afterwards (their placement is never overwritten again).
# A list without a folder stays without one.
def member_folder_adopt(c, lid, uid, force=False):
    r = c.execute("SELECT folder FROM lists WHERE id=?", (lid,)).fetchone()
    f = clean_folder(r[0], strict=False) if r and r[0] else ""
    if not f:
        return False
    only_empty = "" if force else " AND COALESCE(folder, '')=''"
    n = c.execute("UPDATE list_members SET folder=? WHERE list_id=? AND user_id=?" + only_empty, (f, lid, uid)).rowcount
    if n:
        fl = json.loads(usettings(c, uid).get("folders") or "[]")
        want = [x for x in ([f.split(FOLDER_SEP)[0]] if FOLDER_SEP in f else []) + [f] if x not in fl]
        if want:
            uset(c, uid, "folders", json.dumps(fl + want, ensure_ascii=False))
    return bool(n)


def _folder_member_add(c, lid, uid, role, actor):
    """A share made by "Share folder" (no push per list, one News item each, the folder of the owner)."""
    from ..collab.news import news_add
    from ..family.family import is_kid
    from ..agents.core import is_agent
    u = c.execute("SELECT * FROM users WHERE id=? AND disabled=0", (uid,)).fetchone()
    l = c.execute("SELECT name, life, is_inbox, owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not u or not l or l["is_inbox"] or l["owner_id"] == uid or (is_agent(u) and l["life"] == "health"):
        return False
    if c.execute("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (lid, uid)).fetchone():
        return False
    from ..core.access import list_other_agent
    if list_other_agent(c, lid, uid):  # 2.26.0: one agent per list (the list is skipped)
        return False
    from ..accounts.orgs import ws_member_problem
    if ws_member_problem(c, lid, uid):  # 2.28.0 (#935): not of the list's workspace (the list is skipped)
        return False
    from ..agents.safety import bridge_blocks
    if bridge_blocks(c, lid, uid):  # 2.30.0 (#919): would connect lists with different people through an agent (skipped)
        return False
    role = "participant" if is_kid(c, uid) else role
    if role == "admin" and is_agent(u):  # 2.29.0: an agent is never a list admin (as in member_set)
        role = "edit"
    c.execute("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,?,?)",
              (lid, uid, role, role, my_max_sort(c, uid) + 1, iso(now_utc())))
    member_folder_adopt(c, lid, uid)
    news_add(c, uid, "share", list_id=lid, data={"role": role, "name": l["name"]}, actor=actor)
    if is_agent(u):
        from ..admin.hosting import agent_joined_notice
        agent_joined_notice(c, lid, uid, actor)  # 2.24.0 (#896)
    return True


def _in_folder(path, f):
    return bool(f) and (path == f or path.startswith(f + FOLDER_SEP))


def folder_autoshare(c, lid):
    """A list of an owner came into one of their shared folders (created there, moved there): the folder's people get it."""
    r = c.execute("SELECT owner_id, folder FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or not r["folder"] or not collab_all():
        return 0
    return sum(1 for fp in c.execute("SELECT * FROM folder_people WHERE owner_id=?", (r["owner_id"],)).fetchall()
               if _in_folder(r["folder"], fp["folder"]) and _folder_member_add(c, lid, fp["user_id"], fp["role"], r["owner_id"]))


@app.get("/api/folders/people")
def folder_people_get():
    """?folder=: the people my folder is shared with."""
    from flask import request
    c = db()
    f = clean_folder(request.args.get("folder") or "", strict=False)
    return jsonify(people=[{"user_id": r[0], "role": r[1]} for r in
                           c.execute("SELECT user_id, role FROM folder_people WHERE owner_id=? AND folder=? ORDER BY created_at", (me(), f))])


@app.put("/api/folders/people")
def folder_people_put():
    """{folder, user_id, role?}: share my folder with a person: every list in it (and its subfolders) now, and every list
    that comes into it later (DELETE stops that; the lists stay shared)."""
    from ..agents.admin import personal_agent_foreign
    need_collab()
    c, b = db(), body()
    f = clean_folder(b.get("folder") or "")
    role = b.get("role", "edit")
    if not f or role not in ROLES:  # 2.29.0 (#929): admin too (list admins of every list in the folder)
        return err(tr("Invalid value: {0}", "folder" if not f else "role"))
    try:
        uid = int(b.get("user_id") or 0)
    except (TypeError, ValueError):
        uid = 0
    from ..accounts.orgs import may_see
    if not c.execute("SELECT 1 FROM users WHERE id=? AND disabled=0", (uid,)).fetchone() or uid == me() or personal_agent_foreign(c, uid, me()) \
            or not may_see(c, me(), uid):  # 2.22.0 (#752)
        return err(tr("unknown user"), 404)
    from ..agents.core import is_agent
    if role == "admin" and is_agent(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()):
        return err(tr("An agent cannot be a list admin"))
    prev = c.execute("SELECT role FROM folder_people WHERE owner_id=? AND folder=? AND user_id=?", (me(), f, uid)).fetchone()
    c.execute("INSERT INTO folder_people(owner_id,folder,user_id,role,created_at) VALUES(?,?,?,?,?) ON CONFLICT(owner_id,folder,user_id) "
              "DO UPDATE SET role=excluded.role", (me(), f, uid, role, iso(now_utc())))
    from ..core.access import ONE_AGENT_MSG, list_other_agent
    rows = [r for r in c.execute("SELECT id, name, folder FROM lists WHERE owner_id=? AND archived=0 AND is_inbox=0", (me(),)).fetchall()
            if _in_folder(r["folder"], f)]
    # 2.26.0: one agent per list -- lists that already have another agent are skipped and named in the answer
    skipped = [{"id": r["id"], "name": r["name"]} for r in rows if list_other_agent(c, r["id"], uid)
               and not c.execute("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (r["id"], uid)).fetchone()]
    n = sum(1 for r in rows if _folder_member_add(c, r["id"], uid, role, me()))
    # 2.29.0 (#929): a changed folder role reaches the lists in it where the person is already in (their personal share;
    # a role via a group stays the higher one, as everywhere)
    upd = 0
    # only a CHANGED folder role is carried into the lists (a first share keeps roles set per list by hand)
    if prev and prev[0] != role and b.get("apply", True) is not False:
        from ..family.family import is_kid
        r2 = "participant" if is_kid(c, uid) else role
        for r in rows:
            upd += c.execute("""UPDATE list_members SET own_role=?, role=CASE WHEN grole IS NOT NULL AND
                                  (CASE grole WHEN 'admin' THEN 4 WHEN 'edit' THEN 3 WHEN 'participant' THEN 2 ELSE 1 END) >
                                  (CASE ? WHEN 'admin' THEN 4 WHEN 'edit' THEN 3 WHEN 'participant' THEN 2 ELSE 1 END) THEN grole ELSE ? END
                                WHERE list_id=? AND user_id=? AND COALESCE(own_role, role)!=?""", (r2, r2, r2, r["id"], uid, r2)).rowcount
    bump(c)
    c.commit()
    return jsonify(shared=n, updated=upd, **({"skipped": skipped, "skipped_reason": tr(ONE_AGENT_MSG)} if skipped else {}))


@app.delete("/api/folders/people")
def folder_people_delete():
    """{folder, user_id, remove?}: new lists of the folder are no longer shared with that person; 2.29.0 (#929) remove: true
    also takes them out of the folder's lists now (like removing them from each list; a share via a group stays)."""
    from ..api.v1 import V1Error, v1_call
    c, b = db(), body()
    f = clean_folder(b.get("folder") or "", strict=False)
    try:
        uid = int(b.get("user_id") or 0)
    except (TypeError, ValueError):
        uid = 0
    c.execute("DELETE FROM folder_people WHERE owner_id=? AND folder=? AND user_id=?", (me(), f, uid))
    n = 0
    if b.get("remove") is True and f and uid and uid != me():
        c.commit()
        for r in c.execute("SELECT id, folder FROM lists WHERE owner_id=? AND is_inbox=0", (me(),)).fetchall():
            if _in_folder(r["folder"], f) and c.execute("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (r["id"], uid)).fetchone():
                try:
                    v1_call(member_remove, r["id"], uid)
                    n += 1
                except V1Error:
                    pass
    bump(c)
    c.commit()
    return jsonify(ok=True, removed=n)


# ---- 2.4.2 (#391): sharing with an agent in bulk. Per person and agent (user setting agent_share, server-only):
# "Share all existing lists" (POST /api/agents/<aid>/share-all) shares every list the person OWNS (never the inbox,
# archived lists or lists they only manage) with role edit, except the lists they stopped sharing with that agent in
# the table (skip); "Share new lists automatically" (PUT /api/agents/<aid>/autoshare {on}) adds the agent (role edit)
# to every list the person creates from then on. The web app asks first (the agent then sees private lists too).
def agent_share_get(c, uid):
    try:
        d = json.loads(usettings(c, uid).get("agent_share") or "{}")
    except ValueError:
        d = {}
    if not isinstance(d, dict):
        d = {}
    auto = [int(x) for x in d.get("auto", []) if isinstance(x, int) or (isinstance(x, str) and x.isdigit())]
    skip = {str(k): [int(x) for x in v if isinstance(x, int)] for k, v in (d.get("skip") or {}).items()
            if str(k).isdigit() and isinstance(v, list)}
    return {"auto": sorted(set(auto)), "skip": skip}


def agent_share_put(c, uid, d):
    d = {"auto": sorted(set(d.get("auto", []))), "skip": {k: sorted(set(v))[-2000:] for k, v in d.get("skip", {}).items() if v}}
    uset(c, uid, "agent_share", json.dumps(d, separators=(",", ":")))


def agent_share_skip(c, lid, uid, on):
    """The list owner shared (on=False) or stopped sharing (on=True) list lid with agent uid by hand."""
    r = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or not c.execute("SELECT 1 FROM users WHERE id=? AND kind='agent'", (uid,)).fetchone():
        return
    d = agent_share_get(c, r[0])
    cur = set(d["skip"].get(str(uid), []))
    new = cur | {lid} if on else cur - {lid}
    if new != cur:
        d["skip"][str(uid)] = sorted(new)
        agent_share_put(c, r[0], d)


def agent_share_add(c, lid, aid, actor):
    """Share list lid with agent aid (role edit) like PUT /api/lists/<lid>/members; False if it was a member already."""
    from ..collab.news import news_add
    from ..integrations.webhooks import wh_note_list
    from ..core.access import list_other_agent
    from ..accounts.orgs import ws_member_problem
    if c.execute("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (lid, aid)).fetchone() or \
            c.execute("SELECT 1 FROM lists WHERE id=? AND life='health'", (lid,)).fetchone() or \
            list_other_agent(c, lid, aid) or ws_member_problem(c, lid, aid):  # 2.22.0 (#663) health; 2.26.0: one agent per list; 2.28.0: workspace
        return False
    from ..agents.safety import bridge_blocks
    if bridge_blocks(c, lid, aid):  # 2.30.0 (#919): a list with other people than the agent's other lists (skipped)
        return False
    lname = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0]
    c.execute("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,?,?)",
              (lid, aid, "edit", "edit", my_max_sort(c, aid) + 1, iso(now_utc())))
    news_add(c, aid, "share", list_id=lid, data={"role": "edit", "name": lname}, actor=actor)
    wh_note_list(lid, "list.shared", {"member_id": aid, "role": "edit"})
    from ..admin.hosting import agent_joined_notice
    agent_joined_notice(c, lid, aid, actor)  # 2.24.0 (#896)
    return True


def agent_autoshare(c, uid, lid):
    """A list uid just created: share it with the agents uid chose for "Share new lists automatically" (#391)."""
    if not collab_all():
        return
    r = c.execute("SELECT owner_id, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or r["is_inbox"] or r["owner_id"] != uid:
        return
    auto = agent_share_get(c, uid)["auto"]
    for aid in auto:
        if aid != uid and c.execute("SELECT 1 FROM users WHERE id=? AND kind='agent' AND disabled=0", (aid,)).fetchone():
            agent_share_add(c, lid, aid, uid)


def agent_share_target(c, aid):
    from ..agents.admin import personal_agent_foreign
    need_collab()
    u = c.execute("SELECT kind FROM users WHERE id=?", (me(),)).fetchone()
    if not u or u["kind"] == "agent":
        raise Denied(403)
    if not c.execute("SELECT 1 FROM users WHERE id=? AND kind='agent' AND disabled=0", (aid,)).fetchone() or personal_agent_foreign(c, aid, me()):
        raise Denied(404, tr("unknown user"))


@app.get("/api/agents/<int:aid>/share")
def agent_share_state(aid):
    """How I share with agent aid: auto (new lists) + how many of my own lists it does not see yet (share-all would add)."""
    c = db()
    agent_share_target(c, aid)
    d = agent_share_get(c, me())
    return jsonify(auto=aid in d["auto"], **agent_share_counts(c, aid, d))


def agent_share_counts(c, aid, d):
    skip = set(d["skip"].get(str(aid), []))
    # 2.26.0: a list that already has another agent is not "missing" (one agent per list)
    rows = c.execute("""SELECT l.id, EXISTS(SELECT 1 FROM list_members m WHERE m.list_id=l.id AND m.user_id=?) AS has,
                        EXISTS(SELECT 1 FROM list_members m JOIN users u ON u.id=m.user_id WHERE m.list_id=l.id AND u.kind='agent'
                               AND m.user_id!=?) AS other
                        FROM lists l WHERE l.owner_id=? AND l.is_inbox=0 AND COALESCE(l.archived,0)=0""", (aid, aid, me())).fetchall()
    return {"own": len(rows), "shared": sum(1 for r in rows if r["has"]),
            "missing": sum(1 for r in rows if not r["has"] and not r["other"] and r["id"] not in skip),
            "skipped": sum(1 for r in rows if not r["has"] and r["id"] in skip)}


@app.put("/api/lists/<int:lid>/agent")
def list_agent_set(lid):
    """2.26.0: {agent_id: int | null, role?} -- THE agent of list lid (one agent per list): removes the current agent
    member (if another) and shares the list with the new one in one step; null = no agent. Owner / list admins.
    Answers {previous: id | null, agent_id} so the client can offer Undo."""
    from ..api.v1 import v1_call
    from ..agents.core import agent_ids
    need_collab()
    c, b = db(), body()
    role = need_list(c, lid, write=False)
    if role not in MANAGE_ROLES:
        raise Denied(403)
    new = b.get("agent_id")
    if new is not None and (isinstance(new, bool) or not isinstance(new, int) or new not in agent_ids(c)):
        return err(tr("Invalid value: {0}", "agent_id"))
    lr = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if lr["owner_id"] in agent_ids(c):
        return err(tr("The list belongs to an agent"), 409)
    cur = [r[0] for r in c.execute("SELECT m.user_id FROM list_members m JOIN users u ON u.id=m.user_id WHERE m.list_id=? AND u.kind='agent' "
                                   "ORDER BY m.user_id", (lid,))]
    if new is not None and new in cur:
        return jsonify(previous=new, agent_id=new)
    if new is not None:  # 2.30.0 (#919): checked before the old agent leaves (409 agent_bridge; bridge_ok confirms)
        from ..agents.safety import bridge_check
        bridge_check(c, lid, new, ok=b.get("bridge_ok") is True)
    for old in cur:
        v1_call(member_remove, lid, old)
    if new is not None:
        v1_call(member_set, lid, body={"user_id": new, "role": b.get("role") or "edit", "bridge_ok": b.get("bridge_ok") is True})
    if not g.get("folder_applying") and lr["owner_id"] == me():  # 2.29.0 (#1030): chosen for this list itself
        from ..lists.folders import list_own_mark
        list_own_mark(c, lid, "agent_id")
        c.commit()
    return jsonify(previous=cur[0] if cur else None, agent_id=new)


@app.post("/api/agents/<int:aid>/share-all")
def agent_share_all(aid):
    """Share every own list (not the inbox, not archived, not the ones unshared by hand) with agent aid, role edit."""
    c = db()
    agent_share_target(c, aid)
    d = agent_share_get(c, me())
    skip = set(d["skip"].get(str(aid), []))
    from ..core.access import ONE_AGENT_MSG, list_other_agent
    from ..agents.safety import bridge_blocks
    n, other, bridged = 0, [], []
    for (lid, name) in c.execute("SELECT id, name FROM lists WHERE owner_id=? AND is_inbox=0 AND COALESCE(archived,0)=0 ORDER BY id",
                                 (me(),)).fetchall():
        if lid in skip:
            continue
        if agent_share_add(c, lid, aid, me()):
            n += 1
        elif list_other_agent(c, lid, aid) and not c.execute("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (lid, aid)).fetchone():
            other.append({"id": lid, "name": name})  # 2.26.0: one agent per list
        elif not c.execute("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (lid, aid)).fetchone() and bridge_blocks(c, lid, aid):
            bridged.append({"id": lid, "name": name})  # 2.30.0 (#919): other people than its other lists -> share it by hand
    bump(c)
    c.commit()
    return jsonify(added=n, **agent_share_counts(c, aid, d), **({"other_agent": other, "other_agent_reason": tr(ONE_AGENT_MSG)} if other else {}),
                   **({"bridge": bridged, "bridge_reason": tr("These lists have other people than the agent’s other lists: share them one by one to confirm it")} if bridged else {}))


def list_created(c, uid, lid, agents=True):
    """2.25.0 (#931): everything a NEW list of uid gets, on every path that creates one (the list dialog, project types and
    templates, an agent's briefing, imports, family and life lists): the agents of "Share new lists automatically",
    the groups of a shared folder and the people of a shared folder (before, only the list dialog did all three)."""
    from ..lists.groups import grp_touch
    from ..lists.folders import folder_list_arrived, folder_member_created
    if agents:
        agent_autoshare(c, uid, lid)
    grp_touch(c, uid)
    folder_autoshare(c, lid)
    # 2.29.0 (#1030 / #929): the folder's defaults (workspace, agent, tidy ...) and, in a folder shared with uid, its owner +
    # people (the list stays uid's)
    folder_list_arrived(c, lid, keep=g.pop("list_keep", ()) if has_request_context() else ())
    folder_member_created(c, uid, lid)


@app.put("/api/agents/<int:aid>/autoshare")
def agent_autoshare_set(aid):
    """{on: bool}: share my new lists with agent aid automatically (role edit)."""
    b = body()
    if not isinstance(b.get("on"), bool):
        return err(tr("Invalid value: {0}", "on"))
    c = db()
    agent_share_target(c, aid)
    d = agent_share_get(c, me())
    d["auto"] = sorted(set(d["auto"]) | {aid}) if b["on"] else [x for x in d["auto"] if x != aid]
    agent_share_put(c, me(), d)
    bump(c)
    c.commit()
    return jsonify(auto=b["on"])


@app.delete("/api/lists/<int:lid>/members/<int:uid>")
def member_remove(lid, uid):
    """The owner or a list admin removes a member, or a member leaves (uid = self)."""
    from ..collab.news import news_add
    need_collab()
    c = db()
    role = need_list(c, lid, write=False)
    if uid != me() and role not in MANAGE_ROLES:
        raise Denied(403)
    mr = c.execute("SELECT grole FROM list_members WHERE list_id=? AND user_id=?", (lid, uid)).fetchone()
    if not mr:
        return err(tr("unknown"), 404)
    if mr["grole"]:  # 2.10.0 (#441): access via a group stays; only the personal share goes
        c.execute("UPDATE list_members SET own_role=NULL, role=grole WHERE list_id=? AND user_id=?", (lid, uid))
        bump(c)
        c.commit()
        return jsonify(ok=True, via_group=True)
    c.execute("DELETE FROM list_members WHERE list_id=? AND user_id=?", (lid, uid))
    c.execute("UPDATE tasks SET assignee_id=NULL WHERE list_id=? AND assignee_id=?", (lid, uid))
    c.execute("DELETE FROM task_field_values WHERE value=? AND field_id IN (SELECT id FROM list_fields WHERE list_id=? AND type='person')",
              (str(uid), lid))
    agent_share_skip(c, lid, uid, True)  # 2.4.2 (#391): unshared by hand -> "Share all" leaves it out
    if uid != me():  # removed by the owner (leaving on your own is no news for you)
        news_add(c, uid, "unshare", list_id=lid,
                 data={"name": c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0]})
    bump(c)
    c.commit()
    return jsonify(ok=True)
