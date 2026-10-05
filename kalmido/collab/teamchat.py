"""Team chat (rooms and direct messages)."""
import re
from flask import g, jsonify, request, Response

from ..core.config import app, PUBLIC_URL
from ..core.i18n import tr
from ..core.db import body, db, err, iso, iso_ms, now_utc, usettings
from ..accounts.session import me
from ..accounts.pictures import avatar_map
from ..core.access import collab_all, Denied, FULL_ROLES, list_role, MANAGE_ROLES, task_visible, vis_sql
from ..tasks.validation import as_int
from ..collab.comments import collab_on, collab_user, comment_plain, lang_of, MENTION_RE, user_names
from ..collab.news import list_bell, notif_ok
from ..personal.timetrack import reject_unknown
from ..notify.push import push_handled, push_prio, push_reachable
from ..api.v1 import v1_args, v1_call, v1_json, v1_view
from ..agents.core import agent_emit, AGENT_EVENT_COMMENT_CHARS, agent_ids, is_agent
from ..collab.reactions import clean_emoji


# ---------------------------------------------------------------- 2.17.0 (#419): team chat
# People talk to each other: direct messages between two people (who work together: they share a list or a group) and
# one channel per shared list (everyone who sees the whole list; participants, who only see their own tasks, are not in
# it). Agents shared with a list are members of its channel: they read it through the API and get the event
# "team_message" when someone @mentions them there. Messages are Markdown with <@id> mentions, can name a task, get
# reactions; the sender edits / deletes their own (list owners / admins delete any in their channel). Read state per
# person; pushes: every DM and every @mention (notification row "chat"; a muted list bell keeps a channel quiet except
# mentions). Needs collaboration on (instance switch); the person's module "collab" off = no team chat.
TCHAT_MAX, TCHAT_PAGE = 8000, 50


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
    l = c.execute("SELECT owner_id FROM lists WHERE id=? AND archived=0", (lid,)).fetchone()
    if not l:
        return set()
    out = {l["owner_id"]} | {r[0] for r in c.execute("SELECT user_id FROM list_members WHERE list_id=? AND role!='participant'", (lid,))}
    for r in c.execute("""SELECT gm.user_id FROM group_shares s JOIN group_members gm ON gm.group_id=s.group_id
                          WHERE s.list_id=? AND s.role!='participant'""", (lid,)):
        out.add(r[0])
    return {u for u in out if list_role(c, lid, u) in FULL_ROLES}


def tchat_room_members(c, r):
    if r["kind"] == "dm":
        return {r["a"], r["b"]}
    return tchat_list_members(c, r["list_id"])


def tchat_room_ok(c, r, uid):
    if not r:
        return False
    if r["kind"] == "dm":
        return uid in (r["a"], r["b"])
    return list_role(c, r["list_id"], uid) in FULL_ROLES and c.execute(
        "SELECT 1 FROM lists WHERE id=? AND archived=0", (r["list_id"],)).fetchone() is not None


def need_room(c, rid):
    r = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (rid,)).fetchone()
    if not tchat_room_ok(c, r, me()):
        raise Denied(404)
    return r


def tchat_list_room(c, lid, create=True):
    r = c.execute("SELECT * FROM tchat_rooms WHERE kind='list' AND list_id=?", (lid,)).fetchone()
    if r or not create:
        return r
    c.execute("INSERT OR IGNORE INTO tchat_rooms(kind,list_id,created_at) VALUES('list',?,?)", (lid, iso(now_utc())))
    return c.execute("SELECT * FROM tchat_rooms WHERE kind='list' AND list_id=?", (lid,)).fetchone()


def tchat_shared_lists(c, uid):
    """The lists of uid that have a channel: shared (another person or an agent sees the whole list), not archived."""
    out = []
    for l in c.execute(f"SELECT id, name, is_inbox FROM lists WHERE id IN {vis_sql()} AND archived=0 ORDER BY name COLLATE NOCASE", (uid, uid)):
        if list_role(c, l["id"], uid) not in FULL_ROLES:
            continue
        if len(tchat_list_members(c, l["id"])) >= 2:
            out.append(l)
    return out


def tchat_last_read(c, rid, uid):
    r = c.execute("SELECT last_id, muted FROM tchat_reads WHERE room_id=? AND user_id=?", (rid, uid)).fetchone()
    return (r["last_id"], bool(r["muted"])) if r else (0, False)


def tchat_rooms(c, uid):
    """Every conversation of uid: the channels of the shared lists + the DMs that have messages (newest first)."""
    rooms = []
    for l in tchat_shared_lists(c, uid):
        r = tchat_list_room(c, l["id"])
        rooms.append(r)
    for r in c.execute("SELECT * FROM tchat_rooms WHERE kind='dm' AND (a=? OR b=?) AND last_at IS NOT NULL", (uid, uid)):
        rooms.append(r)
    names = user_names(c, {x for r in rooms if r["kind"] == "dm" for x in (r["a"], r["b"])})
    out = []
    for r in rooms:
        last = c.execute("SELECT * FROM tchat_msgs WHERE room_id=? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
        lr, muted = tchat_last_read(c, r["id"], uid)
        unread = c.execute("SELECT COUNT(*) FROM tchat_msgs WHERE room_id=? AND id>? AND deleted_at IS NULL AND COALESCE(user_id,0)!=?",
                           (r["id"], lr, uid)).fetchone()[0]
        mention = bool(unread) and c.execute("SELECT 1 FROM tchat_msgs WHERE room_id=? AND id>? AND deleted_at IS NULL AND body LIKE ?",
                                             (r["id"], lr, f"%<@{uid}>%")).fetchone() is not None
        d = {"id": r["id"], "kind": r["kind"], "unread": unread, "mention": mention, "muted": muted,
             "last": tchat_msg_brief(c, last) if last else None, "last_at": last["created_at"] if last else None}
        if r["kind"] == "dm":
            other = r["b"] if r["a"] == uid else r["a"]
            d.update(user_id=other, name=names.get(other, "?"))
        else:
            l = c.execute("SELECT name, is_inbox, owner_id FROM lists WHERE id=?", (r["list_id"],)).fetchone()
            d.update(list_id=r["list_id"], name=l["name"], members=len(tchat_list_members(c, r["list_id"])))
        out.append(d)
    out.sort(key=lambda d: (d["last_at"] or ""), reverse=True)
    return out


def tchat_sig(c, uid):
    """Change marker for /api/version: the newest message id of my conversations + my read marks."""
    if not collab_all():
        return ""
    r = c.execute("""SELECT COALESCE(MAX(m.id),0), COUNT(m.id) FROM tchat_msgs m JOIN tchat_rooms r ON r.id=m.room_id
                     WHERE (r.kind='dm' AND (r.a=? OR r.b=?)) OR (r.kind='list' AND r.list_id IN """ + vis_sql() + ")",
                  (uid, uid, uid, uid)).fetchone()
    e = c.execute("SELECT COALESCE(MAX(edited_at),'') FROM tchat_msgs m JOIN tchat_rooms r ON r.id=m.room_id WHERE "
                  "(r.kind='dm' AND (r.a=? OR r.b=?)) OR (r.kind='list' AND r.list_id IN " + vis_sql() + ")", (uid, uid, uid, uid)).fetchone()[0]
    rd = c.execute("SELECT COALESCE(SUM(last_id),0) FROM tchat_reads WHERE user_id=?", (uid,)).fetchone()[0]
    return f"{r[0]}.{r[1]}.{rd}.{e[-6:] if e else ''}"


def tchat_unread(c, uid):
    if not tchat_on(c, uid):
        return 0
    return sum(x["unread"] for x in tchat_rooms(c, uid) if not x["muted"] or x["mention"])


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
    return {"id": m["id"], "user_id": m["user_id"], "text": comment_plain(c, md_brief(m["body"]), names)[:140], "created_at": m["created_at"]}


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


def tchat_msg_dict(c, m, rx=None):
    t = c.execute("SELECT id, title FROM tasks WHERE id=? AND deleted_at IS NULL", (m["task_id"],)).fetchone() if m["task_id"] else None
    return {"id": m["id"], "room_id": m["room_id"], "user_id": m["user_id"], "body": "" if m["deleted_at"] else m["body"],
            "task": {"id": t["id"], "title": t["title"]} if t and task_visible(c, t["id"], me()) else None,
            "created_at": m["created_at"], "edited_at": m["edited_at"], "deleted": bool(m["deleted_at"]),
            "reactions": (rx or {}).get(m["id"], [])}


def tchat_clean_mentions(c, r, text):
    allowed = tchat_room_members(c, r)
    names = user_names(c, [int(x) for x in MENTION_RE.findall(text)])
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
    rooms = tchat_rooms(c, uid)
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
    c.execute("INSERT OR IGNORE INTO tchat_rooms(kind,a,b,created_at) VALUES('dm',?,?,?)", (a, b, iso(now_utc())))
    r = c.execute("SELECT * FROM tchat_rooms WHERE kind='dm' AND a=? AND b=?", (a, b)).fetchone()
    c.commit()
    return jsonify(id=r["id"], kind="dm", user_id=other, name=user_names(c, [other]).get(other, "?"))


@app.get("/api/team/rooms/<int:rid>/messages")
def tchat_messages(rid):
    """?before=<id> (older page), ?limit (max 100) -- messages oldest first, with reactions; members of the room."""
    c = db()
    need_tchat(c)
    r = need_room(c, rid)
    before = request.args.get("before")
    before = as_int(before, "before", 1) if before else None
    lim = as_int(request.args.get("limit", TCHAT_PAGE), "limit", 1, 100)
    rows = c.execute("SELECT * FROM tchat_msgs WHERE room_id=?" + (" AND id<?" if before else "") + " ORDER BY id DESC LIMIT ?",
                     (rid, before, lim + 1) if before else (rid, lim + 1)).fetchall()
    more = len(rows) > lim
    rows = list(reversed(rows[:lim]))
    rx = tchat_rx(c, [m["id"] for m in rows])
    mem = tchat_room_members(c, r)
    names = user_names(c, mem | {m["user_id"] for m in rows if m["user_id"]})
    lr, muted = tchat_last_read(c, rid, me())
    return jsonify(room={"id": r["id"], "kind": r["kind"], "list_id": r["list_id"], "muted": muted, "last_read": lr,
                         "members": [{"id": u, "name": names.get(u, "?"), "agent": u in agent_ids(c)} for u in sorted(mem)]},
                   messages=[tchat_msg_dict(c, m, rx) for m in rows], has_more=more, users={str(k): v for k, v in names.items()})


@app.post("/api/team/rooms/<int:rid>/messages")
def tchat_post(rid):
    """{body, task_id?} -- a message; @mentions as <@id> (members of the room only)."""
    c = db()
    need_tchat(c)
    r = need_room(c, rid)
    b = body()
    text = b.get("body")
    if not isinstance(text, str) or not text.strip():
        return err(tr("The message is empty"))
    if len(text) > TCHAT_MAX:
        return err(tr("The message is too long (max. {0} characters)", TCHAT_MAX))
    tid = b.get("task_id")
    if tid is not None and (isinstance(tid, bool) or not isinstance(tid, int) or not task_visible(c, tid, me())):
        return err(tr("Invalid value: {0}", "task_id"))
    text, mentions = tchat_clean_mentions(c, r, text.strip())
    ts = iso_ms(now_utc())
    mid = c.execute("INSERT INTO tchat_msgs(room_id,user_id,body,task_id,created_at) VALUES(?,?,?,?,?)", (rid, me(), text, tid, ts)).lastrowid
    c.execute("UPDATE tchat_rooms SET last_at=? WHERE id=?", (ts, rid))
    c.execute("INSERT INTO tchat_reads(room_id,user_id,last_id) VALUES(?,?,?) ON CONFLICT(room_id,user_id) DO UPDATE SET last_id=excluded.last_id",
              (rid, me(), mid))
    m = c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone()
    tchat_notify(c, r, m, mentions)
    c.commit()
    return jsonify(tchat_msg_dict(c, m)), 201


def tchat_notify(c, r, m, mentions):
    """Pushes (DM: always; channel: @mentions, and every message for whoever set the list bell to "all") + agent events."""
    sender = m["user_id"]
    names = user_names(c, [sender] + mentions)
    who = names.get(sender, "?")
    ags = agent_ids(c)
    members = tchat_room_members(c, r)
    text = comment_plain(c, m["body"])
    for uid in sorted(members - {sender}):
        if uid in ags:
            if uid in mentions:
                agent_emit(c, uid, "team_message", {"room": {"id": r["id"], "kind": r["kind"], "list_id": r["list_id"]},
                                                     "message": {"id": m["id"], "text": text[:AGENT_EVENT_COMMENT_CHARS], "user_id": sender,
                                                                 "task_id": m["task_id"], "created_at": m["created_at"]},
                                                     "user": {"id": sender, "name": who}})
            continue
        s = collab_user(c, uid, r["list_id"])
        if not s:
            continue
        _lr, muted = tchat_last_read(c, r["id"], uid)
        dm, ment = r["kind"] == "dm", uid in mentions
        if r["kind"] == "list" and not ment and not (list_bell(c, uid, r["list_id"])[0] == "all"):
            continue
        if muted and not ment:
            continue
        if not notif_ok(c, uid, s, "mention" if ment else "chat", "push", r["list_id"]) or not push_reachable(c, uid, s):
            continue
        lg = lang_of(s)
        if dm:
            title = who
        else:
            ln = c.execute("SELECT name FROM lists WHERE id=?", (r["list_id"],)).fetchone()
            title = tr("{0} in {1}", who, ln["name"] if ln else "?", lg=lg)
        g.pushes.append((uid, title, text[:300], f"{PUBLIC_URL}/#team/{r['id']}", push_prio(s)))


def need_tmsg(c, mid, edit=False):
    m = c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone()
    if not m:
        raise Denied(404)
    r = need_room(c, m["room_id"])
    if edit and m["user_id"] != me():
        if edit == "delete" and r["kind"] == "list" and list_role(c, r["list_id"]) in MANAGE_ROLES:
            return m, r
        raise Denied(403)
    return m, r


@app.patch("/api/team/messages/<int:mid>")
def tchat_edit(mid):
    """{body} -- change my own message."""
    c = db()
    need_tchat(c)
    m, r = need_tmsg(c, mid, edit=True)
    if m["deleted_at"]:
        return err(tr("The message was deleted"), 409)
    text = body().get("body")
    if not isinstance(text, str) or not text.strip():
        return err(tr("The message is empty"))
    if len(text) > TCHAT_MAX:
        return err(tr("The message is too long (max. {0} characters)", TCHAT_MAX))
    text, _ = tchat_clean_mentions(c, r, text.strip())
    c.execute("UPDATE tchat_msgs SET body=?, edited_at=? WHERE id=?", (text, iso_ms(now_utc()), mid))
    c.commit()
    m = c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone()
    return jsonify(tchat_msg_dict(c, m, tchat_rx(c, [mid])))


@app.delete("/api/team/messages/<int:mid>")
def tchat_delete(mid):
    """My own message (list owners / admins: any in their channel). It stays as "deleted" in the conversation."""
    c = db()
    need_tchat(c)
    m, _r = need_tmsg(c, mid, edit="delete")
    c.execute("UPDATE tchat_msgs SET deleted_at=?, edited_at=?, body='' WHERE id=?", (iso_ms(now_utc()), iso_ms(now_utc()), mid))
    c.execute("DELETE FROM tchat_rx WHERE message_id=?", (mid,))
    c.commit()
    return jsonify(ok=True, id=mid)


@app.post("/api/team/messages/<int:mid>/reactions")
def tchat_react(mid):
    """{emoji: up|down|heart or one emoji, on?: bool} -- toggles my reaction."""
    c = db()
    need_tchat(c)
    m, _r = need_tmsg(c, mid)
    if m["deleted_at"]:
        return err(tr("The message was deleted"), 409)
    b = body()
    emoji = clean_emoji(b.get("emoji"))
    have = c.execute("SELECT 1 FROM tchat_rx WHERE message_id=? AND user_id=? AND emoji=?", (mid, me(), emoji)).fetchone() is not None
    on = b["on"] if isinstance(b.get("on"), bool) else not have
    if on:
        c.execute("INSERT OR IGNORE INTO tchat_rx(message_id,user_id,emoji,created_at) VALUES(?,?,?,?)", (mid, me(), emoji, iso_ms(now_utc())))
    else:
        c.execute("DELETE FROM tchat_rx WHERE message_id=? AND user_id=? AND emoji=?", (mid, me(), emoji))
    c.commit()
    return jsonify(ok=True, message_id=mid, reactions=tchat_rx(c, [mid]).get(mid, []))


@app.post("/api/team/rooms/<int:rid>/read")
def tchat_read(rid):
    """{last_id?, muted?} -- everything up to last_id (default: the newest) is read; muted = no pushes except mentions."""
    c = db()
    need_tchat(c)
    need_room(c, rid)
    b = body()
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


# ---- REST API v1 (people and agents; agents cannot open DMs)
@app.get("/api/v1/team/rooms")
@v1_view
def v1_tchat_rooms():
    v1_args(())
    c = db()
    need_tchat(c)
    rooms = tchat_rooms(c, me())
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
    v1_args(("before", "limit"))
    j = v1_call(tchat_messages, rid)
    return jsonify(data=j["messages"], room=j["room"], has_more=j["has_more"], next_cursor=None)


@app.post("/api/v1/team/rooms/<int:rid>/messages")
@v1_view
def v1_tchat_post(rid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("body", "task_id"))
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
    reject_unknown(b, ("last_id", "muted"))
    return jsonify(v1_call(tchat_read, rid, body=b))


def team_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    TC = "Team chat"
    schemas["TeamRoom"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "kind": {"type": "string", "enum": ["dm", "list"]}, "name": {"type": "string"},
        "list_id": {"type": "integer"}, "user_id": {"type": "integer", "description": "dm: the other person"},
        "unread": {"type": "integer"}, "mention": {"type": "boolean", "description": "An unread message mentions you"},
        "muted": {"type": "boolean"}, "last": nul("object"), "last_at": nul("string", format="date-time")}}
    schemas["TeamRoomPage"] = page("TeamRoom")
    schemas["TeamMessage"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "room_id": {"type": "integer"}, "user_id": nul("integer"),
        "body": {"type": "string", "description": "Markdown, mentions as <@user id>"}, "task": nul("object"),
        "created_at": {"type": "string", "format": "date-time"}, "edited_at": nul("string", format="date-time"),
        "deleted": {"type": "boolean"}, "reactions": {"type": "array", "items": {"type": "object"}}}}
    schemas["TeamMessagePage"] = page("TeamMessage")
    rp, mp = pid(desc="Conversation (room) id"), pid(desc="Message id")
    paths["/team/rooms"] = {"get": op("2.17.0: your team chat conversations (channels of shared lists, direct messages) with unread counts",
                                      TC, ok(ref("TeamRoomPage")) | errs("404"))}
    paths["/team/dm"] = {"post": op("Open the direct conversation with a person you work with (people only, not agents)", TC,
                                    ok({"type": "object"}) | errs("403", "404"), body={"type": "object", "properties": {"user_id": {"type": "integer"}},
                                                                                     "required": ["user_id"]}, scope="comments")}
    paths["/team/rooms/{id}/messages"] = {
        "get": op("Messages of a conversation, oldest first (?before=<id> for older ones)", TC, ok(ref("TeamMessagePage")) | errs("400", "404"),
                  [rp, q("before", "Only messages older than this id", {"type": "integer"}), q("limit", "At most this many (1-100)", {"type": "integer"})]),
        "post": op("Write in a conversation; mention people as <@id>", TC, ok(ref("TeamMessage"), "Created", "201") | errs("400", "404"), [rp],
                   body={"type": "object", "properties": {"body": {"type": "string"}, "task_id": {"type": "integer"}}, "required": ["body"]}, scope="comments")}
    paths["/team/rooms/{id}/read"] = {"post": op("Mark a conversation read (up to last_id) and / or mute it", TC, ok({"type": "object"}) | errs("400", "404"),
                                                 [rp], body={"type": "object", "properties": {"last_id": {"type": "integer"}, "muted": {"type": "boolean"}}}, scope="comments")}
    paths["/team/messages/{id}"] = {
        "patch": op("Change your own message", TC, ok(ref("TeamMessage")) | errs("400", "403", "404", "409"), [mp],
                    body={"type": "object", "properties": {"body": {"type": "string"}}, "required": ["body"]}, scope="comments"),
        "delete": op("Delete your own message (list owners / admins: any in their channel)", TC, {"204": {"description": "Deleted"}} | errs("403", "404"), [mp], scope="comments")}
    paths["/team/messages/{id}/reactions"] = {"post": op("Toggle your reaction on a message", TC, ok({"type": "object"}) | errs("400", "404", "409"), [mp],
                                                         body={"type": "object", "properties": {"emoji": {"type": "string"}, "on": {"type": "boolean"}}, "required": ["emoji"]},
                                                         scope="comments")}
