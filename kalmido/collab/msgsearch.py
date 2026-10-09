"""2.33.0 (#1080): search in conversations -- task comments, team chat (channels + direct messages) and agent chats.

Index: one SQLite FTS5 table msg_fts (tokenizer unicode61, remove_diacritics 2: case and accents do not matter). Its rowid
encodes the source: message id * 4 + kind (1 comment, 2 team chat, 3 agent chat). Triggers on the three message tables keep
it current on every insert / edit / (soft) delete -- also when an older version runs on the same database (a rollback keeps
writing the source tables, the triggers keep the index right; nothing in them is new to an older server). The text is indexed
twice when it has umlauts: as written and with ä -> ae, ö -> oe, ü -> ue, ß -> ss, so "Ärger", "arger" and "aerger" all find
it. init_db() builds the index once for existing messages (msg_index_init) and repairs it when the counts drift.

Visibility is strict and the same as reading the conversation: comments of tasks the person may see with their comments (list
role, participants only their own tasks, a token limited to lists), team chat rooms the person is in (channel: a full role in
the list; DM: one of the two), agent chats of the person with agents they may reach (an agent: only its own chats). Foreign
ids in filters simply find nothing. The snippet is plain text with the hit ranges (marks) -- never HTML.

2.34 (#909) will encrypt direct messages between two people end to end when switched on: those then never reach this index,
the device searches them (the web client merges sources in msgSearch(), see static/js/msgsearch.js). Every hit therefore
names its kind (art: c | t | a) and its chat type (task | list | dm | agent)."""
import re
import unicodedata

from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import db, gset, gsetting
from ..accounts.session import me
from ..core.access import collab_all, Denied, FULL_ROLES, list_role, tvis, vis_sql
from ..tasks.validation import as_int
from ..personal.timetrack import BadInput
from ..collab.comments import comment_plain, MENTION_RE, user_names
from ..collab.teamchat import md_brief, tchat_on, tchat_room_ok
from ..agents.core import agent_ids, agent_shares, is_agent
from ..api.v1 import API_PAGE_MAX, cursor_dec, cursor_enc, v1_args, v1_view

ARTS = {"c": 1, "t": 2, "a": 3}
CHAT_TYPES = ("task", "list", "dm", "agent")
MSG_CAND = 1000          # candidates per kind before the per-row checks
MSG_TERMS = 8
SNIP = 160               # characters of a snippet
INDEX_VERSION = "1"

_FOLD = "{x}"
for _a, _b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
    _FOLD = f"replace({_FOLD},'{_a}','{_b}')"


def _idx(x):
    """SQL: the text to index for column x (as written + the umlaut-folded form when it differs)."""
    f = _FOLD.format(x=x)
    return f"CASE WHEN {f}={x} THEN {x} ELSE {x}||char(10)||{f} END"


# (table, kind, condition for "indexed", text column)
_SRC = (("comments", 1, "{p}deleted_at IS NULL AND {p}body!=''"),
        ("tchat_msgs", 2, "{p}deleted_at IS NULL AND {p}body!=''"),
        ("agent_chat", 3, "{p}body!=''"))


# the names are also in core/schema.py SCHEMA_TRIGGERS (what a restored backup may contain)
TRIGGER_NAMES = tuple(f"msg_fts_{t}_{w}" for t, _k, _c in _SRC for w in ("ai", "au", "ad"))


def _triggers():
    out = []
    for t, k, cond in _SRC:
        upd = "body, deleted_at" if t != "agent_chat" else "body"
        out += [
            # idempotent: a stale index row with the same rowid must never block writing a message (FTS5 refuses it)
            f"CREATE TRIGGER IF NOT EXISTS msg_fts_{t}_ai AFTER INSERT ON {t} WHEN {cond.format(p='new.')} BEGIN "
            f"DELETE FROM msg_fts WHERE rowid=new.id*4+{k}; "
            f"INSERT INTO msg_fts(rowid, body) VALUES (new.id*4+{k}, {_idx('new.body')}); END",
            f"CREATE TRIGGER IF NOT EXISTS msg_fts_{t}_au AFTER UPDATE OF {upd} ON {t} BEGIN "
            f"DELETE FROM msg_fts WHERE rowid=old.id*4+{k}; "
            f"INSERT INTO msg_fts(rowid, body) SELECT new.id*4+{k}, {_idx('new.body')} WHERE {cond.format(p='new.')}; END",
            f"CREATE TRIGGER IF NOT EXISTS msg_fts_{t}_ad AFTER DELETE ON {t} BEGIN "
            f"DELETE FROM msg_fts WHERE rowid=old.id*4+{k}; END"]
    return out


def msg_fts_ok(c):
    return c.execute("SELECT 1 FROM sqlite_master WHERE name='msg_fts'").fetchone() is not None


def _expected(c):
    return sum(c.execute(f"SELECT COUNT(*) FROM {t} WHERE {cond.format(p='')}").fetchone()[0] for t, _k, cond in _SRC)


def msg_index_rebuild(c):
    c.execute("DELETE FROM msg_fts")
    for t, k, cond in _SRC:
        c.execute(f"INSERT INTO msg_fts(rowid, body) SELECT id*4+{k}, {_idx('body')} FROM {t} WHERE {cond.format(p='')}")


def msg_index_init(c):
    """Called by init_db (inside its transaction): table + triggers (once), the first build for existing messages, a
    rebuild when the number of indexed rows does not match the sources (e.g. a restored backup). Without FTS5 in the
    SQLite library the search answers 503 and nothing else changes."""
    try:
        new = not msg_fts_ok(c)
        if new:
            c.execute("CREATE VIRTUAL TABLE msg_fts USING fts5(body, tokenize='unicode61 remove_diacritics 2')")
        # re-created on every start: a restored backup may carry triggers of the same name with another body
        for name in TRIGGER_NAMES:
            c.execute(f"DROP TRIGGER IF EXISTS {name}")
        for sql in _triggers():
            c.execute(sql)
    except Exception as e:  # noqa: BLE001 -- e.g. "no such module: fts5"
        print("message search: no FTS5 index:", e, flush=True)
        return
    if new or gsetting(c, "msg_fts_v") != INDEX_VERSION or c.execute("SELECT COUNT(*) FROM msg_fts").fetchone()[0] != _expected(c):
        msg_index_rebuild(c)
        gset(c, "msg_fts_v", INDEX_VERSION)
        n = c.execute("SELECT COUNT(*) FROM msg_fts").fetchone()[0]
        print("message search: indexed", n, "messages", flush=True)


# ---- matching (also for the snippet: the same folding as the index, in Python)
def _fold_char(ch):
    if ch == "ß":
        return "ss"
    d = unicodedata.normalize("NFKD", ch)
    return "".join(x for x in d if not unicodedata.combining(x)).lower() or ch.lower()


def _folded(text):
    """(folded text, map folded position -> original position)."""
    out, pos = [], []
    for i, ch in enumerate(text):
        f = _fold_char(ch)
        out.append(f)
        pos += [i] * len(f)
    return "".join(out), pos


def msg_terms(q):
    """The words of a query (max 8, each max 64 chars); BadInput when there is none."""
    terms = [w[:64] for w in re.findall(r"\w+", q or "")][:MSG_TERMS]
    if not terms:
        raise BadInput(tr("Invalid value: {0}", "q"))
    return terms


def fts_query(terms):
    """Every word as a prefix; a word with an umlaut also as written with ae / oe / ue ("Spülmaschine" finds "Spuelmaschine")."""
    out = []
    for t in terms:
        t = t.replace('"', '')
        ex = re.sub("[äöüÄÖÜ]", lambda m: m.group(0) + "e", t)
        out.append(f'("{t}"* OR "{ex}"*)' if ex != t else f'"{t}"*')
    return " AND ".join(out)


def _variants(term):
    """Folded forms of a query word: as typed (ä -> a), with ä -> ae (the text says "ae") and ae -> a (the text says "ä")."""
    f = "".join(_fold_char(ch) for ch in term)
    ex = "".join(_fold_char(ch) for ch in re.sub("[äöüÄÖÜ]", lambda m: m.group(0) + "e", term))  # ä -> ae (text written "ae")
    return {f, ex, f.replace("ae", "a").replace("oe", "o").replace("ue", "u")}


def find_marks(text, terms):
    """[[start, end], ...] of every term in text (accents / case / ä=ae ignored), or None when a term is missing."""
    ft, pos = _folded(text)
    marks = []
    for t in terms:
        hit = False
        for v in _variants(t):
            if not v:
                continue
            for m in re.finditer(r"(?<!\w)" + re.escape(v), ft):
                s, e = pos[m.start()], pos[m.end() - 1] + 1
                marks.append([s, e])
                hit = True
        if not hit:
            return None
    marks.sort()
    merged = []
    for s, e in marks:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def snippet(text, marks):
    """(snippet text, marks relative to it): about SNIP characters around the first hit, "…" where it is cut."""
    if len(text) <= SNIP:
        return text, marks
    first = marks[0][0] if marks else 0
    start = max(0, min(first - SNIP // 3, len(text) - SNIP))
    if start > 0:  # not in the middle of a word
        sp = text.find(" ", start, min(first, start + 20))
        start = sp + 1 if sp >= 0 else start
    end = min(len(text), start + SNIP)
    pre, post = ("…" if start > 0 else ""), ("…" if end < len(text) else "")
    out = pre + text[start:end] + post
    sh = len(pre) - start
    return out, [[s + sh, min(e, end) + sh] for s, e in marks if s >= start and s < end]


# ---- the search
def search_messages(c, uid, q, arts=None, sender=None, room=None, agent=None, task=None):
    """Every visible message matching q, newest first: a list of hit dicts (see the module doc)."""
    if not msg_fts_ok(c):
        raise Denied(503, tr("The message search is not available on this server"))
    terms = msg_terms(q)
    match = fts_query(terms)
    agent_me = is_agent(g.user) if getattr(g, "user", None) is not None else False
    arts = set(arts or ARTS)
    if room is not None:
        arts &= {"t"}
    if agent is not None:
        arts &= {"a"}
    if task is not None:
        arts &= {"c"}
    hits = []
    head = "WITH h AS (SELECT rowid/4 AS id FROM msg_fts WHERE msg_fts MATCH ? AND rowid%4={k}) "
    snd = " AND m.user_id=?" if sender is not None else ""
    ags = agent_ids(c)
    roles = {}

    def role(lid):
        if lid not in roles:
            roles[lid] = list_role(c, lid, uid)
        return roles[lid]

    if "c" in arts:
        rows = c.execute(head.format(k=1) + f"""SELECT m.id, m.task_id, m.user_id, m.body, m.created_at, t.list_id, t.title
            FROM h JOIN comments m ON m.id=h.id JOIN tasks t ON t.id=m.task_id
            WHERE m.deleted_at IS NULL AND t.deleted_at IS NULL AND t.list_id IN {vis_sql()} AND {tvis(c, uid, 't.', write=True)}{snd}
            {' AND m.task_id=?' if task is not None else ''} ORDER BY m.id DESC LIMIT {MSG_CAND}""",
                         [match, uid, uid] + ([sender] if sender is not None else []) + ([task] if task is not None else [])).fetchall()
        for r in rows:
            if not role(r["list_id"]):
                continue
            hits.append({"art": "c", "chat_type": "task", "id": r["id"], "task_id": r["task_id"], "list_id": r["list_id"],
                         "chat_name": r["title"], "sender_id": r["user_id"], "created_at": r["created_at"], "_body": r["body"]})
    if "t" in arts and (collab_all() if agent_me else tchat_on(c, uid)):
        rows = c.execute(head.format(k=2) + f"""SELECT m.id, m.room_id, m.user_id, m.body, m.created_at, r.kind, r.list_id, r.a, r.b
            FROM h JOIN tchat_msgs m ON m.id=h.id JOIN tchat_rooms r ON r.id=m.room_id
            WHERE m.deleted_at IS NULL AND ((r.kind='dm' AND (r.a=? OR r.b=?)) OR (r.kind='list' AND r.list_id IN {vis_sql()})){snd}
            {' AND m.room_id=?' if room is not None else ''} ORDER BY m.id DESC LIMIT {MSG_CAND}""",
                         [match, uid, uid, uid, uid] + ([sender] if sender is not None else []) + ([room] if room is not None else [])).fetchall()
        ok, lnames = {}, {}
        for r in rows:
            if r["room_id"] not in ok:
                rr = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (r["room_id"],)).fetchone()
                ok[r["room_id"]] = tchat_room_ok(c, rr, uid) and (r["kind"] == "dm" or role(r["list_id"]) in FULL_ROLES)
            if not ok[r["room_id"]]:
                continue
            d = {"art": "t", "chat_type": "dm" if r["kind"] == "dm" else "list", "id": r["id"], "room_id": r["room_id"],
                 "sender_id": r["user_id"], "created_at": r["created_at"], "_body": r["body"]}
            if r["kind"] == "dm":
                d["_other"] = r["b"] if r["a"] == uid else r["a"]
            else:
                if r["list_id"] not in lnames:
                    lnames[r["list_id"]] = (c.execute("SELECT name FROM lists WHERE id=?", (r["list_id"],)).fetchone() or ["?"])[0]
                d.update(list_id=r["list_id"], chat_name=lnames[r["list_id"]])
            hits.append(d)
    if "a" in arts:
        if agent_me:
            cond, a2 = "m.agent_id=?", [uid]
            if agent is not None:  # an agent filters by the person it talks to
                cond += " AND m.user_id=?"
                a2.append(agent)
        else:
            cond, a2 = "m.user_id=?", [uid]
            if agent is not None:
                cond += " AND m.agent_id=?"
                a2.append(agent)
        sq = ""
        if sender is not None:
            sq = " AND ((m.sender='user' AND m.user_id=?) OR (m.sender='agent' AND m.agent_id=?))"
            a2 += [sender, sender]
        rows = c.execute(head.format(k=3) + f"""SELECT m.id, m.agent_id, m.user_id, m.sender, m.body, m.created_at
            FROM h JOIN agent_chat m ON m.id=h.id WHERE {cond}{sq} ORDER BY m.id DESC LIMIT {MSG_CAND}""", [match] + a2).fetchall()
        reach = {}
        for r in rows:
            if not agent_me:
                if r["agent_id"] not in reach:
                    reach[r["agent_id"]] = agent_shares(c, r["agent_id"], uid)
                if not reach[r["agent_id"]]:
                    continue
            hits.append({"art": "a", "chat_type": "agent", "id": r["id"], "agent_id": r["agent_id"], "user_id": r["user_id"],
                         "_other": r["user_id"] if agent_me else r["agent_id"],
                         "sender_id": r["user_id"] if r["sender"] == "user" else r["agent_id"], "created_at": r["created_at"], "_body": r["body"]})
    hits.sort(key=lambda h: (h["created_at"] or "", h["id"]), reverse=True)
    # plain text (mentions -> @name, Markdown markers out), the words really in it, the snippet with its marks
    ids = {h["sender_id"] for h in hits} | {h.get("_other") for h in hits}
    for h in hits:
        ids |= {int(x) for x in MENTION_RE.findall(h["_body"])}
    names = user_names(c, ids)
    out = []
    for h in hits:
        text = comment_plain(c, md_brief(h.pop("_body")), names)
        marks = find_marks(text, terms)
        if marks is None:  # only in a mention id or a Markdown marker
            continue
        h["snippet"], h["marks"] = snippet(text, marks)
        o = h.pop("_other", None)
        if o is not None:
            h["chat_name"] = names.get(o, "?")
        h["sender"] = {"id": h["sender_id"], "name": names.get(h["sender_id"], "?") if h["sender_id"] else "?",
                       "agent": h["sender_id"] in ags}
        h.pop("sender_id")
        out.append(h)
    return out


def _filters(a):
    arts = None
    if a.get("art"):
        arts = {x.strip() for x in a["art"].split(",") if x.strip()}
        if not arts or arts - set(ARTS):
            raise BadInput(tr("Invalid value: {0}", "art"))
    num = {}
    for k in ("sender", "room", "agent", "task"):
        v = a.get(k)
        num[k] = as_int(v, k, 1) if v not in (None, "") else None
    q = (a.get("q") or "").strip()
    if not q or len(q) > 200:
        raise BadInput(tr("Invalid value: {0}", "q"))
    return q, arts, num


@app.get("/api/search/messages")
def msg_search_web():
    """?q, art=c,t,a, sender, room, agent, task, limit (1-50), offset -- {hits, next_offset, total}."""
    a = request.args
    try:
        q, arts, num = _filters(a)
        lim = as_int(a.get("limit", 20), "limit", 1, 50)
        off = as_int(a.get("offset", 0), "offset", 0, 100000)
    except BadInput as e:
        return jsonify(error=str(e)), 400
    try:
        hits = search_messages(db(), me(), q, arts, **num)
    except Denied as e:
        return jsonify(error=e.text()), e.code
    except BadInput as e:
        return jsonify(error=str(e)), 400
    part = hits[off:off + lim]
    return jsonify(hits=part, total=len(hits), next_offset=off + lim if len(hits) > off + lim else None)


def v1_search_messages():
    """GET /api/v1/search?scope=messages (people and agents, each only in what they may read)."""
    a = v1_args(("scope", "q", "limit", "cursor", "art", "sender", "room", "agent", "task"))
    q, arts, num = _filters(a)
    lim = as_int(a.get("limit", 50), "limit", 1, API_PAGE_MAX)
    off = cursor_dec("m", a.get("cursor"))
    hits = search_messages(db(), me(), q, arts, **num)
    part = hits[off:off + lim]
    return jsonify(data=part, total=len(hits), next_cursor=cursor_enc("m", off + lim) if len(hits) > off + lim else None)


v1_search_messages = v1_view(v1_search_messages)


def msgsearch_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    schemas["MessageHit"] = {"type": "object", "description": "2.33.0: a message found by GET /search?scope=messages", "properties": {
        "art": {"type": "string", "enum": ["c", "t", "a"], "description": "c = task comment, t = team chat, a = agent chat"},
        "chat_type": {"type": "string", "enum": list(CHAT_TYPES), "description": "task (comments) | list (channel) | dm (direct message) | agent"},
        "id": {"type": "integer", "description": "Message (comment) id"},
        "task_id": {"type": "integer"}, "list_id": {"type": "integer"}, "room_id": {"type": "integer"},
        "agent_id": {"type": "integer"}, "user_id": {"type": "integer", "description": "agent chat: the person"},
        "chat_name": {"type": "string", "description": "Task title, list name, the other person or the agent"},
        "sender": {"type": "object", "properties": {"id": nul("integer"), "name": {"type": "string"}, "agent": {"type": "boolean"}}},
        "created_at": {"type": "string", "format": "date-time"},
        "snippet": {"type": "string", "description": "Plain text around the hit (never HTML), cut ends marked with …"},
        "marks": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}},
                  "description": "[start, end) character ranges of the hits in snippet"}}}
