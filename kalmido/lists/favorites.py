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
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403, tr("Favourites are a personal setting of a person"))
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
    bump(c)
    c.commit()
    return jsonify(ok=True, favorite=on, fav_lists=",".join(map(str, ids)))


# 2.46.1 (#1361 point 4): "Quieter pushes from lists without a star" (user setting fav_quiet, default off): while the person has
# at least one favourite, a list without a star pushes only what concerns them directly (@mentions, assignments) and what
# they must not miss (reminders, approvals, shares, ...); the News stay complete, an explicit list bell (all / custom) wins
LC_FAV_QUIET_ROWS = ("comment", "reply", "follow", "newtask", "complete", "status", "unblock", "chat")


def lc_fav_quiet(c, uid, lid, row):
    if row not in LC_FAV_QUIET_ROWS:
        return False
    favs = vw_fav_ids(c, uid)
    return bool(favs) and lid not in favs


# 2.46.1 (#1361 point 6): a suggestion, never automatic: a list the person worked in a lot during the last 14 days (own
# changes of its tasks on at least LC_SUG_DAYS different days, LC_SUG_ACTS in all) and that has no star is offered ONCE
# ("Add to favourites?"); every list is asked at most once (fav_asked), the setting fav_suggest switches it off
LC_SUG_WINDOW, LC_SUG_DAYS, LC_SUG_ACTS = 14, 5, 20


@app.post("/api/favorites/suggestion")
def lc_fav_suggestion():
    """The one list to ask about now ({list_id, name} or list_id null); the list counts as asked from here on."""
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403, tr("Favourites are a personal setting of a person"))
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
