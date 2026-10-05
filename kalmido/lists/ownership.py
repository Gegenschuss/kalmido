"""Transferring the ownership of a list; orphaned lists (owner disabled or an agent)."""
import json
from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import collab_all, Denied, list_role, my_max_sort, need_collab
from ..lists.groups import grp_sync


# ---- 2.1.2 (#349): transfer the ownership of a list. The owner hands it to another active person (a member or anyone they
# could share with); an instance admin takes over (for themselves or another person) any list whose owner is an agent or a
# disabled user. Agents never become owners and never transfer; inbox lists never change hands. The old owner stays as a
# member: role admin (a person) or edit (an agent: never a list admin), with the list where it was in their sidebar. The new
# owner's member row goes (the owner is no member row); they keep its folder, place and view, or (not a member before) get
# the list at the end of their sidebar, top level. One list_activity row "owner" + News (kind owner) for the new owner.
def owner_orphaned(c, uid):
    """Is uid (a list owner) an agent or a disabled user? Then an instance admin may take their lists over."""
    u = c.execute("SELECT kind, disabled FROM users WHERE id=?", (uid,)).fetchone()
    return not u or u["kind"] == "agent" or bool(u["disabled"])


def owner_candidates(c, lid, owner):
    """Active people (never agents) who can become the owner of lid: members first (with their role), then everyone else."""
    roles = {r[0]: r[1] for r in c.execute("SELECT user_id, role FROM list_members WHERE list_id=?", (lid,))}
    rows = c.execute("SELECT id, username, display_name FROM users WHERE disabled=0 AND COALESCE(kind,'user')!='agent' AND id!=? "
                     "ORDER BY id", (owner,)).fetchall()
    out = [{"id": r["id"], "name": r["display_name"] or r["username"], "role": roles.get(r["id"])} for r in rows]
    out.sort(key=lambda x: (x["role"] is None, x["name"].lower()))
    return out


def owner_rights(c, lid):
    """(list row, 'owner' | 'takeover') for the current user, or Denied: 404 when they may neither see nor take it over."""
    from ..agents.core import is_agent
    lr = c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()
    if not lr:
        raise Denied(404)
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot transfer lists"))
    if lr["owner_id"] == me():
        return lr, "owner"
    if g.user["is_admin"] and owner_orphaned(c, lr["owner_id"]):
        return lr, "takeover"
    if list_role(c, lid):
        raise Denied(403, tr("Only the owner can transfer this list"))
    raise Denied(404)


def list_owner_log(c, lid):
    from ..collab.comments import user_names
    rows = c.execute("SELECT * FROM list_activity WHERE list_id=? AND kind='owner' ORDER BY id DESC LIMIT 20", (lid,)).fetchall()
    names = user_names(c, [r["user_id"] for r in rows])
    out = []
    for r in rows:
        d = json.loads(r["data"] or "{}")
        out.append({"at": r["created_at"], "by_id": r["user_id"], "by": names.get(r["user_id"], ""),
                    "from_id": d.get("from"), "from": d.get("from_name", ""), "to_id": d.get("to"), "to": d.get("to_name", "")})
    return out


@app.get("/api/lists/<int:lid>/owner")
def list_owner_get(lid):
    """Who owns the list, whether I may transfer it (owner) or take it over (admin, owner = agent / disabled), the people it
    can go to, and the ownership history. Anyone who sees the list gets the owner + history."""
    from ..agents.core import is_agent
    c = db()
    lr = c.execute("SELECT owner_id, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
    if not lr:
        raise Denied(404)
    ou = c.execute("SELECT id, username, display_name, kind, disabled FROM users WHERE id=?", (lr["owner_id"],)).fetchone()
    mode = None
    if not lr["is_inbox"] and not is_agent(g.user):
        if lr["owner_id"] == me() and collab_all():
            mode = "owner"
        elif g.user["is_admin"] and owner_orphaned(c, lr["owner_id"]):
            mode = "takeover"
    if not mode and not list_role(c, lid):
        raise Denied(404)
    return jsonify(owner={"id": lr["owner_id"], "name": (ou["display_name"] or ou["username"]) if ou else "",
                          "agent": bool(ou) and ou["kind"] == "agent", "disabled": bool(ou) and bool(ou["disabled"])},
                   mode=mode, candidates=owner_candidates(c, lid, lr["owner_id"]) if mode else [],
                   history=list_owner_log(c, lid))


def owner_transfer(c, lr, new):
    """Moves list lr to user id new (checked by the caller); returns (old owner id, new owner name)."""
    from ..collab.comments import user_names
    from ..collab.news import list_push, news_add
    from ..agents.core import agent_ids
    lid, old = lr["id"], lr["owner_id"]
    ag = agent_ids(c)
    ts = iso(now_utc())
    mnew = c.execute("SELECT * FROM list_members WHERE list_id=? AND user_id=?", (lid, new)).fetchone()
    if mnew:
        folder, sort, view = mnew["folder"], mnew["sort"], mnew["view"] or lr["view"]
    else:
        folder, sort, view = "", my_max_sort(c, new) + 1, lr["view"]
    c.execute("DELETE FROM list_members WHERE list_id=? AND user_id IN (?, ?)", (lid, new, old))
    if old and c.execute("SELECT 1 FROM users WHERE id=?", (old,)).fetchone():
        c.execute("INSERT INTO list_members(list_id,user_id,role,own_role,folder,sort,view,added_at) VALUES(?,?,?,?,?,?,?,?)",
                  (lid, old, "edit" if old in ag else "admin", "edit" if old in ag else "admin", lr["folder"] or "", lr["sort"], lr["view"], ts))
    c.execute("UPDATE lists SET owner_id=?, folder=?, sort=?, view=? WHERE id=?", (new, folder, sort, view, lid))
    grp_sync(c, [lid])  # 2.10.0 (#441): the old owner's folder shares no longer reach it, the new owner's may
    names = user_names(c, [old, new, me()])
    c.execute("INSERT INTO list_activity(list_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
              (lid, me(), "owner", json.dumps({"from": old, "to": new, "from_name": names.get(old, ""), "to_name": names.get(new, "")},
                                              ensure_ascii=False), ts))
    news_add(c, new, "owner", list_id=lid, data={"name": lr["name"], "from": names.get(old, "")})
    who = names.get(me(), "?")
    list_push(c, new, "share", lid, lambda lg: tr("{0} made you the owner of a list", who, lg=lg), lambda lg: lr["name"])
    return old, names.get(new, "")


@app.post("/api/lists/<int:lid>/owner")
def list_owner_set(lid):
    """{user_id}: the owner hands the list to another active person; an admin takes over a list of an agent / a disabled user."""
    from ..agents.core import is_agent
    b = body()
    c = db()
    lr, mode = owner_rights(c, lid)
    if mode == "owner":
        need_collab()
    if lr["is_inbox"]:
        return err(tr("The inbox cannot be transferred"), 409)
    try:
        new = int(b.get("user_id") or 0)
    except (TypeError, ValueError):
        new = 0
    u = c.execute("SELECT * FROM users WHERE id=?", (new,)).fetchone()
    if not u or u["disabled"]:
        return err(tr("unknown user"), 404)
    if is_agent(u):
        return err(tr("An agent cannot own a list"))
    if new == lr["owner_id"]:
        return err(tr("{0} already owns this list", u["display_name"] or u["username"]))
    old, nname = owner_transfer(c, lr, new)
    bump(c)
    c.commit()
    print("list", lid, "ownership", old, "->", new, "by", g.user["username"], f"({mode})", flush=True)
    return jsonify(ok=True, id=lid, owner_id=new, owner_name=nname, previous_owner_id=old)


@app.get("/api/admin/lists/orphaned")
def admin_lists_orphaned():
    """Admins: lists (not inboxes) whose owner is an agent or a disabled user -- nobody may manage their sharing otherwise."""
    from ..accounts.users import need_admin
    need_admin()
    c = db()
    rows = c.execute("""SELECT l.id, l.name, l.archived, l.owner_id, u.username, u.display_name, u.kind, u.disabled,
                               (SELECT COUNT(*) FROM list_members m WHERE m.list_id=l.id) AS members,
                               (SELECT COUNT(*) FROM tasks t WHERE t.list_id=l.id AND t.deleted_at IS NULL) AS tasks
                        FROM lists l JOIN users u ON u.id=l.owner_id
                        WHERE l.is_inbox=0 AND (u.kind='agent' OR u.disabled=1) ORDER BY l.id""").fetchall()
    return jsonify(lists=[{"id": r["id"], "name": r["name"], "archived": bool(r["archived"]), "owner_id": r["owner_id"],
                           "owner_name": r["display_name"] or r["username"], "reason": "agent" if r["kind"] == "agent" else "disabled",
                           "members": r["members"], "tasks": r["tasks"]} for r in rows],
                   candidates=[{"id": r["id"], "name": r["display_name"] or r["username"]} for r in c.execute(
                       "SELECT id, username, display_name FROM users WHERE disabled=0 AND COALESCE(kind,'user')!='agent' ORDER BY id")])
