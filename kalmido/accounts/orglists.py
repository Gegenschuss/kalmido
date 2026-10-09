"""2.35.0 (#1101): organisation admins manage the lists of their organisation (Settings > Workspaces > Lists of the
organisation): an overview without contents (name, owner, number of tasks, last change), archive / restore, delete for good
(only from the archive, confirmed with the list's name) and hand a list over to another person of the organisation.

Only lists that belong to the organisation (lists.org_id): private lists, private sharing and inboxes stay invisible and
untouchable. People only (agents 403, also with admin rights). Mode shared: no organisation, no function (404); mode
organisation: the instance admins are its admins (org_role); modes multi / workspaces: the organisation role admin.
The owner and the list's members get a News entry ("archived / deleted by admin X"), every action is logged in
org_list_log (the history of the dialog). App only (APP_ONLY in tests/parity_test.py: an organisation admin's work)."""
from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, my_inbox
from ..accounts.orgs import _need_org_admin, instance_mode, user_orgs

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


def _ol_log(c, oid, lr, action, to_id=None):
    c.execute("INSERT INTO org_list_log(org_id,list_id,list_name,action,by_id,owner_id,to_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
              (oid, lr["id"], lr["name"], action, me(), lr["owner_id"], to_id, iso(now_utc())))


def _ol_news(c, oid, lr, action, gone=False, to_name=""):
    from ..collab.news import news_add
    oname = (c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0]
    for uid in _ol_people(c, lr):
        news_add(c, uid, "orglist", list_id=None if gone else lr["id"],
                 data={"action": action, "name": lr["name"], "org": oname, **({"to": to_name} if to_name else {})})


def _ol_out(c, oid):
    from ..collab.comments import user_names
    rows = c.execute("""SELECT l.id, l.name, l.owner_id, l.archived, l.archived_at, l.created_at,
                               (SELECT COUNT(*) FROM tasks t WHERE t.list_id=l.id AND t.deleted_at IS NULL AND t.status=0) AS open_n,
                               (SELECT COUNT(*) FROM tasks t WHERE t.list_id=l.id AND t.deleted_at IS NULL) AS all_n,
                               (SELECT MAX(t.updated_at) FROM tasks t WHERE t.list_id=l.id) AS changed,
                               (SELECT COUNT(*) FROM list_members m WHERE m.list_id=l.id) AS members
                        FROM lists l WHERE l.org_id=? AND l.is_inbox=0 ORDER BY l.archived, l.name COLLATE NOCASE, l.id""", (oid,)).fetchall()
    log = c.execute("SELECT * FROM org_list_log WHERE org_id=? ORDER BY id DESC LIMIT ?", (oid, OL_LOG_MAX)).fetchall()
    people = c.execute("""SELECT u.id FROM org_members m JOIN users u ON u.id=m.user_id
                          WHERE m.org_id=? AND u.disabled=0 AND COALESCE(u.kind,'user')!='agent'""", (oid,)).fetchall()
    if instance_mode(c) == "organisation":  # the one organisation holds every account
        people = c.execute("SELECT id FROM users WHERE disabled=0 AND COALESCE(kind,'user')!='agent'").fetchall()
    ids = {r["owner_id"] for r in rows} | {x for r in log for x in (r["by_id"], r["owner_id"], r["to_id"]) if x} | {r[0] for r in people}
    names = user_names(c, list(ids))
    agents = {r[0] for r in c.execute(f"SELECT id FROM users WHERE kind='agent' AND id IN ({','.join(str(int(i)) for i in ids) or 'NULL'})")}
    return {
        "lists": [{"id": r["id"], "name": r["name"], "owner_id": r["owner_id"], "owner_name": names.get(r["owner_id"], ""),
                   "owner_agent": r["owner_id"] in agents, "mine": r["owner_id"] == me(), "archived": bool(r["archived"]),
                   "archived_at": r["archived_at"], "open": r["open_n"], "tasks": r["all_n"], "members": r["members"],
                   "changed_at": r["changed"] or r["created_at"]} for r in rows],
        "people": sorted(({"id": r[0], "name": names.get(r[0], "")} for r in people), key=lambda x: x["name"].lower()),
        "log": [{"at": r["created_at"], "action": r["action"], "list_id": r["list_id"], "list_name": r["list_name"],
                 "by": names.get(r["by_id"], ""), "owner": names.get(r["owner_id"], ""), "to": names.get(r["to_id"], "")} for r in log]}


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
