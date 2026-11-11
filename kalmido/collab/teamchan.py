"""2.113.1 B (#2059): team chat channels anyone may open, group conversations of three or more people, files in team chat
messages.

Channels (tchat_rooms.kind 'channel'): opened by a person of an organisation for that organisation (open = every member of
the organisation sees it and may join; else only the invited), or without an organisation in the person's own space (always
"invited only", members = people they may write to anyway, tchat_coworkers). The creator or an admin of the organisation
renames it, opens / closes it, archives / restores it and manages its members; anyone leaves. Members only from the
channel's organisation; agents only when a person adds them explicitly (a personal agent by its owner, an agent of the
organisation by its admins) and only agents of the same organisation (a private channel: personal agents without one).
Group conversations (kind 'group'): three or more people who all work with each other (every pair would be allowed a direct
message, tchat_coworkers), name optional; every member adds people (who again work with all of them) and leaves. Pushes and
read state like a direct message. Members of both are shares of the room's node in the shared core (collab/tcxcore.py; 2.924.0, #5069).

Files (tchat_files): the file path of the agent chat (agents/chat.py): the same limits, checks (files/upsafe.py, kind
"tchat") and names, sealed at rest (core/orgcrypt.py: the organisation of the conversation, else the list owner's / the
uploader's account; a list channel's file follows its list), served to everyone who sees the conversation. Deleting a message takes its files off the disk. An
end-to-end encrypted conversation (an encrypted DM, the channel of a list with the lock) refuses files: the server would
see them in plain."""
import mimetypes
import os
import time
import uuid
from flask import g, has_request_context, jsonify, request, Response

from ..core.config import app, ATT_DIR, MAX_FILE_MB
from ..core.pg import insert_id, system_ctx, write_lock
from ..core.i18n import N_, tr
from ..core.db import body, db, err, iso, iso_ms, now_utc
from ..core.retention import ret_days, ret_on, ret_report  # 2.272.0 A (#3026)
from ..core.access import Denied
from ..core.serializers import unlink_files
from ..accounts.session import me
from ..accounts.orgs import instance_mode, is_org_admin, user_orgs
from ..collab.comments import user_names
from ..core.errors import BadInput, reject_unknown
from ..core.conflict import ccf_check  # 2.564.0 D (#4701)
from ..api.common import v1_args, v1_call, v1_json, v1_view
from ..core.orgcrypt import oc_list_space, oc_seal_path, oc_user_space, OrgCryptError  # 2.149.0 G (#2517): pulled up from functions
from ..accounts.orgroles import FULL_READ, org_say_refusal, user_orgs_full, need_org_write  # 2.369.5 (#2517): pulled up from functions; 2.565.0 (#4719): FULL_READ
from .teamchat import tchat_coworkers, need_tchat, need_room  # 2.369.5 (#2517): pulled up from functions
from ..accounts.orgs import may_see  # 2.369.5 (#2517): pulled up from functions
from ..tasks.attachments import safe_name, unexec_name, send_stored  # 2.369.5 (#2517): pulled up from functions
from ..notify.alerts import aa_count, aa_oserr  # 2.369.5 (#2517): pulled up from functions
from ..core.errors import UnknownFields  # 2.369.5 (#2517): pulled up from functions
from ..lists.groups import need_group  # 2.565.0 (#4719): a channel shared with a group

TCX_KINDS = ("channel", "group")
TCX_NAME_MAX, TCX_MEMBERS_MAX, TCX_FILES_MAX = 80, 200, 10


def tcx_person_ok(c, uid):
    r = c.execute("SELECT disabled, kind FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r and not r["disabled"] and (r["kind"] or "") != "agent")


def tcx_agent_org(c, aid):
    with system_ctx(c):  # an agent's workspace and owner are structure the boundary rules need (also for foreign agents)
        r = c.execute("SELECT a.org_id, a.owner_id, u.disabled FROM agents a JOIN users u ON u.id=a.user_id WHERE a.user_id=? AND u.kind='agent'",
                      (aid,)).fetchone()
    return r


def tcx_member_ids(c, rid):
    """The member rows of room rid: the core's personal shares (2.565.0, #4719; no group's members). 2.924.0 (#5069): the
    core alone (no fallback rows of tchat_members)."""
    from .tcxcore import tcx_core_members_sql
    return {r[0] for r in c.execute(f"SELECT user_id FROM {tcx_core_members_sql()} cm WHERE cm.room_id=? AND cm.via=0", (rid,))}


def tcx_members(c, r):
    """Who is in a channel / group now: its member rows that still qualify (people enabled and, for an organisation's channel,
    still in it; agents of the channel's organisation only; a personal agent only while its owner is a member)."""
    return tcx_members_of(c, [r])[r["id"]]  # 2.281.0 B (#3110)


def tcx_members_of(c, rooms):
    """2.281.0 B (#3110): tcx_members of several rooms in three statements (was two per member and room, three to four
    times per room in the room list): {room id: member ids}. Same rules as before."""
    out = {r["id"]: set() for r in rooms}
    if not out:
        return out
    # 2.565.0 (#4719): the members are the core's shares of the room (a person, an agent, a group's members: via = the group);
    # a group gives a channel only its enabled people who are full members of the channel's organisation (no guests /
    # accounting, the rule of the open channels). 2.924.0 (#5069): the core alone (no fallback rows of tchat_members)
    from .tcxcore import tcx_core_members_sql
    rows = c.execute(f"""SELECT m.room_id, m.user_id, MIN(m.via) AS via, u.disabled, u.kind
                         FROM (SELECT room_id, user_id, via FROM {tcx_core_members_sql()} cm WHERE cm.room_id = ANY(CAST(? AS BIGINT[]))) m
                         JOIN users u ON u.id=m.user_id GROUP BY m.room_id, m.user_id, u.disabled, u.kind""",
                     (sorted(out),)).fetchall()
    ppl = sorted({x["user_id"] for x in rows if (x["kind"] or "") != "agent"})
    ags = sorted({x["user_id"] for x in rows if (x["kind"] or "") == "agent"})
    orgs, full = {}, {}
    if ppl and any(r["org_id"] for r in rooms):
        if instance_mode(c) != "shared":  # user_orgs of every person at once
            with system_ctx(c):
                for x in c.execute("SELECT user_id, org_id, role FROM org_members WHERE user_id = ANY(CAST(? AS BIGINT[]))", (ppl,)):
                    orgs.setdefault(x[0], set()).add(x[1])
                    if x[2] in FULL_READ:
                        full.setdefault(x[0], set()).add(x[1])
    aorg = {}
    if ags:
        with system_ctx(c):  # tcx_agent_org of every agent at once
            aorg = {x[0]: x for x in c.execute("""SELECT a.user_id, a.org_id, a.owner_id, u.disabled FROM agents a JOIN users u ON u.id=a.user_id
                                                  WHERE a.user_id = ANY(CAST(? AS BIGINT[])) AND u.kind='agent'""", (ags,))}
    by = {r["id"]: r for r in rooms}
    for x in rows:  # the people first (a personal agent follows its owner out)
        r = by[x["room_id"]]
        if (x["kind"] or "") != "agent" and not x["disabled"] and (not r["org_id"] or r["org_id"] in orgs.get(x["user_id"], ())) \
                and (not x["via"] or (r["kind"] == "channel" and (not r["org_id"] or r["org_id"] in full.get(x["user_id"], ())))):
            out[r["id"]].add(x["user_id"])
    for x in rows:
        r, a = by[x["room_id"]], aorg.get(x["user_id"])
        if (x["kind"] or "") == "agent" and not x["via"] and r["kind"] == "channel" and a and not a["disabled"] \
                and (a["org_id"] or None) == (r["org_id"] or None) and (a["owner_id"] is None or a["owner_id"] in out[r["id"]]):
            out[r["id"]].add(x["user_id"])
    return out


def tcx_room_ok(c, r, uid, mem=None, who=None):
    """May uid read the channel / group r? Members; an open channel also every person of its organisation.
    2.369.3 (#3199): who = a dict the caller keeps for one person over many rooms (tcx_rooms_of, the channel list): uid's
    organisations, agent flag and person check are read once into it, not again per open channel."""
    if uid in (tcx_members(c, r) if mem is None else mem):  # 2.281.0 B (#3110): mem = tcx_members, when known
        return True
    if not (r["kind"] == "channel" and r["is_open"] and r["org_id"] and not r["archived_at"]):
        return False
    w = _tcx_who(c, uid, {} if who is None else who)
    return bool(not w["agent"] and r["org_id"] in w["orgs"] and w["ok"])  # 2.143.0 A (#2151): not guests / accounting


def _tcx_who(c, uid, who):
    """2.369.3 (#3199): the per-person part of tcx_room_ok, filled once per dict (same order and checks as before)."""
    if who.get("uid") != uid:
        who.clear()
        who["uid"] = uid
    if "agent" not in who:
        who["agent"] = is_agent_id(c, uid)
    if not who["agent"] and "orgs" not in who:
        who["orgs"] = set(_orgs_full(c, uid))
    if not who["agent"] and "ok" not in who and who["orgs"]:
        who["ok"] = tcx_person_ok(c, uid)
    who.setdefault("orgs", set())
    who.setdefault("ok", False)
    return who


def is_agent_id(c, uid):
    from ..agents.core import agent_ids
    return uid in agent_ids(c)


def tcx_can_manage(c, r, uid, mem=None):
    """Channel: its creator (while a member) or an admin of its organisation. Group: every member."""
    if is_agent_id(c, uid):
        return False
    mem = tcx_members(c, r) if mem is None else mem  # 2.281.0 B (#3110)
    if r["kind"] == "group":
        return uid in mem
    if r["org_id"] and org_say_refusal(c, uid, r["org_id"]):
        return False  # 2.607.0 (#4549, review): a creator who is a guest / read-only person of the organisation now only reads
    if r["org_id"] and is_org_admin(c, uid, r["org_id"]):
        return True
    return r["created_by"] == uid and uid in mem  # 2.113.1 (#2059): removed / left = no longer manages it


def tcx_rooms_of(c, uid, mems=None):
    """The channels / groups uid is a member of (not archived) -- for tchat_rooms (teamchat.py). 2.281.0 B (#3110): mems =
    a dict that gets {room id: tcx_members} of these rooms."""
    from .tcxcore import tcx_core_rooms_sql
    from ..core.objects import obj_token_lists
    if obj_token_lists(uid) is not None:
        return []  # 2.565.0 (#4719): the core's floor (obj_role): a token limited to lists reaches no channel / group
    rows = c.execute(f"""SELECT r.* FROM tchat_rooms r WHERE r.id IN ({tcx_core_rooms_sql(uid)})
                         AND r.kind IN ('channel','group') AND r.archived_at IS NULL""").fetchall()  # 2.924.0 (#5069): the core alone
    mm = tcx_members_of(c, rows)
    if mems is not None:
        mems.update(mm)
    who = {}  # 2.369.3 (#3199): uid's organisations once, not per room
    return [r for r in rows if tcx_room_ok(c, r, uid, mm[r["id"]], who)]


def tcx_group_name(c, r, uid, mem=None):
    if r["name"]:
        return r["name"]
    mem = tcx_members(c, r) if mem is None else mem
    names = user_names(c, mem - {uid})
    return ", ".join(sorted(names.values(), key=str.lower)) or "?"


def tcx_room_brief(c, r, uid, mem=None):
    """The fields of a channel / group in the room list (name, members, organisation, open, archived, may manage)."""
    mem = tcx_members(c, r) if mem is None else mem  # 2.281.0 B (#3110): mem = tcx_members, when known
    d = {"name": tcx_group_name(c, r, uid, mem) if r["kind"] == "group" else r["name"], "members": len(mem),
         "org_id": r["org_id"], "open": bool(r["is_open"]), "archived": bool(r["archived_at"]), "joined": uid in mem,
         "manage": tcx_can_manage(c, r, uid, mem), "created_by": r["created_by"],
         "updated_at": tcx_ver(r)}  # 2.564.0 D (#4701): the version the settings dialog sends back
    if r["kind"] == "group":
        d["member_ids"] = sorted(mem)
        d["custom_name"] = r["name"] or ""
    elif d["manage"]:  # 2.565.0 (#4719): the groups shared with the channel (their people are members while they qualify)
        from .tcxcore import tcx_core_groups
        d["groups"] = tcx_core_groups(c, [r["id"]])[r["id"]]
    return d


def tcx_ver(r):
    """2.564.0 D (#4701): the version of a room's settings (updated_at, else created_at for a room never changed)."""
    return (r["updated_at"] if "updated_at" in r.keys() else None) or r["created_at"]


def tcx_sig(c, uid):
    """A part of tchat_sig: my memberships and the names / states of my channels and groups (renamed, archived, joined)."""
    return tcx_sig_fmt(c.execute(*tcx_sig_q(uid)).fetchone())


def tcx_sig_q(uid):
    """2.149.0 C (#2507): the query of tcx_sig (one row, 5 columns; tchat_sig runs it inside its one statement)."""
    from .tcxcore import tcx_core_members_sql, tcx_core_rooms_sql
    # 2.565.0 (#4719): + the rooms and members through the core's shares (a group shared with a channel)
    # 2.924.0 (#5069): the core alone (no fallback rows of tchat_members): no parameters left
    return (f"""SELECT COUNT(*), COALESCE(SUM(length(r.name)),0), COUNT(r.archived_at), COALESCE(SUM(r.is_open),0),
                      COALESCE(SUM((SELECT COUNT(*) FROM (SELECT user_id FROM {tcx_core_members_sql()} cm WHERE cm.room_id=r.id) xs)),0)
                      FROM tchat_rooms r WHERE r.id IN ({tcx_core_rooms_sql(uid)})""", ())


def tcx_sig_fmt(r):
    return f"{r[0]}-{r[1]}-{r[2]}-{r[3]}-{r[4]}"


def _orgs_full(c, uid, write=False):
    """2.143.0 A (#2151): uid's organisations whose open channels / people they see (write: may open a channel in)."""
    full = set(user_orgs_full(c, uid, write))
    return [o for o in user_orgs(c, uid) if o in full]


def _org_rows(c, uid):
    ids = _orgs_full(c, uid)  # 2.143.0 A (#2151)
    if not ids:
        return []
    with system_ctx(c):  # the names of uid's own organisations
        return c.execute(f"SELECT id, name FROM orgs WHERE id IN ({','.join('?' * len(ids))}) ORDER BY lower(name)", ids).fetchall()


def tcx_org_people(c, oid):
    with system_ctx(c):  # the members of an organisation the asker belongs to (checked by the caller)
        return [r[0] for r in c.execute("""SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id
                                           WHERE m.org_id=? AND u.disabled=0 AND COALESCE(u.kind,'')!='agent' ORDER BY m.user_id""", (oid,))]


def tcx_agents_for(c, uid, oid):
    """The agents uid may add to a channel of organisation oid (None = a private channel): uid's own personal agents of that
    space; an admin of the organisation also its shared agents."""
    with system_ctx(c):  # agents and their owners are structure (the caller's own and those of its organisation)
        if oid:
            rows = c.execute("""SELECT a.user_id, a.owner_id FROM agents a JOIN users u ON u.id=a.user_id
                                WHERE u.kind='agent' AND u.disabled=0 AND a.org_id=?""", (oid,)).fetchall()
        else:
            rows = c.execute("""SELECT a.user_id, a.owner_id FROM agents a JOIN users u ON u.id=a.user_id
                                WHERE u.kind='agent' AND u.disabled=0 AND a.org_id IS NULL AND a.owner_id=?""", (uid,)).fetchall()
    adm = bool(oid) and is_org_admin(c, uid, oid)
    return [r[0] for r in rows if r[1] == uid or (r[1] is None and adm)]


TCX_MEMBERS_ONLY = N_("Only members of the channel can do this. Organisation admins can archive it.")


def tcx_insider(c, r, uid):
    """2.148.1 B (#2491): uid is a member of channel / group r (an organisation admin alone is not). 2.223.2 A (#2869): the
    creator only while a member (left / removed = no longer opens it or adds anybody to it)."""
    return uid in tcx_members(c, r)


def tcx_may_add(c, r, actor, uid):
    """None when actor may add uid to channel / group r, else the reason (shown as it is)."""
    if not is_agent_id(c, uid) and not may_see(c, actor, uid):  # 2.148.1 A (#2490): no name or reason for an unseen account
        return tr("This person cannot be added to this conversation")
    name = user_names(c, [uid]).get(uid, "?")
    if is_agent_id(c, uid):
        if r["kind"] != "channel" or uid not in tcx_agents_for(c, actor, r["org_id"]):
            return tr("This person cannot be added to this conversation")  # 2.148.1 H (#2491): no name of a foreign agent
        return None
    if not tcx_person_ok(c, uid):
        return tr("{0} cannot be added to this conversation", name)
    if r["kind"] == "channel":
        if r["org_id"]:
            return None if r["org_id"] in user_orgs(c, uid) else tr("{0} is not in the organisation of this channel", name)
        return None if uid in tchat_coworkers(c, actor) else tr("{0} cannot be added to this conversation", name)
    # a group: the new person works with every member (each of them could write them a direct message)
    for m in tcx_members(c, r) | {actor}:
        if m != uid and uid not in tchat_coworkers(c, m):
            return tr("{0} does not work with {1}", name, user_names(c, [m]).get(m, "?"))
    return None


def tcx_add(c, rid, uid, actor):
    """2.565.0 (#4719): through the core -- the share of the room's node and the fallback row (collab/tcxcore.py)."""
    from .tcxcore import tcx_core_add
    tcx_core_add(c, rid, uid, actor)


def tcx_clean_name(v, required):
    if v is None and not required:
        return None
    if not isinstance(v, str) or (required and not v.strip()):
        raise BadInput(tr("Give the channel a name") if required else tr("Invalid value: {0}", "name"))
    v = " ".join(v.split())
    if len(v) > TCX_NAME_MAX:
        raise BadInput(tr("Invalid value: {0}", "name"))
    return v


def tcx_id_list(v, field="members"):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > TCX_MEMBERS_MAX or any(isinstance(x, bool) or not isinstance(x, int) for x in v):
        raise BadInput(tr("Invalid value: {0}", field))
    return list(dict.fromkeys(v))


def need_person(c):
    from ..agents.core import need_person as person_only  # an alias: this wrapper has the same name
    need_tchat(c)
    person_only(403, tr("Only people open channels and group conversations"))


def need_xroom(c, rid):
    """A channel / group the current user may read or manage (404 otherwise). An organisation admin manages every channel
    of the organisation (name, open, archive, members) without reading a closed one (tchat_room_ok stays the read check)."""
    r = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (rid,)).fetchone()
    if not r or r["kind"] not in TCX_KINDS:
        raise Denied(404)
    if not tcx_room_ok(c, r, me()) and not tcx_can_manage(c, r, me()):
        raise Denied(404)
    from ..core.objects import obj_gate  # 2.633.0 (#4779, review): the core's floor as in tcx_channels / need_room - a token limited
    if not obj_gate(c, me(), "tchat_room", r):  # to lists renames, archives or adds members to no channel by a known id
        raise Denied(404)
    return r


def tcx_out(c, r, uid=None, mem=None):
    uid = uid or me()
    return {"id": r["id"], "kind": r["kind"], **tcx_room_brief(c, r, uid, mem)}  # 2.281.0 B (#3110): mem = tcx_members, when known


# ---------------------------------------------------------------- routes
@app.get("/api/team/channels")
def tcx_channels():
    """The channels I may see or manage: mine, the open ones of my organisations (joined or not), archived ones I may restore;
    plus whom I may add (per organisation: its people and the agents I may add; my own space: the people I work with and my
    personal agents without an organisation)."""
    from ..agents.core import is_agent
    c = db()
    need_tchat(c)
    uid = me()
    orgs = _orgs_full(c, uid)  # 2.143.0 A (#2151)
    from .tcxcore import tcx_core_rooms_sql
    rows = c.execute(f"""SELECT * FROM tchat_rooms WHERE kind='channel' AND (id IN ({tcx_core_rooms_sql(uid)})
                         OR created_by=? {('OR org_id IN (' + ','.join('?' * len(orgs)) + ')') if orgs else ''}) ORDER BY lower(name), id""",
                     (uid, *orgs)).fetchall()  # 2.924.0 (#5069): the core alone
    from ..core.objects import obj_gate  # 2.633.0 (#4779): the core's floor per row, as need_room (a token limited to lists sees none)
    rows = [r for r in rows if obj_gate(c, uid, "tchat_room", r)]
    mm = tcx_members_of(c, rows)  # 2.281.0 B (#3110): the members of every channel at once
    who = {"uid": uid, "orgs": set(orgs)}  # 2.369.3 (#3199): the organisations read above, once for every channel
    chans = [tcx_out(c, r, uid, mm[r["id"]]) for r in rows
             if tcx_room_ok(c, r, uid, mm[r["id"]], who) or tcx_can_manage(c, r, uid, mm[r["id"]])]
    if is_agent(g.user):
        return jsonify(channels=chans, orgs=[], people=[], agents=[], users={})
    people = sorted(tchat_coworkers(c, uid))
    out_orgs, ids = [], set(people)
    for o in _org_rows(c, uid):
        pp, aa = [p for p in tcx_org_people(c, o["id"]) if p != uid], tcx_agents_for(c, uid, o["id"])
        ids |= set(pp) | set(aa)
        out_orgs.append({"id": o["id"], "name": o["name"], "admin": is_org_admin(c, uid, o["id"]), "people": pp, "agents": aa})
    mine = tcx_agents_for(c, uid, None)
    ids |= set(mine)
    names = user_names(c, ids)
    return jsonify(channels=chans, orgs=out_orgs, people=people, agents=mine, users={str(k): v for k, v in names.items()})


@app.post("/api/team/channels")
def tcx_channel_new():
    """{name, org_id? (null = my own space), open? (organisations only), members? [ids]} -- a new channel; I am its first member."""
    c = db()
    need_person(c)
    b = body()
    reject_unknown(b, ("name", "org_id", "open", "members"))
    uid = me()
    name = tcx_clean_name(b.get("name"), True)
    oid = b.get("org_id")
    if oid is not None and (isinstance(oid, bool) or not isinstance(oid, int) or oid not in user_orgs(c, uid)):
        return err(tr("Invalid value: {0}", "org_id"))
    if oid is not None and oid not in _orgs_full(c, uid, write=True):
        need_org_write(c, uid, oid)  # 2.143.0 A (#2151): guests / read-only / accounting open no channel of the organisation
    op = b.get("open", False)
    if not isinstance(op, bool) or (op and not oid):
        return err(tr("Invalid value: {0}", "open"))
    mem = tcx_id_list(b.get("members"))
    rid = insert_id(c, "INSERT INTO tchat_rooms(kind,name,org_id,is_open,created_by,created_at) VALUES('channel',?,?,?,?,?)",
                    (name, oid, int(op), uid, iso(now_utc())))
    tcx_add(c, rid, uid, uid)
    r = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (rid,)).fetchone()
    for u in mem:
        if u == uid:
            continue
        why = tcx_may_add(c, r, uid, u)
        if why:
            c.rollback()
            return err(why)
        tcx_add(c, rid, u, uid)
    c.commit()
    return jsonify(tcx_out(c, r, uid)), 201


@app.post("/api/team/groups")
def tcx_group_new():
    """{members: [ids, at least two others], name?} -- a group conversation of people who all work with each other."""
    c = db()
    need_person(c)
    b = body()
    reject_unknown(b, ("members", "name"))
    uid = me()
    mem = [u for u in tcx_id_list(b.get("members")) if u != uid]
    if len(mem) < 2:
        return err(tr("A group needs at least two other people"))
    name = tcx_clean_name(b.get("name"), False) or ""
    rid = insert_id(c, "INSERT INTO tchat_rooms(kind,name,created_by,created_at) VALUES('group',?,?,?)", (name, uid, iso(now_utc())))
    tcx_add(c, rid, uid, uid)
    r = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (rid,)).fetchone()
    for u in mem:
        why = tcx_may_add(c, r, uid, u)
        if why:
            c.rollback()
            return err(why)
        tcx_add(c, rid, u, uid)
    c.commit()
    return jsonify(tcx_out(c, r, uid)), 201


@app.patch("/api/team/rooms/<int:rid>")
def tcx_room_patch(rid):
    """{name?, open? (channel of an organisation), archived? (channel)} -- channel: its creator or an organisation admin;
    group: every member (name only; '' = the names of the members)."""
    c = db()
    need_person(c)
    r = need_xroom(c, rid)
    if not tcx_can_manage(c, r, me()):
        raise Denied(403, tr("Only the creator of the channel or an admin of the organisation can change it"))
    b = body()
    reject_unknown(b, ("name", "open", "archived", "expect_updated_at"))
    write_lock(c, f"tchat_rooms-{rid}")  # 2.564.0 D (#4701): changed meantime (another manager, another device) -> 409 + the room
    r = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (rid,)).fetchone()
    ccf_check(b, tcx_ver(r), "room", lambda: tcx_out(c, r))
    if r["kind"] == "group" and ("open" in b or "archived" in b):
        return err(tr("Invalid value: {0}", "open" if "open" in b else "archived"))
    if "name" in b:
        name = tcx_clean_name(b["name"], r["kind"] == "channel") or ""
        c.execute("UPDATE tchat_rooms SET name=? WHERE id=?", (name, rid))
    if "open" in b:
        if not isinstance(b["open"], bool) or (b["open"] and not r["org_id"]):
            return err(tr("Invalid value: {0}", "open"))
        if b["open"] and not r["is_open"] and not tcx_insider(c, r, me()):  # 2.148.1 B (#2491): only its members open it
            raise Denied(403, tr(TCX_MEMBERS_ONLY))
        c.execute("UPDATE tchat_rooms SET is_open=? WHERE id=?", (int(b["open"]), rid))
    if "archived" in b:
        if not isinstance(b["archived"], bool):
            return err(tr("Invalid value: {0}", "archived"))
        c.execute("UPDATE tchat_rooms SET archived_at=? WHERE id=?", (iso(now_utc()) if b["archived"] else None, rid))
    if {"name", "open", "archived"} & set(b):  # review 2.564.0: a body with only the version is no new version
        c.execute("UPDATE tchat_rooms SET updated_at=? WHERE id=?", (iso_ms(now_utc()), rid))
    c.commit()
    return jsonify(tcx_out(c, c.execute("SELECT * FROM tchat_rooms WHERE id=?", (rid,)).fetchone()))


@app.post("/api/team/rooms/<int:rid>/members")
def tcx_member_add(rid):
    """{user_id} -- add someone (channel: its managers; group: every member) or join an open channel myself.
    2.565.0 (#4719): {group_id} -- share a channel with a group (its managers, members of the channel): every person of the
    group is a member while they qualify (tcx_members_of); a group conversation takes no group."""
    c = db()
    need_person(c)
    r = need_xroom(c, rid)
    b = body()
    reject_unknown(b, ("user_id", "group_id"))
    if "group_id" in b:
        return tcx_group_add(c, r, b)
    uid, u = me(), b.get("user_id")
    if isinstance(u, bool) or not isinstance(u, int):
        return err(tr("Invalid value: {0}", "user_id"))
    if r["archived_at"]:
        return err(tr("This channel is archived"), 409)
    if u == uid:  # joining: an open channel of my organisation (tcx_room_ok already said I may read it)
        if r["kind"] != "channel" or not (r["is_open"] or uid in tcx_members(c, r)):
            raise Denied(403)
    elif not tcx_can_manage(c, r, uid):
        raise Denied(403, tr("Only the creator of the channel or an admin of the organisation can change it"))
    else:
        # 2.148.1 B (#2491): an agent only by a member of the channel; 2.148.1 H (#2491): into a closed one, too, nobody else
        if (is_agent_id(c, u) or not r["is_open"]) and not tcx_insider(c, r, uid):
            raise Denied(403, tr(TCX_MEMBERS_ONLY))
        why = tcx_may_add(c, r, uid, u)
        if why:
            return err(why)
    tcx_add(c, rid, u, uid)
    c.commit()
    return jsonify(tcx_out(c, r, uid))


@app.delete("/api/team/rooms/<int:rid>/members/<int:uid>")
def tcx_member_del(rid, uid):
    """Leave (my own id) or remove someone (channel: its managers; group: nobody removes another person, only leaves)."""
    from ..agents.core import is_agent
    c = db()
    need_tchat(c)
    r = need_xroom(c, rid)
    if uid != me():
        if is_agent(g.user) or r["kind"] == "group" or not tcx_can_manage(c, r, me()):
            raise Denied(403)
    if uid not in tcx_member_ids(c, rid):
        raise Denied(404)
    from .tcxcore import tcx_core_take
    tcx_core_take(c, rid, [uid], me())  # 2.565.0 (#4719): through the core (restorable), the fallback row with it
    c.execute("DELETE FROM tchat_reads WHERE room_id=? AND user_id=?", (rid, uid))  # 2.223.2 A (#2869): tchat_sig_q counts read rooms
    tcx_agents_out(c, rid, uid)
    c.commit()
    r = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (rid,)).fetchone()
    return jsonify(tcx_out(c, r) if tcx_room_ok(c, r, me()) or tcx_can_manage(c, r, me()) else {"id": rid, "kind": r["kind"], "left": True})


def tcx_agents_out(c, rid, uid):
    """2.113.1 (#2059): a person leaves / is removed from channel rid: their personal agents in it go along."""
    with system_ctx(c):  # the owner of an agent is structure (the person's own agents)
        own = [x[0] for x in c.execute("SELECT user_id FROM agents WHERE owner_id=?", (uid,))]
    if own:
        from .tcxcore import tcx_core_take
        tcx_core_take(c, rid, own, me() if has_request_context() else None)  # 2.565.0 (#4719): through the core


def tcx_group_add(c, r, b):
    """2.565.0 (#4719): POST .../members {group_id} -- the channel's managers who are members of it share it with a group they
    may see (lists/groups.py need_group)."""
    from .tcxcore import tcx_core_group_put
    gid, uid = b.get("group_id"), me()
    if isinstance(gid, bool) or not isinstance(gid, int) or "user_id" in b:
        return err(tr("Invalid value: {0}", "group_id"))
    if r["kind"] != "channel":
        return err(tr("Only channels can be shared with a group"))
    if r["archived_at"]:
        return err(tr("This channel is archived"), 409)
    if not tcx_can_manage(c, r, uid):
        raise Denied(403, tr("Only the creator of the channel or an admin of the organisation can change it"))
    if not tcx_insider(c, r, uid):
        raise Denied(403, tr(TCX_MEMBERS_ONLY))
    need_group(c, gid)
    if not r["org_id"] and not c.execute("SELECT 1 FROM group_members WHERE group_id=? AND user_id=?", (gid, uid)).fetchone():
        # 2.565.0 (#4719, review F1): a channel without an organisation has no full-member filter - its group must be one the
        # sharer is in (they share a group with every member, as tcx_may_add asks of a person), not any group they may see
        raise Denied(403, tr("Only a group you are in can be shared with this channel"))
    tcx_core_group_put(c, r["id"], gid, uid)
    c.commit()
    return jsonify(tcx_out(c, r, uid))


@app.delete("/api/team/rooms/<int:rid>/groups/<int:gid>")
def tcx_group_del(rid, gid):
    """2.565.0 (#4719): the channel is no longer shared with group gid (its managers); its people who are members only
    through it leave it (the share goes into the core's obj_revoked)."""
    from .tcxcore import tcx_core_group_take
    c = db()
    need_person(c)
    r = need_xroom(c, rid)
    if r["kind"] != "channel" or not tcx_can_manage(c, r, me()):
        raise Denied(403, tr("Only the creator of the channel or an admin of the organisation can change it"))
    if not tcx_core_group_take(c, rid, gid, me()):
        raise Denied(404)
    c.commit()
    r = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (rid,)).fetchone()
    return jsonify(tcx_out(c, r) if tcx_room_ok(c, r, me()) or tcx_can_manage(c, r, me()) else {"id": rid, "kind": r["kind"], "left": True})


# ---------------------------------------------------------------- files
def tcx_input(b):
    """(body dict, files) of a team chat message: JSON, or a multipart form (body, task_id, reply_to, client_id, file...;
    2.139.0 B (#2128): voice=1 + duration_ms = the one file is a voice message, kept in g.tvc for tcx_save_files)."""
    g.tvc = None
    if not (request.files or request.form) or (b and not request.form):
        return b, []
    out = {k: request.form.get(k) for k in request.form}
    unknown = sorted(k for k in [*request.form, *request.files]
                     if k not in ("body", "task_id", "reply_to", "client_id", "file", "voice", "duration_ms", "thread_of"))  # 2.139.0 A (#2127)
    if unknown:
        raise UnknownFields(unknown)
    for k in ("task_id", "reply_to", "thread_of"):
        v = out.get(k)
        if v in (None, ""):
            out.pop(k, None)
        elif isinstance(v, str) and v.isdigit():
            out[k] = int(v)
    files = [f for f in request.files.getlist("file") if f and f.filename]
    if len(files) > TCX_FILES_MAX:
        raise BadInput(tr("At most {0} files per message", TCX_FILES_MAX))
    voice, ms = out.pop("voice", None), out.pop("duration_ms", None)
    if voice not in (None, "", "0"):
        if voice != "1" or len(files) != 1:
            raise BadInput(tr("A voice message is exactly one audio file"))
        g.tvc = {"ms": tvc_duration(ms)}
    return out, files


# ---------------------------------------------------------------- 2.139.0 B (#2128): voice messages
# Recorded in the browser (static/js/voice.js, MediaRecorder: audio/mp4 where it plays everywhere, else webm / ogg) and stored
# as a team chat file with voice = 1. Kalmido never converts or transcribes them; the server only checks the content is audio.
TVC_MAX_MS = 5 * 60 * 1000  # the app stops a recording after 5 minutes
TVC_EXT = {"audio/mp4": "m4a", "audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3"}


def tvc_duration(ms):
    """The length the browser measured as a plausible int (0..TVC_MAX_MS plus a second of slack), None when not given / not a number."""
    try:
        v = int(str(ms).strip())
    except (TypeError, ValueError):
        return None
    return max(0, min(v, TVC_MAX_MS + 1000))


def tvc_audio_kind(path):
    """The audio type the first bytes of a (still plain) file show: audio/mp4 | audio/webm | audio/ogg | audio/mpeg, else None."""
    try:
        with open(path, "rb") as fh:
            h = fh.read(64)
    except OSError:
        return None
    if h[4:8] == b"ftyp" and h[8:12] not in (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis"):
        return "audio/mp4"  # M4A / isom / mp42 / iso5 ... (Safari and Chrome record AAC in an mp4 box)
    if h[:4] == b"\x1a\x45\xdf\xa3":
        return "audio/webm"  # EBML (webm / matroska, Opus from Firefox and Chrome)
    if h[:4] == b"OggS":
        return "audio/ogg"
    if h[:3] == b"ID3" or (len(h) > 1 and h[0] == 0xFF and h[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    return None


def tcx_files_refused(c, r):
    """An error response when conversation r cannot take files (end-to-end encrypted), else None."""
    if "e2e" in r.keys() and r["e2e"]:
        return err(tr("Files cannot be sent in an end-to-end encrypted conversation"), 409)
    if r["kind"] == "list":
        from .liste2echan import le2c_mode
        if le2c_mode(c, r)[0]:
            return err(tr("Files cannot be sent in an end-to-end encrypted conversation"), 409)
    if r["kind"] == "channel" and r["archived_at"]:
        return err(tr("This channel is archived"), 409)
    return None


def tcx_space(c, r, uid):
    """The space whose key seals the files of conversation r: a list channel = its list's, a channel of an organisation =
    the organisation's, else the uploader's account (the server opens the file for everyone who may see the conversation)."""
    if r["kind"] == "list":
        return oc_list_space(c, r["list_id"])
    if r["kind"] == "channel" and r["org_id"]:
        return r["org_id"]
    return oc_user_space(uid)


def tcx_save_files(c, r, m, files, saved):
    """Stores the uploaded files of team chat message m (room r). Returns an error message or None (the caller rolls back +
    unlinks saved on an error / OSError)."""
    from ..files.upsafe import h6d_save, up_check_path, up_after_store, UploadRefused
    uid = m["user_id"]
    agent = is_agent_id(c, uid)
    if not agent:  # a person's files count towards their storage (agents: like the agent chat, not counted)
        from ..admin.hosting import quota_guard
        quota_guard(c, uid)
    sub = os.path.join("tchat", str(r["id"]))
    try:
        os.makedirs(os.path.join(ATT_DIR, sub), exist_ok=True)
    except OSError as e:
        aa_count("storage", "attachments", aa_oserr(e))
        raise
    sid, ts = tcx_space(c, r, uid), iso(now_utc())
    oid = sid if sid and sid > 0 else None
    voice = g.get("tvc")  # 2.139.0 B (#2128): {ms} when tcx_input took a voice message (exactly one file)
    for f in files:
        name = safe_name(f.filename)
        unexec = agent and unexec_name(name) != name  # no executable endings from agents (as in the agent chat)
        if unexec:
            name = unexec_name(name)
        rel = os.path.join(sub, f"{uuid.uuid4().hex[:12]}-{name}")
        full = os.path.join(ATT_DIR, rel)
        try:
            h6d_save(f, full)  # stops right after MAX_FILE_MB (refused below)
        except OSError as e:
            aa_count("storage", "attachments", aa_oserr(e))
            raise
        saved.append(rel)
        size = os.path.getsize(full)
        if size > MAX_FILE_MB * 1024 * 1024:
            return tr("{0}: larger than {1} MB", name, MAX_FILE_MB)
        if not size:
            return tr("{0}: the file is empty and was not uploaded", name)
        mime = "text/plain" if unexec else (f.mimetype if f.mimetype and f.mimetype != "application/octet-stream" else None) \
            or mimetypes.guess_type(name)[0] or "application/octet-stream"
        kind = None
        if voice:  # 2.139.0 B (#2128): a voice message must be audio by its content; the name ending follows the content
            kind = tvc_audio_kind(full)
            if not kind:
                return tr("{0}: a voice message must be an audio recording", name)
            mime, name = kind, safe_name(f"{os.path.splitext(name)[0] or 'voice'}.{TVC_EXT[kind]}")
        try:  # virus scan, type from the content, photo metadata removed
            size, mime, info = up_check_path(c, full, name, mime, uid, oid, "tchat")
        except UploadRefused as e:
            return str(e)
        if kind and mime in ("application/octet-stream", "video/mp4"):  # the picture / PDF check knows no audio: keep it
            mime = kind
        oc_seal_path(c, sid, full, fresh=True)  # at rest with the key of the conversation's space (after the checks)
        # 2.113.1 (#2059): a list channel's file row has no organisation (like its room): the list's space is looked up when
        # it moves (admin/orgcrypt_cli.py SPACE_SQL), so the file follows the list into / out of an organisation
        fid = insert_id(c, "INSERT INTO tchat_files(message_id,room_id,org_id,user_id,name,mime,size,path,created_at,voice,duration_ms) "
                           "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (m["id"], r["id"], None if r["kind"] == "list" else oid, uid, name, mime, size, rel, ts,
                         1 if kind else 0, voice["ms"] if kind else None))
        up_after_store(c, "tchat", fid, oid, info)
    return None


def tcx_store(c, r, m, files):
    """tcx_save_files with the clean-up on a refusal (raises BadInput) or a disk error (raises on)."""
    saved = []
    try:
        e = tcx_save_files(c, r, m, files, saved)
    except OSError:
        c.rollback()
        unlink_files(saved)
        raise
    if e:
        c.rollback()
        unlink_files(saved)
        raise BadInput(e)


def tcx_files_of(c, mids, api=None):
    """{message id: [{id, name, mime, size, url, voice, duration_ms, up?}]} of team chat messages (api: the REST address, default:
    from the request); 2.139.0 B (#2128): voice = a voice message recorded in the app, duration_ms its length (null = unknown)."""
    out, mids = {}, [x for x in mids if x]
    if not mids:
        return out
    if api is None:
        api = request.path.startswith("/api/v1/")
    for f in c.execute(f"SELECT id, message_id, name, mime, size, voice, duration_ms FROM tchat_files WHERE message_id IN ({','.join('?' * len(mids))}) ORDER BY id", mids):
        out.setdefault(f["message_id"], []).append({"id": f["id"], "name": f["name"], "mime": f["mime"], "size": f["size"],
                                                    "url": f"/api/v1/team/files/{f['id']}" if api else f"/api/team/files/{f['id']}",
                                                    "voice": bool(f["voice"]), "duration_ms": f["duration_ms"]})
    if out:
        from ..files.scan import sc_up
        sc_up(c, "tchat", [d for v in out.values() for d in v])
    return out


# 2.530.0 A (#4315): tcx_files_drop is gone -- a deleted message keeps its files in the trash (collab/cmttrash.py)


def tcx_user_purge(c, uid):
    """2.113.1 (#2059): an account is deleted: its files sealed with its own key (direct messages, groups, channels of its own
    space) go for good -- rows now, the paths for the caller to unlink after the commit. Files in an organisation's channel
    or a list channel are sealed for that space and stay with their messages."""
    with system_ctx(c):  # the account's own files in every conversation (the deletion's clean-up)
        rows = c.execute("""SELECT f.id, f.path FROM tchat_files f JOIN tchat_rooms r ON r.id=f.room_id
                            WHERE f.user_id=? AND f.org_id IS NULL AND r.kind!='list'""", (uid,)).fetchall()
        if not rows:
            return []
        from ..files.textscan import ts_forget
        for x in rows:
            ts_forget(c, "tchat", x["id"])
        c.execute(f"DELETE FROM tchat_files WHERE id IN ({','.join('?' * len(rows))})", [x["id"] for x in rows])
    return [x["path"] for x in rows if x["path"]]


def tcx_file_access(c, fid):
    """A team chat file the current user may read (sees its conversation; not locked by the virus scan)."""
    need_tchat(c)
    f = c.execute("SELECT * FROM tchat_files WHERE id=?", (fid,)).fetchone()
    if not f:
        raise Denied(404)
    m = c.execute("SELECT deleted_at FROM tchat_msgs WHERE id=?", (f["message_id"],)).fetchone()
    if not m or m["deleted_at"]:
        raise Denied(404)
    need_room(c, f["room_id"])
    from ..files.scan import sc_guard
    sc_guard(c, "tchat", fid)
    return f


@app.get("/api/team/files/<int:fid>")
def tcx_file_get(fid):
    """A file of a team chat message (inline image / pdf / text, ?dl=1 download): everyone who sees the conversation."""
    return tcx_send(tcx_file_access(db(), fid))


def tcx_send(f):
    """send_stored; 2.113.1 (#2059): a file whose key is gone (sealed for a deleted account) answers 410, not an error."""
    try:
        return send_stored(f)
    except OrgCryptError:
        e = err(tr("File damaged or missing"), 410)
        e[0].headers["Cache-Control"] = "no-store"
        return e


def tcx_files_gc(c):
    """Watchdog: team chat files whose message / conversation is gone (a deleted list, organisation, person) leave the disk.
    At most hourly."""
    if time.time() - _TCX_GC["at"] < 3600:
        return 0
    _TCX_GC["at"] = time.time()
    root = os.path.join(ATT_DIR, "tchat")
    if not os.path.isdir(root):
        return 0
    with system_ctx(c):  # every stored path of the instance (server-side clean-up, no content)
        known = {r[0] for r in c.execute("SELECT path FROM tchat_files")}
    # 2.272.0 A (#3026): an orphan file like orf_tick -- switch ret_on("files") (off = count), older than ret_days("files")
    n, purge, age = 0, ret_on("files"), max(3600, ret_days("files") * 86400)
    for d in os.listdir(root):
        for fn in os.listdir(os.path.join(root, d)) if os.path.isdir(os.path.join(root, d)) else []:
            rel = os.path.join("tchat", d, fn)
            if rel in known:
                continue
            try:  # 2.113.1 (#2059): a file deleted meanwhile (a message deleted right now) is simply skipped
                old = time.time() - os.path.getmtime(os.path.join(ATT_DIR, rel)) > age  # one just uploading has no row yet
            except OSError:
                continue
            if old:
                if purge:
                    unlink_files([rel])
                n += 1
    ret_report(c, "files", {"tchat_files": n}, purge, run="tchat_files")
    c.commit()
    return n


_TCX_GC = {"at": 0.0}


# ---------------------------------------------------------------- REST API v1 (people; agents read, write, leave)
@app.get("/api/v1/team/channels")
@v1_view
def v1_tcx_channels():
    v1_args(())
    j = v1_call(tcx_channels)
    return jsonify(data=j["channels"], orgs=j["orgs"], people=j["people"], agents=j["agents"], users=j["users"], next_cursor=None)


@app.post("/api/v1/team/channels")
@v1_view
def v1_tcx_channel_new():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("name", "org_id", "open", "members"))
    return jsonify(v1_call(tcx_channel_new, body=b)), 201


@app.post("/api/v1/team/groups")
@v1_view
def v1_tcx_group_new():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("members", "name"))
    return jsonify(v1_call(tcx_group_new, body=b)), 201


@app.patch("/api/v1/team/rooms/<int:rid>")
@v1_view
def v1_tcx_room_patch(rid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("name", "open", "archived"))
    return jsonify(v1_call(tcx_room_patch, rid, body=b))


@app.post("/api/v1/team/rooms/<int:rid>/members")
@v1_view
def v1_tcx_member_add(rid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("user_id", "group_id"))  # 2.565.0 (#4719): + group_id (people only)
    return jsonify(v1_call(tcx_member_add, rid, body=b))


@app.delete("/api/v1/team/rooms/<int:rid>/groups/<int:gid>")
@v1_view
def v1_tcx_group_del(rid, gid):
    """2.565.0 (#4719): the channel is no longer shared with the group (people only)."""
    v1_args(())
    v1_call(tcx_group_del, rid, gid, body={})
    return Response(status=204)


# 2.139.1 (#2059): the second id as <uid> like the other v1 member routes, so the route matches its documented path
@app.delete("/api/v1/team/rooms/<int:rid>/members/<uid>")
@v1_view
def v1_tcx_member_del(rid, uid):
    v1_args(())
    if not uid.isdigit():
        return err(tr("unknown"), 404)
    v1_call(tcx_member_del, rid, int(uid), body={})
    return Response(status=204)


@app.get("/api/v1/team/files/<int:fid>")
@v1_view
def v1_tcx_file_get(fid):
    """The binary of a team chat file: members of its conversation (people and agents)."""
    v1_args(("dl", "v"))
    return tcx_send(tcx_file_access(db(), fid))


def tcx_spec(paths, schemas, op, ok, errs, ref, pid, nul, page):
    TC = "Team chat"
    schemas["TeamChannel"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "kind": {"type": "string", "enum": ["channel", "group"]}, "name": {"type": "string"},
        "members": {"type": "integer"}, "org_id": nul("integer", description="null = a channel of your own space"),
        "open": {"type": "boolean", "description": "every person of the organisation sees it and may join"},
        "archived": {"type": "boolean"}, "joined": {"type": "boolean"}, "manage": {"type": "boolean", "description": "you may rename / archive it and manage members"},
        "member_ids": {"type": "array", "items": {"type": "integer"}, "description": "group: its members"},
        "groups": {"type": "array", "items": {"type": "integer"}, "description": "2.565.0 (#4719): a channel you manage: the groups shared with it"}}}
    schemas["TeamChannelPage"] = page("TeamChannel")
    rp = pid(desc="Conversation (room) id")
    paths["/team/channels"] = {
        "get": op("2.113.1 (#2059): channels you see or manage (yours, the open ones of your organisations, archived ones you may restore) "
                  "and whom you may add (orgs[].people / agents, people, agents)", TC, ok(ref("TeamChannelPage")) | errs("404")),
        "post": op("2.113.1 (#2059): open a channel (people only): org_id null = your own space (invited only, people you work with)",
                   TC, ok(ref("TeamChannel"), "Created", "201") | errs("400", "403", "404"),
                   body={"type": "object", "properties": {"name": {"type": "string", "maxLength": TCX_NAME_MAX}, "org_id": {"type": "integer"},
                                                          "open": {"type": "boolean"}, "members": {"type": "array", "items": {"type": "integer"}}},
                         "required": ["name"]}, scope="comments")}
    paths["/team/groups"] = {"post": op("2.113.1 (#2059): a group conversation with at least two other people who all work with each other (people only)",
                                        TC, ok(ref("TeamChannel"), "Created", "201") | errs("400", "403", "404"),
                                        body={"type": "object", "properties": {"members": {"type": "array", "items": {"type": "integer"}},
                                                                               "name": {"type": "string", "maxLength": TCX_NAME_MAX}},
                                              "required": ["members"]}, scope="comments")}
    paths["/team/rooms/{id}"] = {"patch": op("2.113.1 (#2059): rename a channel / group, open / close or archive / restore a channel "
                                             "(its creator or an organisation admin; a group: every member)", TC,
                                             ok(ref("TeamChannel")) | errs("400", "403", "404"), [rp],
                                             body={"type": "object", "properties": {"name": {"type": "string"}, "open": {"type": "boolean"},
                                                                                    "archived": {"type": "boolean"}}}, scope="comments")}
    paths["/team/rooms/{id}/members"] = {"post": op("2.113.1 (#2059): add someone to a channel / group, or join an open channel (your own id); "
                                                    "2.565.0 (#4719): or share a channel with a group (group_id, people only: its full members "
                                                    "of the channel's organisation are members)", TC,
                                                    ok(ref("TeamChannel")) | errs("400", "403", "404", "409"), [rp],
                                                    body={"type": "object", "properties": {"user_id": {"type": "integer"}, "group_id": {"type": "integer"}}},
                                                    scope="comments")}
    paths["/team/rooms/{id}/groups/{gid}"] = {"delete": op("2.565.0 (#4719): a channel you manage is no longer shared with the group (people only)",
                                                           TC, {"204": {"description": "Removed"}} | errs("403", "404"),
                                                           [rp, pid("gid", "Group id")], scope="comments")}
    paths["/team/rooms/{id}/members/{uid}"] = {"delete": op("2.113.1 (#2059): leave a channel / group (your own id) or remove someone from a channel you manage",
                                                            TC, {"204": {"description": "Removed"}} | errs("403", "404"),
                                                            [rp, pid("uid", "User id")], scope="comments")}
    paths["/team/files/{id}"] = {"get": op("2.113.1 (#2059): the binary of a file of a team chat message (messages carry attachments[].url)", TC,
                                           {"200": {"description": "The file", "content": {"application/octet-stream": {}}}} | errs("403", "404"),
                                           [pid(desc="File id"), {"name": "dl", "in": "query", "required": False, "schema": {"type": "string"}}])}
