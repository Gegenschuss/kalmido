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

LAYOUT_KEYS = ("view_today", "view_time", "view_agents", "view_projects",
               "view_review")  # 2.43.0 (#1452): the review (and its journal) on the builder
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
    out = {"std": (r["page_layout"] if r else "") or "", "mine": (m["layout"] if m else "") or "",
           "can_std": role in ("owner", "admin")}
    out.update(wg_pinboard(c, lid, role))  # 2.43.0 (#1346): block colours + the notepads
    return out


@app.put("/api/lists/<int:lid>/layout")
def list_layout_put(lid):
    """The project page arrangement. {layout: json | '' | null, scope: 'mine' (default) | 'standard' | 'promote'}.
    promote (2.43.0, #1452): layout becomes the standard and the person's own arrangement goes (owner / admins).
    mine: the person's own arrangement ('' / null = back to the standard); standard: for everyone in the project, only the
    owner and admins ('' / null = the built-in default). Agents: 403."""
    need_person()
    b = body()
    if set(b) - {"layout", "scope"}:
        raise BadInput(tr("Invalid layout"))
    scope = b.get("scope") or "mine"
    if scope not in ("mine", "standard", "promote"):
        raise BadInput(tr("Invalid layout"))
    c = db()
    from ..lists.projects import need_overview
    role = need_overview(c, lid, write=False)
    v = clean_layout(b.get("layout"))
    if scope in ("standard", "promote"):
        if role not in ("owner", "admin"):
            raise Denied(403, tr("Only the owner or an admin of the project can change the standard"))
        c.execute("UPDATE lists SET page_layout=? WHERE id=?", (v, lid))
        if scope == "promote":  # 2.43.0 (#1452): my arrangement becomes the standard, I follow it from now on
            c.execute("DELETE FROM list_layouts WHERE list_id=? AND user_id=?", (lid, me()))
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


# ---------------------------------------------------------------- 2.43.0 (#1452): a standard for everyone of the other views
# The start page, Today, Time tracking, the agents / projects overview and the review: the instance admins set a standard
# (global settings lystd_<key>, same shape as the person's value) that everyone without an own arrangement sees. There is no
# general per-organisation setting yet, so the standard is one for the instance. A person's own value wins when it has an
# arrangement (the client merges: own switches stay, layout parts come from the standard while the own value has none).

WG_STD_KEYS = ("dashboard",) + LAYOUT_KEYS


def wg_std_all(c):
    from ..core.db import gsetting
    return {k: gsetting(c, "lystd_" + k) or "" for k in WG_STD_KEYS}


@app.get("/api/layouts/std")
def wg_std_get():
    c = db()
    return jsonify({"layouts": wg_std_all(c), "can": bool(g.user["is_admin"])})


@app.put("/api/layouts/std/<key>")
def wg_std_put(key):
    """{layout: json | '' | null, promote: bool}: the standard of a view for everyone (instance admins only; agents 403).
    promote: the admin's own value of that view goes back to '' as well (they follow the standard from now on)."""
    need_person()
    if key not in WG_STD_KEYS:
        raise BadInput(tr("Invalid layout"))
    if not g.user["is_admin"]:
        raise Denied(403, tr("Only an admin can change the standard"))
    b = body()
    if set(b) - {"layout", "promote"}:
        raise BadInput(tr("Invalid layout"))
    from ..core.db import gset
    from ..accounts.settings import DASH_WIDGETS
    v = clean_layout(b.get("layout"), DASH_WIDGETS if key == "dashboard" else None)
    c = db()
    gset(c, "lystd_" + key, v)
    if b.get("promote"):
        c.execute("DELETE FROM user_settings WHERE user_id=? AND key=?", (me(), key))
    bump(c)
    c.commit()
    return jsonify({"layouts": wg_std_all(c), "can": True})


# ---------------------------------------------------------------- 2.43.0 (#1346): the project page as a pin board
# Colours per block for everyone in the project (lists.page_style, json {block: colour}) and notepads (table list_notepads:
# Markdown, own title; block key "np<id>"). Everyone who sees the project page reads them, people with write access to the
# list change them. Agents: not through these routes (they refuse them, the overview of an agent has neither); 2.51.0
# (#1352): agents write their own notepads through the REST API (agents/agentpin.py).

WG_COLORS = ("yellow", "green", "blue", "red", "purple", "grey")
WG_PADS_MAX = 20
WG_PAD_TITLE_MAX = 200
WG_PAD_BODY_MAX = 20000


def wg_pad_dict(r):
    # 2.51.0 (#1352): agent_id = the agent that wrote it (marked on the page; agents/agentpin.py)
    return {"id": r["id"], "title": r["title"], "body": r["body"], "updated_at": r["updated_at"], "updated_by": r["updated_by"],
            "agent_id": r["agent_id"] if "agent_id" in r.keys() else None}


def wg_pinboard(c, lid, role):
    from ..agents.core import is_agent
    from ..core.access import WRITE_ROLES
    if is_agent(g.user):
        return {}
    r = c.execute("SELECT page_style FROM lists WHERE id=?", (lid,)).fetchone()
    try:
        st = json.loads(r["page_style"] or "{}") if r else {}
    except ValueError:
        st = {}
    pads = [wg_pad_dict(x) for x in c.execute("SELECT * FROM list_notepads WHERE list_id=? ORDER BY id", (lid,))]
    return {"style": st if isinstance(st, dict) else {}, "pads": pads, "can_style": role in WRITE_ROLES}


def _wg_role(c, lid, write):
    need_person()
    from ..lists.projects import need_overview
    return need_overview(c, lid, write=write)


def _wg_pad_text(b, partial):
    out = {}
    for k, mx in (("title", WG_PAD_TITLE_MAX), ("body", WG_PAD_BODY_MAX)):
        if k in b:
            v = b[k] if b[k] is not None else ""
            if not isinstance(v, str) or len(v) > mx:
                raise BadInput(tr("Invalid notepad"))
            out[k] = v.strip() if k == "title" else v
        elif not partial:
            out[k] = ""
    return out


@app.put("/api/lists/<int:lid>/page-style")
def wg_style_put(lid):
    """{block, color}: the colour of a block of the project page for everyone ('' / null = none). Write access."""
    b = body()
    if set(b) - {"block", "color"} or not isinstance(b.get("block"), str) or not LAYOUT_BLOCK_RE.fullmatch(b["block"]):
        raise BadInput(tr("Invalid colour"))
    col = b.get("color") or ""
    if col and col not in WG_COLORS:
        raise BadInput(tr("Invalid colour"))
    c = db()
    role = _wg_role(c, lid, True)
    st = wg_pinboard(c, lid, role).get("style", {})
    if col:
        st[b["block"]] = col
    else:
        st.pop(b["block"], None)
    if len(st) > LAYOUT_BLOCKS_MAX:
        raise BadInput(tr("Invalid colour"))
    c.execute("UPDATE lists SET page_style=? WHERE id=?", (json.dumps(st, separators=(",", ":")) if st else "", lid))
    bump(c)
    c.commit()
    return jsonify(page_layouts(c, lid, me(), role))


@app.post("/api/lists/<int:lid>/notepads")
def wg_pad_create(lid):
    """{title?, body?}: a new notepad on the project page (write access; at most WG_PADS_MAX per project)."""
    from ..core.pg import insert_id
    b = body()
    if set(b) - {"title", "body"}:
        raise BadInput(tr("Invalid notepad"))
    v = _wg_pad_text(b, False)
    c = db()
    role = _wg_role(c, lid, True)
    # 2.51.0 (#1352): the agents' notepads (at most 3 each, agents/agentpin.py) do not fill the people's pin board
    if c.execute("SELECT COUNT(*) FROM list_notepads WHERE list_id=? AND agent_id IS NULL", (lid,)).fetchone()[0] >= WG_PADS_MAX:
        raise Denied(409, tr("At most {0} notepads", WG_PADS_MAX))
    ts = iso(now_utc())
    nid = insert_id(c, "INSERT INTO list_notepads(list_id,title,body,created_by,created_at,updated_by,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (lid, v["title"], v["body"], me(), ts, me(), ts))
    bump(c)
    c.commit()
    return jsonify({**page_layouts(c, lid, me(), role), "id": nid})


def _wg_pad(c, pid, write):
    r = c.execute("SELECT * FROM list_notepads WHERE id=?", (pid,)).fetchone()
    if not r:
        raise Denied(404)
    return r, _wg_role(c, r["list_id"], write)


@app.patch("/api/notepads/<int:pid>")
def wg_pad_patch(pid):
    """{title?, body?, base?}: change a notepad (write access). base = the updated_at the editor started from: when someone
    else saved in between, 409 with the current notepad (the client keeps the typed text and asks)."""
    b = body()
    if set(b) - {"title", "body", "base"}:
        raise BadInput(tr("Invalid notepad"))
    v = _wg_pad_text(b, True)
    c = db()
    r, role = _wg_pad(c, pid, True)
    if b.get("base") and b["base"] != r["updated_at"] and r["updated_by"] != me():
        return jsonify({"error": tr("Someone else changed this notepad in the meantime"), "pad": wg_pad_dict(r)}), 409
    if v:
        sets = ", ".join(f"{k}=?" for k in v)
        c.execute(f"UPDATE list_notepads SET {sets}, updated_by=?, updated_at=? WHERE id=?", (*v.values(), me(), iso(now_utc()), pid))
        bump(c)
        c.commit()
    return jsonify(page_layouts(c, r["list_id"], me(), role))


@app.delete("/api/notepads/<int:pid>")
def wg_pad_delete(pid):
    c = db()
    r, role = _wg_pad(c, pid, True)
    c.execute("DELETE FROM list_notepads WHERE id=?", (pid,))
    st = wg_pinboard(c, r["list_id"], role).get("style", {})
    if st.pop(f"np{pid}", None):
        c.execute("UPDATE lists SET page_style=? WHERE id=?", (json.dumps(st, separators=(",", ":")) if st else "", r["list_id"]))
    bump(c)
    c.commit()
    return jsonify({**page_layouts(c, r["list_id"], me(), role), "pad": wg_pad_dict(r)})

