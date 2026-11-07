"""GET /api/state: everything the web client loads at start and after a change."""
import json
import threading  # 2.619.0 (#3890): the herd brake
import time
from datetime import timedelta
from flask import g, has_request_context, jsonify, request

from ..core.config import app, COOKIE, MAX_FILE_MB, IOS_SHORTCUT_URL, NTFY_URL, PUBLIC_URL
from ..core.i18n import languages, tr
from ..core.schema import MAX_DEPTH
from ..core.retention import ret_on
from ..core.dlock import dl_list_hidden  # 2.235.0 B (#2902)
from ..core.db import ag_cursor, ag_cursor_parse, db, err, gsetting, inbox_names, iso, like_escape, local_now, lv_versions, now_utc, usettings  # 2.619.0 (#3890): + lv_versions
from ..accounts.session import me, session_gen, user_public
from ..accounts.pictures import avatar_map, list_icon_url
from ..accounts.colors import ac_color_map
from ..core.access import (
    acx_lists_sql, collab_all, Denied, health_hidden, need_task, org_trips_hidden, plists, reading_ids, time_all, tvis, vis_sql, wr_sql, WRITE_ROLES,
)
from ..core.serializers import load_tasks, running_pomo, tags_for, td_lean, TD_DEFAULTS  # 2.575.0 B (#3966): + td_lean
from ..core.pg import st_ids
from ..core.instance import about_info, pub_kinds_off
from ..core.env import env_int  # 2.369.5 (#2517): pulled up from functions
from ..core.pg import system_ctx  # 2.369.5 (#2517): pulled up from functions


# ---------------------------------------------------------------- state

def _vis_mode(c):  # 2.22.0 (#752)
    from ..accounts.orgs import vis_mode
    return vis_mode(c)


def _inst_mode(c):  # 2.23.0 (#799)
    from ..accounts.orgs import instance_mode
    return instance_mode(c)


def _org_names(c, uid):  # 2.22.0 (#752)
    from ..accounts.orgs import org_names
    return org_names(c, uid)


def _st_org_labels(c, uid):
    """2.609.0 (#3373, review F3): the labels of the organisations uid fully sees (the roles of accounts/orgroles.py FULL_READ,
    as the templates of the state)."""
    return [dict(r) for r in c.execute("""SELECT id, org_id, name, color FROM org_tags WHERE org_id IN (SELECT org_id FROM org_members
                                          WHERE user_id=? AND role IN ('admin', 'member', 'readonly')) ORDER BY org_id, sort, lower(name), id""", (uid,))]


def _jtrip(v):
    try:
        t = json.loads(v) if v else None
    except ValueError:
        return None
    return t if isinstance(t, dict) else None


def folder_orders(c, uid, lists):
    """2.27.0 (#988): {owner id: [folder, ...]} the order of the folders of other people the viewer sees mirrored lists in, as
    their owners arranged them (only folders the viewer sees anyway: the folders of those lists and their parents)."""
    seen = {}
    for d in lists:
        if d.get("mirrored") and d["folder"]:
            f = seen.setdefault(d["owner_id"], set())
            f.add(d["folder"])
            if "/" in d["folder"]:
                f.add(d["folder"].split("/", 1)[0])
    out = {}
    for oid, fs in seen.items():
        try:
            arr = json.loads(usettings(c, oid).get("folders") or "[]")
        except ValueError:
            arr = []
        order = [x for x in arr if isinstance(x, str) and x in fs]
        out[str(oid)] = order + sorted(fs - set(order))
    return out


def h6a_kid_ids(c, uid, vl):
    """2.86.0 (N9): the kid accounts among the people uid may see (organisations, connections) and the members of uid's
    lists -- not every kid of the instance."""
    from ..accounts.orgs import visible_people
    kids = [r[0] for r in c.execute("SELECT id FROM users WHERE kid=1 AND disabled=0 ORDER BY id")]
    seen = visible_people(c, uid)
    if seen is None or not kids:
        return kids
    seen = seen | {m["user_id"] for li in vl for m in li.get("members") or []}
    seen |= {r[0] for r in c.execute("SELECT kid_id FROM kid_parents WHERE parent_id=?", (uid,))}
    if c.execute("SELECT 1 FROM users WHERE id=? AND is_admin=1", (uid,)).fetchone():
        from ..family.family import H6A_ADMIN_KIDS
        with system_ctx(c):  # membership structure (ids only), as family.kids_for
            seen |= {r[0] for r in c.execute("SELECT id FROM users WHERE kid=1 AND " + H6A_ADMIN_KIDS, (uid,))}
    return [k for k in kids if k in seen]


def visible_lists(c, uid, light=False):
    """Lists the user sees, with role, sharing info and the user's own folder / sort / view. light (2.280.0 B, #3116): the
    same lists with their own columns only (name, color, rate, client ...; no role, members, progress, repositories ...) and
    in no particular order -- for callers that only look up names (the time report)."""
    from ..lists.lists import columns_out
    from ..lists.groups import grp_shares_of_lists  # 2.280.0 B (#3116): was grp_name, grp_shares_of_list per list
    from ..collab.comments import user_names
    from ..collab.news import bell_custom_of
    from ..notify.caps import cap_hint, tpl_prefetch
    from ..lists.projects import list_progress, milestones_of_lists
    from ..agents.core import agent_ids, listen_default, listen_ids
    from ..collab.reactions import ltags_of_lists
    from ..integrations.git import git_repos_of_lists
    rows = c.execute(f"""SELECT l.*, m.role AS m_role, m.folder AS m_folder, m.sort AS m_sort, m.view AS m_view
                        FROM lists l LEFT JOIN list_members m ON m.list_id=l.id AND m.user_id=?
                        WHERE l.id IN {acx_lists_sql(req=False)}""", (uid, uid, uid)).fetchall()  # 2.36.2 (#1142): the one list scope
    if health_hidden(c, uid):  # 2.22.0 (#663): health lists stay private (agents, tokens without the scope "private")
        rows = [r for r in rows if r["life"] not in ("health", "budget")]  # 2.72.0 (#1333): budgets too
    rows = [r for r in rows if not dl_list_hidden(c, uid, r["id"], r["life"], r["org_id"])]  # 2.235.0 B (#2902): an agent's data lock
    if org_trips_hidden() and uid == g.user["id"]:  # 2.173.0 A (#2680): an organisation's trip: in the app only for now
        rows = [r for r in rows if not (r["life"] == "travel" and r["org_id"])]
        rd = reading_ids(c, [r["id"] for r in rows])  # 2.172.1 A (#2689): read later: in the app only
        rows = [r for r in rows if r["id"] not in rd]
    if has_request_context() and getattr(g, "user", None) is not None and uid == g.user["id"]:
        from ..core.access import token_lists
        tl = token_lists()  # 2.30.0 (#919): a token limited to selected lists
        if tl is not None:
            rows = [r for r in rows if r["id"] in tl]
    if light:
        return [{k: r[k] for k in r.keys() if not k.startswith("m_")} for r in rows]
    ids = [r["id"] for r in rows]
    members, names = {}, {}
    if ids and collab_all():
        q = ",".join("?" * len(ids))
        for m in c.execute(f"""SELECT m.list_id, m.role, m.own_role, m.grole, m.frole, u.id, u.username, u.display_name FROM list_members m
                               JOIN users u ON u.id=m.user_id WHERE m.list_id IN ({q}) ORDER BY m.added_at, u.id""", ids):
            members.setdefault(m["list_id"], []).append({"user_id": m["id"], "name": m["display_name"] or m["username"],
                                                         "role": m["role"], "username": m["username"],  # 2.4.2 (#389): @username
                                                         # 2.10.0 (#441): only via a group (no own share) / the role via groups
                                                         "via_group": bool(m["grole"]) and m["own_role"] is None, "group_role": m["grole"],
                                                         # 2.352.0 A (#2748): only through a folder's share / the role from folders
                                                         "via_folder": bool(m["frole"]) and m["own_role"] is None and not m["grole"],
                                                         "folder_role": m["frole"]})
    if ids:
        owners = {r["owner_id"] for r in rows}
        q2 = ",".join("?" * len(owners))
        names = {u["id"]: u["display_name"] or u["username"]
                 for u in c.execute(f"SELECT id, username, display_name FROM users WHERE id IN ({q2})", list(owners))}
    subs = usettings(c, uid).get("progress_subtasks") == "1"
    prog = list_progress(c, ids, subs, uid)
    ltags = ltags_of_lists(c, ids)
    ag = agent_ids(c)
    viewer_admin = bool((c.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone() or [0])[0])
    # 2.46.6 (#1680): a personal agent in a list: its owner's name (only the owner can address it, whatever agent_members says)
    pown = {r[0]: r[1] for r in c.execute("SELECT a.user_id, COALESCE(NULLIF(u.display_name, ''), u.username) FROM agents a "
                                          "JOIN users u ON u.id=a.owner_id WHERE a.owner_id IS NOT NULL")} if members and uid not in ag else {}  # agents do not need it
    for ms in members.values():
        for m in ms:
            if m["user_id"] in ag:
                m["agent"] = True
                if m["user_id"] in pown:
                    m["agent_owner"] = pown[m["user_id"]]
    snames = user_names(c, [r["status_by"] for r in rows])
    bells = {r[0]: (r[1], r[2]) for r in c.execute("SELECT list_id, mode, custom FROM list_bell WHERE user_id=?", (uid,))}
    repos = git_repos_of_lists(c, ids)  # 2.2.0 (#271)
    if collab_all():  # 2.280.0 B (#3116): the owners' limits of all foreign lists at once (cap_hint below reads the cache)
        tpl_prefetch(c, [r["id"] for r in rows if r["owner_id"] != uid], uid)
    _pl = set(plists(c, uid))  # 2.223.7 B (#2918): a participant sees no milestones of the list
    mss = milestones_of_lists(c, [r["id"] for r in rows if not r["is_inbox"] and r["id"] not in _pl])  # 2.7.1 (#410): timeline markers
    from ..lists.sprints import spr_of_lists
    sprs = spr_of_lists(c, [r for r in rows if not r["is_inbox"] and r["id"] not in _pl])  # 2.60.0 (#343); 2.352.0 G (review N14): like milestones
    has_groups = collab_all() and bool(c.execute("SELECT 1 FROM group_shares LIMIT 1").fetchone())
    gshares, gnames = grp_shares_of_lists(c, rows) if has_groups else ({}, {})  # 2.280.0 B (#3116): all lists at once
    from ..lists.playbook import pb_flags
    pbs = pb_flags(c, rows)  # 2.39.0 (#1168): lists with an effective Playbook
    lfids = {}  # 2.14.0 (#425): custom field ids per list (columns of deleted fields are dropped)
    if ids:
        for f in c.execute(f"SELECT id, list_id FROM list_fields WHERE list_id IN ({','.join('?' * len(ids))})", ids):
            lfids.setdefault(f["list_id"], set()).add(f["id"])
    from ..collab.liste2e import le2a_state
    le2s = le2a_state(c, rows, uid)  # 2.64.1 (#1817): the lock per list (waiting list, my key of the current generation)
    out = []
    for r in rows:
        d = {k: r[k] for k in r.keys() if not k.startswith("m_")}
        d.update(le2s.get(r["id"], {"e2e_pending": 0, "e2e_mine": False}))
        d["progress"] = prog.get(r["id"], {"done": 0, "total": 0, "overdue": 0, "next_due": None})
        d["status_by_name"] = snames.get(r["status_by"], "")
        if r["owner_id"] != uid:
            d.update(folder=r["m_folder"], sort=r["m_sort"], view=r["m_view"] or r["view"], role=r["m_role"])
            if r["m_role"] is None:  # 2.46.0 (#1603): in the scope only through "Everyone in the organisation" (not joined)
                d.update(role="edit" if r["org_edit"] else "view", org_reader=True, folder="", sort=r["sort"])
            if r["folder"]:  # 2.27.0 (#988): a list in its owner's folder sits for everyone where the owner put it (mirrored)
                d.update(folder=r["folder"], sort=r["sort"], mirrored=True)
        else:
            d["role"] = "owner"
        if r["org_id"]:
            from ..accounts.orgroles import cap_list_role, org_say_refusal
            d["role"] = cap_list_role(c, uid, r["org_id"], d["role"])  # 2.143.0 A (#2151): read-only in the organisation -> view
            sn = org_say_refusal(c, uid, r["org_id"])  # 2.607.0 (#4549): a guest / read-only person who cannot change the list
            if sn and d["role"] not in WRITE_ROLES:  # only reads: no comment box, no reactions (the server says 403 too)
                d["say_no"] = tr(sn)
        d["members"] = members.get(r["id"], [])
        if d["role"] == "participant" and d["members"]:  # 2.86.0 (N20 review): only the people who share a task with uid
            from ..collab.comments import h6r_shared_people
            keep = h6r_shared_people(c, r["id"], uid)
            if keep is not None:
                d["members"] = [m for m in d["members"] if m["user_id"] in keep]
        d["shared"] = bool(d["members"])
        d["tags"] = ltags.get(r["id"], [])
        d["owner_name"] = names.get(r["owner_id"], "")
        # 2.36.2 (#1139): who else it is shared with, by kind (people: a number, agents: their names); only from the members
        # and the owner the viewer already gets, the viewer not counted
        others = {m["user_id"]: m["name"] for m in d["members"] if m["user_id"] != uid}
        if d["members"] and r["owner_id"] != uid:
            others[r["owner_id"]] = d["owner_name"]
        d["shared_people"] = sum(1 for i in others if i not in ag)
        d["shared_agents"] = sorted(n for i, n in others.items() if i in ag)
        d["icon"] = list_icon_url(r)  # 2.0.2: URL of the own list icon, "" = none
        d["bell"], bc = bells.get(r["id"], ("default", None))  # 2.1.0 (#317): my bell for this list
        d["bell_custom"] = bell_custom_of(bc)  # 2.6.1 (#404): my own choice of events (kept while another mode is set)
        # 2.33.0 (#927): the owner limits my pushes about this list ({tpl, by, allowed}; null = not limited)
        d["notif_cap"] = cap_hint(c, r["id"], uid, d["owner_name"]) if r["owner_id"] != uid and collab_all() else None
        d["repos"] = repos.get(r["id"], [])
        d["milestones"] = mss.get(r["id"], [])
        if r["id"] in sprs:  # 2.60.0 (#343): sprint settings + the active / planned / last closed sprints (lists with sprints on)
            d["sprints"], d["sprint_cfg"] = sprs[r["id"]]["sprints"], sprs[r["id"]]["cfg"]
        else:
            d.pop("sprint_cfg", None)
        # 2.10.0 (#441): the groups the list is shared with (directly or through a folder of its owner)
        d["groups"] = [{"group_id": gid, "name": gnames.get(gid, "") if gid else "", "role": role, "via": via}
                       for gid, role, via in gshares.get(r["id"], [])] if has_groups else []
        # 2.4.1 (#379): the one agent that tidies it up (same rule as tidy_agent_of, from the rows already loaded)
        cands = sorted(([r["owner_id"]] if r["owner_id"] in ag else [])
                       + [m["user_id"] for m in d["members"] if m.get("agent") and m["role"] in WRITE_ROLES])
        d["tidy_agent_id"] = r["tidy_agent"] if r["tidy_agent"] in cands else (cands[0] if cands else None)
        d.pop("tidy_agent", None)
        # 2.13.1 (#471): the agents that read every comment of a person in this list (same rule as listen_agents_of);
        # 2.30.0 (#1034): they "listen in" (new / moved tasks too), by default in software lists (listen_default)
        lag = ({r["owner_id"]} if r["owner_id"] in ag else set()) | {m["user_id"] for m in d["members"] if m.get("agent")}
        d["listen_agent_ids"] = listen_ids(r["agent_listen"], r["ptype"], lag)
        d["listen_default"] = listen_default(r["ptype"])
        d.pop("agent_listen", None)
        # 2.26.0 (#928): may the viewer address this list's agents (mention, assign, chat)? owner / list admin / instance
        # admin, a list of an agent, or "Members may see and use the agent" on
        d["agents_open"] = d["role"] in ("owner", "admin") or bool(r["agent_members"]) or r["owner_id"] in ag or viewer_admin
        d["columns"] = columns_out(r["col_cfg"], lfids.get(r["id"], set()))  # 2.14.0 (#425)
        d["trip"] = _jtrip(r["trip"])  # 2.22.0 (#663): {from, to, where} of a trip list, else null
        d["playbook"] = bool(pbs.get(r["id"]))  # 2.39.0 (#1168): the list has an effective Playbook (its own or a folder's)
        d.pop("col_cfg", None)
        from ..lists.kpis import fx_list_out
        fx_list_out(d, r)  # 2.43.0 (#1328): col_sums + kpis
        out.append(d)
    # 2.27.0 (#988): lists placed by their owner (mirrored) come first in their order, then the viewer's own (two numberings)
    out.sort(key=lambda d: (-d["is_inbox"], 0 if d.get("mirrored") else 1, d["sort"], d["id"]))
    return out


def visible_sections(c, uid, tasks=None):
    """Sections of the lists uid sees. In a participant list only the sections that hold a task uid sees (tasks: the
    already loaded visible tasks; else they are queried)."""
    rows = [dict(r) for r in c.execute(f"SELECT * FROM sections WHERE list_id IN {vis_sql()} ORDER BY sort, id", (uid, uid))]
    pl = set(plists(c, uid))
    if not pl:
        return rows
    if tasks is None:
        used = {r[0] for r in c.execute(f"SELECT DISTINCT section_id FROM tasks WHERE section_id IS NOT NULL AND deleted_at IS NULL "
                                        f"AND list_id IN ({','.join(str(x) for x in pl)}) AND {tvis(c, uid)}")}
    else:
        used = {t["section_id"] for t in tasks if t.get("section_id")}
    return [r for r in rows if r["list_id"] not in pl or r["id"] in used]


# 2.280.0 A (#3109): the brake. A reload of the live update (?auto=1, never one after an own action) of the same account
# within ST_BRAKE_S of the last one answers {brake: true} (the client keeps its state, the next poll asks again): one
# account cannot load its whole state over and over (several tabs / devices, a burst of changes). Per process, like the rate limits.
# 2.280.0 F (#3109): per sign-in (session cookie; behind the proxy the browser): the phone and the desktop of one person are not
# held back by each other, only the tabs of one browser
ST_BRAKE_S = 8
_st_auto = {}
# 2.619.0 (#3890): the herd brake. A change everyone sees (a list's members, an organisation, an area without delta such as
# "other") makes every open client load its whole state at its next poll (within the 4 s of the poll, all at once on one
# core: /api/version waited up to 19 s in the measurement of #3137). At most KALMIDO_STATE_AUTO_MAX of these reloads
# (?auto=1) run at the same time in this process; one more answers {brake: true} like the brake above (the client keeps
# its state and asks again with its next poll), so the wave is spread over a few polls. Loads after an own action, the
# start of the app and agents (no auto) are never held. 0 = off.
_st_herd = {"n": 0}
_st_herd_lock = threading.Lock()


def st_herd_max():
    return env_int("KALMIDO_STATE_AUTO_MAX", 4, lo=0)


def st_herd_take(m=None):
    """2.619.0 (#3890): a place for one reload of the live update: None = the brake is off, True = taken (st_herd_give
    gives it back at the end of the request), False = all places busy (the caller answers brake)."""
    m = st_herd_max() if m is None else m
    if not m:
        return None
    with _st_herd_lock:
        if _st_herd["n"] >= m:
            return False
        _st_herd["n"] += 1
        return True


def st_herd_give():
    with _st_herd_lock:
        _st_herd["n"] = max(0, _st_herd["n"] - 1)


@app.teardown_request
def st_herd_end(_exc=None):
    if g.pop("st_herd", None):
        st_herd_give()


@app.get("/api/state")
def state():
    from ..accounts.supportgrant import sga_is_support  # 2.538.0 (#4365): accounts sits above core, inside the function like its neighbours
    if request.args.get("auto") == "1" and me() is not None:
        t, k = time.monotonic(), (me(), g.get("auth_via"), hash(request.cookies.get(COOKIE) or request.headers.get("User-Agent", "")))
        if t - _st_auto.get(k, -ST_BRAKE_S) < ST_BRAKE_S:
            return jsonify(brake=True, v=int(gsetting(db(), "version")))
        took = st_herd_take()  # 2.619.0 (#3890): the herd brake (not counted as loaded: this sign-in comes again at once)
        if took is False:
            return jsonify(brake=True, v=int(gsetting(db(), "version")))
        g.st_herd = bool(took)
        if len(_st_auto) > 5000:
            _st_auto.clear()
        _st_auto[k] = t
    from ..lists.folders import folders_shared_in, my_folder_props
    from ..lists.foldershare import sh_folder_shares
    from ..notify.caps import notif_ask_state
    from ..lists.groups import groups_for, grp_of_user
    from ..collab.news import news_items, news_sig, news_unread, news_unread_me, notif_matrix
    from ..personal.habits import habits_trash, pomo_stats
    from ..personal.timetrack import time_day_h, time_list_totals, time_running, time_totals
    from ..accounts.onboarding import ind_state, sample_state  # 2.578.0 (#4573): + the app's industry
    from ..lists.fields import field_dicts  # 2.640.0 (#4185)
    from ..calendars.caldav import dav_info
    from ..notify.push import vapid_public, webpush_count, WEBPUSH_ON
    from ..calendars.subscriptions import CAL_ON
    from ..assistant.web import asst_state  # 2.75.0 A (#1411)
    from ..api.v1 import API_ON, WH_ON
    from ..tasks.dayplan import dayplan_state
    from ..agents.core import agents_for
    from ..agents.proposals import prop_agents
    from ..lists.public import public_links_on
    from ..collab.notes import notes_brief
    from ..collab.teamchat import tchat_on, tchat_unread_both
    from ..accounts.orgs import has_workspaces, org_peers, workspaces_for, ws_mismatches
    from ..family.family import kids_for
    from ..events.model import cals_for, events_on
    from ..contacts.model import books_for, contacts_on, task_contacts
    from ..team.clients import clients_brief
    from ..tasks.mineorder import mt_mine_hidden, vw_mine_order, vw_mine_sections
    c = db()
    uid = me()
    # 2.619.0 (#3890): the change counters per area (as /api/version "a"), read BEFORE the version: a window takes them as
    # the areas of its first poll (liveparts.js lpChanged), which then fetches a delta instead of the whole state again;
    # read first, a change in between counts as changed (never missed)
    lva = lv_versions(c)
    v0 = int(gsetting(c, "version"))  # 2.42.0 (#1376): before the tasks: they are at least this new (the delta starts here)
    s = usettings(c, uid)
    cutoff = iso(now_utc() - timedelta(days=14))
    # checklist lists (package B): every done item stays (the "Done" section is the reusable part of such a list)
    base, bargs = st_where(), (uid, uid, cutoff)
    # 2.369.2 (#3136): a big account (more than KALMIDO_STATE_LAZY_MIN tasks) of a client that asks for it (lz=1) gets the
    # start set only; the lists' tasks come with GET /api/state/lists when the client opens them (lz_plan)
    lz = lz_plan(c, uid, base, bargs) if request.args.get("lz") == "1" else None
    tasks = load_tasks(c, base + (" AND id = ANY(CAST(? AS BIGINT[]))" if lz else "") + " ORDER BY id",
                       (*bargs, st_ids(sorted(lz["ids"]))) if lz else bargs,
                       lean_notes=True)  # 2.280.0 A (#3108): long notes come with the detail
    td = request.args.get("td") == "1"  # 2.575.0 B (#3966): a client that fills the defaults back (older ones / agents: all as before)
    habits = [dict(r) for r in c.execute("SELECT * FROM habits WHERE user_id=? AND deleted_at IS NULL ORDER BY archived, sort, id", (uid,))]
    since = (local_now().date() - timedelta(days=400)).isoformat()
    logs, notes = {}, {}
    for r in c.execute("""SELECT l.habit_id, l.day, l.count, l.note FROM habit_logs l JOIN habits h ON h.id=l.habit_id
                          WHERE h.user_id=? AND h.deleted_at IS NULL AND l.day>=?""", (uid, since)):
        if r["count"]:
            logs.setdefault(r["habit_id"], {})[r["day"]] = r["count"]
        if r["note"]:
            notes.setdefault(r["habit_id"], {})[r["day"]] = r["note"]
    for h in habits:
        h["logs"] = logs.get(h["id"], {})
        h["notes"] = notes.get(h["id"], {})
    u = g.user
    nitems = news_items(c, uid, s)[0]
    # 2.65.0 (#1505): stays jsonify with sorted keys: the client compares parts of it as text with the delta's answer
    # (liveparts.js lpSideCnt), so the key order is part of the contract
    return jsonify(
        v=v0, lva=lva,  # 2.619.0 (#3890): + lva
        me={**user_public(u), "orgs": _org_names(c, u["id"]), "is_admin": bool(u["is_admin"]), "auth": g.auth_via, "has_password": bool(u["password_hash"]),
            # 2.138.0 C (#1907): only whether an upload token is set (the token itself is shown once, when created)
            "drop_token_set": bool(not u["kid"] and u["drop_token_hash"]), "drop_token_at": "" if u["kid"] else (u["drop_token_at"] or ""),
            "workspaces": (ws := workspaces_for(c, uid)), "sgen": session_gen(u, ws),  # 2.28.0 (#935): my organisations [{id, name, icon, role}]; 2.238.0 B (#2872): + the sign-in mark
            "since": str(u["created_at"] or "")[:10],  # 2.364.0 B (#3031): the account's first day (Today's review from the second week)
            "support_session": sga_is_support(c)},  # 2.538.0 (#4365): the app hides what a support session may not fetch
        workspaces=has_workspaces(c),  # 2.28.0 (#935): lists / agents have a workspace (private | an organisation)
        ws_mismatches={str(k): v for k, v in ws_mismatches(c, uid).items()},  # 2.28.0: agents of another workspace in my lists
        setup_pending=bool(u["is_admin"]) and gsetting(c, "setup_step2") == "pending",  # 2.13.0 (#453 A16)
        lists=(vl := visible_lists(c, uid)),
        folder_orders=folder_orders(c, uid, vl),  # 2.27.0 (#988)
        folder_props=my_folder_props(c, uid), folders_shared_in=folders_shared_in(c, uid),  # 2.29.0 (#1030 / #929)
        folder_shares=sh_folder_shares(c, uid),  # 2.41.0 (#1428)
        inbox_names=inbox_names(),  # 2.15.0 (#632): default names of an inbox (shown in the UI language)
        filters=[{**dict(r), "rules": json.loads(r["rules"] or "{}")}
                 for r in c.execute("SELECT * FROM filters WHERE user_id=? ORDER BY sort, id", (uid,))],
        sections=visible_sections(c, uid),
        fields=field_dicts(c.execute(f"SELECT * FROM list_fields WHERE list_id IN {vis_sql()} ORDER BY sort, id",
                                     (uid, uid)).fetchall()),  # 2.43.0 (#1328): formula text with names; 2.640.0 (#4185): from these rows
        tasks=td_lean(tasks) if td else tasks,  # 2.575.0 B (#3966): the later keys read only the ids
        habits=habits,
        habits_trash=habits_trash(c, uid),  # 2.530.0 B (#4315): deleted habits until the trash period ends
        pomo=running_pomo(c),
        pomo_today=pomo_stats(c, days=1),
        counts=dict(
            done=c.execute(f"SELECT COUNT(*) FROM tasks WHERE list_id IN {vis_sql()} AND deleted_at IS NULL AND status!=0 "
                           f"AND {tvis(c, uid)}", (uid, uid)).fetchone()[0],
            trash=c.execute(f"SELECT COUNT(*) FROM tasks WHERE list_id IN {wr_sql()} AND deleted_at IS NOT NULL",
                            (uid, uid)).fetchone()[0]),
        settings={k: v for k, v in s.items() if k not in ("digest_sent", "digest_mail_sent", "digest_mail_try", "review_sent", "reset_undo") and not k.startswith("sup_key")},  # 2.74.0 (#338): never the licence key; 2.593.0 (#4590): nor the values kept for undoing a reset
        mine_order=vw_mine_order(c, uid),  # 2.40.0 (#1344): the own order of "My tasks" {task id: pos}
        mine_hidden=mt_mine_hidden(c, uid),  # 2.41.0 (#1365): ids of the lists I switched off for "My tasks"
        mine_sections=vw_mine_sections(c, uid),  # 2.569.0 (#4395): my own sections of "My tasks" and the tasks put into them
        notify=notif_matrix(s),  # 2.1.0 (#317)
        ntfy_url=NTFY_URL,
        trash_purge=ret_on("trash"),  # 2.223.3 A (#2877): False = the trash runs only count, nothing is deleted after the period
        max_file_mb=MAX_FILE_MB,  # 2.273.0 D (#3051): the upload limit per file (the client checks before it sends)
        max_depth=MAX_DEPTH,  # 2.156.0 A (#1949): the levels of tasks (dragging, mind map, detail read it)
        webpush={"enabled": WEBPUSH_ON, "key": vapid_public() if WEBPUSH_ON else "", "devices": webpush_count(c, uid)},
        languages=languages(),
        news={"unread": sum(1 for x in nitems if not x["read"]), "unread_me": news_unread_me(c, uid, s, nitems), "sig": news_sig(c, uid)},  # 2.28.0 (#987): + "For you"
        avatars=avatar_map(c, uid),
        colors=ac_color_map(c, uid),  # 2.47.1 (#1721): {user id: fixed account colour} of the accounts I see
        # 2.609.0 (#3373): + the templates of the person's organisations (full view; lists/templates.py need_template decides)
        templates=[dict(r) for r in c.execute("""SELECT id, kind, name, org_id FROM templates WHERE deleted_at IS NULL AND ((org_id IS NULL AND user_id=?) OR org_id IN
                                                 (SELECT org_id FROM org_members WHERE user_id=? AND role IN ('admin', 'member', 'readonly')))
                                                 ORDER BY lower(name), id""", (uid, uid))],
        # 2.609.0 (#3373): the labels of the person's organisations (lists/orglabels.py); review F3: only with the full view
        # (user_orgs_full) -- a guest / accounting person sees the labels linked in a shared project there (its tags), no more
        org_labels=_st_org_labels(c, uid),
        timer=time_running(c, uid) if time_all() else None,
        time_totals=time_totals(c, uid) if time_all() else {},
        time_lists=time_list_totals(c, uid, own=True) if time_all() else {},  # 2.7.0 (#407); 2.144.5 C (#1523): own=True
        time_day_h=time_day_h(c),
        collab_all=collab_all(),
        org_peers=org_peers(c, uid),  # 2.364.0 D (#3036): someone else in one of my organisations (the client's hasPeers)
        time_all=time_all(),
        about=about_info(c, u),
        calendars={"enabled": CAL_ON, "subs": c.execute("SELECT COUNT(*) FROM cal_subs WHERE user_id=? AND visible=1", (uid,)).fetchone()[0]},
        # 2.364.0 C (#3044): mine = own API tokens / webhooks (Settings > Access is listed only then, else under Integrations)
        api={"enabled": API_ON, "mine": API_ON and c.execute("SELECT 1 FROM api_tokens WHERE user_id=? LIMIT 1", (uid,)).fetchone() is not None},
        webhooks={"enabled": WH_ON, "mine": WH_ON and c.execute("SELECT 1 FROM webhooks WHERE user_id=? AND org_id IS NULL LIMIT 1", (uid,)).fetchone() is not None},
        caldav=dav_info(u), public_links=public_links_on(c), public_links_off=sorted(pub_kinds_off(c)),  # 2.489.0 C (#2656)
        share={"drop_url": PUBLIC_URL.rstrip("/") + "/drop", "ios_shortcut": IOS_SHORTCUT_URL},
        sample=sample_state(c, uid),
        industry=ind_state(c, uid),  # 2.578.0 (#4573): the app's industry {code: "" | "film", can_set, choices, updated_at}
        notes=notes_brief(c, uid),  # 2.17.0 (#442)
        team=dict(zip(("enabled", "unread", "dm_unread"), (tchat_on(c, uid), *tchat_unread_both(c, uid)))),  # 2.17.0 (#419); 2.28.0 (#987): + DMs; 2.149.0 C (#2507): one tchat_rooms
        agents=agents_for(c, uid),
        proposers=prop_agents(c, uid),  # 2.3.0: agents I may ask for a proposal
        **asst_state(c, uid),  # 2.75.0 A (#1411): "assistant" only when the server configured one (assistant/web.py)
        groups=groups_for(c, full=bool(u["is_admin"])) if collab_all() else [],  # 2.10.0 (#441)
        my_groups=grp_of_user(c, uid) if collab_all() else [],
        dayplan=dayplan_state(c, uid),  # 2.10.0 (#440): working hours, review card
        kids=kids_for(c, uid),  # 2.19.0 (#653): the kids I look after (or me, a kid) with stars + rewards
        kid_ids=h6a_kid_ids(c, uid, vl),  # 2.19.0: who gets stars; 2.86.0 (N9): only kids this person sees
        people_visibility=_vis_mode(c),  # 2.22.0 (#752): all | org | contacts
        instance_mode=_inst_mode(c),  # 2.23.0 (#799): organisation | shared | multi
        # 2.21.0 (#659 / #658): event calendars, a change marker of the events I see (the views refetch their range), the
        # events that tasks prepare; address books and the contacts linked to tasks
        evcals=cals_for(c, uid) if events_on(c, uid) else [],
        evsig=ev_sig(c, uid),
        evlinks=ev_links(c, uid, [t["id"] for t in tasks]) if events_on(c, uid) else {},
        books=books_for(c, uid) if contacts_on(c, uid) else [],
        tcontacts=task_contacts(c, uid, {t["id"] for t in tasks}),
        clients=clients_brief(c, uid),  # 2.23.0 (#463): the clients I see (module clients) with their lists
        storage=_quota(c, uid),  # 2.24.0 (#910): used / limit / level
        announce=_announce(c),  # 2.24.0 (#907): the notice above the app (or null)
        notif_ask=notif_ask_state(c, uid, s),  # 2.33.0 (#927): owners of lists shared before 2.33 are asked once
        **({"lz": {"pending": lz["pending"], "counts": lz["counts"]}} if lz else {}),  # 2.369.2 (#3136)
        **({"tdef": TD_DEFAULTS} if td else {}),  # 2.575.0 B (#3966): the defaults the client fills back (liveparts.js tdFill)
    )


# ---------------------------------------------------------------- 2.369.2 (#3136): the start set of a big account
# Audit Q (#3108): /api/state of a person who sees 200 lists with 20.600 tasks was 18 MB. Such an account (more than
# KALMIDO_STATE_LAZY_MIN tasks in its start state; only clients that send lz=1) gets the start set: the tasks Today,
# Tomorrow, Next 7 days, Pinned, Waiting and My tasks need (due up to 8 days ahead or overdue, deadlines, planned, assigned
# to the person or one of their groups, pinned, waiting), every task of the lists the client names in lzl (the open list,
# the basket, the lists it loaded before = its offline cache) and of the lists where the person is a participant, plus the
# parents and subtasks of all those (the views show trees). lz.pending = the visible lists whose tasks are not all in it,
# lz.counts = their open top-level tasks and tags (the sidebar's numbers); GET /api/state/lists?ids= loads them.
LZ_DAYS = 8         # due up to this many days ahead (Next 7 days + a day for time zones)
LZ_KEEP_MAX = 2000  # lists named in lzl / ids at most


def st_where():
    """The where clause of the tasks of /api/state (three parameters: uid, uid, the 14-day cutoff of completed tasks)."""
    return (f"list_id IN {vis_sql()} AND deleted_at IS NULL AND (status=0 OR completed_at>=? OR "
            "list_id IN (SELECT id FROM lists WHERE checklist=1))")


def lz_min():
    return env_int("KALMIDO_STATE_LAZY_MIN", 3000, lo=0)


def lz_ids_arg(raw):
    """'all' -> None (every list), '1,2,x' -> {1, 2} (at most LZ_KEEP_MAX)."""
    if (raw or "").strip() == "all":
        return None
    return {int(x) for x in (raw or "").split(",")[:LZ_KEEP_MAX] if x.strip().isdigit()}


def lz_tree(c, base, bargs, ids):
    """ids + their parents (up the tree) + their subtasks (down), all within the state's where clause."""
    ids = set(ids)
    for col, other in (("id", "parent_id"), ("parent_id", "id")):  # up: the rows' parents; down: rows whose parent is in
        front = set(ids)
        for _ in range(MAX_DEPTH + 2):
            if not front:
                break
            if col == "id":
                want = {r[0] for r in c.execute("SELECT parent_id FROM tasks WHERE id = ANY(CAST(? AS BIGINT[])) AND parent_id IS NOT NULL",
                                                (st_ids(sorted(front)),))} - ids
                rows = {r[0] for r in c.execute(f"SELECT id FROM tasks WHERE {base} AND id = ANY(CAST(? AS BIGINT[]))",
                                                (*bargs, st_ids(sorted(want))))} if want else set()
            else:
                rows = {r[0] for r in c.execute(f"SELECT id FROM tasks WHERE {base} AND parent_id = ANY(CAST(? AS BIGINT[]))",
                                                (*bargs, st_ids(sorted(front))))} - ids
            ids |= rows
            front = rows
    return ids


def lz_plan(c, uid, base, bargs):
    """None = the whole state (a small account, lzl=all); else {ids, pending, counts} (see above)."""
    keep = lz_ids_arg(request.args.get("lzl", ""))
    if keep is None:
        return None
    lim = lz_min()
    if lim and c.execute(f"SELECT COUNT(*) FROM tasks WHERE {base}", bargs).fetchone()[0] <= lim:
        return None
    keep |= set(plists(c, uid))  # a participant's view hangs on assignments and the tree: those lists come whole
    keep |= {r[0] for r in c.execute("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (uid,))}  # the basket (Today can show it)
    t0 = local_now().date()
    kl = ",".join(str(int(x)) for x in sorted(keep))
    start = ("(status=0 OR completed_at>=?) AND ((due IS NOT NULL AND due<>'' AND due<=?) OR (deadline=2 AND due IS NOT NULL) "
             "OR COALESCE(plan_start, '')>=? OR assignee_id=? OR pinned=1 OR COALESCE(waiting_at, '')<>''"
             "OR assignee_group_id IN (SELECT group_id FROM group_members WHERE user_id=?))")
    sargs = (bargs[2], (t0 + timedelta(days=LZ_DAYS)).isoformat(), (t0 - timedelta(days=1)).isoformat(), uid, uid)
    more = (f" OR list_id IN ({kl}) OR id IN (SELECT task_id FROM task_links WHERE list_id IN ({kl}))") if kl else ""
    ids = {r[0] for r in c.execute(f"SELECT id FROM tasks WHERE {base} AND (({start}){more})", (*bargs, *sargs))}
    ids = lz_tree(c, base, bargs, ids)
    vis = [r[0] for r in c.execute(f"SELECT id FROM lists WHERE id IN {vis_sql()}", (uid, uid))]
    pending = sorted(set(vis) - keep)
    return {"ids": ids, "pending": pending, "counts": lz_counts(c, uid, pending)}


def lz_counts(c, uid, lids):
    """{list id: {n, tags}} = the open top-level tasks of these lists the person sees (with the further lists' links, as the
    client counts a task's "also") and their tags (own + list tags, each tag once per task): the sidebar of the start set."""
    if not lids:
        return {}
    q = ",".join(str(int(x)) for x in lids)
    rows = [(r[0], r[1]) for r in c.execute(f"SELECT id, list_id FROM tasks WHERE list_id IN ({q}) AND deleted_at IS NULL AND status=0 "
                                            f"AND parent_id IS NULL AND {tvis(c, uid)}")]
    rows += [(r[0], r[1]) for r in c.execute(f"""SELECT k.task_id, k.list_id FROM task_links k JOIN tasks t ON t.id=k.task_id
                     JOIN lists o ON o.id=t.list_id JOIN lists x ON x.id=k.list_id
                     WHERE k.list_id IN ({q}) AND k.list_id!=t.list_id AND t.parent_id IS NULL AND t.status=0 AND t.deleted_at IS NULL
                     AND o.org_id IS NOT DISTINCT FROM x.org_id AND t.list_id IN {vis_sql()} AND {tvis(c, uid, 't.')}""", (uid, uid))]
    ids = {i for i, _ in rows}
    tg, lt = {}, {}
    if ids:
        tg = tags_for(c, ids, uid)
        for r in c.execute("""SELECT x.task_id, lt.name FROM task_list_tags x JOIN list_tags lt ON lt.id=x.tag_id JOIN tasks t ON t.id=x.task_id
                              WHERE x.task_id = ANY(CAST(? AS BIGINT[])) AND lt.list_id=t.list_id""", (st_ids(sorted(ids)),)):
            lt.setdefault(r[0], []).append(r[1])  # the list tags (as collab.reactions.ltags_for, a higher layer)
    out = {str(x): {"n": 0, "tags": {}} for x in lids}
    for i, lid in rows:
        o = out[str(lid)]
        o["n"] += 1
        for t in set(tg.get(i, [])) | set(lt.get(i, [])):
            o["tags"][t] = o["tags"].get(t, 0) + 1
    return out


def _quota(c, uid):
    from ..admin.hosting import quota_info
    return quota_info(c, uid, cached=True)  # 2.549.0 (#3139): the list pictures from a short cache (admin/hosting.py)


def _announce(c):
    from ..admin.hosting import announce_get
    return announce_get(c)


def ev_sig(c, uid):
    """Changes as soon as an event or calendar I see (or am invited to) changes."""
    from ..events.model import my_cal_ids
    ids = my_cal_ids(c, uid)
    q = ",".join("?" * len(ids)) or "NULL"
    a = c.execute(f"SELECT COUNT(*), MAX(changed_at) FROM ev_cals WHERE id IN ({q})", list(ids)).fetchone()
    # 2.102.0 A (#2003): only invitations that still count (ev_att_ok, same join as ev_range) -- a former org member's
    # signature no longer moves with that org's events
    from ..events.model import ev_att_ok
    rows = c.execute("SELECT k.org_id, COUNT(*), MAX(e.updated_at) FROM events e JOIN event_attendees x ON x.event_id=e.id "
                     "JOIN ev_cals k ON k.id=e.cal_id WHERE x.user_id=? GROUP BY k.org_id", (uid,)).fetchall()
    ok = [r for r in rows if ev_att_ok(c, uid, r[0])]
    b = (sum(r[1] for r in ok), max((r[2] for r in ok if r[2]), default=None))
    # 2.102.0 A (#2006): the count of invitations comes first ("<n>|..."): calEvOn shows the calendar from it alone
    return f"{b[0]}|{a[0]}.{a[1] or ''}.{b[1] or ''}"


def ev_links(c, uid, task_ids):
    """{task id: [{id, title, start, all_day}]}: the events (I see) that my visible tasks prepare."""
    from ..events.model import my_cal_ids
    ids = my_cal_ids(c, uid)
    if not ids or not task_ids:
        return {}
    q = ",".join("?" * len(ids))
    tset, out = set(task_ids), {}
    # 2.579.0 (#4184): only the events of these tasks (events_task index), was: every event with a task of my calendars
    for r in c.execute(f"SELECT id, task_id, title, start, all_day FROM events WHERE cal_id IN ({q}) AND task_id IS NOT NULL "
                       "AND deleted_at IS NULL AND task_id = ANY(CAST(? AS BIGINT[]))", [*ids, st_ids(sorted(tset))]):
        if r["task_id"] in tset:
            out.setdefault(r["task_id"], []).append({"id": r["id"], "title": r["title"], "start": r["start"], "all_day": bool(r["all_day"])})
    return out


@app.get("/api/tasks")
def task_query():
    from ..tasks.lifecycle import tre_plan
    c = db()
    uid = me()
    scope = request.args.get("scope", "done")
    limit = min(int(request.args.get("limit", 300)), 2000)
    # 2.40.0 (#1432): completed / trash page by ?before=<next> (completed_at resp. deleted_at + id); next = null at the end
    try:
        cur = ag_cursor_parse(request.args.get("before")) if scope in ("done", "trash") else None
    except ValueError:
        return err(tr("Invalid value: {0}", "before"))
    extra = {}
    if scope == "trash":
        rows = load_tasks(c, f"list_id IN {wr_sql()} AND deleted_at IS NOT NULL" + (" AND (deleted_at, id) < (?, ?)" if cur else "")
                          + " ORDER BY deleted_at DESC, id DESC LIMIT ?", (uid, uid, *(cur or ()), limit + 1))
        # 2.530.0 D (#4316): the same plan as "Empty" (lifecycle.tre_plan): own trash only (also instance admins: others =
        # what their explicit "also the other owners'" would take), projects kept by law stay
        _ids, ok, cnt = tre_plan(c, uid)
        for t in rows:  # 2.0.5: stays when the trash is emptied (shared list of another owner)
            if t["list_id"] not in ok:
                t["keep"] = True
        if not cur:  # 2.40.0 (#1432): "Empty" counts the whole trash, not only the loaded page
            extra = {"deletable": cnt["deleted"], "kept": cnt["kept"] + cnt["kept_law"], "others": cnt["others"]}
        from ..tasks.tasktrash import ttp_days
        extra["days"] = ttp_days()  # 2.116.0 A (#2063): the trash period (the client shows the days left per row)
        extra["purge_on"] = ret_on("trash")  # 2.223.3 A (#2877): whether the run really deletes after the period
    elif scope == "search":
        rows = search_tasks(c, uid, request.args.get('q', '').strip(), limit)
        if request.args.get("semantic") == "1":  # 2.59.0 B (#1375): + tasks of similar meaning (only visible ones)
            from ..tasks.related import rt9_search_extend
            rows = rt9_search_extend(c, uid, request.args.get('q', '').strip(), rows, limit)
    else:
        rows = load_tasks(c, f"list_id IN {vis_sql()} AND deleted_at IS NULL AND status!=0 AND {tvis(c, uid)} "
                             + ("AND (COALESCE(completed_at, ''), id) < (?, ?) " if cur else "")
                             + "ORDER BY COALESCE(completed_at, '') DESC, id DESC LIMIT ?", (uid, uid, *(cur or ()), limit + 1))
    if scope in ("done", "trash"):
        more = len(rows) > limit
        rows = rows[:limit]
        last = rows[-1] if rows else None
        extra["next"] = ag_cursor(last["deleted_at" if scope == "trash" else "completed_at"], last["id"]) if more and last else None
    return jsonify(tasks=rows, **extra)


def search_tasks(c, uid, raw, limit, files=True):
    """Visible tasks whose title, notes, link or a custom field value contains raw (web search, REST API). files=False
    (audit G4: an API token without attachments:read): the recognised text of files does not count."""
    from ..lists.fields import search_field_ids
    q = f"%{like_escape(raw)}%"  # 2.37.0 (#1150): the text literally (Postgres reads a backslash as an escape in LIKE)
    fids = sorted(search_field_ids(c, uid, raw))[:2000] if raw else []
    from ..files.textscan import ts_task_hits
    fhit = ts_task_hits(c, uid, raw) if files else {}  # 2.61.0 (#1820): the recognised text of a task's files finds the task
    fids = sorted(set(fids) | set(sorted(fhit)[:2000]))
    # participants: only their own tasks match (a context parent's notes / link / fields are not theirs to search)
    # 2.64.1 B (#1817): lists with the lock are searched in the browser only (the server holds ciphertexts)
    # 2.149.0 C (#2515): the same conditions as one set of ids per field (each can use its trigram index, core/schema.py
    # tasks_trgm_*; an OR over all of them could only scan) -- the matches are exactly those of the OR before
    rows = load_tasks(c, f"list_id IN {vis_sql()} AND list_id NOT IN (SELECT id FROM lists WHERE e2e IS NOT NULL) "
                         f"AND deleted_at IS NULL AND {tvis(c, uid, write=True)} "
                         "AND id IN (SELECT id FROM tasks WHERE title ILIKE ? ESCAPE '\\' UNION SELECT id FROM tasks WHERE content ILIKE ? ESCAPE '\\' "
                         "UNION SELECT id FROM tasks WHERE url ILIKE ? ESCAPE '\\' "
                         "UNION SELECT id FROM tasks WHERE snippets IS NOT NULL AND EXISTS (SELECT 1 FROM "
                         "jsonb_array_elements(CASE WHEN jsonb_typeof(snippets)='array' THEN snippets ELSE '[]'::jsonb END) j "
                         "WHERE (j->>'code') ILIKE ? ESCAPE '\\' OR (j->>'path') ILIKE ? ESCAPE '\\') "
                         "UNION SELECT unnest(CAST(? AS BIGINT[]))) "
                         "ORDER BY status, updated_at DESC LIMIT ?", (uid, uid, q, q, q, q, q, list(fids), limit))
    for t in rows:  # 2.61.0 (#1820): "in file <name>" when only a file's text matched
        if t["id"] in fhit and not any(raw.casefold() in (t.get(k) or "").casefold() for k in ("title", "content", "url")):
            t["file_hit"] = fhit[t["id"]]
    return rows


@app.get("/api/tasks/<int:tid>")
def task_get(tid):
    """One task I can see (e.g. an old completed one opened from the News feed)."""
    c = db()
    need_task(c, tid, write=False)
    rows = load_tasks(c, "id=? AND deleted_at IS NULL", (tid,), full_snips=True)  # 2.35.0 (#1095): with the code snippets
    if not rows:
        raise Denied(404)
    return jsonify(rows[0])
