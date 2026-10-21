"""2.55.0 (#1066): agents propose how a view is arranged -- the person decides.

An agent with the right "layouts" (scope, off for every agent until a person turns it on) reads the arrangement of a view
of the person it works for (GET /api/v1/layouts/<view>: block keys, order, widths, heights, hidden -- never what the blocks
show), which blocks the view has (GET /api/v1/layouts/blocks) and sends ONE proposal (POST /api/v1/layouts/proposals,
MCP propose_layout). It changes nothing itself: the proposal is a ready proposal job of kind "layout" (agent_jobs, as the
time / shoot proposals of 2.51), the person gets News + push "Proposal ready" and a card with before / after; 👍 stores it
as a saved arrangement "<name> (proposal by <agent>)" (accounts/layoutsets.py lyv_save, source agent) and, ticked by
default, uses it at once; 👎 discards it. The agent hears both as the event job. Undo = one step back to the previous
arrangement.

Whose views: the token's agent works for its owner (a personal agent) or, for a team agent, a person who may chat with it
(user_id, agents/agenttime.py atm_person) and who belongs to the agent's organisation. The project page (view
"list:<id>") only when the list is shared with the agent (and within agents.list_ids) and the person sees its project
page. One open proposal per agent, person and view (a new one replaces the old one); a proposal expires after LYP_DAYS.
Kalmido never runs a model itself."""
import json
from datetime import timedelta

from flask import g, jsonify, request

from ..core.config import app
from ..core.pg import insert_id
from ..core.i18n import N_, tr
from ..core.db import bump, db, iso, now_utc, gsetting, parse_iso, uset
from ..core.access import Denied, list_role, acx_of, is_project
from ..accounts.session import me
from ..core.errors import BadInput
from ..api.common import v1_args, v1_err, v1_json, v1_view

LYP_KIND = "layout"
LYP_DAYS = 14                 # an open proposal expires after this many days
LYP_DAY_MAX = 20              # proposals of one agent for one person per 24 hours
LYP_W, LYP_H = (2, 3, 4, 6), (1, 2, 3)   # widths in columns of six, heights (1 compact, 2 normal, 3 tall)
LYP_NAME_MAX = 40             # the name part; " (proposal by <agent>)" follows
# the blocks of each view as the client builds them (static/js/dashboard.js LY, projects.js POV_BLOCKS):
# (key, name, default width, fixed = cannot be hidden), in the default order. Names stay English (agents work in any language).
LYP_BLOCKS = {
    "dashboard": (("wait", "Waiting for you", 2, False), ("today", "Today", 2, False), ("news", "News", 2, False),
                  ("chat", "Team chat", 2, False), ("projects", "Projects", 2, False), ("pinned", "Pinned", 2, False),
                  ("notes", "Notes", 2, False), ("agents", "Agents", 2, False), ("stats", "Statistics", 2, False),
                  ("search", "Search", 2, False), ("family", "Family", 2, False),
                  ("kpi", "Figures", 2, False)),  # 2.55.1: shown only to office admins (2.50.0 #1197)
    "view_today": (("brief", "Briefing", 6, False), ("wait", "Waiting for you", 6, False), ("review", "Daily review", 6, False),
                   ("overdue", "Overdue", 6, False), ("events", "Events today", 6, False), ("tasks", "Tasks", 6, True),
                   ("inbox", "Basket", 6, False)),
    "view_time": (("tiles", "Totals", 6, False), ("chart", "Per day", 6, False), ("lists", "By list and task", 6, False),
                  ("entries", "Entries", 6, False)),
    "view_agents": (("agents", "Agents", 6, False), ("usage", "Usage", 6, False), ("jobs", "Jobs", 6, True),
                    ("hint", "Explanation", 6, False)),
    "view_projects": (("tiles", "Totals", 6, False), ("projects", "Projects", 6, True), ("note", "Explanation", 6, False)),
    "view_review": (("done", "Done", 3, False), ("open", "Still open", 3, False), ("moved", "Moved", 3, False),
                    ("next", "Coming up", 3, False), ("journal", "Journal", 3, False)),
}
LYP_PAGE = (("kpis", "Key figures", 6, False), ("desc", "Description", 6, False), ("status", "Status updates", 3, False),
            ("ms", "Milestones", 3, False), ("files", "Project files", 6, False), ("links", "Key links", 3, False),
            ("people", "Members", 3, False), ("notes", "Notes", 3, False), ("chat", "Team chat", 3, False),
            ("time", "Tracked time", 3, False))
# the start page's own default (dashboard.js LY.home.def, 2.45.0 #1504) when neither the person nor an admin arranged it
LYP_DEFAULTS = {"dashboard": {"order": ["today", "agents", "news", "projects", "wait", "pinned", "chat", "notes", "stats", "family",
                                        "search"], "hidden": ["search"], "opts": {"today": {"lw": 4}, "news": {"lw": 4}}}}
LYP_VIEW_NAMES = {"dashboard": N_("Start page"), "view_today": N_("Today"), "view_time": N_("Time tracking"),
                  "view_agents": N_("Agents"), "view_projects": N_("Projects"), "view_review": N_("Review")}


def lyp_reg(view, blocks, name=None):
    """2.55.0 (#1067): a view added to the builder announces its blocks for agents: [(key, English name, width, fixed)]."""
    LYP_BLOCKS[view] = tuple((str(k), str(n), int(w) if w in LYP_W else 6, bool(f)) for k, n, w, f in blocks)
    if name:
        LYP_VIEW_NAMES[view] = name


def lyp_view_name(key):
    return tr("Project page") if key.startswith("list:") else tr(LYP_VIEW_NAMES.get(key, key))


# ---------------------------------------------------------------- whose view, which blocks
def lyp_person(c, aid, uid_arg):
    """The person agent aid proposes for: its owner (personal agent) or user_id (a person who may chat with it), and in
    the agent's organisation when it has one. 404 for everyone else."""
    from ..agents.agenttime import atm_person
    pid, _ = atm_person(c, {"user_id": uid_arg})
    if pid == aid:
        raise BadInput(tr("Missing field: {0}", "user_id"))
    a = c.execute("SELECT org_id FROM agents WHERE user_id=?", (aid,)).fetchone()
    if a and a["org_id"] and a["org_id"] not in (acx_of(c, pid).org_ids or ()):
        raise Denied(404)
    return pid


def lyp_need(c, aid, pid, key):
    """The view key is one an agent may propose for (else 400 / 404); returns the block catalogue of that view."""
    from ..accounts.layoutsets import lyv_key_ok
    if not isinstance(key, str) or not lyv_key_ok(key):
        raise BadInput(tr("Invalid value: {0}", "view"))
    if not key.startswith("list:"):
        if key not in LYP_BLOCKS:
            raise BadInput(tr("Agents cannot propose an arrangement for this view"))
        return LYP_BLOCKS[key]
    from ..agents.safety import ids_parse
    lid = int(key[5:])
    a = c.execute("SELECT list_ids FROM agents WHERE user_id=?", (aid,)).fetchone()
    # the list shared with the agent (its token's list limit applies in list_role), inside its own list limit, and the
    # person sees that project page; either missing = 404 (no hint that the list exists)
    if not list_role(c, lid) or (a and a["list_ids"] and lid not in ids_parse(a["list_ids"])) \
            or not list_role(c, lid, pid) or not is_project(c, lid):
        raise Denied(404)
    pads = [(f"np{r[0]}", "Notepad", 3, False) for r in c.execute("SELECT id FROM list_notepads WHERE list_id=? ORDER BY id", (lid,))]
    return LYP_PAGE + tuple(pads)


def _has_layout(o):
    return bool(o) and bool(o.get("order") or o.get("hidden") or o.get("half") or o.get("full") or o.get("mobile")
                            or any(isinstance(x, dict) and (x.get("lw") is not None or x.get("lh") is not None)
                                   for x in (o.get("opts") or {}).values()))


def _load(s):
    try:
        o = json.loads(s or "{}")
    except ValueError:
        return {}
    return o if isinstance(o, dict) else {}


def lyp_own(c, pid, key):
    """The person's own stored value of the view ('' = none)."""
    if key.startswith("list:"):
        r = c.execute("SELECT layout FROM list_layouts WHERE list_id=? AND user_id=?", (int(key[5:]), pid)).fetchone()
    else:
        r = c.execute("SELECT value FROM user_settings WHERE user_id=? AND key=?", (pid, key)).fetchone()
    return (r[0] if r else "") or ""


def lyp_value(c, pid, key):
    """(the arrangement the person sees as a dict, source own | standard | default)."""
    own = _load(lyp_own(c, pid, key))
    if _has_layout(own):
        return own, "own"
    if key.startswith("list:"):
        r = c.execute("SELECT page_layout FROM lists WHERE id=?", (int(key[5:]),)).fetchone()
        std = _load(r[0] if r else "")
    else:
        std = _load(gsetting(c, "lystd_" + key))
    if _has_layout(std):
        return std, "standard"
    return dict(LYP_DEFAULTS.get(key) or {}), "default"


def _width(b, part, opts):
    k, _, dw, _ = b
    lw = (opts.get(k) or {}).get("lw")
    if lw in LYP_W:
        return lw
    if k in (part.get("full") or []):
        return 6
    if k in (part.get("half") or []):
        return dw if dw < 6 else 3
    return dw


def lyp_out(cat, o):
    """A stored arrangement -> what an agent reads: block keys only, the full order (new blocks where they stand by
    default, as the client does), widths and heights of every block, hidden ones, the phone part when there is one."""
    keys = [b[0] for b in cat]
    fixed = {b[0] for b in cat if b[3]}

    def part(p, opts):
        order = [k for k in (p.get("order") or []) if k in keys]
        for i, k in enumerate(keys):
            if k not in order:
                nx = next((x for x in keys[i + 1:] if x in order), None)
                order.insert(order.index(nx) if nx else len(order), k)
        return {"order": list(dict.fromkeys(order)),
                "hidden": [k for k in keys if k in (p.get("hidden") or []) and k not in fixed],
                "widths": {b[0]: _width(b, p, opts) for b in cat}}
    opts = o.get("opts") if isinstance(o.get("opts"), dict) else {}
    out = part(o, opts)
    out["heights"] = {k: (opts.get(k) or {}).get("lh") if (opts.get(k) or {}).get("lh") in LYP_H else 2 for k in keys}
    m = o.get("mobile")
    out["mobile"] = {k: v for k, v in part(m, {}).items() if k != "widths"} if isinstance(m, dict) else None
    return out


def _keys_in(cat, v, what):
    keys = [b[0] for b in cat]
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > 60:
        raise BadInput(tr("Invalid value: {0}", what))
    for x in v:
        if x not in keys:
            raise BadInput(tr("Unknown block “{0}” (GET /api/v1/layouts/blocks lists the blocks of the view)", str(x)[:40]))
    return list(dict.fromkeys(v))


def lyp_in(cat, b, base=None):
    """What an agent sends {order, hidden, widths, heights, mobile: {order, hidden}} -> the stored shape (layouts.py
    clean_layout: order, hidden, half / full against the block's default for 2.42, opts lw / lh). Unknown blocks: 400.
    base = the arrangement the person sees now (read shape): the named blocks come first, the others keep their order after
    them; a field left out (hidden, a block's width / height, mobile) stays as it is."""
    from ..agents.proposals import _p_keys
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid value: {0}", "layout"))
    _p_keys(b, "layout", ("order", "hidden", "widths", "heights", "mobile"))
    fixed = {x[0] for x in cat if x[3]}
    out = {}
    order = _keys_in(cat, b.get("order"), "layout.order")
    hidden = _keys_in(cat, b.get("hidden"), "layout.hidden")
    if base:
        order = order + [k for k in base["order"] if k not in order]
        hidden = hidden if "hidden" in b else [k for k in base["hidden"] if k not in fixed]
        b = {**b, "widths": {**base["widths"], **(b.get("widths") or {})} if isinstance(b.get("widths") or {}, dict) else b.get("widths"),
             "heights": {**base["heights"], **(b.get("heights") or {})} if isinstance(b.get("heights") or {}, dict) else b.get("heights")}
        if "mobile" not in b and base.get("mobile"):
            b["mobile"] = base["mobile"]
    if set(hidden) & fixed:
        raise BadInput(tr("This block cannot be hidden: {0}", sorted(set(hidden) & fixed)[0]))
    if order:
        out["order"] = order
    if hidden:
        out["hidden"] = hidden
    opts, half, full = {}, [], []
    for f, allowed in (("widths", LYP_W), ("heights", LYP_H)):
        v = b.get(f)
        if v is None:
            continue
        if not isinstance(v, dict):
            raise BadInput(tr("Invalid value: {0}", "layout." + f))
        _keys_in(cat, list(v), "layout." + f)
        for k, x in v.items():
            if isinstance(x, bool) or x not in allowed:
                raise BadInput(tr("Invalid value: {0}", f"layout.{f}.{k}"))
    for k, _, dw, _ in cat:
        w, h = (b.get("widths") or {}).get(k, dw), (b.get("heights") or {}).get(k, 2)
        x = {}
        if w != dw:
            x["lw"] = w
        if h != 2:
            x["lh"] = h
        if x:
            opts[k] = x
        size, dsize = "full" if w >= 4 else "half", "full" if dw == 6 else "half"
        if size != dsize:
            (full if size == "full" else half).append(k)
    if half:
        out["half"] = half
    if full:
        out["full"] = full
    if opts:
        out["opts"] = opts
    m = b.get("mobile")
    if m is not None:
        if not isinstance(m, dict):
            raise BadInput(tr("Invalid value: {0}", "layout.mobile"))
        _p_keys(m, "layout.mobile", ("order", "hidden"))
        mh = _keys_in(cat, m.get("hidden"), "layout.mobile.hidden")
        if set(mh) & fixed:
            raise BadInput(tr("This block cannot be hidden: {0}", sorted(set(mh) & fixed)[0]))
        out["mobile"] = {k: v for k, v in (("order", _keys_in(cat, m.get("order"), "layout.mobile.order")), ("hidden", mh)) if v}
    if not out or (base and lyp_out(cat, out) == base):
        raise BadInput(tr("The proposal does not change anything"))
    return out


def lyp_merge(new, own):
    """The proposed arrangement with the person's own block switches kept (opts other than width / height)."""
    out = json.loads(json.dumps(new))
    for k, x in ((own or {}).get("opts") or {}).items():
        sw = {n: v for n, v in (x or {}).items() if n not in ("lw", "lh")} if isinstance(x, dict) else {}
        if sw:
            out.setdefault("opts", {}).setdefault(k, {}).update(sw)
    return out


# ---------------------------------------------------------------- the routes for agents
def _lyp_agent():
    from ..agents.core import need_agent
    from ..api.scopes import need_scope
    aid = need_agent()
    need_scope("layouts")
    return aid


@app.get("/api/v1/layouts/blocks")
@v1_view
def v1_lyp_blocks():
    """?view=<key>&user_id= -> the blocks of a view: [{key, name, width, fixed}] in the default order, and the views."""
    a = v1_args(("view", "user_id"))
    aid = _lyp_agent()
    c = db()
    pid = lyp_person(c, aid, a.get("user_id"))
    key = a.get("view") or "dashboard"
    cat = lyp_need(c, aid, pid, key)
    return jsonify(view=key, user_id=pid, views=sorted(LYP_BLOCKS), widths=list(LYP_W), heights=list(LYP_H),
                   blocks=[{"key": k, "name": n, "width": w, "fixed": f} for k, n, w, f in cat])


@app.get("/api/v1/layouts/<view>")
@v1_view
def v1_lyp_get(view):
    """The arrangement the person sees in a view (?user_id=): block keys, order, widths, heights, hidden -- no content."""
    a = v1_args(("user_id",))
    aid = _lyp_agent()
    c = db()
    pid = lyp_person(c, aid, a.get("user_id"))
    cat = lyp_need(c, aid, pid, view)
    o, src = lyp_value(c, pid, view)
    return jsonify(view=view, user_id=pid, source=src, layout=lyp_out(cat, o))


def lyp_expire(c):
    """Open layout proposals older than LYP_DAYS are discarded (the agent is not told: it simply expired)."""
    ts = iso(now_utc())
    c.execute("""UPDATE agent_jobs SET prop_state='discarded', state='stopped', updated_at=? WHERE kind=? AND prop_state='ready'
                 AND created_at<?""", (ts, LYP_KIND, iso(now_utc() - timedelta(days=LYP_DAYS))))


@app.post("/api/v1/layouts/proposals")
@v1_view
def v1_lyp_propose():
    """{view, name, layout: {order, hidden, widths, heights, mobile}, summary?, user_id?} -> a ready proposal job (kind layout)
    for the person; an open one of this agent for the same view is replaced. Nothing changes until the person accepts it."""
    from ..agents.core import JOB_TITLE_MAX, job_dict
    from ..agents.proposals import _p_str, prop_ready_notify, prop_validate, PROP_MAX_BYTES
    from ..agents.usage import usage_block
    v1_args(())
    aid = _lyp_agent()
    if len(request.data or b"") > PROP_MAX_BYTES:
        return v1_err(413, tr("The proposal is too large (at most {0} KB)", PROP_MAX_BYTES // 1024))
    b = v1_json()
    c = db()
    pid = lyp_person(c, aid, b.get("user_id"))
    if usage_block(c, aid):
        return v1_err(409, tr("You reached your usage limit"))
    key = b.get("view")
    inp = {"user_id": pid, "view": key}
    p = prop_validate(LYP_KIND, {k: v for k, v in b.items() if k != "user_id"}, inp)
    lyp_expire(c)
    since = iso(now_utc() - timedelta(days=1))
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND user_id=? AND kind=? AND created_at>=?",
                 (aid, pid, LYP_KIND, since)).fetchone()[0] >= LYP_DAY_MAX:
        return v1_err(429, tr("At most {0} arrangement proposals per person and day", LYP_DAY_MAX))
    ts = iso(now_utc())
    # one open proposal per agent, person and view: the new one replaces the old one (its News is marked read)
    for r in c.execute("""SELECT id FROM agent_jobs WHERE agent_id=? AND user_id=? AND kind=? AND prop_state='ready'
                          AND input::jsonb->>'view' = ?""", (aid, pid, LYP_KIND, key)).fetchall():
        c.execute("UPDATE agent_jobs SET prop_state='discarded', state='stopped', updated_at=? WHERE id=?", (ts, r[0]))
        c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND kind='proposal' AND read_at IS NULL AND data->>'job' = ?",
                  (ts, pid, str(r[0])))
    title = _p_str(b.get("title"), "title", 120) or tr("New arrangement: {0}", lyp_view_name(key))
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id,proposal)
                       VALUES(?,NULL,?,?,'waiting','',?,?,?,?,'ready',?,?)""",
                    (aid, pid, title[:JOB_TITLE_MAX], ts, ts, LYP_KIND, json.dumps(inp, ensure_ascii=False),
                     int(key[5:]) if key.startswith("list:") else None, json.dumps(p, ensure_ascii=False)))
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    prop_ready_notify(c, j)
    bump(c)
    c.commit()
    return jsonify({**job_dict(c, j), "proposal": p}), 201


# ---------------------------------------------------------------- the hooks of agents/proposals.py
def lyp_validate(b, inp):
    """prop_validate for kind layout: {view, name, layout, summary} -> {view, name, layout (stored shape), proposed (read shape)}.
    Checks again who it is for (the job's person) and that the agent may propose for that view."""
    from ..agents.proposals import _p_keys, _p_str
    _p_keys(b, "", ("kind", "summary", "view", "name", "layout", "title"))
    c = db()
    pid = int(inp.get("user_id") or 0)
    key = inp.get("view") if inp.get("view") is not None else b.get("view")
    if b.get("view") not in (None, key):
        raise BadInput(tr("Invalid value: {0}", "view"))
    cat = lyp_need(c, me(), pid, key)
    lay = lyp_in(cat, b.get("layout"), lyp_out(cat, lyp_value(c, pid, key)[0]))
    from ..accounts.layoutsets import lyv_clean
    lyv_clean(key, lay)  # the same check as every stored arrangement
    return {"view": key, "name": _p_str(b.get("name"), "name", LYP_NAME_MAX, True), "layout": lay,
            "proposed": lyp_out(cat, lay)}


def lyp_view_extra(c, j):
    """For the card: the arrangement the person sees now (read shape) and the block names (before / after)."""
    p = json.loads(j["proposal"] or "null") or {}
    key = p.get("view")
    if not key or j["user_id"] != me():
        return {}
    try:
        cat = LYP_BLOCKS.get(key) or (lyp_page_cat(c, key) if key.startswith("list:") else None)
    except Denied:
        cat = None
    if not cat:
        return {}
    o, src = lyp_value(c, me(), key)
    return {"layout_now": lyp_out(cat, o), "layout_source": src, "view_name": lyp_view_name(key),
            "blocks": [{"key": k, "name": tr(n), "width": w, "fixed": f} for k, n, w, f in cat],
            "expires_at": iso(parse_iso(j["created_at"]) + timedelta(days=LYP_DAYS)) if j["created_at"] else None}


def lyp_page_cat(c, key):
    """The project page's blocks for the person (no agent check: the person's own card)."""
    lid = int(key[5:])
    if not list_role(c, lid) or not is_project(c, lid):
        raise Denied(404)
    return LYP_PAGE + tuple((f"np{r[0]}", "Notepad", 3, False)
                            for r in c.execute("SELECT id FROM list_notepads WHERE list_id=? ORDER BY id", (lid,)))


def _set_own(c, uid, key, v):
    if key.startswith("list:"):
        lid = int(key[5:])
        if v:
            c.execute("""INSERT INTO list_layouts(list_id,user_id,layout,updated_at) VALUES(?,?,?,?)
                         ON CONFLICT(list_id,user_id) DO UPDATE SET layout=excluded.layout, updated_at=excluded.updated_at""",
                      (lid, uid, v, iso(now_utc())))
        else:
            c.execute("DELETE FROM list_layouts WHERE list_id=? AND user_id=?", (lid, uid))
    elif v:
        uset(c, uid, key, v)
    else:
        c.execute("DELETE FROM user_settings WHERE user_id=? AND key=?", (uid, key))


def _active(fn, *a):
    """The active saved arrangement (column of #1069, accounts/layoutsets.py) when that part is there."""
    from ..accounts import layoutsets
    f = getattr(layoutsets, fn, None)
    return f(*a) if f else None


def lyp_run(c, j, sel, ed, extra, rec):
    """👍 (as the person): the proposal becomes a saved arrangement (source agent, prop:<job>) and, with use (default),
    the person's arrangement of that view at once. rec = the undo record."""
    from ..accounts.layoutsets import lyv_clean, lyv_save, LYV_NAME_MAX
    p = json.loads(j["proposal"])
    key, uid = p["view"], me()
    if j["created_at"] and j["created_at"] < iso(now_utc() - timedelta(days=LYP_DAYS)):
        raise Denied(409, tr("This proposal has expired"))
    if key.startswith("list:"):
        lyp_page_cat(c, key)  # still sees that project page
    own = lyp_own(c, uid, key)
    v = lyv_clean(key, lyp_merge(p["layout"], _load(own)))
    agent = c.execute("SELECT display_name, username FROM users WHERE id=?", (j["agent_id"],)).fetchone()
    suf = tr(" (proposal by {0})", (agent["display_name"] or agent["username"]) if agent else "?")
    name = p["name"][:max(8, LYV_NAME_MAX - len(suf))] + suf
    vid = lyv_save(c, uid, key, name[:LYV_NAME_MAX], v, "agent", f"prop:{j['id']}")
    use = extra.get("use") is not False
    rec.update(view=key, layout_id=vid, used=use, before=own, set=v if use else None,
               before_active=_active("lyv_active_id", c, uid, key) if use else None)
    if use:  # #1069: save, mark it active, then the value (written here directly: no lyv_follow needed)
        _active("lyv_set_active", c, uid, key, vid)
        _set_own(c, uid, key, v)
    return rec


def lyp_undo(c, j, rec, back=True):
    """Undo: the saved arrangement goes, the previous arrangement comes back (unless the person changed it since).
    Redo: lyp_run again (a new saved arrangement)."""
    uid, key = me(), rec.get("view")
    if not back:
        r = lyp_run(c, j, rec.get("sel") or ["0"], {}, rec.get("extra") or {}, dict(rec, undone=False))
        rec.clear()
        rec.update(r)
        return 1, []
    n, skipped = 0, []
    n += c.execute("DELETE FROM view_layouts WHERE id=? AND user_id=? AND source_ref=?",
                   (rec.get("layout_id"), uid, f"prop:{j['id']}")).rowcount
    if rec.get("used"):
        if lyp_own(c, uid, key) == (rec.get("set") or ""):
            _active("lyv_set_active", c, uid, key, rec.get("before_active"))
            _set_own(c, uid, key, rec.get("before") or "")
            n = max(n, 1)
        else:
            skipped.append(lyp_view_name(key))
    return n, skipped


def lyp_result(rec):
    return {"layout_id": rec.get("layout_id"), "view": rec.get("view"), "used": bool(rec.get("used"))}


# ---------------------------------------------------------------- OpenAPI
def lyp_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI of the arrangement routes for agents (2.55.0, #1066)."""
    T = "Agents"
    who = q("user_id", "The person you work for (someone who may chat with you); a personal agent: its owner (default)", {"type": "integer"})
    shape = {"type": "object", "properties": {
        "order": {"type": "array", "items": {"type": "string"}, "description": "Block keys top to bottom"},
        "hidden": {"type": "array", "items": {"type": "string"}, "description": "Blocks not shown (fixed blocks cannot be hidden)"},
        "widths": {"type": "object", "additionalProperties": {"type": "integer", "enum": list(LYP_W)},
                   "description": "Width per block in columns of six: 2 = a third, 3 = half, 4 = two thirds, 6 = full"},
        "heights": {"type": "object", "additionalProperties": {"type": "integer", "enum": list(LYP_H)},
                    "description": "1 compact, 2 normal, 3 tall"},
        "mobile": {"type": ["object", "null"], "description": "Different on the phone: {order, hidden}",
                   "properties": {"order": {"type": "array", "items": {"type": "string"}},
                                  "hidden": {"type": "array", "items": {"type": "string"}}}}}}
    schemas["ViewLayout"] = shape
    vdesc = ("dashboard (start page), view_today, view_time, view_agents, view_projects, view_review (and further views of the builder) "
             "or list:<id> (the project page of a list shared with you)")
    paths["/layouts/blocks"] = {"get": op(
        "2.55.0 (#1066): the blocks of a view (key, name, default width, fixed)", T,
        ok({"type": "object", "properties": {"view": {"type": "string"}, "user_id": {"type": "integer"},
                                             "views": {"type": "array", "items": {"type": "string"}},
                                             "blocks": {"type": "array", "items": {"type": "object"}}}}) | errs("400", "403", "404"),
        [q("view", "The view: " + vdesc), who], scope="layouts",
        desc="Agents only, scope layouts (off until a person turns it on for you). Names are English; the person sees them in their language.")}
    paths["/layouts/{view}"] = {"get": op(
        "2.55.0 (#1066): how a view of the person is arranged now (blocks only, never their content)", T,
        ok({"type": "object", "properties": {"view": {"type": "string"}, "user_id": {"type": "integer"},
                                             "source": {"type": "string", "enum": ["own", "standard", "default"]},
                                             "layout": ref("ViewLayout")}}) | errs("400", "403", "404"),
        [{"name": "view", "in": "path", "required": True, "description": vdesc, "schema": {"type": "string"}}, who], scope="layouts",
        desc="source: own = the person arranged it, standard = the admins' standard for everyone, default = the built-in one.")}
    paths["/layouts/proposals"] = {"post": op(
        "2.55.0 (#1066): propose an arrangement of a view to the person (they accept or decline; you never change it yourself)", T,
        ok({"type": "object"}, "Created", "201") | errs("400", "403", "404", "409", "413", "429"),
        body={"type": "object", "required": ["view", "name", "layout"], "properties": {
            "view": {"type": "string"}, "name": {"type": "string", "maxLength": LYP_NAME_MAX, "description": "e.g. Focus"},
            "layout": ref("ViewLayout"), "summary": {"type": "string", "description": "Markdown: why this helps"},
            "title": {"type": "string"}, "user_id": {"type": "integer"}}}, scope="layouts",
        desc=f"Starts from the arrangement the person sees now: the blocks named in order come first, the others keep their order "
             f"after them; hidden, widths, heights and mobile left out stay as they are. A ready proposal (kind layout) for the person: News + push per their settings, a card with before / after. Accepting stores "
             f"it as a saved arrangement \"<name> (proposal by <you>)\" and uses it at once unless they untick that. One open proposal per view: "
             f"a new one replaces yours. Expires after {LYP_DAYS} days; at most {LYP_DAY_MAX} per person and day. The answer comes as the event "
             "job (action approve / reject). Never propose the same again unasked after a decline.")}
