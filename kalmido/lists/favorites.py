"""2.40.0 (#1361): favourite lists and projects, personal per person (the user setting fav_lists).

Nobody else sees someone's stars (not the other members, not the agents): the ids live in the person's own user settings,
which /api/state hands only to that person. The web app reads them from there; this route sets / clears one star."""
from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, uset, usettings
from ..core.access import Denied, need_list
from ..accounts.session import me

VW_FAV_MAX = 500  # the same bound as the other id lists of the settings (clean_setting)


def vw_fav_ids(c, uid):
    """The person's favourite list ids, in the order they were starred."""
    return [int(x) for x in (usettings(c, uid).get("fav_lists") or "").split(",") if x.strip().isdigit()]


# 2.40.0 (#1361): one decorator per method, so parity_test / the route scans see both routes
@app.put("/api/lists/<int:lid>/favorite")
@app.delete("/api/lists/<int:lid>/favorite")
def vw_list_favorite(lid):
    """PUT {"on": true|false} (default true) stars / unstars list lid for the signed-in person; DELETE unstars it.
    404 for a list the person cannot see; agents have no favourites (403)."""
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403, tr("Favourites are a personal setting of a person"))
    c = db()
    on = request.method == "PUT" and bool((body() or {}).get("on", True))
    ids = [x for x in vw_fav_ids(c, me()) if x != lid]
    if on:
        need_list(c, lid, write=False)
        if len(ids) >= VW_FAV_MAX:
            ids = ids[1 - VW_FAV_MAX:]
        ids.append(lid)
    uset(c, me(), "fav_lists", ",".join(map(str, ids)))
    bump(c)
    c.commit()
    return jsonify(ok=True, favorite=on, fav_lists=",".join(map(str, ids)))
