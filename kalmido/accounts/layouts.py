"""2.32.0 (#1063, #983): views built from blocks ("Customize"): one arrangement per person and view (user settings
view_today, view_time, view_agents, view_projects and, since 2.17.0, dashboard), optionally a different one for phones,
and the project page: a standard for everyone set by the owner / admins (lists.page_layout) that each person can
override for themselves (table list_layouts). Only the person themselves change these: agents get 403."""
import json
import re

from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, now_utc
from ..core.access import Denied, need_list
from ..accounts.session import me
from ..personal.timetrack import BadInput

LAYOUT_KEYS = ("view_today", "view_time", "view_agents", "view_projects")
LAYOUT_BLOCK_RE = re.compile(r"[a-z][a-z0-9_]{0,23}")
LAYOUT_BLOCKS_MAX = 40
LAYOUT_OPTS_MAX = 10          # saved switches per block
LAYOUT_OPT_STR_MAX = 40


def _blocks(xs, allowed):
    if not isinstance(xs, list) or len(xs) > LAYOUT_BLOCKS_MAX:
        raise BadInput(tr("Invalid layout"))
    for x in xs:
        if not isinstance(x, str) or not LAYOUT_BLOCK_RE.fullmatch(x) or (allowed and x not in allowed):
            raise BadInput(tr("Invalid layout"))
    return list(dict.fromkeys(xs))


def _opts(o, allowed):
    if not isinstance(o, dict) or len(o) > LAYOUT_BLOCKS_MAX:
        raise BadInput(tr("Invalid layout"))
    out = {}
    for k, v in o.items():
        if not isinstance(k, str) or not LAYOUT_BLOCK_RE.fullmatch(k) or (allowed and k not in allowed) \
                or not isinstance(v, dict) or len(v) > LAYOUT_OPTS_MAX:
            raise BadInput(tr("Invalid layout"))
        vv = {}
        for n, x in v.items():
            if not isinstance(n, str) or not LAYOUT_BLOCK_RE.fullmatch(n):
                raise BadInput(tr("Invalid layout"))
            if isinstance(x, bool) or x is None or (isinstance(x, (int, float)) and abs(x) < 1e9):
                vv[n] = x
            elif isinstance(x, str) and len(x) <= LAYOUT_OPT_STR_MAX:
                vv[n] = x
            else:
                raise BadInput(tr("Invalid layout"))
        out[k] = vv
    return out


def _part(o, allowed, top):
    keys = {"order", "hidden", "half", "full"} | ({"opts", "mobile"} if top else set())
    if not isinstance(o, dict) or set(o) - keys:
        raise BadInput(tr("Invalid layout"))
    out = {}
    for k in ("order", "hidden", "half", "full"):
        if k in o:
            out[k] = _blocks(o[k], allowed)
    if top and "opts" in o:
        out["opts"] = _opts(o["opts"], allowed)
    if top and o.get("mobile") is not None:
        out["mobile"] = _part(o["mobile"], allowed, False)
    return out


def clean_layout(v, allowed=None):
    """A layout as stored: '' (the default) or compact json {"order", "hidden", "half", "full", "opts", "mobile"}.
    order = the blocks top to bottom (unknown / new blocks are appended by the client), hidden = not shown,
    half / full = the width chosen against the block's default, opts = saved switches of a block ({block: {name: value}}),
    mobile = the same without opts and mobile, used on phones when set ("Different on the phone")."""
    if v is None or v == "" or v == {}:
        return ""
    try:
        o = json.loads(v) if isinstance(v, str) else v
    except ValueError:
        raise BadInput(tr("Invalid layout")) from None
    s = json.dumps(_part(o, allowed, True), separators=(",", ":"))
    if len(s) > 8000:
        raise BadInput(tr("Invalid layout"))
    return s


def need_person():
    """Views are arranged by the person themselves: never by an agent (its token or its session)."""
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot change how views are arranged"))


# ---------------------------------------------------------------- the project page (#983)

def page_layouts(c, lid, uid, role):
    """{std, mine, can_std} of the project page of list lid: the standard for everyone, the person's own override."""
    r = c.execute("SELECT page_layout FROM lists WHERE id=?", (lid,)).fetchone()
    m = c.execute("SELECT layout FROM list_layouts WHERE list_id=? AND user_id=?", (lid, uid)).fetchone()
    return {"std": (r["page_layout"] if r else "") or "", "mine": (m["layout"] if m else "") or "",
            "can_std": role in ("owner", "admin")}


@app.put("/api/lists/<int:lid>/layout")
def list_layout_put(lid):
    """The project page arrangement. {layout: json | '' | null, scope: 'mine' (default) | 'standard'}.
    mine: the person's own arrangement ('' / null = back to the standard); standard: for everyone in the project, only the
    owner and admins ('' / null = the built-in default). Agents: 403."""
    need_person()
    b = body()
    if set(b) - {"layout", "scope"}:
        raise BadInput(tr("Invalid layout"))
    scope = b.get("scope") or "mine"
    if scope not in ("mine", "standard"):
        raise BadInput(tr("Invalid layout"))
    c = db()
    from ..lists.projects import need_overview
    role = need_overview(c, lid, write=False)
    v = clean_layout(b.get("layout"))
    if scope == "standard":
        if role not in ("owner", "admin"):
            raise Denied(403, tr("Only the owner or an admin of the project can change the standard"))
        c.execute("UPDATE lists SET page_layout=? WHERE id=?", (v, lid))
    elif v:
        c.execute("""INSERT INTO list_layouts(list_id,user_id,layout,updated_at) VALUES(?,?,?,?)
                     ON CONFLICT(list_id,user_id) DO UPDATE SET layout=excluded.layout, updated_at=excluded.updated_at""",
                  (lid, me(), v, iso(now_utc())))
    else:
        c.execute("DELETE FROM list_layouts WHERE list_id=? AND user_id=?", (lid, me()))
    bump(c)
    c.commit()
    return jsonify(page_layouts(c, lid, me(), role))


@app.get("/api/lists/<int:lid>/layout")
def list_layout_get(lid):
    c = db()
    from ..lists.projects import need_overview
    role = need_overview(c, lid, write=False)
    return jsonify(page_layouts(c, lid, me(), role))
