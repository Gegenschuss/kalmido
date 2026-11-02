"""2.40.0 (#1361): favourite lists and projects, personal per person (the user setting fav_lists).

Nobody else sees someone's stars (not the other members, not other agents): the ids live in the person's own user settings,
which /api/state hands only to that person. 2.46.1 (#1361 point 7): the person's own agents (agents.owner_id) see the flag
"favorite" on the lists they see anyway (GET /api/v1/lists). The web app reads them from there; this route sets / clears one star."""
from datetime import timedelta

from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, now_utc, uset, usettings
from ..core.access import Denied, need_list, vis_sql
from ..accounts.session import me
from ..accounts.settings import FV2_MAX  # 2.369.5 (#2517): pulled up from functions
from .lists import FOLDER_SEP  # 2.369.5 (#2517): pulled up from functions

VW_FAV_MAX = 500  # the same bound as the other id lists of the settings (clean_setting)


def vw_fav_ids(c, uid):
    """The person's favourite list ids, in the order they were starred."""
    return [int(x) for x in (usettings(c, uid).get("fav_lists") or "").split(",") if x.strip().isdigit()]


def lc_fav_of(c, uid):
    """2.46.1 (#1361 point 7): the favourites an account works with: a person's own stars; an agent sees the stars of
    the person it belongs to (agents.owner_id; a team agent without an owner: none). Callers only mark lists the account
    sees anyway."""
    from ..agents.core import agent_ids
    if uid in agent_ids(c):
        r = c.execute("SELECT owner_id FROM agents WHERE user_id=?", (uid,)).fetchone()
        return set(vw_fav_ids(c, r[0])) if r and r[0] else set()
    return set(vw_fav_ids(c, uid))


# 2.40.0 (#1361): one decorator per method, so parity_test / the route scans see both routes
@app.put("/api/lists/<int:lid>/favorite")
@app.delete("/api/lists/<int:lid>/favorite")
def vw_list_favorite(lid):
    """PUT {"on": true|false} (default true) stars / unstars list lid for the signed-in person; DELETE unstars it.
    404 for a list the person cannot see (DELETE of an own old star still works); agents have no favourites (403)."""
    from ..agents.core import need_person
    need_person(403, tr("Favourites are a personal setting of a person"))
    c = db()
    on = request.method == "PUT" and bool((body() or {}).get("on", True))
    had = vw_fav_ids(c, me())
    ids = [x for x in had if x != lid]
    # 2.40.1: a list the person cannot see is 404 for PUT and DELETE alike (route scan); only an own star of a list the
    # person lost access to can still be removed
    if on or lid not in had:
        need_list(c, lid, write=False)
    if on:
        if len(ids) >= VW_FAV_MAX:
            ids = ids[1 - VW_FAV_MAX:]
        ids.append(lid)
    uset(c, me(), "fav_lists", ",".join(map(str, ids)))
    items = fv2_items_follow(c, me(), lid, on)
    bump(c)
    c.commit()
    return jsonify(ok=True, favorite=on, fav_lists=",".join(map(str, ids)), fav_items=items)


def fv2_items_follow(c, uid, lid, on):
    """2.57.0 (#1798): the list's place in the sidebar's favourites (fav_items) follows its star: a new star goes to the end,
    an unstarred list leaves; returns the stored json. A star set by an older app / an agent without it is added by the
    web app when it draws the favourites."""
    import json
    try:
        items = [x for x in json.loads(usettings(c, uid).get("fav_items") or "[]") if isinstance(x, str)]
    except ValueError:
        items = []
    key = "l:%d" % lid
    if not (on and key in items):  # a star set again keeps its place
        items = [x for x in items if x != key] + ([key] if on else [])
    out = json.dumps(items[-FV2_MAX:], ensure_ascii=False, separators=(",", ":"))
    uset(c, uid, "fav_items", out)
    return out


# 2.46.1 (#1361 point 4): "Quieter pushes from lists without a star" (user setting fav_quiet, default off): while the person has
# at least one favourite, a list without a star pushes only what concerns them directly (@mentions, assignments) and what
# they must not miss (reminders, approvals, shares, ...); the News stay complete, an explicit list bell (all / custom) wins
LC_FAV_QUIET_ROWS = ("comment", "follow", "newtask", "complete", "status", "unblock", "chat")  # 2.46.1 review: a reply to you always comes


def lc_fav_quiet(c, uid, lid, row):
    if row not in LC_FAV_QUIET_ROWS:
        return False
    favs = vw_fav_ids(c, uid)
    return bool(favs) and lid not in favs


# 2.46.1 (#1361 point 6): a suggestion, never automatic: a list the person worked in a lot during the last 14 days (own
# changes of its tasks on at least LC_SUG_DAYS different days, LC_SUG_ACTS in all) and that has no star is offered ONCE
# ("Add to favourites?"); every list is asked at most once (fav_asked), the setting fav_suggest switches it off
LC_SUG_WINDOW, LC_SUG_DAYS, LC_SUG_ACTS = 14, 5, 20


# 2.441.0 (#3592): what can be a favourite beyond the client's own state: the kinds of files/fsref.py (their name, route and space
# come from its registry) and, as nodes of the file store, files and documents. Trash: the two kinds whose base role ignores it.
FV2_REF_KINDS = ("office_doc", "office_letter", "office_gendoc", "office_receipt", "wiki", "sheet", "contact", "address_book")
FV2_AREA = {"office_doc": "office", "office_letter": "office", "office_gendoc": "office", "office_receipt": "office", "wiki": "wiki",
            "sheet": "sheets", "contact": "contacts", "address_book": "contacts"}  # the area an organisation can switch off (orgs.areas_off)


def _fv2_ws(c, uid, org_id, owner_id):
    """The workspace an object opens in; '' = none of the person's own (shared from outside: nothing to switch)."""
    from ..accounts.orgs import user_orgs
    if org_id:
        return "org:%d" % org_id if org_id in user_orgs(c, uid) else ""
    return "private" if owner_id == uid else ""


def _fv2_ref(c, uid, kind, rid):
    """The public form of an object the person may read now, else None (gone, in the trash, no right, area locked)."""
    from ..files.fsref import FSR, fs_ref_role
    reg = FSR.get(kind)
    if reg is None or kind not in FV2_REF_KINDS:
        return None
    if kind == "wiki" and (x := _fv2_locked_page(c, uid, rid, reg)):
        return x
    if fs_ref_role(c, uid, kind, rid) is None:
        return None
    sp = reg["space"](c, rid)
    if sp is None or _fv2_off(c, sp[0], kind):
        return None
    if reg.get("content_gate"):
        reg["content_gate"](c, uid, rid)
    return {"name": _fv2_name(reg["title"](c, rid) if reg.get("title") else "", reg["label"]), "label": tr(reg["label"]),
            "to": reg["open_url"](rid), "ws": _fv2_ws(c, uid, sp[0], sp[1])}


def _fv2_off(c, org_id, kind):
    """Has the organisation's admins' switch taken the object's area away?"""
    from ..accounts.wsareas import wsa_org_off
    return bool(org_id) and FV2_AREA[kind] in wsa_org_off(c, org_id)


def _fv2_name(name, label):
    """The shown name; a name that is ciphertext (a page or folder with a lock) means nothing here: the kind's name."""
    return tr(label) if not name or name.startswith("e2e1:") else name


def _fv2_locked_page(c, uid, rid, reg):
    """A page of a locked space has no reference (a folder opens nothing there): the area's own role alone, never a title."""
    from ..wiki.wkfolder import wkf_base, wkf_locked
    r = c.execute("SELECT * FROM wiki_pages WHERE id=?", (rid,)).fetchone()
    if not r or r["deleted_at"] or not wkf_locked(c, r) or wkf_base(c, uid, r) is None:
        return None
    if _fv2_off(c, r["org_id"], "wiki"):
        return None
    return {"name": tr(reg["label"]), "label": tr(reg["label"]), "to": reg["open_url"](rid), "ws": _fv2_ws(c, uid, r["org_id"], r["owner_id"])}


def _fv2_node(c, uid, kind, nid):
    """A file or folder of the file store / a document, by the same check as opening it."""
    from ..files.store import need_node
    n = need_node(c, nid)
    if kind == "doc":
        from ..docs import store as doc_store
        if not doc_store.meta_row(c, nid):
            return None
    label = "Document" if kind == "doc" else "File store"
    return {"name": _fv2_name(n["name"], label), "folder": n["kind"] == "folder", "label": tr(label),
            "to": ("docs/%d" if kind == "doc" else "ablage/%d") % nid, "ws": _fv2_ws(c, uid, n["org_id"], n["owner_id"])}


@app.get("/api/favorites/targets")
def fv2_targets():
    """The person's favourites that live on the server: {items: {key: {name, label, to, ws}}, gone: [key]}. A key is checked here
    each time with the rights of the object's own area, so nothing of a target the person cannot read (any more) leaves."""
    import json
    if g.user["kind"] == "agent":
        raise Denied(403, tr("Favourites are a personal setting of a person"))
    c, uid = db(), me()
    try:
        keys = [x for x in json.loads(usettings(c, uid).get("fav_items") or "[]") if isinstance(x, str)]
    except ValueError:
        keys = []
    items, gone = {}, []
    for key in keys:
        p = key.split(":")
        try:
            if p[0] == "r" and len(p) == 3:
                x = _fv2_ref(c, uid, p[1], int(p[2]))
            elif p[0] in ("file", "doc"):
                x = _fv2_node(c, uid, p[0], int(p[1]))
            else:
                continue
        except Denied:
            x = None
        if x:
            items[key] = x
        else:
            gone.append(key)
    return jsonify(items=items, gone=gone)


@app.post("/api/favorites/suggestion")
def lc_fav_suggestion():
    """The one list to ask about now ({list_id, name} or list_id null); the list counts as asked from here on."""
    from ..agents.core import need_person
    need_person(403, tr("Favourites are a personal setting of a person"))
    c, uid = db(), me()
    s = usettings(c, uid)
    if s.get("fav_suggest") == "0":
        return jsonify(list_id=None)
    skip = set(vw_fav_ids(c, uid)) | {int(x) for x in (s.get("fav_asked") or "").split(",") if x.strip().isdigit()}
    since = iso(now_utc() - timedelta(days=LC_SUG_WINDOW))
    rows = c.execute(f"""SELECT t.list_id, COUNT(*) AS n, COUNT(DISTINCT substr(a.created_at, 1, 10)) AS d
                         FROM activity a JOIN tasks t ON t.id=a.task_id JOIN lists l ON l.id=t.list_id
                         WHERE a.user_id=? AND a.created_at>? AND l.archived=0 AND l.is_inbox=0 AND t.list_id IN {vis_sql()}
                         GROUP BY t.list_id ORDER BY COUNT(*) DESC, t.list_id""", (uid, since, uid, uid)).fetchall()
    for r in rows:
        if r["list_id"] in skip or r["n"] < LC_SUG_ACTS or r["d"] < LC_SUG_DAYS:
            continue
        asked = [x for x in (s.get("fav_asked") or "").split(",") if x.strip().isdigit()][-(VW_FAV_MAX - 1):]
        uset(c, uid, "fav_asked", ",".join(asked + [str(r["list_id"])]))
        c.commit()
        name = c.execute("SELECT name FROM lists WHERE id=?", (r["list_id"],)).fetchone()[0]
        return jsonify(list_id=r["list_id"], name=name)
    return jsonify(list_id=None)


def fv2_folder_rename(c, uid, old, new):
    """2.57.0 (#1798): a renamed / moved folder keeps its place among the favourites (fav_items), its subfolders too."""
    import json
    raw = usettings(c, uid).get("fav_items") or "[]"
    try:
        items = [x for x in json.loads(raw) if isinstance(x, str)]
    except ValueError:
        return
    def mv(x):
        p = x[7:] if x.startswith("folder:") else None
        return "folder:" + new + p[len(old):] if p is not None and (p == old or p.startswith(old + FOLDER_SEP)) else x
    out = json.dumps(list(dict.fromkeys(mv(x) for x in items)), ensure_ascii=False, separators=(",", ":"))
    if out != json.dumps(items, ensure_ascii=False, separators=(",", ":")):
        uset(c, uid, "fav_items", out)
