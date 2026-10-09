"""2.33.0 (#927): notification templates of a shared list / folder, set by its owner.

The owner of a list (or of a shared folder: its lists inherit it, a list can override it) decides how much the OTHER
people of that list may be notified at most -- a ceiling over each person's own settings (Settings > Notifications and
the list bell): a person can be quieter, never louder. Templates:
  read    "Read only": pushes only for @mentions, assignments, direct replies and an agent waiting for their approval
  work    "Collaborate": + comments on their own / assigned tasks and due reminders (also nags and follow-ups)
  all     "Everything": no ceiling (as before 2.33)
  custom  "Custom": the owner ticks the events one by one (CUSTOM_ROWS)
Per person the owner can choose another template (list or folder). Resolution for person P in list L of owner O:
P's own row of L, L's row for everyone, then for every folder of L from the nearest upwards: P's row of that folder,
its row for everyone; nothing set = TPL_DEFAULT (new shares start quiet). The owner is never limited.
Without any template a share gets TPL_DEFAULT ("read", or KALMIDO_NOTIF_TEMPLATE). Only PUSHES are limited, the News list stays complete. Checked in ONE place: notif_ok (collab/news.py) asks cap_ok.
Lists and folders that were shared before 2.33 got "all" written once (migration in core/db.py), and their owners are
asked once in the app (user setting notif_tpl_ask: "1" = ask, "0" = answered).
Tables (new, so 2.32 runs on with the database): list_notif, folder_notif; user_id 0 = everyone of the list / folder.
"""
import json
import os

from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc, uset
from ..accounts.session import me
from ..core.access import Denied, list_role, need_collab
from ..personal.timetrack import BadInput
from ..api.v1 import v1_args, v1_call, v1_view

NOTIF_TPLS = ("read", "work", "all", "custom")
# the events an owner can choose for "custom" (rows of the notification settings, see collab/news.py NOTIF_ROWS)
CUSTOM_ROWS = ("mention", "reply", "assign", "approval", "comment", "follow", "newtask", "complete", "status", "unblock",
               "chat", "reminder", "errreport", "share")
CUSTOM_KEY = {"nag": "reminder", "followup": "reminder"}  # a nag / follow-up is a due reminder
CAP_ROWS = CUSTOM_ROWS + ("nag", "followup")  # events of a list that the ceiling applies to (usage, proposals: never)
TPL_ROWS = {"read": {"mention", "reply", "assign", "approval"}}
TPL_ROWS["work"] = TPL_ROWS["read"] | {"comment", "reminder", "nag", "followup"}
# what a share without any template gets: "read" (new shares start quiet); KALMIDO_NOTIF_TEMPLATE = read | work | all
TPL_DEFAULT = os.environ.get("KALMIDO_NOTIF_TEMPLATE", "read").strip().lower()
TPL_DEFAULT = TPL_DEFAULT if TPL_DEFAULT in ("read", "work", "all") else "read"


def _fsep():
    from ..lists.lists import FOLDER_SEP
    return FOLDER_SEP


def _ancestors(path):
    """'A/x' -> ['A/x', 'A'] (nearest first)."""
    if not path:
        return []
    parts = path.split(_fsep())
    return [_fsep().join(parts[:i]) for i in range(len(parts), 0, -1)]


def custom_of(raw):
    try:
        o = json.loads(raw or "{}")
    except ValueError:
        return {}
    return {k: int(bool(v)) for k, v in o.items() if k in CUSTOM_ROWS and v in (0, 1, True, False)} if isinstance(o, dict) else {}


def custom_clean(v):
    """A custom choice from a client -> stored json; BadInput when invalid."""
    bad = BadInput(tr("Invalid value: {0}", "custom"))
    if v is None:
        return "{}"
    if not isinstance(v, dict) or len(v) > len(CUSTOM_ROWS) or any(k not in CUSTOM_ROWS or v[k] not in (0, 1, True, False) for k in v):
        raise bad
    return json.dumps({k: int(bool(x)) for k, x in sorted(v.items())}, separators=(",", ":"))


def _folder_rows(c, owner, folder, uid):
    return {r["user_id"]: r for r in c.execute("SELECT user_id, tpl, custom FROM folder_notif WHERE owner_id=? AND folder=? AND user_id IN (?, 0)",
                                               (owner, folder, uid))}


def tpl_for(c, lid, uid):
    """The template that limits uid in list lid -> {tpl, custom, source, folder} (source: member | list | folder-member |
    folder | default), or None when nothing limits uid (the owner, an unknown list, a list without owner)."""
    cache = g.setdefault("_notif_tpl", {}) if _has_g() else {}
    key = (lid, uid)
    if key in cache:
        return cache[key]
    out = _tpl_for(c, lid, uid)
    cache[key] = out
    return out


def _has_g():
    from flask import has_app_context
    return has_app_context()


def _tpl_for(c, lid, uid):
    lr = c.execute("SELECT l.owner_id, l.folder, u.kind AS owner_kind FROM lists l LEFT JOIN users u ON u.id=l.owner_id WHERE l.id=?",
                   (lid,)).fetchone()
    if not lr or not lr["owner_id"] or lr["owner_id"] == uid or lr["owner_kind"] == "agent":
        return None  # the owner is never limited; a list of an agent has nobody who could choose a template: not limited
    rows = {r["user_id"]: r for r in c.execute("SELECT user_id, tpl, custom FROM list_notif WHERE list_id=? AND user_id IN (?, 0)", (lid, uid))}
    for u, src in ((uid, "member"), (0, "list")):
        if u in rows:
            return {"tpl": rows[u]["tpl"], "custom": custom_of(rows[u]["custom"]), "source": src, "folder": None}
    for f in _ancestors(lr["folder"] or ""):
        rows = _folder_rows(c, lr["owner_id"], f, uid)
        for u, src in ((uid, "folder-member"), (0, "folder")):
            if u in rows:
                return {"tpl": rows[u]["tpl"], "custom": custom_of(rows[u]["custom"]), "source": src, "folder": f}
    return {"tpl": TPL_DEFAULT, "custom": {}, "source": "default", "folder": None}


def tpl_allows(t, row):
    if not t or t["tpl"] == "all" or t["tpl"] not in NOTIF_TPLS:
        return True
    if t["tpl"] == "custom":
        return bool(t["custom"].get(CUSTOM_KEY.get(row, row), 0))
    return row in TPL_ROWS[t["tpl"]]


def cap_ok(c, uid, row, lid):
    """THE ceiling check (called by notif_ok for pushes): may a push of event row about list lid reach uid?"""
    if not lid or row not in CAP_ROWS:
        return True
    try:
        return tpl_allows(tpl_for(c, lid, uid), row)
    except Exception as e:  # noqa: BLE001 - a broken template row never blocks a push
        print("notification template check failed:", type(e).__name__, e, flush=True)
        return True


def cap_hint(c, lid, uid, owner_name):
    """For a member's list in /api/state: {tpl, by} when the owner limits their pushes, else None."""
    t = tpl_for(c, lid, uid)
    if not t or t["tpl"] == "all":
        return None
    return {"tpl": t["tpl"], "by": owner_name, "allowed": sorted(r for r in CUSTOM_ROWS if tpl_allows(t, r))}


# ---------------------------------------------------------------- the owner's settings
def _people_list(c, lid, owner):
    return [{"user_id": r["id"], "name": r["display_name"] or r["username"]} for r in c.execute(
        """SELECT u.id, u.username, u.display_name FROM list_members m JOIN users u ON u.id=m.user_id
           WHERE m.list_id=? AND u.id!=? AND COALESCE(u.kind,'')!='agent' ORDER BY m.added_at, u.id""", (lid, owner or 0))]


def _row_out(r):
    return {"tpl": r["tpl"], "custom": custom_of(r["custom"])} if r else None


def _inherited(c, owner, path, uid=0, skip_first=False):
    """The folder template that applies at path (nearest folder upwards) -> {tpl, custom, folder} or the default."""
    anc = _ancestors(path)
    for f in anc[1:] if skip_first else anc:
        rows = _folder_rows(c, owner, f, uid)
        for u in ((uid, 0) if uid else (0,)):
            if u in rows:
                return {"tpl": rows[u]["tpl"], "custom": custom_of(rows[u]["custom"]), "folder": f}
    return {"tpl": TPL_DEFAULT, "custom": {}, "folder": None}


def list_tpl_info(c, lid):
    lr = c.execute("SELECT id, owner_id, folder FROM lists WHERE id=?", (lid,)).fetchone()
    own = {r["user_id"]: r for r in c.execute("SELECT user_id, tpl, custom FROM list_notif WHERE list_id=?", (lid,))}
    inh = _inherited(c, lr["owner_id"], lr["folder"] or "")
    people = []
    for p in _people_list(c, lid, lr["owner_id"]):
        t = _tpl_for(c, lid, p["user_id"]) or {"tpl": "all", "custom": {}}
        people.append({**p, "own": _row_out(own.get(p["user_id"])), "effective": t["tpl"]})
    eff = _row_out(own.get(0)) or {"tpl": inh["tpl"], "custom": inh["custom"]}
    return {"scope": "list", "list_id": lid, "own": _row_out(own.get(0)), "inherited": inh, "effective": eff, "people": people,
            "templates": list(NOTIF_TPLS), "custom_rows": list(CUSTOM_ROWS), "default": TPL_DEFAULT}


def folder_tpl_info(c, owner, f):
    from ..lists.lists import _in_folder
    own = {r["user_id"]: r for r in c.execute("SELECT user_id, tpl, custom FROM folder_notif WHERE owner_id=? AND folder=?", (owner, f))}
    inh = _inherited(c, owner, f, skip_first=True)
    people = [{"user_id": r["id"], "name": r["display_name"] or r["username"], "own": _row_out(own.get(r["id"]))} for r in c.execute(
        """SELECT u.id, u.username, u.display_name FROM folder_people p JOIN users u ON u.id=p.user_id
           WHERE p.owner_id=? AND p.folder=? AND COALESCE(u.kind,'')!='agent' ORDER BY p.created_at, u.id""", (owner, f))]
    lids = [r["id"] for r in c.execute("SELECT id, folder FROM lists WHERE owner_id=? AND is_inbox=0", (owner,)).fetchall()
            if _in_folder(r["folder"] or "", f)]
    own_lists = [r[0] for r in c.execute(f"SELECT list_id FROM list_notif WHERE user_id=0 AND list_id IN ({','.join('?' * len(lids))})", lids)] if lids else []
    eff = _row_out(own.get(0)) or {"tpl": inh["tpl"], "custom": inh["custom"]}
    return {"scope": "folder", "folder": f, "own": _row_out(own.get(0)), "inherited": inh, "effective": eff, "people": people,
            "lists": len(lids), "lists_own": len(own_lists), "templates": list(NOTIF_TPLS), "custom_rows": list(CUSTOM_ROWS),
            "default": TPL_DEFAULT}


def _no_agent():
    from ..agents.core import is_agent
    if is_agent(g.user):  # agents read the setting at most, they never change it
        raise Denied(403)


def _tpl_in(b):
    tpl = b.get("tpl")
    if tpl is not None and tpl not in NOTIF_TPLS:
        raise BadInput(tr("Invalid value: {0}", "tpl"))
    cust = custom_clean(b.get("custom")) if tpl == "custom" else None
    return tpl, cust


def _uid_in(b):
    try:
        return int(b.get("user_id") or 0)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "user_id")) from None


@app.get("/api/lists/<int:lid>/notify-template")
def list_tpl_get(lid):
    """The owner: the template of the list for everyone, per person, what it inherits from the folder. Everyone else in
    the list: what limits THEM ({effective, by}); a list I do not see -> 404."""
    c = db()
    role = list_role(c, lid)
    if not role:
        raise Denied(404)
    if role == "owner":
        return jsonify(list_tpl_info(c, lid))
    t = tpl_for(c, lid, me()) or {"tpl": "all", "custom": {}}
    lr = c.execute("SELECT u.display_name, u.username FROM lists l JOIN users u ON u.id=l.owner_id WHERE l.id=?", (lid,)).fetchone()
    return jsonify(scope="list", list_id=lid, effective={"tpl": t["tpl"], "custom": t["custom"]},
                   by=(lr["display_name"] or lr["username"]) if lr else "", allowed=sorted(r for r in CUSTOM_ROWS if tpl_allows(t, r)))


@app.put("/api/lists/<int:lid>/notify-template")
def list_tpl_put(lid):
    """{tpl: read | work | all | custom | null (= from the folder / default), custom?: {event: 0|1}, user_id?: one person}
    -- only the list's owner (not an agent)."""
    need_collab()
    c, b = db(), body()
    role = list_role(c, lid)
    if not role:
        raise Denied(404)
    if role != "owner":
        raise Denied(403)
    _no_agent()
    try:
        tpl, cust = _tpl_in(b)
        uid = _uid_in(b)
    except BadInput as e:
        return err(str(e))
    if uid and (uid == me() or not c.execute("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (lid, uid)).fetchone()):
        return err(tr("unknown user"), 404)
    if tpl is None:
        c.execute("DELETE FROM list_notif WHERE list_id=? AND user_id=?", (lid, uid))
    else:
        c.execute("INSERT INTO list_notif(list_id,user_id,tpl,custom,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(list_id,user_id) "
                  "DO UPDATE SET tpl=excluded.tpl, custom=COALESCE(excluded.custom, custom), updated_at=excluded.updated_at",
                  (lid, uid, tpl, cust, iso(now_utc())))
    uset(c, me(), "notif_tpl_ask", "0")  # chosen: the one-time question is answered
    bump(c)
    c.commit()
    return jsonify(list_tpl_info(c, lid))


def _my_folder(c, f):
    from ..lists.lists import _in_folder
    return any(_in_folder(r[0] or "", f) for r in c.execute("SELECT folder FROM lists WHERE owner_id=? AND is_inbox=0", (me(),))) or \
        bool(c.execute("SELECT 1 FROM folder_people WHERE owner_id=? AND folder=?", (me(), f)).fetchone())


@app.get("/api/folders/notify-template")
def folder_tpl_get():
    """?folder=: the template of my folder (for its lists and the lists that come into it later)."""
    from ..lists.lists import clean_folder
    c = db()
    f = clean_folder(request.args.get("folder") or "", strict=False)
    if not f or not _my_folder(c, f):
        raise Denied(404)
    return jsonify(folder_tpl_info(c, me(), f))


@app.put("/api/folders/notify-template")
def folder_tpl_put():
    """{folder, tpl (null = from the parent folder / default), custom?, user_id?, reset_lists?: true = the lists in it drop
    their own template for everyone and follow the folder} -- my folder only."""
    from ..lists.lists import _in_folder, clean_folder
    need_collab()
    _no_agent()
    c, b = db(), body()
    f = clean_folder(str(b.get("folder") or ""), strict=False)
    if not f or not _my_folder(c, f):
        raise Denied(404)
    try:
        tpl, cust = _tpl_in(b)
        uid = _uid_in(b)
    except BadInput as e:
        return err(str(e))
    if uid and not c.execute("SELECT 1 FROM folder_people WHERE owner_id=? AND folder=? AND user_id=?", (me(), f, uid)).fetchone():
        return err(tr("unknown user"), 404)
    if "tpl" in b:
        if tpl is None:
            c.execute("DELETE FROM folder_notif WHERE owner_id=? AND folder=? AND user_id=?", (me(), f, uid))
        else:
            c.execute("INSERT INTO folder_notif(owner_id,folder,user_id,tpl,custom,updated_at) VALUES(?,?,?,?,?,?) "
                      "ON CONFLICT(owner_id,folder,user_id) DO UPDATE SET tpl=excluded.tpl, custom=COALESCE(excluded.custom, custom), "
                      "updated_at=excluded.updated_at", (me(), f, uid, tpl, cust, iso(now_utc())))
    if b.get("reset_lists") is True:
        for r in c.execute("SELECT id, folder FROM lists WHERE owner_id=? AND is_inbox=0", (me(),)).fetchall():
            if _in_folder(r["folder"] or "", f):
                c.execute("DELETE FROM list_notif WHERE list_id=? AND user_id=0", (r["id"],))
    uset(c, me(), "notif_tpl_ask", "0")
    bump(c)
    c.commit()
    return jsonify(folder_tpl_info(c, me(), f))


def folder_tpl_rename(c, uid, old, new):
    """A folder of uid was renamed / moved (old -> new, subfolders along): its templates go along."""
    from ..lists.lists import folder_under
    for r in c.execute("SELECT DISTINCT folder FROM folder_notif WHERE owner_id=?", (uid,)).fetchall():
        if folder_under(r[0], old):
            c.execute("UPDATE OR REPLACE folder_notif SET folder=? WHERE owner_id=? AND folder=?", (new + r[0][len(old):], uid, r[0]))


# ---------------------------------------------------------------- the one-time question to owners of lists shared before 2.33
def notif_ask_state(c, uid, s):
    """[{kind: list|folder, id?, folder?, name}] of my lists / folders shared before 2.33 (kept on "all"), while the
    question is open (setting notif_tpl_ask = "1"); else []."""
    if (s or {}).get("notif_tpl_ask") != "1":
        return []
    out = [{"kind": "folder", "folder": r[0], "name": r[0].split(_fsep())[-1]} for r in c.execute(
        "SELECT DISTINCT p.folder FROM folder_people p JOIN folder_notif n ON n.owner_id=p.owner_id AND n.folder=p.folder AND n.user_id=0 "
        "JOIN users hu ON hu.id=p.user_id AND COALESCE(hu.kind,'')!='agent' "
        "WHERE p.owner_id=? AND n.tpl='all' ORDER BY p.folder", (uid,))]
    out += [{"kind": "list", "id": r["id"], "name": r["name"]} for r in c.execute(
        """SELECT l.id, l.name FROM lists l JOIN list_notif n ON n.list_id=l.id AND n.user_id=0
           WHERE l.owner_id=? AND l.archived=0 AND n.tpl='all' AND EXISTS (SELECT 1 FROM list_members m JOIN users hu ON hu.id=m.user_id AND COALESCE(hu.kind,'')!='agent' WHERE m.list_id=l.id)
           ORDER BY l.name COLLATE NOCASE""", (uid,))]
    return out[:20]


@app.post("/api/notify-templates/asked")
def notif_ask_done():
    """The one-time question is answered ("Keep as it is" or "Choose template")."""
    c = db()
    uset(c, me(), "notif_tpl_ask", "0")
    c.commit()
    return jsonify(ok=True)


def notif_tpl_migrate(c):
    """Once (2.33.0): lists and folders shared so far keep every notification ("all", written explicitly); their owners
    are asked once. A list in a shared folder of its owner follows the folder (only the folder gets the row)."""
    from ..lists.lists import _in_folder
    now = iso(now_utc())
    folders = {}
    for r in c.execute("SELECT DISTINCT p.owner_id, p.folder FROM folder_people p JOIN users hu ON hu.id=p.user_id "
                       "AND COALESCE(hu.kind,'')!='agent'").fetchall():  # shared with people (only agents: nothing to ask)
        folders.setdefault(r[0], []).append(r[1])
        c.execute("INSERT OR IGNORE INTO folder_notif(owner_id,folder,user_id,tpl,custom,updated_at) VALUES(?,?,0,'all',NULL,?)", (r[0], r[1], now))
    owners, n = set(folders), 0
    for r in c.execute("""SELECT l.id, l.owner_id, l.folder FROM lists l WHERE l.owner_id IS NOT NULL
                          AND EXISTS (SELECT 1 FROM list_members m JOIN users hu ON hu.id=m.user_id AND COALESCE(hu.kind,'')!='agent' WHERE m.list_id=l.id AND m.user_id!=l.owner_id)""").fetchall():
        owners.add(r["owner_id"])
        if any(_in_folder(r["folder"] or "", f) for f in folders.get(r["owner_id"], [])):
            continue
        n += c.execute("INSERT OR IGNORE INTO list_notif(list_id,user_id,tpl,custom,updated_at) VALUES(?,0,'all',NULL,?)", (r["id"], now)).rowcount
    for uid in owners:
        if c.execute("SELECT 1 FROM users WHERE id=? AND COALESCE(kind,'')!='agent'", (uid,)).fetchone():
            uset(c, uid, "notif_tpl_ask", "1")
    return n, sum(len(v) for v in folders.values())


# ---------------------------------------------------------------- token API: read only (agents never change it)
@app.get("/api/v1/lists/<int:lid>/notify-template")
@v1_view
def v1_list_tpl(lid):
    v1_args(())
    return jsonify(v1_call(list_tpl_get, lid))


def notif_tpl_spec(paths, schemas, op, ok, errs, ref, pid, nul, page):
    schemas["NotifyTemplate"] = {"type": "object", "description": "2.33: the owner's ceiling for the notifications of the other people "
                                 "in a list (pushes only; the News list stays complete)", "properties": {
        "scope": {"type": "string", "enum": ["list"]}, "list_id": {"type": "integer"},
        "effective": {"type": "object", "properties": {"tpl": {"type": "string", "enum": list(NOTIF_TPLS)},
                                                         "custom": {"type": "object", "additionalProperties": {"type": "integer", "enum": [0, 1]}}}},
        "own": nul("object", description="Owner only: the list's own template for everyone (null = from the folder / default)"),
        "inherited": {"type": "object", "description": "Owner only: what the folder (or the default \"read\") gives"},
        "people": {"type": "array", "description": "Owner only: per person their own template (own, null = the list's) and the effective one",
                   "items": {"type": "object"}},
        "by": {"type": "string", "description": "Members: the owner who set it"},
        "allowed": {"type": "array", "items": {"type": "string", "enum": list(CUSTOM_ROWS)}, "description": "Members: events that may push"}}}
    paths["/lists/{id}/notify-template"] = {"get": op(
        "Notification template of a list (read only)", "Lists", ok(ref("NotifyTemplate")) | errs("404"), [pid(desc="List id")],
        desc="read = pushes only for mentions, assignments, direct replies and approvals; work = + comments on own / assigned "
             "tasks and due reminders; all = no limit; custom = the ticked events. The owner sees the whole setting, everyone "
             "else what limits them. Only the owner changes it, in the app; agents cannot.")}
