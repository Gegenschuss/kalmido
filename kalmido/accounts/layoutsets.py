"""2.55.0 (#1069): several saved arrangements per view and person (table view_layouts), e.g. "Focus" and "Overview",
switched in the view's header and the same on all devices. The person's current value (user setting / list_layouts) stays
what the view shows, so 2.53 keeps working with the new table; a saved arrangement is a named copy of such a value.
lyv_save() is the one way in: the person saving (#1069), a template taken over (#1068) and an accepted agent proposal
(#1066) all land here as one more saved arrangement."""
import re

from flask import jsonify, request

from ..core.config import app, PUBLIC_URL
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, now_utc, uset
from ..accounts.session import me
from ..core.access import Denied, collab_all, is_project, list_role
from ..core.errors import BadInput
from .layouts import WG_STD_KEYS, clean_layout, need_person
from ..core.pg import insert_id, system_ctx  # 2.149.0 G (#2517): pulled up from functions

LYV_MAX = 12          # saved arrangements per person and view
LYV_NAME_MAX = 60
LYV_SOURCES = ("", "template", "agent")
LYV_LIST_RE = re.compile(r"list:[1-9][0-9]{0,15}")


def lyv_key_ok(key):
    """A view that can have saved arrangements. For "list:<id>" the caller checks the person may see that project page."""
    return isinstance(key, str) and (key in WG_STD_KEYS or bool(LYV_LIST_RE.fullmatch(key)))


def lyv_clean(key, layout):
    from .settings import DASH_WIDGETS
    return clean_layout(layout, DASH_WIDGETS if key == "dashboard" else None)


def lyv_name(c, uid, key, name, skip=0):
    """The name trimmed and made unique among the person's arrangements of that view ("Focus", "Focus (2)", ...)."""
    n = (name or "").strip()[:LYV_NAME_MAX] if isinstance(name, str) else ""
    if not n:
        raise BadInput(tr("Give the arrangement a name"))
    have = {r["name"] for r in c.execute("SELECT name FROM view_layouts WHERE user_id=? AND view_key=? AND id<>?", (uid, key, skip))}
    base, i = n, 2
    while n in have:
        suf = f" ({i})"
        n, i = base[:LYV_NAME_MAX - len(suf)] + suf, i + 1
    return n


def lyv_save(c, uid, key, name, layout, source="", source_ref=None):
    """Store one more saved arrangement of view key for person uid and return its id (no commit, no bump: the caller does).
    layout = json text / dict as the view stores it (cleaned here). 409 at LYV_MAX per view."""
    if not lyv_key_ok(key) or source not in LYV_SOURCES:
        raise BadInput(tr("Invalid layout"))
    v = lyv_clean(key, layout)
    if c.execute("SELECT COUNT(*) FROM view_layouts WHERE user_id=? AND view_key=?", (uid, key)).fetchone()[0] >= LYV_MAX:
        raise Denied(409, tr("At most {0} saved arrangements per view", LYV_MAX))
    pos = c.execute("SELECT COALESCE(MAX(pos), 0) + 1 FROM view_layouts WHERE user_id=? AND view_key=?", (uid, key)).fetchone()[0]
    ts = iso(now_utc())
    return insert_id(c, """INSERT INTO view_layouts(user_id,view_key,name,layout,pos,source,source_ref,created_at,updated_at)
                            VALUES(?,?,?,?,?,?,?,?,?)""",
                     (uid, key, lyv_name(c, uid, key, name), v, pos, source, source_ref, ts, ts))


# ---------------------------------------------------------------- the person's own value of a view
# A view's value is what it shows: user_settings[<key>] (dashboard, view_today, ...) or list_layouts (a project page).
# "Active" = view_layouts.active = 1 (at most one per person and view): the view shows its name and changes made while
# customizing go into it as well (lyv_follow). Switching copies the saved arrangement into the own value, so the standard
# bar, "Different on the phone" and 2.53 work on as before.

def _lid(key):
    return int(key[5:]) if key.startswith("list:") else None


def lyv_need_key(c, key):
    """400 for an unknown view; a project page: the person must see it (need_overview, like accounts/layouts.py)."""
    if not lyv_key_ok(key):
        raise BadInput(tr("Invalid layout"))
    if _lid(key):
        from ..lists.projects import need_overview
        need_overview(c, _lid(key), write=False)


def lyv_own(c, uid, key):
    if _lid(key):
        r = c.execute("SELECT layout FROM list_layouts WHERE list_id=? AND user_id=?", (_lid(key), uid)).fetchone()
    else:
        r = c.execute("SELECT value FROM user_settings WHERE user_id=? AND key=?", (uid, key)).fetchone()
    return (r[0] if r else "") or ""


def _own_put(c, uid, key, v):
    if not _lid(key):
        uset(c, uid, key, v)
    elif v:
        c.execute("""INSERT INTO list_layouts(list_id,user_id,layout,updated_at) VALUES(?,?,?,?)
                     ON CONFLICT(list_id,user_id) DO UPDATE SET layout=excluded.layout, updated_at=excluded.updated_at""",
                  (_lid(key), uid, v, iso(now_utc())))
    else:
        c.execute("DELETE FROM list_layouts WHERE list_id=? AND user_id=?", (_lid(key), uid))


def lyv_has_layout(v):
    """The value arranges blocks (not just a block's switches): mirrors wgHasLayout in static/js/widgets.js."""
    import json
    try:
        o = json.loads(v) if v else {}
    except ValueError:
        return False
    if not isinstance(o, dict):
        return False
    return any(k in o for k in ("order", "hidden", "mobile")) or bool(o.get("half") or o.get("full")) \
        or any(isinstance(x, dict) and (x.get("lw") is not None or x.get("lh") is not None) for x in (o.get("opts") or {}).values())


def lyv_follow(c, uid, key, v):
    """The person's value of view key changed to v (settings PATCH, the project page PUT, a reset): the active saved
    arrangement follows. A value without an arrangement (back to the standard) ends "active" instead of overwriting it."""
    r = c.execute("SELECT id, layout FROM view_layouts WHERE user_id=? AND view_key=? AND active=1", (uid, key)).fetchone()
    if not r:
        return
    if not lyv_has_layout(v):
        c.execute("UPDATE view_layouts SET active=0 WHERE id=?", (r["id"],))
    elif v != r["layout"]:
        c.execute("UPDATE view_layouts SET layout=?, updated_at=? WHERE id=?", (v, iso(now_utc()), r["id"]))


def lyv_active_id(c, uid, key):
    """The id of the active saved arrangement of view key, or None (#1066 keeps it for undo)."""
    r = c.execute("SELECT id FROM view_layouts WHERE user_id=? AND view_key=? AND active=1", (uid, key)).fetchone()
    return r[0] if r else None


def lyv_set_active(c, uid, key, sid):
    """Mark saved arrangement sid (None = none) active for view key WITHOUT touching the person's value (the caller sets it;
    #1066 does after a 👍). No commit."""
    c.execute("UPDATE view_layouts SET active=CASE WHEN id=? THEN 1 ELSE 0 END WHERE user_id=? AND view_key=?", (sid or 0, uid, key))


def lyv_dict(r):
    return {"id": r["id"], "key": r["view_key"], "name": r["name"], "layout": r["layout"] or "", "pos": r["pos"],
            "source": r["source"] or "", "active": bool(r["active"]), "updated_at": r["updated_at"]}


def _row(c, sid):
    """A saved arrangement of the current person; someone else's = 404 (as unknown)."""
    r = c.execute("SELECT * FROM view_layouts WHERE id=? AND user_id=?", (sid, me())).fetchone()
    if not r:
        raise Denied(404, tr("Not found"))
    return r


def lyv_activate(c, uid, r):
    """Make saved arrangement r the active one of its view: its layout becomes the person's value."""
    c.execute("UPDATE view_layouts SET active=0 WHERE user_id=? AND view_key=? AND id<>?", (uid, r["view_key"], r["id"]))
    c.execute("UPDATE view_layouts SET active=1 WHERE id=?", (r["id"],))
    _own_put(c, uid, r["view_key"], r["layout"] or "")
    return r["layout"] or ""


def _str_arg(b, k):
    v = b.get(k)
    if v is not None and not isinstance(v, (str, dict)):
        raise BadInput(tr("Invalid layout"))
    return v


@app.get("/api/layouts/saved")
def lyv_list():
    """The person's saved arrangements (?key = of one view), in their order."""
    need_person()
    c, key = db(), request.args.get("key")
    if key is not None:
        lyv_need_key(c, key)
        rows = c.execute("SELECT * FROM view_layouts WHERE user_id=? AND view_key=? ORDER BY pos, id", (me(), key)).fetchall()
    else:
        rows = c.execute("SELECT * FROM view_layouts WHERE user_id=? ORDER BY view_key, pos, id", (me(),)).fetchall()
    return jsonify(saved=[lyv_dict(r) for r in rows])


@app.post("/api/layouts/saved")
def lyv_create():
    """{key, name, layout?, activate?, pos?}: one more saved arrangement (without layout = the person's current value).
    activate: it becomes the active one (the view's value is set to it). 409 at LYV_MAX."""
    need_person()
    b = body()
    if set(b) - {"key", "name", "layout", "activate", "pos"}:
        raise BadInput(tr("Invalid layout"))
    c, key = db(), b.get("key")
    lyv_need_key(c, key)
    lay = _str_arg(b, "layout")
    sid = lyv_save(c, me(), key, b.get("name"), lyv_own(c, me(), key) if lay is None else lay)
    if isinstance(b.get("pos"), int) and not isinstance(b.get("pos"), bool):
        _move(c, me(), key, sid, b["pos"])
    r = _row(c, sid)
    val = lyv_activate(c, me(), r) if b.get("activate") else None
    bump(c)
    c.commit()
    return jsonify(saved=lyv_dict(_row(c, sid)), value=val)


def _move(c, uid, key, sid, pos):
    ids = [r[0] for r in c.execute("SELECT id FROM view_layouts WHERE user_id=? AND view_key=? ORDER BY pos, id", (uid, key))]
    ids.remove(sid)
    ids.insert(max(0, min(pos, len(ids))), sid)
    for i, x in enumerate(ids):
        c.execute("UPDATE view_layouts SET pos=? WHERE id=?", (i + 1, x))


@app.patch("/api/layouts/saved/<int:sid>")
def lyv_patch(sid):
    """{name?, layout?, pos?}: rename, overwrite (an active one: the view's value too), move to place pos (0 = first)."""
    need_person()
    b = body()
    if not b or set(b) - {"name", "layout", "pos"}:
        raise BadInput(tr("Invalid layout"))
    c = db()
    r = _row(c, sid)
    val = None
    if "name" in b:
        n = b["name"].strip() if isinstance(b["name"], str) else ""
        if n != r["name"]:
            c.execute("UPDATE view_layouts SET name=?, updated_at=? WHERE id=?",
                      (lyv_name(c, me(), r["view_key"], n, sid), iso(now_utc()), sid))
    if "layout" in b:
        v = lyv_clean(r["view_key"], _str_arg(b, "layout"))
        c.execute("UPDATE view_layouts SET layout=?, updated_at=? WHERE id=?", (v, iso(now_utc()), sid))
        if r["active"]:
            lyv_need_key(c, r["view_key"])
            _own_put(c, me(), r["view_key"], v)
            val = v
    if "pos" in b:
        if not isinstance(b["pos"], int) or isinstance(b["pos"], bool):
            raise BadInput(tr("Invalid layout"))
        _move(c, me(), r["view_key"], sid, b["pos"])
    bump(c)
    c.commit()
    return jsonify(saved=lyv_dict(_row(c, sid)), value=val)


@app.delete("/api/layouts/saved/<int:sid>")
def lyv_delete(sid):
    """Delete a saved arrangement; the answer is the row as it was (undo posts it again). The view keeps showing what it
    shows (an active one just stops being active)."""
    need_person()
    c = db()
    r = _row(c, sid)
    d = lyv_dict(r)
    d["index"] = c.execute("SELECT COUNT(*) FROM view_layouts WHERE user_id=? AND view_key=? AND (pos<? OR (pos=? AND id<?))",
                           (r["user_id"], r["view_key"], r["pos"], r["pos"], sid)).fetchone()[0]
    c.execute("DELETE FROM view_layouts WHERE id=?", (sid,))
    bump(c)
    c.commit()
    return jsonify(deleted=d)


@app.post("/api/layouts/saved/<int:sid>/activate")
def lyv_activate_route(sid):
    """Switch the view to this saved arrangement -> {key, value (the view's value now), active}."""
    need_person()
    c = db()
    r = _row(c, sid)
    lyv_need_key(c, r["view_key"])
    v = lyv_activate(c, me(), r)
    bump(c)
    c.commit()
    return jsonify(key=r["view_key"], value=v, active=sid)


@app.post("/api/layouts/saved/standard")
def lyv_standard():
    """{key, value?}: no saved arrangement active; the view's value becomes value ('' = the standard; undo sends the old
    value back). -> {key, value, active: null}."""
    need_person()
    b = body()
    if set(b) - {"key", "value"}:
        raise BadInput(tr("Invalid layout"))
    c, key = db(), b.get("key")
    lyv_need_key(c, key)
    v = lyv_clean(key, _str_arg(b, "value"))
    c.execute("UPDATE view_layouts SET active=0 WHERE user_id=? AND view_key=?", (me(), key))
    _own_put(c, me(), key, v)
    bump(c)
    c.commit()
    return jsonify(key=key, value=v, active=None)


# ---------------------------------------------------------------- 2.55.0 (#1068): an arrangement as a template for others
# Only the arrangement travels (the cleaned layout value: block keys, widths, heights, switches), never content: a block the
# recipient cannot see or does not have just stays empty / off for them. Recipients: people (not agents) the sender sees
# and who see the sender (the people the share dialog offers), not blocked by the recipient; a project page only to people
# with access to it (checked when sending and again when taking it over). News item "lytpl" (row "share" of the
# notification settings, like connection requests). Agents neither send nor take over templates (#1066 = their proposals).
LYO_TO_MAX = 20       # recipients per sending
LYO_OPEN_MAX = 50     # open templates per recipient
LYO_PAIR_MAX = 3      # open templates from one sender to one recipient (one sender cannot fill the recipient's slots)


def _pair_ok(c, a, b):
    """a and b see each other, b is an enabled person (not an agent) and b did not block a."""
    from ..accounts.orgs import may_see
    with system_ctx(c):  # the recipient's account kind / state and their block list (ids only, no content)
        u = c.execute("SELECT kind, disabled FROM users WHERE id=?", (b,)).fetchone()
        blocked = c.execute("SELECT 1 FROM conn_blocks WHERE user_id=? AND blocked_id=?", (b, a)).fetchone()
    return bool(u) and (u["kind"] or "user") != "agent" and not u["disabled"] and not blocked \
        and may_see(c, a, b) and may_see(c, b, a)


def _page_ok(c, key, uid):
    """A project page template: uid has access to that project page (always True for the other views)."""
    if not _lid(key):
        return True
    with system_ctx(c):  # the role of ANOTHER person in a list the sender sees (no content read)
        return bool(list_role(c, _lid(key), uid)) and is_project(c, _lid(key))


def _uname(c, uid):
    with system_ctx(c):  # the sender's display name, shown to a recipient who sees them (_pair_ok)
        r = c.execute("SELECT display_name, username FROM users WHERE id=?", (uid,)).fetchone()
    return (r["display_name"] or r["username"]) if r else ""


@app.post("/api/layouts/offers")
def lyo_send():
    """{key, name, layout, to: [user ids]}: send an arrangement as a template -> {sent}. 404 for a person the sender may not
    send to (as unknown); a recipient with LYO_OPEN_MAX open templates or who blocked the sender is skipped silently."""
    from ..collab.news import news_add, list_push
    need_person()
    b = body()
    if set(b) - {"key", "name", "layout", "to"}:
        raise BadInput(tr("Invalid layout"))
    c, key, to = db(), b.get("key"), b.get("to")
    lyv_need_key(c, key)
    if not collab_all():
        raise Denied(403, tr("Sharing is off"))
    if not isinstance(to, list) or not to or len(to) > LYO_TO_MAX \
            or not all(isinstance(x, int) and not isinstance(x, bool) for x in to):
        raise BadInput(tr("Choose up to {0} people", LYO_TO_MAX))
    n = (b.get("name") or "").strip()[:LYV_NAME_MAX] if isinstance(b.get("name"), str) else ""
    if not n:
        raise BadInput(tr("Give the arrangement a name"))
    v = lyv_clean(key, _str_arg(b, "layout"))
    sender = me()
    from ..accounts.orgs import may_see
    from ..agents.core import agent_ids
    ags = agent_ids(c)
    for x in dict.fromkeys(to):
        if x == sender or x in ags or not may_see(c, sender, x):
            raise Denied(404, tr("unknown user"))
        if not _page_ok(c, key, x):  # someone the sender sees: naming them tells nothing new
            raise Denied(409, tr("{0} cannot see this project page", _uname(c, x)))
    who, ts = _uname(c, sender), iso(now_utc())
    for x in dict.fromkeys(to):
        if not _pair_ok(c, sender, x):
            continue  # a disabled account / blocked by them: nothing reaches them, the sender learns nothing
        if c.execute("SELECT COUNT(*) FROM view_layout_offers WHERE to_user=? AND state='open'", (x,)).fetchone()[0] >= LYO_OPEN_MAX \
                or c.execute("SELECT COUNT(*) FROM view_layout_offers WHERE from_user=? AND to_user=? AND state='open'",
                             (sender, x)).fetchone()[0] >= LYO_PAIR_MAX:
            continue
        oid = insert_id(c, """INSERT INTO view_layout_offers(from_user,to_user,view_key,name,layout,state,created_at)
                               VALUES(?,?,?,?,?,'open',?)""", (sender, x, key, n, v, ts))
        news_add(c, x, "lytpl", data={"offer": oid, "name": n, "view": key}, row="share")
        list_push(c, x, "share", None, lambda lg: tr("Arrangement template", lg=lg),
                  lambda lg, n=n: tr("{0} sent you the arrangement {1}", who, n, lg=lg), click=f"{PUBLIC_URL}/#news")
    bump(c)
    c.commit()
    return jsonify(sent=len(dict.fromkeys(to)))


def lyo_open(c, uid, oid):
    """The open template oid for recipient uid while the sender is still someone they exchange with; else None."""
    r = c.execute("SELECT * FROM view_layout_offers WHERE id=? AND to_user=? AND state='open'", (oid, uid)).fetchone()
    if not r or not _pair_ok(c, uid, r["from_user"]) or not _pair_ok(c, r["from_user"], uid) or not _page_ok(c, r["view_key"], uid):
        return None
    return r


def _offer(c, oid):
    r = lyo_open(c, me(), oid)
    if not r:
        raise Denied(404, tr("This template is no longer available"))
    return r


@app.get("/api/layouts/offers/<int:oid>")
def lyo_get(oid):
    """An open template sent to me: {id, key, name, layout, from: {id, name}, created_at}."""
    need_person()
    c = db()
    r = _offer(c, oid)
    return jsonify(id=r["id"], key=r["view_key"], name=r["name"], layout=r["layout"], created_at=r["created_at"],
                   **{"from": {"id": r["from_user"], "name": _uname(c, r["from_user"])}})


@app.post("/api/layouts/offers/<int:oid>/accept")
def lyo_accept(oid):
    """{activate?}: take the template over as a saved arrangement of my own (name = sender + name, made unique), on wish
    active right away -> {saved, value}. Nothing links it to the sender afterwards."""
    need_person()
    b = body()
    if set(b) - {"activate"}:
        raise BadInput(tr("Invalid layout"))
    c = db()
    r = _offer(c, oid)
    lyv_need_key(c, r["view_key"])
    if not c.execute("UPDATE view_layout_offers SET state='accepted', decided_at=? WHERE id=? AND state='open' RETURNING id",
                     (iso(now_utc()), oid)).fetchone():  # two taps / devices at once: only the first takes it over
        raise Denied(404, tr("This template is no longer available"))
    sid = lyv_save(c, me(), r["view_key"], f"{_uname(c, r['from_user'])}: {r['name']}"[:LYV_NAME_MAX], r["layout"],
                   source="template", source_ref=f"user:{r['from_user']}")
    val = lyv_activate(c, me(), _row(c, sid)) if b.get("activate") else None
    bump(c)
    c.commit()
    return jsonify(saved=lyv_dict(_row(c, sid)), value=val)


@app.post("/api/layouts/offers/<int:oid>/decline")
def lyo_decline(oid):
    need_person()
    c = db()
    r = c.execute("SELECT id FROM view_layout_offers WHERE id=? AND to_user=? AND state='open'", (oid, me())).fetchone()
    if not r:
        raise Denied(404, tr("This template is no longer available"))
    c.execute("UPDATE view_layout_offers SET state='declined', decided_at=? WHERE id=?", (iso(now_utc()), oid))
    bump(c)
    c.commit()
    return jsonify(ok=True)
