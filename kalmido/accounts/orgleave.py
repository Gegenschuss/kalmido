"""2.361.0 (#2920 / #2922): what leaving or deleting an organisation means for its members -- before it happens.

- Leaving (or being removed): GET /api/orgs/<oid>/leave-info[?uid=<member>] = the projects the person brought in from their
  private space (they go back there, org_leave), the projects / calendars / address books that go to an admin, what stays in
  the organisation (files, knowledge pages, tables, office drafts, absences ... counted per area) and the assignments that end.
- Deleting: odl_delete_info (orgs.py) adds per member what they own in it (olv_members); the instance admin may tell the
  members first (POST /api/admin/orgs/<oid>/delete-notice: a News item with the day, the deletion waits until then), and
  every member gets a News item when it is gone (olv_gone_news, kinds orgdelnotice / orggone, no push).
Numbers only: no names of files, pages or tables leave the organisation's boundary.
"""
import json
from datetime import timedelta

from flask import jsonify, request

from ..core.config import app
from ..core.db import bump, db, err, iso, iso_ms, now_utc
from ..core.i18n import trn, tr
from ..core.pg import system_ctx
from ..core.access import Denied
from .session import me
from .orgretain import Nn_


# what of person uid stays in organisation oid when they leave it (and goes when it is deleted): (key, words, count query);
# whose = who made it (created_by: an organisation's file, page, table or video has no private owner)
OLV_STAYS = (
    ("files", Nn_("{0} file", "{0} files"),
     "SELECT COUNT(*) FROM fs_nodes WHERE org_id=? AND created_by=? AND kind='file' AND deleted_at IS NULL"),
    ("wiki_pages", Nn_("{0} knowledge page", "{0} knowledge pages"),
     "SELECT COUNT(*) FROM wiki_pages WHERE org_id=? AND created_by=? AND deleted_at IS NULL"),
    ("tables", Nn_("{0} table", "{0} tables"), "SELECT COUNT(*) FROM sheets WHERE org_id=? AND created_by=? AND deleted_at IS NULL"),
    ("bookmarks", Nn_("{0} bookmark", "{0} bookmarks"), "SELECT COUNT(*) FROM bookmarks WHERE org_id=? AND user_id=? AND deleted_at IS NULL"),
    ("polls", Nn_("{0} poll", "{0} polls"), "SELECT COUNT(*) FROM sched_polls WHERE org_id=? AND user_id=? AND deleted_at IS NULL"),
    ("videos", Nn_("{0} video review", "{0} video reviews"),
     "SELECT COUNT(*) FROM video_reviews WHERE org_id=? AND created_by=? AND deleted_at IS NULL"),
    ("drafts", Nn_("{0} office draft", "{0} office drafts"),
     "SELECT COUNT(*) FROM office_docs WHERE org_id=? AND created_by=? AND status='draft'"),
    ("clients", Nn_("{0} client", "{0} clients"), "SELECT COUNT(*) FROM clients WHERE org_id=? AND created_by=? AND deleted_at IS NULL"),
    ("absences", Nn_("{0} absence", "{0} absences"), "SELECT COUNT(*) FROM hub_absences WHERE org_id=? AND user_id=? AND deleted_at IS NULL"),
    ("leave_quota", Nn_("{0} vacation account", "{0} vacation accounts"), "SELECT COUNT(*) FROM hub_leave_quota WHERE org_id=? AND user_id=?"),
    ("timesheets", Nn_("{0} timesheet", "{0} timesheets"), "SELECT COUNT(*) FROM time_sheets WHERE org_id=? AND user_id=?"),
    ("time", Nn_("{0} time entry", "{0} time entries"),
     "SELECT COUNT(*) FROM time_entries WHERE list_id IN (SELECT id FROM lists WHERE org_id=?) AND user_id=?"),
    ("drives", Nn_("{0} drive", "{0} drives"), "SELECT COUNT(*) FROM office_drives WHERE org_id=? AND user_id=? AND deleted_at IS NULL"),
)
OLV_NOTICE_DAYS = 14  # the default period between telling the members and the deletion


def olv_stays(c, oid, uid, skip=()):
    """{key: n} of OLV_STAYS for uid in oid (zeros left out). skip: keys not to count."""
    with system_ctx(c):  # numbers only
        out = {k: c.execute(sql, (int(oid), int(uid))).fetchone()[0] for k, _w, sql in OLV_STAYS if k not in skip}
    return {k: v for k, v in out.items() if v}


def olv_text(counts):
    """"3 files, 2 tables" (translated) of olv_stays, in the order of OLV_STAYS."""
    return ", ".join(trn(*w, counts[k]) for k, w, _s in OLV_STAYS if counts.get(k))


def olv_info(c, oid, uid, heir):
    """What uid leaving oid means (heir = who gets their projects, calendars, address books): back (names of the projects
    uid brought in, they go back private), to_heir {lists, calendars, books}, heir (name), stays + stays_text, assigned."""
    with system_ctx(c):
        lists = c.execute("SELECT id, name, brought_by, deleted_at FROM lists WHERE owner_id=? AND org_id=? AND is_inbox=0 ORDER BY name",
                          (uid, oid)).fetchall()
        back = [x["name"] for x in lists if x["brought_by"] == uid and not x["deleted_at"]]
        given = sum(1 for x in lists if not (x["brought_by"] == uid and not x["deleted_at"]))
        cals = c.execute("SELECT COUNT(*) FROM ev_cals WHERE owner_id=? AND org_id=?", (uid, oid)).fetchone()[0]
        books = c.execute("SELECT COUNT(*) FROM books WHERE owner_id=? AND org_id=?", (uid, oid)).fetchone()[0]
        assigned = c.execute("SELECT COUNT(*) FROM tasks WHERE assignee_id=? AND deleted_at IS NULL AND list_id IN "
                             "(SELECT id FROM lists WHERE org_id=? AND owner_id!=?)", (uid, oid, uid)).fetchone()[0]
        from ..collab.comments import user_names
        hname = user_names(c, [heir]).get(heir, "") if heir and heir != uid else ""
    stays = olv_stays(c, oid, uid)
    return {"back": back, "to_heir": {"lists": given if hname else 0, "calendars": cals if hname else 0, "books": books if hname else 0},
            "heir": hname, "stays": stays, "stays_text": olv_text(stays), "assigned": assigned}


@app.get("/api/orgs/<int:oid>/leave-info")
def olv_leave_info(oid):
    """2.361.0 (#2922): the preview of leaving organisation oid (?uid = a member an admin removes; default: me) -- olv_info.
    The heir is the one org_member_remove would choose: the removing admin, else the organisation's first other admin."""
    from .orgs import _need_org_admin, _operator_apart, org_role
    c = db()
    try:
        uid = int(request.args.get("uid") or me())
    except ValueError:
        return err(tr("Invalid value: {0}", "uid"))
    if uid != me():
        _need_org_admin(c, oid)
    elif not org_role(c, me(), oid):
        raise Denied(404)
    if not c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone():
        return err(tr("unknown"), 404)
    heir = me() if uid != me() else (c.execute(
        "SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role='admin' AND u.disabled=0 "
        "AND m.user_id!=? ORDER BY m.user_id LIMIT 1", (oid, uid)).fetchone() or [None])[0]
    if uid != me() and request.args.get("to", "").isdigit():  # review: the admin hands the lists to another member (?to=, as the removal)
        heir = int(request.args["to"])
    if heir is None and not _operator_apart():  # review: the only admin leaves: the operator takes over (as org_member_remove)
        heir = (c.execute("SELECT id FROM users WHERE is_admin=1 AND disabled=0 AND kind!='agent' AND id!=? ORDER BY id LIMIT 1",
                          (uid,)).fetchone() or [None])[0]
    return jsonify(olv_info(c, oid, uid, heir))


def olv_people(c, oid):
    """The people (no agents) of organisation oid: [(id, name)]."""
    from ..collab.comments import user_names
    with system_ctx(c):
        ids = [r[0] for r in c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? "
                                       "AND COALESCE(u.kind,'user')!='agent' ORDER BY m.user_id", (int(oid),)).fetchall()]
        names = user_names(c, ids)
    return [(u, names.get(u, "")) for u in ids]


def olv_members(c, oid):
    """2.361.0 (#2920): per person of oid what they own in it (for the delete dialog): [{id, name, counts, text}], only
    the people with something."""
    out = []
    for uid, name in olv_people(c, oid):
        n = olv_stays(c, oid, uid, skip=("leave_quota",))
        if n:
            out.append({"id": uid, "name": name, "counts": n, "text": olv_text(n)})
    return out


def _olv_news(c, oid, kind, data):
    """A News item of kind (orgdelnotice | orggone) to every person of oid but me, with their own numbers (data.own = olv_stays,
    worded by the app in the reader's language; always, no push: like the invitation orgjoin, it does not depend on a list
    bell). The caller commits."""
    at = iso_ms(now_utc())
    n = 0
    for uid, _name in olv_people(c, oid):
        if uid == me():
            continue
        own = olv_stays(c, oid, uid, skip=("leave_quota",))
        c.execute("INSERT INTO notifications(user_id,kind,task_id,list_id,actor_id,comment_id,data,created_at) VALUES(?,?,NULL,NULL,?,NULL,?,?)",
                  (uid, kind, me(), json.dumps({**data, "org_id": int(oid), "own": own}, ensure_ascii=False), at))
        n += 1
    return n


def olv_gone_news(c, oid, name):
    """2.361.0 (#2920): right before organisation oid goes (the rows are still there): every member learns it, with what of
    theirs went along."""
    return _olv_news(c, oid, "orggone", {"name": name})


def olv_notice(c, oid):
    """The day the members were told the deletion of oid for (YYYY-MM-DD) or None."""
    with system_ctx(c):
        r = c.execute("SELECT delete_notice FROM orgs WHERE id=?", (int(oid),)).fetchone()
    return (r[0] or None) if r else None


@app.post("/api/admin/orgs/<int:oid>/delete-notice")
def olv_delete_notice(oid):
    """2.361.0 (#2920): the instance admin tells the members of organisation oid that it is deleted on a day ({days}: 1-90,
    default OLV_NOTICE_DAYS): each gets a News item with that day and what of theirs is in it; deleting waits until then
    (org_delete). DELETE takes the notice back (the members are told)."""
    from .orgs import _need_admin, instance_mode, _no_change
    from ..core.db import body
    _need_admin()
    c = db()
    b = body()
    try:
        days = int(b.get("days", OLV_NOTICE_DAYS))
    except (TypeError, ValueError):
        days = 0
    if not 1 <= days <= 90:
        return err(tr("Invalid value: {0}", "days"))
    with system_ctx(c):
        if instance_mode(c) != "workspaces":
            _no_change()
        r = c.execute("SELECT name FROM orgs WHERE id=? AND personal_of IS NULL AND retired_at IS NULL", (oid,)).fetchone()
        if not r:
            return err(tr("Not found"), 404)
        day = (now_utc() + timedelta(days=days)).date().isoformat()
        c.execute("UPDATE orgs SET delete_notice=? WHERE id=?", (day, oid))
        n = _olv_news(c, oid, "orgdelnotice", {"name": r[0], "day": day})
        bump(c)
        c.commit()
    return jsonify(ok=True, notice=day, told=n)


@app.delete("/api/admin/orgs/<int:oid>/delete-notice")
def olv_delete_notice_off(oid):
    """2.361.0 (#2920): the deletion announced for oid is called off; the members get a News item (orgdelnotice, day empty)."""
    from .orgs import _need_admin, instance_mode, _no_change
    _need_admin()
    c = db()
    with system_ctx(c):
        if instance_mode(c) != "workspaces":
            _no_change()
        r = c.execute("SELECT name, delete_notice FROM orgs WHERE id=? AND personal_of IS NULL", (oid,)).fetchone()
        if not r:
            return err(tr("Not found"), 404)
        if r["delete_notice"]:
            c.execute("UPDATE orgs SET delete_notice=NULL WHERE id=?", (oid,))
            _olv_news(c, oid, "orgdelnotice", {"name": r["name"], "day": ""})
            bump(c)
            c.commit()
    return jsonify(ok=True)


def olv_news_live(c, uid, data):
    """News filter (collab/news.py): orgdelnotice while the person is still in that organisation and the notice stands
    (the same day); orggone always."""
    try:
        d = json.loads(data or "{}")
        oid = int(d.get("org_id") or 0)
    except (ValueError, TypeError, AttributeError):
        return False
    with system_ctx(c):
        if not c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone():
            return False
    return (olv_notice(c, oid) or "") == (d.get("day") or "")


def olv_early(c, oid):
    """The day the members were told for, while it is still ahead (org_delete waits), else None."""
    day = olv_notice(c, oid)
    return day if day and day > iso(now_utc())[:10] else None
