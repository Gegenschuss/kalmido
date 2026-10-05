"""GET /api/state: everything the web client loads at start and after a change."""
import json
from datetime import timedelta
from flask import g, jsonify, request

from ..core.config import app, IOS_SHORTCUT_URL, NTFY_IN, NTFY_URL, PUBLIC_URL
from ..core.i18n import languages
from ..core.db import db, gsetting, inbox_names, iso, local_now, now_utc, usettings
from ..accounts.session import me, user_public
from ..accounts.pictures import avatar_map, list_icon_url
from ..core.access import (
    _members_on, collab_all, Denied, need_task, plists, time_all, tvis, vis_sql, wr_sql, WRITE_ROLES,
)
from ..core.serializers import load_tasks, running_pomo
from ..core.pages import inbox_user
from ..core.instance import about_info


# ---------------------------------------------------------------- state

def visible_lists(c, uid):
    """Lists the user sees, with role, sharing info and the user's own folder / sort / view."""
    from ..lists.lists import columns_out
    from ..lists.groups import grp_name, grp_shares_of_list
    from ..collab.comments import user_names
    from ..collab.news import bell_custom_of
    from ..lists.projects import list_progress, milestones_of_lists
    from ..agents.core import agent_ids, listen_ids
    from ..collab.reactions import ltags_of_lists
    from ..integrations.git import git_repos_of_lists
    rows = c.execute(f"""SELECT l.*, m.role AS m_role, m.folder AS m_folder, m.sort AS m_sort, m.view AS m_view
                        FROM lists l LEFT JOIN list_members m ON m.list_id=l.id AND m.user_id=?
                        WHERE l.owner_id=? OR (m.user_id IS NOT NULL{_members_on()})""", (uid, uid)).fetchall()
    ids = [r["id"] for r in rows]
    members, names = {}, {}
    if ids and collab_all():
        q = ",".join("?" * len(ids))
        for m in c.execute(f"""SELECT m.list_id, m.role, m.own_role, m.grole, u.id, u.username, u.display_name FROM list_members m
                               JOIN users u ON u.id=m.user_id WHERE m.list_id IN ({q}) ORDER BY m.added_at, u.id""", ids):
            members.setdefault(m["list_id"], []).append({"user_id": m["id"], "name": m["display_name"] or m["username"],
                                                         "role": m["role"], "username": m["username"],  # 2.4.2 (#389): @username
                                                         # 2.10.0 (#441): only via a group (no own share) / the role via groups
                                                         "via_group": bool(m["grole"]) and m["own_role"] is None, "group_role": m["grole"]})
    if ids:
        owners = {r["owner_id"] for r in rows}
        q2 = ",".join("?" * len(owners))
        names = {u["id"]: u["display_name"] or u["username"]
                 for u in c.execute(f"SELECT id, username, display_name FROM users WHERE id IN ({q2})", list(owners))}
    subs = usettings(c, uid).get("progress_subtasks") == "1"
    prog = list_progress(c, ids, subs, uid)
    ltags = ltags_of_lists(c, ids)
    ag = agent_ids(c)
    for ms in members.values():
        for m in ms:
            if m["user_id"] in ag:
                m["agent"] = True
    snames = user_names(c, [r["status_by"] for r in rows])
    bells = {r[0]: (r[1], r[2]) for r in c.execute("SELECT list_id, mode, custom FROM list_bell WHERE user_id=?", (uid,))}
    repos = git_repos_of_lists(c, ids)  # 2.2.0 (#271)
    mss = milestones_of_lists(c, [r["id"] for r in rows if r["kind"] == "project"])  # 2.7.1 (#410): timeline markers
    has_groups = collab_all() and bool(c.execute("SELECT 1 FROM group_shares LIMIT 1").fetchone())
    lfids = {}  # 2.14.0 (#425): custom field ids per list (columns of deleted fields are dropped)
    if ids:
        for f in c.execute(f"SELECT id, list_id FROM list_fields WHERE list_id IN ({','.join('?' * len(ids))})", ids):
            lfids.setdefault(f["list_id"], set()).add(f["id"])
    out = []
    for r in rows:
        d = {k: r[k] for k in r.keys() if not k.startswith("m_")}
        d["progress"] = prog.get(r["id"], {"done": 0, "total": 0, "overdue": 0, "next_due": None})
        d["status_by_name"] = snames.get(r["status_by"], "")
        if r["owner_id"] != uid:
            d.update(folder=r["m_folder"], sort=r["m_sort"], view=r["m_view"] or r["view"], role=r["m_role"])
        else:
            d["role"] = "owner"
        d["members"] = members.get(r["id"], [])
        d["shared"] = bool(d["members"])
        d["tags"] = ltags.get(r["id"], [])
        d["owner_name"] = names.get(r["owner_id"], "")
        d["icon"] = list_icon_url(r)  # 2.0.2: URL of the own list icon, "" = none
        d["bell"], bc = bells.get(r["id"], ("default", None))  # 2.1.0 (#317): my bell for this list
        d["bell_custom"] = bell_custom_of(bc)  # 2.6.1 (#404): my own choice of events (kept while another mode is set)
        d["repos"] = repos.get(r["id"], [])
        d["milestones"] = mss.get(r["id"], [])
        # 2.10.0 (#441): the groups the list is shared with (directly or through a folder of its owner)
        d["groups"] = [{"group_id": gid, "name": grp_name(c, gid), "role": role, "via": via}
                       for gid, role, via in grp_shares_of_list(c, r["id"])] if has_groups else []
        # 2.4.1 (#379): the one agent that tidies it up (same rule as tidy_agent_of, from the rows already loaded)
        cands = sorted(([r["owner_id"]] if r["owner_id"] in ag else [])
                       + [m["user_id"] for m in d["members"] if m.get("agent") and m["role"] in WRITE_ROLES])
        d["tidy_agent_id"] = r["tidy_agent"] if r["tidy_agent"] in cands else (cands[0] if cands else None)
        d.pop("tidy_agent", None)
        # 2.13.1 (#471): the agents that read every comment of a person in this list (same rule as listen_agents_of)
        lag = ({r["owner_id"]} if r["owner_id"] in ag else set()) | {m["user_id"] for m in d["members"] if m.get("agent")}
        d["listen_agent_ids"] = listen_ids(r["agent_listen"], r["agent_tidy"], d["tidy_agent_id"], lag)
        d.pop("agent_listen", None)
        d["columns"] = columns_out(r["col_cfg"], lfids.get(r["id"], set()))  # 2.14.0 (#425)
        d.pop("col_cfg", None)
        out.append(d)
    out.sort(key=lambda d: (-d["is_inbox"], d["sort"], d["id"]))
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


@app.get("/api/state")
def state():
    from ..lists.groups import groups_for, grp_of_user
    from ..integrations.paperless import pl_state
    from ..collab.news import news_sig, news_unread, notif_matrix
    from ..personal.habits import pomo_stats
    from ..personal.timetrack import time_day_h, time_list_totals, time_running, time_totals
    from ..accounts.onboarding import sample_state
    from ..lists.fields import field_dict
    from ..calendars.caldav import dav_info
    from ..notify.push import vapid_public, webpush_count, WEBPUSH_ON
    from ..calendars.subscriptions import CAL_ON
    from ..api.v1 import API_ON, WH_ON
    from ..tasks.dayplan import dayplan_state
    from ..agents.core import agents_for
    from ..agents.proposals import prop_agents
    from ..lists.public import public_links_on
    from ..collab.notes import notes_brief
    from ..collab.teamchat import tchat_on, tchat_unread
    from ..family.family import kids_for
    c = db()
    uid = me()
    s = usettings(c, uid)
    cutoff = iso(now_utc() - timedelta(days=14))
    # checklist lists (package B): every done item stays (the "Done" section is the reusable part of such a list)
    tasks = load_tasks(c, f"list_id IN {vis_sql()} AND deleted_at IS NULL AND (status=0 OR completed_at>=? OR "
                          "list_id IN (SELECT id FROM lists WHERE checklist=1)) ORDER BY id", (uid, uid, cutoff))
    habits = [dict(r) for r in c.execute("SELECT * FROM habits WHERE user_id=? ORDER BY archived, sort, id", (uid,))]
    since = (local_now().date() - timedelta(days=400)).isoformat()
    logs, notes = {}, {}
    for r in c.execute("""SELECT l.habit_id, l.day, l.count, l.note FROM habit_logs l JOIN habits h ON h.id=l.habit_id
                          WHERE h.user_id=? AND l.day>=?""", (uid, since)):
        if r["count"]:
            logs.setdefault(r["habit_id"], {})[r["day"]] = r["count"]
        if r["note"]:
            notes.setdefault(r["habit_id"], {})[r["day"]] = r["note"]
    for h in habits:
        h["logs"] = logs.get(h["id"], {})
        h["notes"] = notes.get(h["id"], {})
    u = g.user
    return jsonify(
        v=int(gsetting(c, "version")),
        me={**user_public(u), "is_admin": bool(u["is_admin"]), "auth": g.auth_via, "has_password": bool(u["password_hash"]),
            "ntfy_inbox": bool(NTFY_IN["token"]) and inbox_user(c) == uid},
        setup_pending=bool(u["is_admin"]) and gsetting(c, "setup_step2") == "pending",  # 2.13.0 (#453 A16)
        lists=visible_lists(c, uid),
        inbox_names=inbox_names(),  # 2.15.0 (#632): default names of an inbox (shown in the UI language)
        filters=[{**dict(r), "rules": json.loads(r["rules"] or "{}")}
                 for r in c.execute("SELECT * FROM filters WHERE user_id=? ORDER BY sort, id", (uid,))],
        sections=visible_sections(c, uid),
        fields=[field_dict(r) for r in c.execute(f"SELECT * FROM list_fields WHERE list_id IN {vis_sql()} ORDER BY sort, id",
                                                 (uid, uid))],
        tasks=tasks,
        habits=habits,
        pomo=running_pomo(c),
        pomo_today=pomo_stats(c, days=1),
        counts=dict(
            done=c.execute(f"SELECT COUNT(*) FROM tasks WHERE list_id IN {vis_sql()} AND deleted_at IS NULL AND status!=0 "
                           f"AND {tvis(c, uid)}", (uid, uid)).fetchone()[0],
            trash=c.execute(f"SELECT COUNT(*) FROM tasks WHERE list_id IN {wr_sql()} AND deleted_at IS NOT NULL",
                            (uid, uid)).fetchone()[0]),
        settings={k: v for k, v in s.items() if k not in ("digest_sent", "digest_mail_sent", "review_sent")},
        notify=notif_matrix(s),  # 2.1.0 (#317)
        paperless=pl_state(c, u),
        ntfy_inbox={"enabled": bool(NTFY_IN["token"]), "server": NTFY_IN["public"], "topic": NTFY_IN["topic"]},
        ntfy_url=NTFY_URL,
        webpush={"enabled": WEBPUSH_ON, "key": vapid_public() if WEBPUSH_ON else "", "devices": webpush_count(c, uid)},
        languages=languages(),
        news={"unread": news_unread(c, uid, s), "sig": news_sig(c, uid)},
        avatars=avatar_map(c, uid),
        templates=[dict(r) for r in c.execute("SELECT id, kind, name FROM templates WHERE user_id=? ORDER BY name COLLATE NOCASE, id",
                                              (uid,))],
        timer=time_running(c, uid) if time_all() else None,
        time_totals=time_totals(c, uid) if time_all() else {},
        time_lists=time_list_totals(c, uid) if time_all() else {},  # 2.7.0 (#407)
        time_day_h=time_day_h(c),
        collab_all=collab_all(),
        time_all=time_all(),
        about=about_info(c, u),
        calendars={"enabled": CAL_ON, "subs": c.execute("SELECT COUNT(*) FROM cal_subs WHERE user_id=? AND visible=1", (uid,)).fetchone()[0]},
        api={"enabled": API_ON}, webhooks={"enabled": WH_ON}, caldav=dav_info(u), public_links=public_links_on(c),
        share={"drop_url": PUBLIC_URL.rstrip("/") + "/drop", "ios_shortcut": IOS_SHORTCUT_URL},
        sample=sample_state(c, uid),
        notes=notes_brief(c, uid),  # 2.17.0 (#442)
        team={"enabled": tchat_on(c, uid), "unread": tchat_unread(c, uid)},  # 2.17.0 (#419)
        agents=agents_for(c, uid),
        proposers=prop_agents(c, uid),  # 2.3.0: agents I may ask for a proposal
        groups=groups_for(c, full=bool(u["is_admin"])) if collab_all() else [],  # 2.10.0 (#441)
        my_groups=grp_of_user(c, uid) if collab_all() else [],
        dayplan=dayplan_state(c, uid),  # 2.10.0 (#440): working hours, review card
        kids=kids_for(c, uid),  # 2.19.0 (#653): the kids I look after (or me, a kid) with stars + rewards
        kid_ids=[r[0] for r in c.execute("SELECT id FROM users WHERE kid=1 AND disabled=0")],  # 2.19.0: who gets stars
    )


@app.get("/api/tasks")
def task_query():
    from ..tasks.lifecycle import purge_lists
    c = db()
    uid = me()
    scope = request.args.get("scope", "done")
    limit = min(int(request.args.get("limit", 300)), 2000)
    if scope == "trash":
        rows = load_tasks(c, f"list_id IN {wr_sql()} AND deleted_at IS NOT NULL ORDER BY deleted_at DESC LIMIT ?",
                          (uid, uid, limit))
        ok = purge_lists(c, uid)
        for t in rows:  # 2.0.5: stays when the trash is emptied (shared list of another owner)
            if t["list_id"] not in ok:
                t["keep"] = True
    elif scope == "search":
        rows = search_tasks(c, uid, request.args.get('q', '').strip(), limit)
    else:
        rows = load_tasks(c, f"list_id IN {vis_sql()} AND deleted_at IS NULL AND status!=0 AND {tvis(c, uid)} "
                             "ORDER BY completed_at DESC LIMIT ?", (uid, uid, limit))
    return jsonify(tasks=rows)


def search_tasks(c, uid, raw, limit):
    """Visible tasks whose title, notes, link or a custom field value contains raw (web search, REST API)."""
    from ..lists.fields import search_field_ids
    q = f"%{raw}%"
    fids = sorted(search_field_ids(c, uid, raw))[:2000] if raw else []
    # participants: only their own tasks match (a context parent's notes / link / fields are not theirs to search)
    return load_tasks(c, f"list_id IN {vis_sql()} AND deleted_at IS NULL AND {tvis(c, uid, write=True)} "
                         "AND (title LIKE ? OR content LIKE ? OR url LIKE ? "
                         f"OR id IN ({','.join('?' * len(fids)) or 'NULL'})) "
                         "ORDER BY status, updated_at DESC LIMIT ?", (uid, uid, q, q, q, *fids, limit))


@app.get("/api/tasks/<int:tid>")
def task_get(tid):
    """One task I can see (e.g. an old completed one opened from the News feed)."""
    c = db()
    need_task(c, tid, write=False)
    rows = load_tasks(c, "id=? AND deleted_at IS NULL", (tid,))
    if not rows:
        raise Denied(404)
    return jsonify(rows[0])
