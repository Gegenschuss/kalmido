"""2.35.0 (#1101): organisation admins manage the lists of their organisation (Settings > Workspaces > Lists of the
organisation): an overview without contents (name, owner, number of tasks, last change), archive / restore, delete for good
(only from the archive, confirmed with the list's name) and hand a list over to another person of the organisation.

Only lists that belong to the organisation (lists.org_id): private lists, private sharing and inboxes stay invisible and
untouchable; 2.39.1 (#1188): the overview only shows the ones shared with at least one more person. People only (agents 403, also with admin rights). Mode shared: no organisation, no function (404); mode
organisation: the instance admins are its admins (org_role); modes multi / workspaces: the organisation role admin.
The owner and the list's members get a News entry ("archived / deleted by admin X"), every action is logged in
org_list_log (the history of the dialog). 2.56.0 (#1795): and change a list's name, icon and colour (nothing else). App only (APP_ONLY in tests/parity_test.py: an organisation admin's work)."""
import json

from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, my_inbox
from ..accounts.orgs import _need_org_admin, user_orgs
from ..accounts.pictures import list_icon_url

OL_LOG_MAX = 50


def _ol_list(c, oid, lid):
    """The list lid of organisation oid (never an inbox), else 404 -- the same answer for a private list, another
    organisation's list and a list that does not exist."""
    lr = c.execute("SELECT * FROM lists WHERE id=? AND org_id=? AND is_inbox=0", (lid, oid)).fetchone()
    if not lr:
        raise Denied(404)
    return lr


def _ol_people(c, lr):
    """The people of a list (owner + members, never agents) -- who hears about an admin's action."""
    ids = [lr["owner_id"]] + [r[0] for r in c.execute(
        "SELECT m.user_id FROM list_members m JOIN users u ON u.id=m.user_id WHERE m.list_id=? AND COALESCE(u.kind,'user')!='agent'",
        (lr["id"],))]
    return list(dict.fromkeys(i for i in ids if i))


def _ol_log(c, oid, lr, action, to_id=None, detail=None):
    if detail is not None:  # 2.56.0 (#1795): what changed, old -> new (column detail, JSON)
        c.execute("INSERT INTO org_list_log(org_id,list_id,list_name,action,by_id,owner_id,to_id,created_at,detail) VALUES(?,?,?,?,?,?,?,?,?)",
                  (oid, lr["id"], lr["name"], action, me(), lr["owner_id"], to_id, iso(now_utc()), json.dumps(detail, ensure_ascii=False)))
        return
    c.execute("INSERT INTO org_list_log(org_id,list_id,list_name,action,by_id,owner_id,to_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
              (oid, lr["id"], lr["name"], action, me(), lr["owner_id"], to_id, iso(now_utc())))


def _ol_news(c, oid, lr, action, gone=False, to_name="", extra=None):
    from ..collab.news import news_add
    oname = (c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0]
    for uid in _ol_people(c, lr):
        news_add(c, uid, "orglist", list_id=None if gone else lr["id"],
                 data={"action": action, "name": lr["name"], "org": oname, **({"to": to_name} if to_name else {}), **(extra or {})})


def _ol_out(c, oid):
    from ..collab.comments import user_names
    # 2.39.1 (#1188): only lists of the organisation that are shared with at least one more person (people, not agents):
    # private lists never (also when shared), lists without members never, inboxes never; the folder path of the owner
    rows = c.execute("""SELECT l.id, l.name, l.color, l.icon, l.owner_id, l.archived, l.archived_at, l.created_at, l.folder,
                               (SELECT COUNT(*) FROM tasks t WHERE t.list_id=l.id AND t.deleted_at IS NULL AND t.status=0) AS open_n,
                               (SELECT COUNT(*) FROM tasks t WHERE t.list_id=l.id AND t.deleted_at IS NULL) AS all_n,
                               (SELECT MAX(t.updated_at) FROM tasks t WHERE t.list_id=l.id) AS changed,
                               (SELECT COUNT(*) FROM list_members m JOIN users u ON u.id=m.user_id
                                 WHERE m.list_id=l.id AND m.user_id!=l.owner_id AND COALESCE(u.kind,'user')!='agent') AS members
                        FROM lists l WHERE l.org_id=? AND l.is_inbox=0 ORDER BY l.archived, lower(l.name), l.id""", (oid,)).fetchall()
    rows = [r for r in rows if r["members"] > 0]
    log = c.execute("SELECT * FROM org_list_log WHERE org_id=? ORDER BY id DESC LIMIT ?", (oid, OL_LOG_MAX)).fetchall()
    people = c.execute("""SELECT u.id FROM org_members m JOIN users u ON u.id=m.user_id
                          WHERE m.org_id=? AND u.disabled=0 AND COALESCE(u.kind,'user')!='agent'""", (oid,)).fetchall()
    ids = {r["owner_id"] for r in rows} | {x for r in log for x in (r["by_id"], r["owner_id"], r["to_id"]) if x} | {r[0] for r in people}
    names = user_names(c, list(ids))
    agents = {r[0] for r in c.execute(f"SELECT id FROM users WHERE kind='agent' AND id IN ({','.join(str(int(i)) for i in ids) or 'NULL'})")}
    return {
        "lists": [{"id": r["id"], "name": r["name"], "owner_id": r["owner_id"], "owner_name": names.get(r["owner_id"], ""),
                   "owner_agent": r["owner_id"] in agents, "mine": r["owner_id"] == me(), "archived": bool(r["archived"]),
                   "archived_at": r["archived_at"], "open": r["open_n"], "tasks": r["all_n"], "members": r["members"], "folder": r["folder"] or "",
                   "changed_at": r["changed"] or r["created_at"],
                   "color": r["color"] or "", "icon": list_icon_url(r)} for r in rows],  # 2.56.0 (#1795): for "Edit"
        "people": sorted(({"id": r[0], "name": names.get(r[0], "")} for r in people), key=lambda x: x["name"].lower()),
        "log": [{"at": r["created_at"], "action": r["action"], "list_id": r["list_id"], "list_name": r["list_name"],
                 "by": names.get(r["by_id"], ""), "owner": names.get(r["owner_id"], ""), "to": names.get(r["to_id"], ""),
                 **_ole_detail(r)} for r in log]}


@app.get("/api/orgs/<int:oid>/lists")
def oadm_lists(oid):
    """The lists of organisation oid for its admins: name, owner, open / all tasks, members, last change, archived -- never
    their contents; the people a list can be handed to; the history of the admins' actions."""
    c = db()
    _need_org_admin(c, oid)
    return jsonify(_ol_out(c, oid))


@app.post("/api/orgs/<int:oid>/lists/<int:lid>/archive")
def oadm_archive(oid, lid):
    """{archived: true | false}: an organisation admin archives a list of the organisation (it leaves everyone's sidebar, nothing
    is deleted) or brings it back from the archive. The owner and the members are told (News)."""
    c, b = db(), body()
    _need_org_admin(c, oid)
    lr = _ol_list(c, oid, lid)
    on = b.get("archived", True)
    if not isinstance(on, bool):
        return err(tr("Invalid value: {0}", "archived"))
    if bool(lr["archived"]) == on:
        return jsonify(ok=True, **_ol_out(c, oid))
    c.execute("UPDATE lists SET archived=?, archived_at=? WHERE id=?", (int(on), iso(now_utc()) if on else None, lid))
    _ol_log(c, oid, lr, "archive" if on else "restore")
    _ol_news(c, oid, lr, "archive" if on else "restore")
    bump(c)
    c.commit()
    print("organisation", oid, "list", lid, "archived" if on else "restored", "by admin", g.user["username"], flush=True)
    return jsonify(ok=True, **_ol_out(c, oid))


@app.delete("/api/orgs/<int:oid>/lists/<int:lid>")
def oadm_delete(oid, lid):
    """{confirm: the list's name}: an organisation admin deletes an archived list of the organisation for good -- like the
    owner: its tasks go to the trash in the owner's inbox (restorable), its files and repository link go as with a normal
    delete. Only from the archive (409), only with the exact name (400)."""
    from ..lists.lists import list_purge
    from ..lists.projects import list_files_drop
    from ..accounts.pictures import list_icon_drop_file
    c, b = db(), body()
    _need_org_admin(c, oid)
    lr = _ol_list(c, oid, lid)
    if not lr["archived"]:
        return err(tr("Archive the list first: only archived lists can be deleted for good"), 409)
    if str(b.get("confirm") or "").strip() != lr["name"].strip():
        return err(tr("Type the name of the list to delete it for good"))
    _ol_news(c, oid, lr, "delete", gone=True)
    _ol_log(c, oid, lr, "delete")
    icon, lfiles = list_purge(c, lid, my_inbox(c, lr["owner_id"]))
    bump(c)
    c.commit()
    list_icon_drop_file(lid, icon)
    list_files_drop(lfiles)
    print("organisation", oid, "list", lid, "deleted for good by admin", g.user["username"], "owner", lr["owner_id"], flush=True)
    return jsonify(ok=True, **_ol_out(c, oid))


@app.post("/api/orgs/<int:oid>/lists/<int:lid>/owner")
def oadm_owner(oid, lid):
    """{user_id}: an organisation admin hands a list of the organisation to another person of it (typically: someone leaves).
    Like a transfer by the owner: the old owner stays as a list admin, News for the new owner (and the old one, the members)."""
    from ..lists.ownership import owner_transfer
    from ..accounts.orgs import ws_check_member
    c, b = db(), body()
    _need_org_admin(c, oid)
    lr = _ol_list(c, oid, lid)
    new = b.get("user_id")
    if not isinstance(new, int) or isinstance(new, bool):
        return err(tr("Invalid value: {0}", "user_id"))
    u = c.execute("SELECT * FROM users WHERE id=? AND disabled=0", (new,)).fetchone()
    if not u or oid not in user_orgs(c, new):
        return err(tr("unknown user"), 404)
    if (u["kind"] or "user") == "agent":
        return err(tr("An agent cannot own a list"))
    if new == lr["owner_id"]:
        return err(tr("{0} already owns this list", u["display_name"] or u["username"]))
    ws_check_member(c, lid, new)
    _ol_log(c, oid, lr, "owner", to_id=new)
    old, nname = owner_transfer(c, lr, new)
    _ol_news(c, oid, {"id": lid, "name": lr["name"], "owner_id": old}, "owner", to_name=nname)
    bump(c)
    c.commit()
    print("organisation", oid, "list", lid, "handed", old, "->", new, "by admin", g.user["username"], flush=True)
    return jsonify(ok=True, **_ol_out(c, oid))


# ---- 2.56.0 (#1795): an organisation admin changes the name (with its emoji), the picture icon and the colour of a list of the
# organisation -- nothing else (no tasks, sections, members, settings, sharing) and never its contents; also without a role in
# the list. The same lists as the other actions (_ol_list: the organisation's own, never private ones or inboxes), people only
# (_need_org_admin: agents 403). Logged (old -> new) and told to the owner and the members (News kind orglist, row "share").
OLE_KEYS = ("name", "color")


def ole_org_admin(c, lid):
    """The current person (never an agent) administers the organisation list lid belongs to (never an inbox)."""
    from ..agents.core import is_agent
    from ..accounts.orgs import org_role
    if is_agent(g.user):
        return False
    r = c.execute("SELECT org_id FROM lists WHERE id=? AND is_inbox=0", (lid,)).fetchone()
    return bool(r and r["org_id"] and org_role(c, me(), r["org_id"]) == "admin")


def _ole_detail(r):
    try:
        d = json.loads(r["detail"] or "null")
    except (KeyError, IndexError, ValueError, TypeError):
        return {}
    return {"detail": d} if isinstance(d, dict) else {}


def _ole_icon_label(v):
    """The stored icon for the log: '' (none), "picture" (an own picture) or the preset's name -- never the file token."""
    v = v or ""
    return "picture" if v.startswith("u:") else v[2:] if v.startswith("p:") else ""


@app.patch("/api/orgs/<int:oid>/lists/<int:lid>")
def ole_patch(oid, lid):
    """{name?, color?}: an organisation admin renames / recolours a list of the organisation (the emoji is part of the name).
    Any other field: 403 (the owner's and the list admins' way stays PATCH /api/lists/{id})."""
    from ..lists.lists import clean_list_value
    from ..personal.timetrack import BadInput
    c, b = db(), body()
    _need_org_admin(c, oid)
    lr = _ol_list(c, oid, lid)
    if not isinstance(b, dict) or not b or any(k not in OLE_KEYS for k in b):
        return err(tr("An organisation admin only changes the name, the icon and the colour of a list"), 403)
    try:
        vals = {k: clean_list_value(k, b[k]) for k in OLE_KEYS if k in b}
    except BadInput as e:
        return err(str(e))
    det = {k: [lr[k] or "", vals[k] or ""] for k in vals if (lr[k] or "") != (vals[k] or "")}
    if det:
        for k in det:
            c.execute(f"UPDATE lists SET {k}=? WHERE id=?", (vals[k], lid))
        _ol_log(c, oid, lr, "edit", detail=det)
        if "name" in det:
            _ol_news(c, oid, {"id": lid, "name": vals["name"], "owner_id": lr["owner_id"]}, "rename", extra={"old": lr["name"]})
        else:
            _ol_news(c, oid, lr, "restyle")
        bump(c)
        c.commit()
        print("organisation", oid, "list", lid, "changed", ",".join(det), "by admin", g.user["username"], flush=True)
    return jsonify(ok=True, **_ol_out(c, oid))


def _ole_icon_set(c, oid, lr, value):
    from ..accounts.pictures import list_icon_drop_file
    old = lr["icon"]
    if (old or None) != (value or None):
        c.execute("UPDATE lists SET icon=? WHERE id=?", (value, lr["id"]))
        _ol_log(c, oid, lr, "icon", detail={"icon": [_ole_icon_label(old), _ole_icon_label(value)]})
        _ol_news(c, oid, lr, "restyle")
        bump(c)
        c.commit()
        list_icon_drop_file(lr["id"], old)
        print("organisation", oid, "list", lr["id"], "icon changed by admin", g.user["username"], flush=True)
    return jsonify(ok=True, icon=list_icon_url({"id": lr["id"], "icon": value}), **_ol_out(c, oid))


@app.put("/api/orgs/<int:oid>/lists/<int:lid>/icon")
def ole_icon_preset(oid, lid):
    """{preset: "kalmido" | "coffee" | ... | null}: an organisation admin picks a preset icon for a list of the organisation."""
    from ..accounts.pictures import LIST_ICON_PRESETS
    c = db()
    _need_org_admin(c, oid)
    lr = _ol_list(c, oid, lid)
    p = body().get("preset")
    if p is not None and p not in LIST_ICON_PRESETS:
        return err(tr("Invalid value: {0}", "preset"))
    return _ole_icon_set(c, oid, lr, f"p:{p}" if p else None)


@app.post("/api/orgs/<int:oid>/lists/<int:lid>/icon")
def ole_icon_upload(oid, lid):
    """multipart "file": an own picture as the icon of a list of the organisation (as POST /api/lists/{id}/icon)."""
    from ..accounts.users import list_icon_store
    c = db()
    _need_org_admin(c, oid)
    lr = _ol_list(c, oid, lid)
    v = list_icon_store(lid)
    return v if not isinstance(v, str) else _ole_icon_set(c, oid, lr, v)


@app.delete("/api/orgs/<int:oid>/lists/<int:lid>/icon")
def ole_icon_delete(oid, lid):
    c = db()
    _need_org_admin(c, oid)
    return _ole_icon_set(c, oid, _ol_list(c, oid, lid), None)
