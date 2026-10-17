"""2.37.0 (#1159): save a chat message as a task to look at later -- from the chat with an agent or from the team chat.

POST /api/chat-save {kind: agent | team, msg_id, list_id?, due?, title?}: only a person, only a message they may read (agent
chat: their own conversation; team chat: a room they are in, the message not deleted), only into a list they may change (the
inbox by default). The task gets the whole text as Markdown (mentions as @name), a line with a link back to the message
(#msg/<a|t>/<agent or room>/<id>, the app jumps to it) and copies of the message's files (agent chat; copied, not linked,
within the person's storage). chat_saves remembers it per person: saving again answers "already saved" with the task (no
second task) while that task exists and is not deleted; afterwards the message can be saved again. The chat pages carry
saved_task_id per message (only for the person asking).

2.42.0 (#1383): kind "comment": a comment of an agent on a task (msg_id = the comment id; only a comment of an agent, only by
someone who sees its task) becomes a subtask of that task (as: "sub", the default) or a new task in the same list (as: "list");
the person needs the right to add tasks there (no list choice). The link points back to the task; the comment's files are
copied. The task timeline carries saved_task_id per agent comment (for the person asking).

Agents never save (403): they may only offer it -- POST /api/v1/agent/chats/{uid} with offer_save: true shows the button
"Save as task" under their message, which opens the same dialog for the person."""
import os
import re
import uuid

from flask import g, jsonify, request

from ..core.config import app, ATT_DIR, PUBLIC_URL
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, my_inbox, need_list
from ..tasks.validation import TITLE_MAX, as_int, log_act
from ..personal.timetrack import BadInput, UnknownFields

CHAT_SAVE_KINDS = ("agent", "team", "comment")  # 2.42.0 (#1383): + comment (of an agent, on a task)
CHAT_SAVE_FIELDS = ("kind", "msg_id", "list_id", "due", "title", "as")
CHAT_SAVE_AS = ("sub", "list")  # 2.42.0 (#1383): a saved comment: subtask of its task / new task in the same list
CHAT_SAVE_TITLE = 120  # the title made from the message (the person may type a longer one, up to TITLE_MAX)


def chat_save_title(text):
    """The first Markdown heading, else the first line with text -- without Markdown marks, shortened."""
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    head = next((x for x in lines if re.match(r"^#{1,6}\s+\S", x)), None)
    t = head or (lines[0] if lines else "")
    t = re.sub(r"^(#{1,6}|>|[-*+]|\d+[.)])\s+", "", t)
    t = re.sub(r"[*_`~]+", "", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)).strip()
    return t if len(t) <= CHAT_SAVE_TITLE else t[:CHAT_SAVE_TITLE - 1].rstrip() + "…"


def chat_save_of(c, uid, kind, mids):
    """{message id: task id} of the messages uid saved and whose task still exists (not deleted)."""
    mids = [int(x) for x in mids if x]
    if not mids:
        return {}
    return {r[0]: r[1] for r in c.execute(
        f"""SELECT s.msg_id, s.task_id FROM chat_saves s JOIN tasks t ON t.id=s.task_id AND t.deleted_at IS NULL
            WHERE s.user_id=? AND s.kind=? AND s.msg_id IN ({','.join('?' * len(mids))})""", (uid, kind, *mids))}


def _plain_mentions(c, text):
    from ..collab.comments import MENTION_RE, user_names
    names = user_names(c, [int(x) for x in MENTION_RE.findall(text or "")])
    return MENTION_RE.sub(lambda m: "@" + names.get(int(m.group(1)), "?"), text or "")


def _message(c, kind, mid, uid):
    """(text, files [(name, mime, size, path)], where (the conversation), who (the author), created_at, link) of a message uid
    may read, else Denied(404)."""
    from ..collab.comments import user_names
    if kind == "comment":
        return dl_comment_message(c, mid)
    if kind == "agent":
        m = c.execute("SELECT * FROM agent_chat WHERE id=?", (mid,)).fetchone()
        if not m or m["user_id"] != uid:  # only the person's own conversation with the agent
            raise Denied(404)
        files = [(f["name"], f["mime"], f["size"], f["path"]) for f in c.execute(
            "SELECT name, mime, size, path FROM chat_files WHERE message_id=? ORDER BY id", (mid,))]
        where = user_names(c, [m["agent_id"]]).get(m["agent_id"], "?")
        who = where if m["sender"] == "agent" else user_names(c, [uid]).get(uid, "?")
        return m["body"] or "", files, tr("Chat with {0}", where), who, m["created_at"], f"#msg/a/{m['agent_id']}/{mid}"
    from ..collab.teamchat import tchat_on, tchat_room_ok
    if not tchat_on(c):
        raise Denied(404)
    m = c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone()
    r = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (m["room_id"],)).fetchone() if m else None
    if not m or not tchat_room_ok(c, r, uid) or m["deleted_at"] or m["enc"]:  # 2.42.0 (#909): an encrypted DM stays in the chat
        raise Denied(404)
    if r["kind"] == "dm":
        other = r["b"] if r["a"] == uid else r["a"]
        where = tr("Direct message with {0}", user_names(c, [other]).get(other, "?"))
    else:
        ln = c.execute("SELECT name FROM lists WHERE id=?", (r["list_id"],)).fetchone()
        where = tr("Team chat {0}", ln["name"] if ln else "?")
    who = user_names(c, [m["user_id"]]).get(m["user_id"], "?") if m["user_id"] else "?"
    return _plain_mentions(c, m["body"]), [], where, who, m["created_at"], f"#msg/t/{r['id']}/{mid}"


def dl_comment_message(c, cid):
    """2.42.0 (#1383): _message of a comment: only an agent's, only on a task the person sees (else 404 / 400)."""
    from ..collab.comments import need_live_comment, user_names
    from ..agents.core import agent_ids
    k, _ = need_live_comment(c, cid)  # 404 gone / task not visible (participants: only their tasks)
    if k["user_id"] not in agent_ids(c):
        raise Denied(400, tr("Only comments of agents can be saved as a task"))
    t = c.execute("SELECT id, title FROM tasks WHERE id=?", (k["task_id"],)).fetchone()
    files = [(f["name"], f["mime"], f["size"], f["path"]) for f in c.execute(
        "SELECT name, mime, size, path FROM attachments WHERE comment_id=? ORDER BY id", (cid,))]
    who = user_names(c, [k["user_id"]]).get(k["user_id"], "?")
    return k["body"] or "", files, tr("Comment on {0}", t["title"]), who, k["created_at"], f"#t/{t['id']}"


def _copy_files(c, tid, uid, files):
    """Copies the message's files to the task (the person's storage counts; what does not fit is skipped). -> skipped names."""
    from ..admin.hosting import quota_fits
    skipped, ts = [], iso(now_utc())
    for name, mime, size, path in files:
        src = os.path.join(ATT_DIR, path)
        if not os.path.isfile(src) or not quota_fits(c, uid, size or 0):
            skipped.append(name)
            continue
        rel = os.path.join(str(tid), f"{uuid.uuid4().hex[:12]}-{name}")
        os.makedirs(os.path.join(ATT_DIR, str(tid)), exist_ok=True)
        from ..core.orgcrypt import oc_copy_file, oc_task_space
        # 2.64.0 (#1864): opened with the chat's key, sealed for the task's space (organisation or the list owner's account)
        oc_copy_file(c, src, os.path.join(ATT_DIR, rel), oc_task_space(c, tid))
        g.chat_save_new = getattr(g, "chat_save_new", []) + [rel]
        c.execute("INSERT INTO attachments(task_id,name,mime,size,path,created_at,user_id) VALUES(?,?,?,?,?,?,?)",
                  (tid, name, mime, size, rel, ts, uid))
    return skipped


@app.post("/api/chat-save")
def chat_save():
    """{kind: agent | team, msg_id, list_id? (default: the inbox), due? (YYYY-MM-DD), title? (default: the first heading or
    line)} -> 201 {task, skipped_files} | 200 {already: true, task_id, task: {id, title}} when this person saved it already."""
    from ..core.serializers import unlink_files
    from ..agents.core import is_agent
    from ..api.v1 import V1Error, v1_call
    from ..tasks.tasks import one_task, task_create
    c, b = db(), body()
    if is_agent(g.user):
        raise Denied(403, tr("Agents can only offer this; the person saves"))
    unknown = sorted(k for k in b if k not in CHAT_SAVE_FIELDS)
    if unknown:
        return err(str(UnknownFields(unknown)))
    kind = b.get("kind")
    if kind not in CHAT_SAVE_KINDS:
        return err(tr("Invalid value: {0}", "kind"))
    try:
        mid = as_int(b.get("msg_id"), "msg_id", 1)
        lid = as_int(b["list_id"], "list_id", 1) if b.get("list_id") not in (None, "") else None
    except BadInput as e:
        return err(str(e))
    if (b.get("as") is not None and (kind != "comment" or b["as"] not in CHAT_SAVE_AS)) or (kind == "comment" and lid):
        return err(tr("Invalid value: {0}", "as" if b.get("as") is not None else "list_id"))
    uid = me()
    text, files, where, who, at, link = _message(c, kind, mid, uid)
    have = chat_save_of(c, uid, kind, [mid])
    if mid in have:
        t = c.execute("SELECT id, title FROM tasks WHERE id=?", (have[mid],)).fetchone()
        return jsonify(already=True, task_id=t["id"], task={"id": t["id"], "title": t["title"]})
    parent = None
    if kind == "comment":  # 2.42.0 (#1383): in the comment's list, as a subtask of its task by default
        ct = c.execute("SELECT t.id, t.list_id FROM comments k JOIN tasks t ON t.id=k.task_id WHERE k.id=?", (mid,)).fetchone()
        lid, parent = ct["list_id"], (ct["id"] if b.get("as", "sub") == "sub" else None)
    lid = lid or my_inbox(c, uid)
    need_list(c, lid)  # 404 unknown / not visible, 403 without the right to change the list
    title = b.get("title")
    if title is not None and not isinstance(title, str):
        return err(tr("Invalid value: {0}", "title"))
    title = (title or "").strip()[:TITLE_MAX] or chat_save_title(text) or tr("Saved message")
    base = (PUBLIC_URL or request.url_root).rstrip("/")
    line = f"{tr('Saved from: {0}', where)} · {who}, {at[:10]} · [{tr('Open the comment in the task') if kind == 'comment' else tr('Open the message in the chat')}]({base}/{link})"
    content = (text.rstrip() + "\n\n---\n" if text.strip() else "") + line
    new = {"title": title, "content": content, "list_id": lid}
    if parent:
        new["parent_id"] = parent
    if b.get("due") not in (None, ""):
        new["due"] = b["due"]
    try:
        t = v1_call(task_create, body=new)  # the usual rules, activity and events of a new task (commits)
    except V1Error as e:
        return e.resp
    tid = t["id"]
    g.chat_save_new = []
    try:
        skipped = _copy_files(c, tid, uid, files)
        if files and len(skipped) < len(files):
            log_act(c, tid, "attach", {"names": [f[0] for f in files if f[0] not in skipped][:20], "n": len(files) - len(skipped)})
        c.execute("""INSERT INTO chat_saves(user_id,kind,msg_id,task_id,created_at) VALUES(?,?,?,?,?)
                     ON CONFLICT (user_id,kind,msg_id) DO UPDATE SET task_id=excluded.task_id, created_at=excluded.created_at""",
                  (uid, kind, mid, tid, iso(now_utc())))
        bump(c)
        c.commit()
    except Exception:
        c.rollback()
        unlink_files(g.chat_save_new)
        raise
    print("chat-save", kind, mid, "->", tid, "by", g.user["username"], flush=True)
    return jsonify(task=one_task(c, tid), skipped_files=skipped), 201
