"""Team chat (rooms and direct messages)."""
import re
from flask import g, has_request_context, jsonify, request, Response

from ..core.config import app, PUBLIC_URL
from ..core.pg import insert_id, system_ctx, write_lock
from ..core.i18n import tr
from ..core.db import body, db, err, iso, iso_ms, now_utc, usettings
from ..accounts.session import me
from ..accounts.pictures import avatar_map
from ..accounts.orgs import may_see
from ..core.access import collab_all, Denied, FULL_ROLES, list_role, MANAGE_ROLES, task_visible, vis_sql
from ..core.access import access_note, health_hidden, org_trips_hidden, otr_live, ov_open, reading_sql, token_lists  # 2.281.0 B (#3110)
from ..accounts.orgroles import FULL_READ, role_known
from ..accounts.orgs import INSTANCE_ENV
from ..tasks.validation import as_int
from ..collab.comments import collab_on, collab_user, comment_plain, lang_of, MENTION_RE, user_names
from ..collab.news import list_bell, notif_ok
from ..core.errors import reject_unknown, BadInput
from ..notify.push import push_handled, push_prio, push_reachable
from ..api.common import hit_limit, v1_args, v1_call, v1_json, v1_view
from ..agents.core import agent_emit, AGENT_EVENT_COMMENT_CHARS, agent_ids, is_agent, listen_agents_of
from ..collab.reactions import clean_emoji
from ..collab.replies import reply_check, reply_quotes


# ---------------------------------------------------------------- 2.17.0 (#419): team chat
# People talk to each other: direct messages between two people (who work together: they share a list or a group) and
# one channel per shared list (everyone who sees the whole list; participants, who only see their own tasks, are not in
# it). Agents shared with a list are members of its channel: they read it through the API and get the event
# "team_message" when someone @mentions them there. Messages are Markdown with <@id> mentions, can name a task, get
# reactions; the sender edits / deletes their own (list owners / admins delete any in their channel). Read state per
# person; pushes: every DM and every @mention (notification row "chat"; a muted list bell keeps a channel quiet except
# mentions). Needs collaboration on (instance switch); the person's module "collab" off = no team chat.
TCHAT_MAX, TCHAT_PAGE = 8000, 50
TCHAT_RATE = 60  # 2.281.0 B (#3117): messages per person and minute (each one costs pushes and badge counts for the room)
TCX_KINDS = ("channel", "group")  # 2.113.1 (#2059): rooms with their own members (collab/teamchan.py)


def tchat_on(c, uid=None):
    if not collab_all():
        return False
    s = usettings(c, uid or me())
    return collab_on(s)


def need_tchat(c):
    if is_agent(g.user):
        if not collab_all():
            raise Denied(404)
        return
    if not tchat_on(c):
        raise Denied(404)


def tchat_coworkers(c, uid):
    """Ids of the people uid works with: a common list (any role) or a common group; never agents, never disabled."""
    rows = c.execute("""SELECT DISTINCT x.u FROM (
          SELECT m2.user_id AS u FROM list_members m1 JOIN list_members m2 ON m2.list_id=m1.list_id WHERE m1.user_id=?
          UNION SELECT l.owner_id FROM list_members m JOIN lists l ON l.id=m.list_id WHERE m.user_id=?
          UNION SELECT m.user_id FROM list_members m JOIN lists l ON l.id=m.list_id WHERE l.owner_id=?
          UNION SELECT g2.user_id FROM group_members g1 JOIN group_members g2 ON g2.group_id=g1.group_id WHERE g1.user_id=?) x
        JOIN users u ON u.id=x.u WHERE x.u!=? AND u.disabled=0 AND COALESCE(u.kind,'')!='agent'""", (uid, uid, uid, uid, uid)).fetchall()
    return {r[0] for r in rows}


def tchat_list_members(c, lid):
    """Who is in a list's channel: everyone who sees the whole list (owner, admin, member, viewer), agents included."""
    return tchat_members_of(c, [lid]).get(lid, set())  # 2.281.0 B (#3110): the set rule of tchat_members_of


def tchat_members_of(c, lids):
    """2.281.0 B (#3110): tchat_list_members for many lists in a fixed number of statements (was list_role per member, twice
    per list: 3,000 statements for /api/team): {list id: member ids}. The candidates stay the owner, the members and the
    people of a shared group (no participants); each one counts when list_role would give them a role in FULL_ROLES -- the
    same checks (trash, health / budget, organisation boundary, token allowlist, read later, "Everyone in the organisation"),
    read for all candidates at once. Archived lists have no channel."""
    lids = sorted({int(x) for x in lids if x})
    out = {lid: set() for lid in lids}
    if not lids:
        return out
    rows = {r["id"]: r for r in c.execute(
        f"SELECT l.id, l.owner_id, l.life, l.org_id, l.family, l.org_visibility, l.org_edit, {reading_sql()} AS rd FROM lists l "
        f"WHERE l.id = ANY(CAST(? AS BIGINT[])) AND l.archived=0 AND {otr_live()}", (lids,))}
    if not rows:
        return out
    ids = sorted(rows)
    mem = {(r[0], r[1]): r[2] for r in c.execute(
        "SELECT list_id, user_id, role FROM list_members WHERE list_id = ANY(CAST(? AS BIGINT[]))", (ids,))}
    cand = {lid: {rows[lid]["owner_id"]} for lid in ids}
    for (lid, u), role in mem.items():
        if role != "participant":
            cand[lid].add(u)
    for r in c.execute("""SELECT s.list_id, gm.user_id FROM group_shares s JOIN group_members gm ON gm.group_id=s.group_id
                          WHERE s.list_id = ANY(CAST(? AS BIGINT[])) AND s.role!='participant'""", (ids,)):
        cand[r[0]].add(r[1])
    aid = g.get("audit_aid") if has_request_context() else None  # list_role notes an agent's access for every role it finds
    uids = sorted({u for s in cand.values() for u in s if u} | ({aid} if aid else set()))
    kinds = {r[0]: r[1] for r in c.execute("SELECT id, kind FROM users WHERE id = ANY(CAST(? AS BIGINT[]))", (uids,))}
    orgs, oroles, agents, boundary = {}, {}, {}, False
    if any(rows[lid]["org_id"] for lid in ids):
        with system_ctx(c):  # memberships are structure (as acx_of / org_roles_of read them, also of other people)
            agents = {r[0]: r[1] for r in c.execute("SELECT user_id, org_id FROM agents WHERE user_id = ANY(CAST(? AS BIGINT[]))", (uids,))}
            if INSTANCE_ENV != "shared":
                for r in c.execute("SELECT user_id, org_id, role FROM org_members WHERE user_id = ANY(CAST(? AS BIGINT[]))", (uids,)):
                    oroles.setdefault(r[0], {})[r[1]] = role_known(r[2], r[1], r[0])
                for r in c.execute("SELECT personal_of, id FROM orgs WHERE personal_of = ANY(CAST(? AS BIGINT[]))", (uids,)):
                    orgs.setdefault(r[0], set()).add(r[1])
        for u in uids:  # acx_of: an agent's own workspace; a person's organisations + the personal office
            orgs[u] = ({agents[u]} if agents[u] else set()) if u in agents else (set(oroles.get(u, {})) | orgs.get(u, set()))
        boundary = INSTANCE_ENV != "shared"
    req = g.user["id"] if has_request_context() and getattr(g, "user", None) is not None else None
    collab, tl = collab_all(), token_lists()

    def hidden(u):  # health_hidden(c, u) without a statement per person
        return health_hidden() if u == req else kinds.get(u) == "agent"

    def role_of(lid, u):  # list_role(c, lid, u) as a truth value + whether it sees the whole list
        r = rows[lid]
        if (r["life"] or "") in ("health", "budget") and hidden(u):
            return None
        if r["org_id"] and boundary and not (u in agents and not agents[u]) and r["org_id"] not in orgs.get(u, ()):
            return None  # acx_org_ok
        if u == req and tl is not None and lid not in tl:
            return None
        if ((u == req and org_trips_hidden()) or hidden(u)) and r["rd"]:
            return None
        if r["owner_id"] == u:
            return "owner"
        if (lid, u) in mem:
            return mem[(lid, u)] if collab else None
        if not (collab and ov_open(r)) or kinds.get(u) == "agent" or u in agents:
            return None  # ov_role: people of the organisation who see all of it ("Everyone in the organisation")
        return "view" if oroles.get(u, {}).get(r["org_id"]) in FULL_READ else None

    for lid in ids:
        for u in cand[lid] | ({aid} if aid else set()):
            role = role_of(lid, u) if u else None
            if role and u == aid:
                access_note(lid)
            if role in FULL_ROLES and u in cand[lid]:
                out[lid].add(u)
    return out


def tchat_room_members(c, r):
    if r["kind"] == "dm":
        return {x for x in (r["a"], r["b"]) if x}  # 2.152.0 A (#2164): a deleted partner is NULL (the room stays)
    if r["kind"] in TCX_KINDS:  # 2.113.1 (#2059): channels / groups (collab/teamchan.py)
        from .teamchan import tcx_members
        return tcx_members(c, r)
    return tchat_list_members(c, r["list_id"])


def tchat_room_ok(c, r, uid):
    if not r:
        return False
    if r["kind"] == "dm":
        return uid in (r["a"], r["b"])
    if r["kind"] in TCX_KINDS:  # 2.113.1 (#2059)
        from .teamchan import tcx_room_ok
        return tcx_room_ok(c, r, uid)
    if r["kind"] != "list":
        return False
    return list_role(c, r["list_id"], uid) in FULL_ROLES and c.execute(
        "SELECT 1 FROM lists WHERE id=? AND archived=0", (r["list_id"],)).fetchone() is not None


def tchat_dm_open(c, r, uid):
    """2.266.0 (#2970): may uid still WRITE in this DM (and so push to the partner)? Only while both still see each other
    (may_see both ways: a common organisation or connection) or still share a list or group (tchat_coworkers, the rule that
    opens a DM; review: a guest / accounting member sees only the admins through may_see) and the partner is active. After
    leaving or being removed from the organisation (and its lists) the room stays readable, but frozen."""
    if r["kind"] != "dm":
        return True
    other = r["b"] if r["a"] == uid else r["a"]
    if not other or c.execute("SELECT 1 FROM users WHERE id=? AND disabled=0", (other,)).fetchone() is None:
        return False
    return (may_see(c, uid, other) and may_see(c, other, uid)) or other in tchat_coworkers(c, uid)


def need_dm_open(c, r):
    if not tchat_dm_open(c, r, me()):
        raise Denied(403, tr("You no longer work together - this conversation is read-only"))


def need_room(c, rid):
    r = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (rid,)).fetchone()
    if not tchat_room_ok(c, r, me()):
        raise Denied(404)
    return r


def tchat_list_room(c, lid, create=True):
    r = c.execute("SELECT * FROM tchat_rooms WHERE kind='list' AND list_id=?", (lid,)).fetchone()
    if r or not create:
        return r
    c.execute("INSERT INTO tchat_rooms(kind,list_id,created_at) VALUES('list',?,?) ON CONFLICT DO NOTHING", (lid, iso(now_utc())))
    return c.execute("SELECT * FROM tchat_rooms WHERE kind='list' AND list_id=?", (lid,)).fetchone()


def tchat_shared_lists(c, uid, mm=None):
    """The lists of uid that have a channel: shared (another person or an agent sees the whole list), not archived.
    2.281.0 B (#3110): mm = a dict that gets {list id: members} of every list (tchat_rooms reuses it)."""
    # 2.46.0 (#1603): channels of the joined lists (not of those seen only through "Everyone in the organisation")
    ls = c.execute(f"SELECT id, name, is_inbox FROM lists WHERE id IN {vis_sql(ov=False)} AND archived=0 ORDER BY lower(name)", (uid, uid)).fetchall()
    mem = tchat_members_of(c, [l["id"] for l in ls])  # 2.281.0 B (#3110): uid is a candidate of each (owner / member row)
    if mm is not None:
        mm.update(mem)
    return [l for l in ls if uid in mem.get(l["id"], ()) and len(mem[l["id"]]) >= 2]


def tchat_last_read(c, rid, uid):
    r = c.execute("SELECT last_id, muted FROM tchat_reads WHERE room_id=? AND user_id=?", (rid, uid)).fetchone()
    return (r["last_id"], bool(r["muted"])) if r else (0, False)


def tchat_rooms(c, uid, create=False, full=True):
    """Every conversation of uid: the channels of the shared lists + the DMs that have messages (newest first).
    2.281.0 B (#3110): the list channels in a fixed number of statements; create = add the missing channel rows of shared
    lists (only /api/team and /api/v1/team/rooms, which commit right away; /api/state, pushes and mails never write: a
    channel without its row has no messages, so nothing unread). full=False: only what the unread counts need."""
    mm, ls = {}, {}
    for l in tchat_shared_lists(c, uid, mm):
        ls[l["id"]] = l
    have = {r["list_id"]: r for r in c.execute("SELECT * FROM tchat_rooms WHERE kind='list' AND list_id = ANY(CAST(? AS BIGINT[]))",
                                               (sorted(ls),))} if ls else {}
    rooms = []
    for lid in ls:
        r = have.get(lid) or (tchat_list_room(c, lid) if create else None)
        if r:
            rooms.append(r)
    for r in c.execute("SELECT * FROM tchat_rooms WHERE kind='dm' AND (a=? OR b=?) AND last_at IS NOT NULL", (uid, uid)):
        rooms.append(r)
    from .teamchan import tcx_room_brief, tcx_rooms_of
    xm = {}
    rooms += tcx_rooms_of(c, uid, xm)  # 2.113.1 (#2059): my channels and groups (also without messages); 2.281.0 B: + members
    names = user_names(c, {x for r in rooms if r["kind"] == "dm" for x in (r["a"], r["b"])}) if full else {}
    lasts, reads, unr, thr = _tchat_room_counts(c, [r["id"] for r in rooms], uid)
    out = []
    for r in rooms:
        # 2.139.0 A (#2127): the preview and the unread count: the main conversation + the threads I take part in
        last = lasts.get(r["id"])
        muted = reads.get(r["id"], (0, False))[1]
        unread, any_mention = unr.get(r["id"], (0, False))
        tu, tm = thr.get(r["id"], (0, False))
        mention = (bool(unread) and any_mention) or tm
        unread += tu
        d = {"id": r["id"], "kind": r["kind"], "unread": unread, "mention": mention, "muted": muted,
             "last": tchat_msg_brief(c, last) if last and full else None, "last_at": last["created_at"] if last else None}
        if not full:  # 2.281.0 B (#3110): the unread counts (/api/state, read, pushes, mails)
            pass
        elif r["kind"] == "dm":
            other = r["b"] if r["a"] == uid else r["a"]
            d.update(user_id=other, name=names.get(other, "?"), e2e=bool(r["e2e"]))  # 2.42.0 (#909)
            if not tchat_dm_open(c, r, uid):  # 2.266.0 (#2970): frozen (read-only)
                d["closed"] = True
        elif r["kind"] in TCX_KINDS:
            d.update(tcx_room_brief(c, r, uid, xm.get(r["id"])))
        else:  # 2.281.0 B (#3110): name and members from tchat_shared_lists (was two lookups per list)
            d.update(list_id=r["list_id"], name=ls[r["list_id"]]["name"], members=len(mm[r["list_id"]]))
            from ..collab.liste2echan import le2c_room
            d.update(le2c_room(c, r))  # 2.64.2 C (#1817): list_e2e, gen
        out.append(d)
    out.sort(key=lambda d: (d["last_at"] or ""), reverse=True)
    return out


def _tchat_room_counts(c, ids, uid):
    """2.149.0 C (#2507): what tchat_rooms needs per room in four statements for all rooms (was four to five per room):
    ({room: newest main message}, {room: (last read id, muted)}, {room: (unread main messages of others, a message after
    my read mark @mentions me)}, {room: tth_unread()}). Same conditions as the per-room queries before."""
    ids = sorted({int(i) for i in ids})
    if not ids:
        return {}, {}, {}, {}
    lasts = {r["room_id"]: r for r in c.execute(
        "SELECT DISTINCT ON (room_id) * FROM tchat_msgs WHERE room_id = ANY(CAST(? AS BIGINT[])) AND deleted_at IS NULL "
        "AND thread_of IS NULL ORDER BY room_id, id DESC", (ids,))}
    reads = {r[0]: (r[1], bool(r[2])) for r in c.execute(
        "SELECT room_id, last_id, muted FROM tchat_reads WHERE user_id=? AND room_id = ANY(CAST(? AS BIGINT[]))", (uid, ids))}
    pat = f"%<@{uid}>%"
    unr = {r[0]: (r[1], bool(r[2])) for r in c.execute(
        """SELECT m.room_id, COUNT(*) FILTER (WHERE COALESCE(m.user_id,0)!=?), bool_or(m.body ILIKE ?) FROM tchat_msgs m
           LEFT JOIN tchat_reads d ON d.room_id=m.room_id AND d.user_id=?
           WHERE m.room_id = ANY(CAST(? AS BIGINT[])) AND m.id>COALESCE(d.last_id,0) AND m.deleted_at IS NULL AND m.thread_of IS NULL
           GROUP BY m.room_id""", (uid, pat, uid, ids))}
    thr = {r[0]: (r[1], bool(r[2])) for r in c.execute(
        """SELECT t.room_id, COUNT(*), COALESCE(SUM(CASE WHEN m.body ILIKE ? THEN 1 ELSE 0 END),0) FROM tchat_msgs m
           JOIN tchat_thread_reads t ON t.root_id=m.thread_of AND t.user_id=? AND t.follow=1
           WHERE t.room_id = ANY(CAST(? AS BIGINT[])) AND m.room_id=t.room_id AND m.id>t.last_id AND m.deleted_at IS NULL
           AND COALESCE(m.user_id,0)!=? GROUP BY t.room_id""", (pat, uid, ids, uid))}
    return lasts, reads, unr, thr


def tchat_unread_both(c, uid):
    """2.149.0 C (#2507): (tchat_unread, tchat_dm_unread) from one tchat_rooms (/api/state read it twice)."""
    if not tchat_on(c, uid):
        return 0, 0
    rooms = tchat_rooms(c, uid, full=False)  # 2.281.0 B (#3110): no writes, no previews
    return (sum(x["unread"] for x in rooms if not x["muted"] or x["mention"]),
            sum(x["unread"] for x in rooms if x["kind"] in ("dm", "group") and not x["muted"]))


def tchat_sig(c, uid):
    """Change marker for /api/version: the newest message id of my conversations + my read marks."""
    if not collab_all():
        return ""
    return tchat_sig_fmt(c.execute(*tchat_sig_q(uid)).fetchone())


def tchat_sig_q(uid):
    """2.149.0 C (#2507): the parts of tchat_sig as ONE statement (one row, 16 columns; was five queries, the messages of
    the list / DM conversations were read twice). /api/version runs it inside its own one statement."""
    from .teamchan import tcx_sig_q
    # the list / DM conversations: newest id, count, pins, newest pin, newest edit (2.62.0 #1848: + the pins)
    m = ("""SELECT COALESCE(MAX(m.id),0), COUNT(m.id), COUNT(m.pinned_at), COALESCE(MAX(m.pinned_at),''), COALESCE(MAX(m.edited_at),'')
            FROM tchat_msgs m JOIN tchat_rooms r ON r.id=m.room_id
            WHERE (r.kind='dm' AND (r.a=? OR r.b=?)) OR (r.kind='list' AND r.list_id IN """ + vis_sql(ov=False) + ")")
    # 2.139.0 A (#2129, #2127): + the read marks of everyone (mine included) in the conversations I have read and in their
    # threads, so "Read by" shows without reloading
    rd = """SELECT (SELECT COALESCE(SUM(last_id),0) FROM tchat_reads WHERE room_id IN (SELECT room_id FROM tchat_reads WHERE user_id=?)),
                   (SELECT COALESCE(SUM(last_id),0) + COUNT(*) FROM tchat_thread_reads
                    WHERE room_id IN (SELECT room_id FROM tchat_reads WHERE user_id=?))"""
    # 2.113.1 (#2059): + the messages of my channels / groups and their names, states, members
    x = """SELECT COALESCE(MAX(m.id),0), COUNT(m.id), COALESCE(MAX(m.edited_at),''), COUNT(m.pinned_at) FROM tchat_msgs m
           WHERE m.room_id IN (SELECT room_id FROM tchat_members WHERE user_id=?)"""
    tq, ta = tcx_sig_q(uid)
    return (f"SELECT * FROM ({m}) s1 CROSS JOIN ({rd}) s2 CROSS JOIN ({x}) s3 CROSS JOIN ({tq}) s4",
            (uid, uid, uid, uid, uid, uid, uid, *ta))


TCHAT_SIG_COLS = 16


def tchat_sig_fmt(row):
    from .teamchan import tcx_sig_fmt
    r, rd, x, t = row[0:5], row[5:7], row[7:11], row[11:16]
    e = r[4]
    tx = f".{x[0]}.{x[1]}.{x[2][-6:]}.{x[3]}.{tcx_sig_fmt(t)}"
    return f"{r[0]}.{r[1]}.{rd[0]}-{rd[1]}.{e[-6:] if e else ''}.{r[2]}{r[3][-6:]}{tx}"


def tchat_unread(c, uid):
    if not tchat_on(c, uid):
        return 0
    return sum(x["unread"] for x in tchat_rooms(c, uid, full=False) if not x["muted"] or x["mention"])  # 2.281.0 B (#3110)


def tchat_dm_unread(c, uid):
    """2.28.0 (#987): unread direct messages (people writing to me) -- counted at the bell as "For you"."""
    if not tchat_on(c, uid):
        return 0
    return sum(x["unread"] for x in tchat_rooms(c, uid, full=False) if x["kind"] in ("dm", "group") and not x["muted"])  # 2.113.1 (#2059): groups like DMs


def md_brief(text):
    """2.18.0 (review): the Markdown markers out of a one-line preview (team chat list): code fences ("```js"), `code`,
    **bold**, ~~strike~~, *italic*, headings, quotes, list / checkbox markers, links -> their text. Keep in sync with
    mdBrief() in static/js/chat.js (it cleans the preview of a message sent from this device)."""
    out = []
    for ln in (text or "").split("\n"):
        ln = re.sub(r"^\s*(```|~~~)[\w+#.-]*\s*", "", ln)
        ln = re.sub(r"^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+\[[ xX]\]\s+|[-*+]\s+|\d+[.)]\s+)", "", ln)
        out.append(ln)
    t = re.sub(r"!?\[([^\]]*)\]\([^)\s]*\)", r"\1", "\n".join(out))
    t = re.sub(r"\*\*|__|~~|`", "", t)
    return re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?!\w)", r"\1", t)


def tchat_msg_brief(c, m):
    names = user_names(c, [int(x) for x in MENTION_RE.findall(m["body"])])
    d = {"id": m["id"], "user_id": m["user_id"], "text": comment_plain(c, md_brief(m["body"]), names)[:140], "created_at": m["created_at"]}
    if not d["text"] and not m["enc"]:  # 2.113.1 (#2059): a message with files only: the first file's name
        f = c.execute("SELECT name FROM tchat_files WHERE message_id=? ORDER BY id LIMIT 1", (m["id"],)).fetchone()
        if f:
            d.update(text=f["name"][:140], file=True)
    if m["enc"]:  # 2.42.0 (#909): an encrypted message / a notice: the app says so (the server has no text)
        from ..collab.e2e import e2e_msg_parse
        d["enc"] = (e2e_msg_parse(m["enc"]) or {}).get("sys") or "msg"
    return d


def tchat_rx(c, ids):
    out = {}
    if not ids:
        return out
    names = {}
    rows = c.execute(f"SELECT message_id, user_id, emoji FROM tchat_rx WHERE message_id IN ({','.join('?' * len(ids))}) ORDER BY created_at",
                     list(ids)).fetchall()
    names = user_names(c, {r["user_id"] for r in rows})
    for r in rows:
        lst = out.setdefault(r["message_id"], [])
        e = next((x for x in lst if x["emoji"] == r["emoji"]), None)
        if not e:
            e = {"emoji": r["emoji"], "users": []}
            lst.append(e)
        e["users"].append({"id": r["user_id"], "name": names.get(r["user_id"], "?")})
    return out


def tchat_msg_dict(c, m, rx=None, quotes=None, files=None, th=None):
    t = c.execute("SELECT id, title FROM tasks WHERE id=? AND deleted_at IS NULL", (m["task_id"],)).fetchone() if m["task_id"] else None
    # 2.33.0 (#1076): reply_to + reply (a short quote of the answered message; quotes = reply_quotes of a page)
    rt = m["reply_to"] if "reply_to" in m.keys() and not m["deleted_at"] else None
    rq = (quotes if quotes is not None else reply_quotes(c, "t", [rt])).get(rt) if rt else None
    return {"id": m["id"], "room_id": m["room_id"], "user_id": m["user_id"], "body": "" if m["deleted_at"] else m["body"],
            "task": {"id": t["id"], "title": t["title"]} if t and task_visible(c, t["id"], me()) else None,
            "created_at": m["created_at"], "edited_at": m["edited_at"], "deleted": bool(m["deleted_at"]),
            "reactions": (rx or {}).get(m["id"], []), "reply_to": rt, "reply": rq,
            "enc": None if m["deleted_at"] or not m["enc"] else _e2e_parse(m["enc"]),  # 2.42.0 (#909): {v, iv, ct} | {sys}
            # 2.62.0 (#1848): pinned (collab/chatpins.py); a deleted message is never pinned
            "pinned_at": None if m["deleted_at"] or "pinned_at" not in m.keys() else m["pinned_at"],
            "pinned_by": None if m["deleted_at"] or "pinned_by" not in m.keys() or not m["pinned_at"] else m["pinned_by"],
            # 2.113.1 (#2059): the files of the message (collab/teamchan.py; files = tcx_files_of of a page)
            "attachments": [] if m["deleted_at"] else (files if files is not None else _tcx_files(c, [m["id"]])).get(m["id"], []),
            # 2.139.0 A (#2127): the thread it answers in (NULL = the main conversation); a root: its answers (th = tth_summary of a page)
            "thread_of": m["thread_of"] if "thread_of" in m.keys() else None,
            **tth_fields((th if th is not None else tth_summary(c, me(), [m["id"]])).get(m["id"]))}


def _tcx_files_api(c, mid):
    from .teamchan import tcx_files_of
    return tcx_files_of(c, [mid], api=True).get(mid, [])


def _tcx_files(c, ids):
    from .teamchan import tcx_files_of
    return tcx_files_of(c, ids)


def _e2e_parse(v):
    from ..collab.e2e import e2e_msg_parse
    return e2e_msg_parse(v)


def tchat_clean_mentions(c, r, text):
    allowed = tchat_room_members(c, r)
    from ..collab.comments import mention_names
    names = mention_names(c, [int(x) for x in MENTION_RE.findall(text)])  # 2.148.1 A (#2490): '@?' for unseen accounts
    found = []

    def sub(m):
        uid = int(m.group(1))
        if uid in allowed:
            found.append(uid)
            return m.group(0)
        return "@" + names.get(uid, "?")
    return MENTION_RE.sub(sub, text), list(dict.fromkeys(found))


@app.get("/api/team")
def tchat_overview():
    """My conversations (channels of shared lists, DMs), the people I may start a DM with, the unread count."""
    c = db()
    need_tchat(c)
    uid = me()
    rooms = tchat_rooms(c, uid, create=True)
    c.commit()  # channels are created on first sight
    ppl = sorted(tchat_coworkers(c, uid))
    names = user_names(c, ppl)
    return jsonify(rooms=rooms, people=[{"id": p, "name": names.get(p, "?")} for p in ppl], users={str(k): v for k, v in names.items()},
                   unread=sum(x["unread"] for x in rooms if not x["muted"] or x["mention"]), avatars=avatar_map(c, uid))


@app.post("/api/team/dm")
def tchat_dm():
    """{user_id} -- the direct conversation with a person I work with (created on first use)."""
    c = db()
    need_tchat(c)
    if is_agent(g.user):
        raise Denied(403, tr("Agents talk to people in their own chat"))
    other = body().get("user_id")
    if isinstance(other, bool) or not isinstance(other, int) or other not in tchat_coworkers(c, me()):
        raise Denied(404)
    a, b = sorted((me(), other))
    c.execute("INSERT INTO tchat_rooms(kind,a,b,created_at) VALUES('dm',?,?,?) ON CONFLICT DO NOTHING", (a, b, iso(now_utc())))
    r = c.execute("SELECT * FROM tchat_rooms WHERE kind='dm' AND a=? AND b=?", (a, b)).fetchone()
    c.commit()
    return jsonify(id=r["id"], kind="dm", user_id=other, name=user_names(c, [other]).get(other, "?"), e2e=bool(r["e2e"]))


@app.get("/api/team/rooms/<int:rid>/messages")
def tchat_messages(rid):
    """?before=<id> (older page), ?limit (max 100) -- messages oldest first, with reactions; members of the room.
    2.139.0 A (#2127): the main conversation (no thread answers); ?thread=<message id> = the answers of that message's thread
    (an answer's id names its thread too) with root = the thread's first message."""
    c = db()
    need_tchat(c)
    r = need_room(c, rid)
    before = request.args.get("before")
    before = as_int(before, "before", 1) if before else None
    lim = as_int(request.args.get("limit", TCHAT_PAGE), "limit", 1, 100)
    root = None
    if request.args.get("thread"):
        root = tth_get(c, rid, as_int(request.args.get("thread"), "thread", 1))
        if not root:
            raise Denied(404)
    where = "thread_of=?" if root else "thread_of IS NULL"
    args = (rid, root["id"]) if root else (rid,)
    rows = c.execute("SELECT * FROM tchat_msgs WHERE room_id=? AND " + where + (" AND id<?" if before else "") + " ORDER BY id DESC LIMIT ?",
                     (*args, before, lim + 1) if before else (*args, lim + 1)).fetchall()
    more = len(rows) > lim
    rows = list(reversed(rows[:lim]))
    rx = tchat_rx(c, [m["id"] for m in rows])
    qs = reply_quotes(c, "t", [m["reply_to"] for m in rows if not m["deleted_at"]])
    fs = _tcx_files(c, [m["id"] for m in rows if not m["deleted_at"]])  # 2.113.1 (#2059)
    mem = tchat_room_members(c, r)
    th = tth_summary(c, me(), [m["id"] for m in rows] + ([root["id"]] if root else []))  # 2.139.0 A (#2127)
    names = user_names(c, mem | {m["user_id"] for m in rows if m["user_id"]} | {u for x in th.values() for u in x["users"]}
                       | ({root["user_id"]} if root and root["user_id"] else set()))
    lr, muted = tchat_last_read(c, rid, me())
    marks = trd_marks(c, rid, mem, me(), root["id"] if root else None)  # 2.139.0 A (#2129): None = read receipts off for me
    ags = agent_ids(c) if mem else set()  # 2.281.0 B (#3110): once (was one query per member)
    from ..collab.chatsave import chat_save_of
    from ..collab.chatpins import cpin_team_list
    saved = chat_save_of(c, me(), "team", [m["id"] for m in rows])  # 2.37.0 (#1159): saved as a task by me
    from ..collab.liste2echan import le2c_out, le2c_room  # 2.64.2 C (#1817): the lock of the list (agents / API: no ciphertext)
    xr = {}
    if r["kind"] in TCX_KINDS:  # 2.113.1 (#2059): name, organisation, open / archived, joined, may manage
        from .teamchan import tcx_room_brief
        xr = {k: v for k, v in tcx_room_brief(c, r, me()).items() if k != "members"}
    out = {}
    if root:  # 2.139.0 A (#2127): the thread's first message and my read mark in it
        saved.update(chat_save_of(c, me(), "team", [root["id"]]))
        rq = reply_quotes(c, "t", [root["reply_to"]] if not root["deleted_at"] else [])
        out = {"root": le2c_out(c, r, [{**tchat_msg_dict(c, root, tchat_rx(c, [root["id"]]), rq, _tcx_files(c, [root["id"]]), th),
                                         "saved_task_id": saved.get(root["id"])}])[0],
               "thread_read": tth_last_read(c, root["id"], me())}
    return jsonify(room={"id": r["id"], "kind": r["kind"], "list_id": r["list_id"], "muted": muted, "last_read": lr, "e2e": bool(r["e2e"]),
                         "members": [{"id": u, "name": names.get(u, "?"), "agent": u in ags} for u in sorted(mem)], **le2c_room(c, r), **xr,
                         "read_ok": None if marks is None else sorted(marks)},  # 2.139.0 A (#2129): who may show up in "Read by"
                   messages=le2c_out(c, r, [{**tchat_msg_dict(c, m, rx, qs, fs, th), "saved_task_id": saved.get(m["id"]),
                                             **trd_field(marks, m, me())} for m in rows]), has_more=more,
                   users={str(k): v for k, v in names.items()}, pins=le2c_out(c, r, cpin_team_list(c, rid)), **out)  # 2.62.0 (#1848): also older than the page; 2.64.2 C: the lock


@app.post("/api/team/rooms/<int:rid>/messages")
def tchat_post(rid):
    """{body, task_id?, reply_to?} -- a message; @mentions as <@id> (members of the room only); 2.33.0 (#1076) reply_to: a message
    of the same conversation (its author gets "replied to your message", like a mention)."""
    c = db()
    need_tchat(c)
    r = need_room(c, rid)
    need_dm_open(c, r)  # 2.266.0 (#2970)
    from .teamchan import tcx_add, tcx_files_refused, tcx_input, tcx_members, tcx_store
    b, files = tcx_input(body())  # 2.113.1 (#2059): JSON, or a multipart form with files (field file, repeatable)
    if r["kind"] == "channel" and r["archived_at"]:
        return err(tr("This channel is archived"), 409)
    if files:
        bad = tcx_files_refused(c, r)
        if bad:
            return bad
    text = b.get("body")
    if files and (text is None or (isinstance(text, str) and not text.strip())):
        text = None
    if r["kind"] == "list":  # 2.64.2 C (#1817): the channel of a list with the lock takes only a ciphertext of the list key
        from ..collab.liste2echan import le2c_check
        enc = le2c_check(c, r, b)
    else:
        enc = tchat_e2e_check(r, b)  # 2.42.0 (#909): an encrypted DM takes only ciphertext (and only it takes one)
    if isinstance(enc, tuple):
        return enc
    if enc:
        text = ""
    elif files and text is None:  # 2.113.1 (#2059): only files
        text = ""
    elif not isinstance(text, str) or not text.strip():
        return err(tr("The message is empty"))
    if len(text) > TCHAT_MAX:
        return err(tr("The message is too long (max. {0} characters)", TCHAT_MAX))
    tid = b.get("task_id")
    if tid is not None and (isinstance(tid, bool) or not isinstance(tid, int) or not task_visible(c, tid, me())):
        return err(tr("Invalid value: {0}", "task_id"))
    text, mentions = tchat_clean_mentions(c, r, text.strip()) if not enc and text else ("", [])
    if enc and r["kind"] == "list":  # 2.64.2 C (#1817): the browser names the @mentioned members of an encrypted message
        from ..collab.liste2echan import le2c_mentions
        mentions = le2c_mentions(c, r, b)
    try:
        orig = reply_check(c, "t", b.get("reply_to"), room_id=rid)
        root = tth_root(c, rid, b.get("thread_of"))  # 2.139.0 A (#2127): an answer in a thread (400: not a live message of this room)
    except BadInput as e:
        return err(str(e))
    cid = csd_client_id(b)  # 2.62.0 (#1530): the same message sent again (several Enter presses) -> the stored one
    if cid and not files:
        dup = csd_dup(c, "tchat_msgs", "room_id=? AND user_id=?", (rid, me()), cid, text)
        if dup:
            return jsonify(tchat_msg_dict(c, dup, tchat_rx(c, [dup["id"]]))), 200
    if hit_limit(f"tchat:{me()}", TCHAT_RATE):  # 2.281.0 B (#3117): a soft limit per person (a resent duplicate is not counted)
        return err(tr("Too many requests, please slow down"), 429)
    ts = iso_ms(now_utc())
    mid = insert_id(c, "INSERT INTO tchat_msgs(room_id,user_id,body,task_id,created_at,reply_to,enc,thread_of) VALUES(?,?,?,?,?,?,?,?)",
                    (rid, me(), text, tid, ts, orig["id"] if orig else None, enc, root))
    if cid:
        c.execute("UPDATE tchat_msgs SET client_id=? WHERE id=?", (cid, mid))
    if r["kind"] == "channel" and me() not in tcx_members(c, r):  # 2.113.1 (#2059): writing in an open channel joins it
        tcx_add(c, rid, me(), me())
    if files:
        tcx_store(c, r, c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone(), files)
    c.execute("UPDATE tchat_rooms SET last_at=? WHERE id=?", (ts, rid))
    if root:  # 2.139.0 A (#2127): the thread's people (its first message's author, the @mentioned, me: read up to here)
        tth_follow(c, r, root, [*mentions, *([orig["user_id"]] if orig and orig["user_id"] else [])], mid)
    else:
        c.execute("INSERT INTO tchat_reads(room_id,user_id,last_id) VALUES(?,?,?) ON CONFLICT(room_id,user_id) DO UPDATE SET last_id=excluded.last_id",
                  (rid, me(), mid))
    m = c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone()
    tchat_notify(c, r, m, mentions, replied=orig["user_id"] if orig and orig["user_id"] != me() else None)
    c.commit()
    return jsonify(tchat_msg_dict(c, m)), 201


# ---- 2.62.0 (#1530): a message the app sends carries client_id (one per message, the same on a retry). The same text of
# the same person in the same conversation with the same client_id within CSD_WINDOW seconds is answered with the stored
# message instead of a new one (a second Enter while the first send still ran, e.g. right after waking a laptop). Without
# client_id (agents, older apps) nothing changes. The check runs under a lock per conversation and person, so two
# requests arriving at the same moment cannot both pass it.
CSD_WINDOW = 10


def csd_client_id(b):
    v = b.get("client_id") if isinstance(b, dict) else None
    return v.strip()[:64] if isinstance(v, str) and v.strip() else None


def csd_dup(c, table, where, args, cid, text):
    """The row of table (where + args = the conversation and the sender) sent with client_id cid and the same text within
    CSD_WINDOW seconds, else None. Takes the lock that the caller's insert then holds until its commit."""
    from datetime import timedelta
    write_lock(c, f"csd:{table}:{':'.join(str(a) for a in args)}")
    r = c.execute(f"SELECT * FROM {table} WHERE {where} AND client_id=? AND created_at>=? ORDER BY id DESC LIMIT 1",
                  (*args, cid, iso_ms(now_utc() - timedelta(seconds=CSD_WINDOW)))).fetchone()
    return r if r and (r["body"] or "") == (text or "") else None


def tchat_e2e_check(r, b):
    """2.42.0 (#909): the ciphertext of a message to store (JSON text), None for a plain message, or an error response. An
    encrypted DM refuses plain text; a plain room refuses ciphertext."""
    from ..collab.e2e import E2E_MSG_MAX, e2e_blob
    if "e2e" not in r.keys() or not r["e2e"]:
        return err(tr("This conversation is not encrypted"), 409) if b.get("enc") is not None else None
    if isinstance(b.get("body"), str) and b["body"].strip():
        return err(tr("This conversation is end-to-end encrypted: plain text is not accepted"), 409)
    enc = e2e_blob(b.get("enc"), E2E_MSG_MAX)
    return enc or err(tr("Invalid value: {0}", "enc"))


def tchat_notify(c, r, m, mentions, replied=None):
    """Pushes (DM: always; channel: @mentions, and every message for whoever set the list bell to "all") + agent events.
    2.33.0 (#1076): replied = the author of the answered message: it counts as a mention ("replied to your message")."""
    sender = m["user_id"]
    if replied and replied not in mentions and replied in tchat_room_members(c, r):
        mentions = [*mentions, replied]
    rq = reply_quotes(c, "t", [m["reply_to"]]).get(m["reply_to"]) if m["reply_to"] else None
    names = user_names(c, [sender] + mentions)
    who = names.get(sender, "?")
    ags = agent_ids(c)
    members = tchat_room_members(c, r)
    text = comment_plain(c, m["body"])
    sealed = bool(m["enc"])  # 2.42.0 (#909): an encrypted message: the push only says who wrote
    # 2.46.1 (#1639): an agent that listens in on the list gets every channel message, not only an @mention; never a message of
    # an agent (no loop between agents); health lists and an agent's list limit stay with agent_emit
    listen = set(listen_agents_of(c, r["list_id"])) if r["kind"] == "list" and sender not in ags else set()
    root = m["thread_of"] if "thread_of" in m.keys() else None  # 2.139.0 A (#2127): an answer in a thread notifies its people only
    follow = {x[0] for x in c.execute("SELECT user_id FROM tchat_thread_reads WHERE root_id=? AND follow=1", (root,))} if root else set()
    for uid in sorted(members - {sender}):
        if uid in ags:
            if r["kind"] == "channel":  # 2.113.1 (#2059): a personal agent in a channel is addressed by its owner only (like agent_usable)
                from .teamchan import tcx_agent_org
                a = tcx_agent_org(c, uid)
                if a and a["owner_id"] and a["owner_id"] != sender:
                    continue
            if uid in mentions or uid in listen:
                agent_emit(c, uid, "team_message", {"room": {"id": r["id"], "kind": r["kind"], "list_id": r["list_id"]},
                                                     "mentioned": uid in mentions, "listening": uid in listen,
                                                     "message": {"id": m["id"], "text": text[:AGENT_EVENT_COMMENT_CHARS], "user_id": sender,
                                                                 "task_id": m["task_id"], "created_at": m["created_at"],
                                                                 "reply_to": m["reply_to"], "reply": rq,
                                                                 "attachments": _tcx_files_api(c, m["id"]),  # 2.113.1 (#2059)
                                                                 "thread_of": root},  # 2.139.0 A (#2127)
                                                     "user": {"id": sender, "name": who}})
            continue
        s = collab_user(c, uid, r["list_id"])
        if not s:
            continue
        _lr, muted = tchat_last_read(c, r["id"], uid)
        dm, ment = r["kind"] in ("dm", "group"), uid in mentions  # 2.113.1 (#2059): a group pushes like a DM
        if root:  # 2.139.0 A (#2127): a thread answer: only its people (the room's mute / the chat row still apply)
            if uid not in follow and not ment:
                continue
        elif r["kind"] == "list" and not ment and not (list_bell(c, uid, r["list_id"])[0] == "all"):
            continue
        elif r["kind"] == "channel" and not ment:  # 2.113.1 (#2059): a channel pushes @mentions and answers only
            continue
        if muted and not ment:
            continue
        if not notif_ok(c, uid, s, "mention" if ment else "chat", "push", r["list_id"]) or not push_reachable(c, uid, s):
            continue
        lg = lang_of(s)
        if r["kind"] in TCX_KINDS:  # 2.113.1 (#2059)
            from .teamchan import tcx_group_name
            title = tr("{0} in {1}", who, tcx_group_name(c, r, uid) if r["kind"] == "group" else r["name"], lg=lg)
        elif dm:
            title = who
        else:
            ln = c.execute("SELECT name FROM lists WHERE id=?", (r["list_id"],)).fetchone()
            title = tr("{0} in {1}", who, ln["name"] if ln else "?", lg=lg)
        msg = tr("New message from {0}", who, lg=lg) if sealed else \
            tr("{0} replied to your message: {1}", who, text, lg=lg) if uid == replied and r["kind"] != "dm" else \
            tr("Replied to your message: {0}", text, lg=lg) if uid == replied else (text or tr("Sent a file", lg=lg))  # 2.113.1 (#2059): only files
        g.pushes.append((uid, title, msg[:300], f"{PUBLIC_URL}/#msg/t/{r['id']}/{m['id']}" if root else f"{PUBLIC_URL}/#team/{r['id']}",
                         push_prio(s),  # 2.139.0 A (#2127): a thread answer opens its thread
                         {"scope": f"l:{r['list_id']}" if r["list_id"] else f"o:{r['org_id']}" if r["org_id"] else f"dm:{sender}"}))  # 2.240.0 B2 (#2867)


def need_tmsg(c, mid, edit=False):
    m = c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone()
    if not m:
        raise Denied(404)
    r = need_room(c, m["room_id"])
    if edit and m["user_id"] != me():
        if edit == "delete" and r["kind"] == "list" and list_role(c, r["list_id"]) in MANAGE_ROLES:
            return m, r
        if edit == "delete" and r["kind"] == "channel":  # 2.113.1 (#2059): its creator / an organisation admin
            from .teamchan import tcx_can_manage
            if tcx_can_manage(c, r, me()):
                return m, r
        raise Denied(403)
    return m, r


@app.patch("/api/team/messages/<int:mid>")
def tchat_edit(mid):
    """{body} -- change my own message."""
    c = db()
    need_tchat(c)
    m, r = need_tmsg(c, mid, edit=True)
    need_dm_open(c, r)  # 2.266.0 (#2970): a frozen DM takes no edits (deleting one's own stays)
    if m["deleted_at"]:
        return err(tr("The message was deleted"), 409)
    b = body()
    text = b.get("body")
    if r["kind"] == "list":  # 2.64.2 C (#1817): a channel of a list with the lock: changed by encrypting it again
        from ..collab.liste2echan import le2c_edit
        enc, bad = le2c_edit(c, r, m, b)
        if bad:
            return bad
        if enc:
            c.execute("UPDATE tchat_msgs SET body='', enc=?, edited_at=? WHERE id=?", (enc, iso_ms(now_utc()), mid))
            c.commit()
            m = c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone()
            return jsonify(tchat_msg_dict(c, m, tchat_rx(c, [mid])))
    if m["enc"] or r["e2e"]:  # 2.42.0 (#909): an encrypted message is changed by encrypting it again (the notices never)
        from ..collab.e2e import E2E_MSG_MAX, e2e_blob, e2e_msg_parse
        if (e2e_msg_parse(m["enc"]) or {}).get("sys") or not m["enc"]:
            return err(tr("This conversation is end-to-end encrypted: plain text is not accepted"), 409)
        enc = e2e_blob(b.get("enc"), E2E_MSG_MAX)
        if not enc or (isinstance(text, str) and text.strip()):
            return err(tr("Invalid value: {0}", "enc"))
        c.execute("UPDATE tchat_msgs SET enc=?, edited_at=? WHERE id=?", (enc, iso_ms(now_utc()), mid))
        c.commit()
        m = c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone()
        return jsonify(tchat_msg_dict(c, m, tchat_rx(c, [mid])))
    # 2.113.1 (#2059): a message with files may lose its text (the files stay the message)
    if not isinstance(text, str) or (not text.strip() and not c.execute("SELECT 1 FROM tchat_files WHERE message_id=? LIMIT 1", (mid,)).fetchone()):
        return err(tr("The message is empty"))
    if len(text) > TCHAT_MAX:
        return err(tr("The message is too long (max. {0} characters)", TCHAT_MAX))
    text, _ = tchat_clean_mentions(c, r, text.strip())
    c.execute("UPDATE tchat_msgs SET body=?, edited_at=? WHERE id=?", (text, iso_ms(now_utc()), mid))
    from ..agents.chat import med_team_edited  # 2.39.0 (#1179): agents that got it as team_message learn the change
    med_team_edited(c, r, c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone(), m["body"])
    c.commit()
    m = c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone()
    return jsonify(tchat_msg_dict(c, m, tchat_rx(c, [mid])))


@app.delete("/api/team/messages/<int:mid>")
def tchat_delete(mid):
    """My own message (list owners / admins: any in their channel). It stays as "deleted" in the conversation."""
    c = db()
    need_tchat(c)
    m, _r = need_tmsg(c, mid, edit="delete")
    c.execute("UPDATE tchat_msgs SET deleted_at=?, edited_at=?, body='', enc=NULL WHERE id=?", (iso_ms(now_utc()), iso_ms(now_utc()), mid))
    c.execute("DELETE FROM tchat_rx WHERE message_id=?", (mid,))
    from .teamchan import tcx_files_drop
    gone = tcx_files_drop(c, mid)  # 2.113.1 (#2059): its files go for good (rows now, the disk after the commit)
    c.commit()
    if gone:
        from ..core.serializers import unlink_files
        unlink_files(gone)
    return jsonify(ok=True, id=mid)


@app.post("/api/team/messages/<int:mid>/reactions")
def tchat_react(mid):
    """{emoji: up|down|heart or one emoji, on?: bool} -- toggles my reaction."""
    c = db()
    need_tchat(c)
    m, _r = need_tmsg(c, mid)
    if m["deleted_at"]:
        return err(tr("The message was deleted"), 409)
    need_dm_open(c, _r)  # 2.266.0 (#2970)
    b = body()
    emoji = clean_emoji(b.get("emoji"))
    have = c.execute("SELECT 1 FROM tchat_rx WHERE message_id=? AND user_id=? AND emoji=?", (mid, me(), emoji)).fetchone() is not None
    on = b["on"] if isinstance(b.get("on"), bool) else not have
    if on and m["user_id"] == me():  # 2.23.0 (#823): not on one's own message
        return err(tr("You cannot react to your own message"))
    if on:
        c.execute("INSERT INTO tchat_rx(message_id,user_id,emoji,created_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING", (mid, me(), emoji, iso_ms(now_utc())))
    else:
        c.execute("DELETE FROM tchat_rx WHERE message_id=? AND user_id=? AND emoji=?", (mid, me(), emoji))
    c.commit()
    return jsonify(ok=True, message_id=mid, reactions=tchat_rx(c, [mid]).get(mid, []))


@app.post("/api/team/rooms/<int:rid>/read")
def tchat_read(rid):
    """{last_id?, muted?} -- everything up to last_id (default: the newest) is read; muted = no pushes except mentions.
    2.139.0 A (#2127): {thread: <first message id>, last_id?} = the read mark in that thread (default: its newest answer)."""
    c = db()
    need_tchat(c)
    need_room(c, rid)
    b = body()
    if b.get("thread") is not None:
        return tth_read(c, rid, b)
    lid = b.get("last_id")
    if lid is None and "muted" in b:  # only (un)muting: the read mark stays
        lid = 0
    elif lid is None:
        lid = c.execute("SELECT COALESCE(MAX(id),0) FROM tchat_msgs WHERE room_id=?", (rid,)).fetchone()[0]
    elif isinstance(lid, bool) or not isinstance(lid, int):
        return err(tr("Invalid value: {0}", "last_id"))
    lr, muted = tchat_last_read(c, rid, me())
    if "muted" in b:
        if not isinstance(b["muted"], bool):
            return err(tr("Invalid value: {0}", "muted"))
        muted = b["muted"]
    c.execute("INSERT INTO tchat_reads(room_id,user_id,last_id,muted) VALUES(?,?,?,?) ON CONFLICT(room_id,user_id) "
              "DO UPDATE SET last_id=excluded.last_id, muted=excluded.muted", (rid, me(), max(lr, lid), int(muted)))
    if lid and not c.execute("SELECT 1 FROM tchat_msgs WHERE room_id=? AND id>?", (rid, max(lr, lid))).fetchone():
        push_handled(c, me(), [], (f"team-{rid}",))  # 2.19.0 (#668): read here = its notification closes elsewhere
    c.commit()
    return jsonify(ok=True, last_id=max(lr, lid), muted=muted, unread=tchat_unread(c, me()))


# ---- 2.139.0 A (#2127): threads. A message answers in a thread when it carries thread_of = the id of the thread's first
# message (the root, a message of the main conversation of the same room). One level: an answer to an answer hangs at the same
# root. The main conversation lists no thread answers; the root carries thread_count / thread_last_at / thread_users and my
# unread answers. tchat_thread_reads keeps a read mark per person and thread; follow = the person takes part (the root's
# author, who answered, who was @mentioned or answered by reply_to; in a DM both): only they count its answers as unread and
# get its pushes. The plain id is metadata, so threads work in end-to-end encrypted rooms too (the text stays sealed).
TTH_USERS = 3  # avatars of a thread's line


def tth_get(c, rid, mid):
    """The root row of the thread message mid of room rid belongs to (an answer names its root; any other message is a root), else None."""
    m = c.execute("SELECT * FROM tchat_msgs WHERE id=? AND room_id=?", (mid, rid)).fetchone()
    if m and m["thread_of"]:
        m = c.execute("SELECT * FROM tchat_msgs WHERE id=? AND room_id=?", (m["thread_of"], rid)).fetchone()
    return m


def tth_root(c, rid, v):
    """thread_of of a new message -> the root id (None = the main conversation); BadInput when it is no live message of rid."""
    if v in (None, "", 0, "0"):
        return None
    if isinstance(v, bool) or not (isinstance(v, int) or (isinstance(v, str) and v.isdigit())):
        raise BadInput(tr("Invalid value: {0}", "thread_of"))
    m = tth_get(c, rid, int(v))
    if not m or m["deleted_at"]:
        raise BadInput(tr("This thread cannot be answered here"))
    return m["id"]


def tth_follow(c, r, root, uids, mid):
    """After answer mid in thread root: its people take part (the root's author and in a DM both: every answer is new to them;
    uids = the @mentioned / answered: from this answer on), the sender also read it up to mid."""
    ra = c.execute("SELECT user_id FROM tchat_msgs WHERE id=?", (root,)).fetchone()
    full = {ra[0] if ra else None, *((r["a"], r["b"]) if r["kind"] == "dm" else ())} - {None, me()}
    for u in sorted(full | (set(uids) - {None, me()})):
        c.execute("INSERT INTO tchat_thread_reads(root_id,user_id,room_id,last_id,follow) VALUES(?,?,?,?,1) "
                  "ON CONFLICT(root_id,user_id) DO UPDATE SET follow=1", (root, u, r["id"], 0 if u in full else mid - 1))
    c.execute("INSERT INTO tchat_thread_reads(root_id,user_id,room_id,last_id,follow) VALUES(?,?,?,?,1) ON CONFLICT(root_id,user_id) "
              "DO UPDATE SET follow=1, last_id=GREATEST(tchat_thread_reads.last_id, excluded.last_id)", (root, me(), r["id"], mid))


def tth_unread(c, rid, uid):
    """(unread answers in the threads of room rid uid takes part in, whether one of them @mentions uid)."""
    r = c.execute("""SELECT COUNT(*), COALESCE(SUM(CASE WHEN m.body ILIKE ? THEN 1 ELSE 0 END),0) FROM tchat_msgs m
                     JOIN tchat_thread_reads t ON t.root_id=m.thread_of AND t.user_id=? AND t.follow=1
                     WHERE t.room_id=? AND m.room_id=? AND m.id>t.last_id AND m.deleted_at IS NULL AND COALESCE(m.user_id,0)!=?""",
                  (f"%<@{uid}>%", uid, rid, rid, uid)).fetchone()
    return r[0], bool(r[1])


def tth_summary(c, uid, ids):
    """{root id: {count, last_at, users, unread, follow}} for the messages ids that have live answers."""
    ids = sorted({int(i) for i in ids if i})
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    out = {r[0]: {"count": r[1], "last_at": r[2], "users": [], "unread": 0, "follow": False} for r in c.execute(
        f"SELECT thread_of, COUNT(*), MAX(created_at) FROM tchat_msgs WHERE thread_of IN ({q}) AND deleted_at IS NULL GROUP BY thread_of", ids)}
    if not out:
        return out
    for r in c.execute(f"""SELECT thread_of, user_id FROM tchat_msgs WHERE thread_of IN ({q}) AND deleted_at IS NULL AND user_id IS NOT NULL
                           GROUP BY thread_of, user_id ORDER BY MAX(id) DESC""", ids):
        if r[0] in out and len(out[r[0]]["users"]) < TTH_USERS:
            out[r[0]]["users"].append(r[1])
    for r in c.execute(f"""SELECT t.root_id, t.follow, (SELECT COUNT(*) FROM tchat_msgs m WHERE m.thread_of=t.root_id AND m.id>t.last_id
                             AND m.deleted_at IS NULL AND COALESCE(m.user_id,0)!=?) FROM tchat_thread_reads t
                           WHERE t.user_id=? AND t.root_id IN ({q})""", (uid, uid, *ids)):
        if r[0] in out:
            out[r[0]].update(follow=bool(r[1]), unread=r[2] if r[1] else 0)
    return out


def tth_fields(x):
    """The thread fields of a message (x = its tth_summary entry, None = no answers)."""
    x = x or {}
    return {"thread_count": x.get("count", 0), "thread_last_at": x.get("last_at"), "thread_users": x.get("users", []),
            "thread_unread": x.get("unread", 0), "thread_follow": x.get("follow", False)}


def tth_last_read(c, root, uid):
    r = c.execute("SELECT last_id FROM tchat_thread_reads WHERE root_id=? AND user_id=?", (root, uid)).fetchone()
    return r[0] if r else 0


def tth_read(c, rid, b):
    """POST read with {thread, last_id?}: my read mark in a thread (only looking does not make me take part)."""
    v, lid = b.get("thread"), b.get("last_id")
    if isinstance(v, bool) or not isinstance(v, int):
        return err(tr("Invalid value: {0}", "thread"))
    root = tth_get(c, rid, v)
    if not root:
        raise Denied(404)
    if lid is None:
        lid = c.execute("SELECT COALESCE(MAX(id),0) FROM tchat_msgs WHERE thread_of=?", (root["id"],)).fetchone()[0]
    elif isinstance(lid, bool) or not isinstance(lid, int):
        return err(tr("Invalid value: {0}", "last_id"))
    c.execute("INSERT INTO tchat_thread_reads(root_id,user_id,room_id,last_id,follow) VALUES(?,?,?,?,0) ON CONFLICT(root_id,user_id) "
              "DO UPDATE SET last_id=GREATEST(tchat_thread_reads.last_id, excluded.last_id)", (root["id"], me(), rid, max(lid, 0)))
    c.commit()
    return jsonify(ok=True, thread=root["id"], last_id=tth_last_read(c, root["id"], me()), unread=tchat_unread(c, me()))


# ---- 2.139.0 A (#2129): "Read by". The read marks are there (tchat_reads.last_id, in a thread tchat_thread_reads.last_id); a
# member of the room sees, at their own messages, who of the others read up to there. The personal setting chat_read_receipts
# ("Send read receipts", default on) off = the others do not see my mark and I see nobody's (both ways). Agents read through
# mark_team_chat_read and count like people.
TRD_USERS = 20


def trd_marks(c, rid, mem, uid, root=None):
    """{member: read mark} of the others in room rid (root: in that thread) who send read receipts; None when uid sends none."""
    if usettings(c, uid).get("chat_read_receipts") == "0":
        return None
    others = sorted(u for u in mem if u != uid)
    if not others:
        return {}
    off = {r[0] for r in c.execute("SELECT user_id FROM user_settings WHERE key='chat_read_receipts' AND value='0' AND user_id IN "
                                   f"({','.join('?' * len(others))})", others)}
    have = {r[0]: r[1] for r in (c.execute("SELECT user_id, last_id FROM tchat_thread_reads WHERE root_id=?", (root,)) if root
                                 else c.execute("SELECT user_id, last_id FROM tchat_reads WHERE room_id=?", (rid,)))}
    return {u: have.get(u, 0) for u in others if u not in off}


def trd_field(marks, m, uid):
    """{read_by: {count, users (the first TRD_USERS)}} at a live message of uid, else {}."""
    if marks is None or m["user_id"] != uid or m["deleted_at"]:
        return {}
    who = [u for u, last in marks.items() if last >= m["id"]]
    return {"read_by": {"count": len(who), "users": who[:TRD_USERS]}}


# ---- REST API v1 (people and agents; agents cannot open DMs)
@app.get("/api/v1/team/rooms")
@v1_view
def v1_tchat_rooms():
    v1_args(())
    c = db()
    need_tchat(c)
    rooms = tchat_rooms(c, me(), create=True)
    c.commit()
    return jsonify(data=rooms, next_cursor=None)


@app.post("/api/v1/team/dm")
@v1_view
def v1_tchat_dm():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("user_id",))
    return jsonify(v1_call(tchat_dm, body=b))


@app.get("/api/v1/team/rooms/<int:rid>/messages")
@v1_view
def v1_tchat_messages(rid):
    v1_args(("before", "limit", "thread"))  # 2.139.0 A (#2127): thread
    j = v1_call(tchat_messages, rid)
    return jsonify(data=j["messages"], room=j["room"], has_more=j["has_more"], next_cursor=None, pins=j["pins"],  # 2.62.0 (#1848): pins
                   **({"root": j["root"], "thread_read": j["thread_read"]} if "root" in j else {}))


@app.post("/api/v1/team/rooms/<int:rid>/messages")
@v1_view
def v1_tchat_post(rid):
    v1_args(())
    if request.files or request.form:  # 2.113.1 (#2059): a multipart form with files (body, task_id, reply_to, file...)
        b = {k: request.form.get(k) for k in request.form}
        reject_unknown({k: v for k, v in b.items()}, ("body", "task_id", "reply_to", "thread_of"))
    else:
        b = v1_json()
        reject_unknown(b, ("body", "task_id", "reply_to", "thread_of"))  # 2.33.0 (#1076): reply_to; 2.139.0 A (#2127): thread_of
    return jsonify(v1_call(tchat_post, rid, body=b)), 201


@app.patch("/api/v1/team/messages/<int:mid>")
@v1_view
def v1_tchat_edit(mid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("body",))
    return jsonify(v1_call(tchat_edit, mid, body=b))


@app.delete("/api/v1/team/messages/<int:mid>")
@v1_view
def v1_tchat_delete(mid):
    v1_args(())
    v1_call(tchat_delete, mid, body={})
    return Response(status=204)


@app.post("/api/v1/team/messages/<int:mid>/reactions")
@v1_view
def v1_tchat_react(mid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("emoji", "on"))
    return jsonify(v1_call(tchat_react, mid, body=b))


@app.post("/api/v1/team/rooms/<int:rid>/read")
@v1_view
def v1_tchat_read(rid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("last_id", "muted", "thread"))  # 2.139.0 A (#2127): thread
    return jsonify(v1_call(tchat_read, rid, body=b))


def team_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    TC = "Team chat"
    schemas["TeamRoom"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "kind": {"type": "string", "enum": ["dm", "list", "channel", "group"], "description": "2.113.1: + channel, group (collab channels)"}, "name": {"type": "string"},
        "list_id": {"type": "integer"}, "user_id": {"type": "integer", "description": "dm: the other person"},
        "unread": {"type": "integer"}, "mention": {"type": "boolean", "description": "An unread message mentions you"},
        "muted": {"type": "boolean"}, "last": nul("object"), "last_at": nul("string", format="date-time"),
        "e2e": {"type": "boolean", "description": "2.42.0: dm: end-to-end encrypted (messages carry enc, plain text is refused)"}}}
    schemas["TeamRoomPage"] = page("TeamRoom")
    schemas["TeamMessage"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "room_id": {"type": "integer"}, "user_id": nul("integer"),
        "body": {"type": "string", "description": "Markdown, mentions as <@user id>"}, "task": nul("object"),
        "created_at": {"type": "string", "format": "date-time"}, "edited_at": nul("string", format="date-time"),
        "deleted": {"type": "boolean"}, "reactions": {"type": "array", "items": {"type": "object"}},
        "reply_to": nul("integer", description="2.33.0: the answered message of this conversation"),
        "reply": {"anyOf": [ref("ReplyQuote"), {"type": "null"}]},
        "enc": nul("object", description="2.42.0: an end-to-end encrypted DM: {v, iv, ct} (body empty, only the two people can "
                   "decrypt it in their browser) or {sys: on | off} (the notice that switched it)"),
        "pinned_at": nul("string", description="2.62.0 (#1848): pinned since (null = not pinned); the conversation's page carries pins"),
        "pinned_by": nul("integer", description="2.62.0 (#1848): who pinned it"),
        "attachments": {"type": "array", "items": {"type": "object"}, "description": "2.113.1 (#2059): files [{id, name, mime, size, url, voice, duration_ms}] (url = /api/v1/team/files/{id}; 2.139.0 (#2128): voice = a voice message, duration_ms its length, not transcribed)"},
        "thread_of": nul("integer", description="2.139.0 (#2127): the first message of the thread this message answers in (null = the main conversation)"),
        "thread_count": {"type": "integer", "description": "2.139.0 (#2127): answers in this message's thread (0 = none)"},
        "thread_last_at": nul("string", format="date-time", description="2.139.0 (#2127): the newest answer of its thread"),
        "thread_users": {"type": "array", "items": {"type": "integer"}, "description": "2.139.0 (#2127): who answered last in its thread (up to 3)"},
        "thread_unread": {"type": "integer", "description": "2.139.0 (#2127): answers you have not read in a thread you take part in"},
        "thread_follow": {"type": "boolean", "description": "2.139.0 (#2127): you take part in its thread (wrote it, answered or were mentioned)"},
        "read_by": {"type": "object", "description": "2.139.0 (#2129): only at your own messages, when read receipts are on for you: "
                    "{count, users (the first 20 member ids)} of the others who read up to it (in a thread: in that thread)"}}}
    schemas["TeamMessagePage"] = page("TeamMessage")
    rp, mp = pid(desc="Conversation (room) id"), pid(desc="Message id")
    from .teamchan import tcx_spec
    tcx_spec(paths, schemas, op, ok, errs, ref, pid, nul, page)  # 2.113.1 (#2059): channels, groups, files
    paths["/team/rooms"] = {"get": op("2.17.0: your team chat conversations (channels of shared lists, direct messages) with unread counts",
                                      TC, ok(ref("TeamRoomPage")) | errs("404"))}
    paths["/team/dm"] = {"post": op("Open the direct conversation with a person you work with (people only, not agents)", TC,
                                    ok({"type": "object"}) | errs("403", "404"), body={"type": "object", "properties": {"user_id": {"type": "integer"}},
                                                                                     "required": ["user_id"]}, scope="comments")}
    paths["/team/rooms/{id}/messages"] = {
        "get": op("Messages of a conversation, oldest first (?before=<id> for older ones); 2.62.0 (#1848): pins = its pinned messages. "
                  "2.139.0 (#2127): the main conversation without thread answers; ?thread=<message id> = the answers of that message's "
                  "thread (root = its first message, thread_read = your read mark there)", TC, ok(ref("TeamMessagePage")) | errs("400", "404"),
                  [rp, q("before", "Only messages older than this id", {"type": "integer"}), q("limit", "At most this many (1-100)", {"type": "integer"}),
                   q("thread", "2.139.0 (#2127): the answers of this message's thread", {"type": "integer"})]),
        "post": op("Write in a conversation; mention people as <@id>. 2.113.1 (#2059): or multipart/form-data with body, task_id, reply_to "
                   "and up to 10 fields file (the body may then be empty; not in end-to-end encrypted conversations: 409)", TC, ok(ref("TeamMessage"), "Created", "201") | errs("400", "404"), [rp],
                   body={"type": "object", "properties": {"body": {"type": "string"}, "task_id": {"type": "integer"},
                                                          "reply_to": {"type": "integer", "description": "2.33.0: answer this message of the same conversation (else 400)"},
                                                          "thread_of": {"type": "integer", "description": "2.139.0 (#2127): answer in the thread of this message "
                                                                        "of the same conversation (an answer's id names its thread; deleted / other room: 400)"}},
                         "required": ["body"]}, scope="comments")}
    paths["/team/rooms/{id}/read"] = {"post": op("Mark a conversation read (up to last_id) and / or mute it; 2.139.0 (#2127): with thread = "
                                                 "the read mark in that thread", TC, ok({"type": "object"}) | errs("400", "404"),
                                                 [rp], body={"type": "object", "properties": {"last_id": {"type": "integer"}, "muted": {"type": "boolean"},
                                                                                              "thread": {"type": "integer", "description": "2.139.0 (#2127): the thread's first message"}}},
                                                 scope="comments")}
    paths["/team/messages/{id}"] = {
        "patch": op("Change your own message", TC, ok(ref("TeamMessage")) | errs("400", "403", "404", "409"), [mp],
                    body={"type": "object", "properties": {"body": {"type": "string"}}, "required": ["body"]}, scope="comments"),
        "delete": op("Delete your own message (list owners / admins: any in their channel)", TC, {"204": {"description": "Deleted"}} | errs("403", "404"), [mp], scope="comments")}
    paths["/team/messages/{id}/reactions"] = {"post": op("Toggle your reaction on a message", TC, ok({"type": "object"}) | errs("400", "404", "409"), [mp],
                                                         body={"type": "object", "properties": {"emoji": {"type": "string"}, "on": {"type": "boolean"}}, "required": ["emoji"]},
                                                         scope="comments")}
