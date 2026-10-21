"""2.64.1 B (#1817): the lock per list -- the other ways out of the server (findings H2, M4, M5, M7, L6).

A list with the lock (lists.e2e not NULL, collab/liste2e.py) keeps its texts as browser ciphertexts. Only the web app of a
signed-in person gets them (and decrypts them); every other way that hands texts out gets empty texts or the neutral word
(le2e_neutral) and, in the API, the flag encrypted: true. Every way that writes texts without a browser is refused.

- API v1 / MCP / agents (one place for all of /api/v1/): a write that touches a locked list (path ids, list_id / task_id in
  the body) -> 403; a read answer is masked (texts of objects of locked lists empty + encrypted: true, any ciphertext anywhere
  empty). le2b_mask is also used for webhook payloads.
- History (activity.data): never texts of a locked list (le2b_act_data, called by tasks/validation.py log_act).
- Copies (le2b_scrub, called by part A when the lock is switched on): history texts, time entry snapshots, the shopping
  memory, news data, waiting webhook deliveries, agent events, the list's mail address. Templates (private copies of people)
  are NOT deleted: deleting data is a one-way step (named in docs/SECURITY.md).

Prefix le2b_ (part B)."""
import json
import re

from flask import g, has_request_context, request

from ..core.config import API_PREFIX, app
from ..core.db import db
from ..core.i18n import N_, tr
from .liste2e import LE2E_PREFIX, le2e_is_cipher, le2e_modes, le2e_neutral

LE2B_API_MSG = N_("This list is encrypted in the browser. Its texts cannot be read or changed through the API or by agents.")
LE2B_OFF_MSG = N_("Not available in lists encrypted in the browser.")
# text keys of objects of a locked list that are blanked for every reader but the web app (task, comment, note, section,
# news, search hit, webhook / event payload); names / values stay unless they are ciphertexts (list names, field names)
LE2B_TEXT_KEYS = frozenset(("title", "notes", "content", "url", "body", "text", "excerpt", "snippet", "task_title", "summary",
                            "description", "prev", "note_title", "note_body"))
# history data keys that never carry a text of the task (everything else of a locked list is dropped)
LE2B_ACT_SAFE = frozenset(("via", "due", "time", "start", "p", "from", "to_id", "n", "id", "rule", "inbox", "status", "kind",
                           "count", "e2e", "user_id", "assignee", "group_id", "blocker", "child", "files", "emoji", "role"))


def le2b_msg():
    return tr(LE2B_API_MSG)


def le2b_off():
    return tr(LE2B_OFF_MSG)


def le2b_web():
    """Is this request from a signed-in person in the web app (session cookie / proxy login)? Agents, API tokens, CalDAV,
    mail and public links never are."""
    return has_request_context() and getattr(g, "auth_via", None) in ("session", "proxy") and bool(getattr(g, "user", None)) \
        and g.user["kind"] != "agent"


def le2b_any(c):
    """Is any list locked (or being switched)? Once per request: the fast way out for the API wrappers."""
    if has_request_context() and "le2b_any" in g:
        return g.le2b_any
    v = bool(c.execute("SELECT 1 FROM lists WHERE e2e IS NOT NULL LIMIT 1").fetchone())
    if has_request_context():
        g.le2b_any = v
    return v


def le2b_list_locked(c, lid):
    return bool(lid) and bool(le2e_modes(c, [lid]))


def le2b_task_locked(c, tid):
    if not tid:
        return False
    return bool(c.execute("SELECT 1 FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=? AND l.e2e IS NOT NULL",
                          (tid,)).fetchone())


def le2b_locked_lists(c, lids):
    return set(le2e_modes(c, lids))


def le2b_task_lists(c, tids):
    """{task_id: list_id} of the tasks in tids that belong to a locked list."""
    out, tids = {}, [int(x) for x in set(tids or []) if isinstance(x, int) and not isinstance(x, bool)]
    for i in range(0, len(tids), 5000):
        part = tids[i:i + 5000]
        for r in c.execute(f"""SELECT t.id, t.list_id FROM tasks t JOIN lists l ON l.id=t.list_id
                               WHERE l.e2e IS NOT NULL AND t.id IN ({','.join('?' * len(part))})""", part):
            out[r[0]] = r[1]
    return out


# ---- masking of answers / payloads (API v1, MCP, webhooks, agent events)
def _ids(o, lids, tids, depth=0):
    if depth > 12:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, int) and not isinstance(v, bool):
                if k == "list_id":
                    lids.add(v)
                elif k in ("task_id", "parent_id"):
                    tids.add(v)
            elif isinstance(v, (dict, list)):
                _ids(v, lids, tids, depth + 1)
    elif isinstance(o, list):
        for v in o:
            _ids(v, lids, tids, depth + 1)


def _blank(o, depth=0):
    """o is (part of) an object of a locked list: every text gone."""
    if depth > 12:
        return o
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k in LE2B_TEXT_KEYS and isinstance(v, str):
                out[k] = ""
            elif k == "snippets" and isinstance(v, (list, str)):
                out[k] = [] if isinstance(v, list) else ""
            else:
                out[k] = _blank(v, depth + 1)
        if any(k in out for k in ("title", "body", "notes", "content")):
            out["encrypted"] = True
        return out
    if isinstance(o, list):
        return [_blank(v, depth + 1) for v in o]
    return "" if le2e_is_cipher(o) else o


def _mask(o, lids, tids, depth=0):
    if depth > 12:
        return o
    if isinstance(o, dict):
        lid, tid = o.get("list_id"), o.get("task_id")
        if (isinstance(lid, int) and lid in lids) or (isinstance(tid, int) and tid in tids):
            return _blank(o, depth)
        return {k: _mask(v, lids, tids, depth + 1) for k, v in o.items()}
    if isinstance(o, list):
        return [_mask(v, lids, tids, depth + 1) for v in o]
    return "" if le2e_is_cipher(o) else o


def le2b_mask(c, obj, force=False):
    """A JSON-like answer / payload for a reader without the list key: objects of locked lists (by list_id, task_id or a task
    id) lose their texts (+ encrypted: true), any ciphertext anywhere becomes "". force: the whole payload belongs to a locked
    list (a webhook of one task)."""
    if force:
        return _blank(obj)
    lids, tids = set(), set()
    _ids(obj, lids, tids)
    locked = le2b_locked_lists(c, lids)
    tl = le2b_task_lists(c, tids)
    locked |= set(tl.values())
    if not locked and not tl:
        return _mask(obj, set(), set())  # only the ciphertext net
    return _mask(obj, locked, set(tl))


LE2B_BODY_LISTS = ("list_id", "to_list_id", "target_list_id")
LE2B_BODY_TASKS = ("task_id", "parent_id", "milestone_id", "blocker_id")


def _body_ids(o, lids, tids, depth=0):
    """List / task ids a v1 request body names (only keys that are ids of lists / tasks: no false positives from numbers
    like reminders)."""
    if depth > 6:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                if k in LE2B_BODY_LISTS:
                    lids.add(v)
                elif k in LE2B_BODY_TASKS:
                    tids.add(v)
            elif isinstance(v, list) and k in ("ids", "task_ids"):
                tids.update(x for x in v if isinstance(x, int) and not isinstance(x, bool))
            elif isinstance(v, (dict, list)):
                _body_ids(v, lids, tids, depth + 1)
    elif isinstance(o, list):
        for v in o:
            if isinstance(v, (dict, list)):
                _body_ids(v, lids, tids, depth + 1)


def le2b_v1_target(c):
    """Does this /api/v1/ write touch a locked list (path ids, ids in the body)?"""
    va, path = request.view_args or {}, request.path
    lids, tids = set(), set()
    if "lid" in va:
        lids.add(va["lid"])
    if "tid" in va:
        tids.add(va["tid"])
    for key, table in (("sid", "sections"), ("nid", "notes")):
        if key in va and (path.startswith(f"{API_PREFIX}sections/") or path.startswith(f"{API_PREFIX}notes/")):
            r = c.execute(f"SELECT list_id FROM {table} WHERE id=?", (va[key],)).fetchone()
            if r:
                lids.add(r[0])
    if "cid" in va and path.startswith(f"{API_PREFIX}comments/"):
        r = c.execute("SELECT task_id FROM comments WHERE id=?", (va["cid"],)).fetchone()
        if r:
            tids.add(r[0])
    # 2.64.2 C (#1817): the channel of a list with the lock (room / message ids of the team chat)
    rid = va.get("rid") if path.startswith(f"{API_PREFIX}team/rooms/") else None
    if "mid" in va and path.startswith(f"{API_PREFIX}team/messages/"):
        r = c.execute("SELECT room_id FROM tchat_msgs WHERE id=?", (va["mid"],)).fetchone()
        rid = r[0] if r else None
    if rid:
        r = c.execute("SELECT list_id FROM tchat_rooms WHERE id=? AND kind='list'", (rid,)).fetchone()
        if r:
            lids.add(r[0])
    b = request.get_json(silent=True) if request.data else None
    if isinstance(b, (dict, list)):
        _body_ids(b, lids, tids)
    return bool(le2b_locked_lists(c, lids)) or bool(le2b_task_lists(c, tids))


@app.before_request
def le2b_v1_guard():
    """2.64.1 B (#1817): agents and API tokens never write into a locked list (403, a clear text). Leaving a list stays."""
    if not request.path.startswith(API_PREFIX) or request.method in ("GET", "HEAD", "OPTIONS") or not getattr(g, "user", None):
        return None
    if request.method == "DELETE" and "/members/" in request.path:
        return None  # removing a member (or oneself) only makes the circle smaller
    c = db()
    if le2b_any(c) and le2b_v1_target(c):
        from ..api.common import v1_err
        return v1_err(403, le2b_msg(), name="list_e2e")
    return None


@app.after_request
def le2b_v1_mask(resp):
    """2.64.1 B (#1817): every /api/v1/ answer (API, MCP, agents) without texts of locked lists."""
    if not has_request_context() or not request.path.startswith(API_PREFIX) or not resp.is_json or resp.direct_passthrough \
            or resp.status_code >= 400:
        return resp  # an error answer carries no texts (and its transaction may be gone)
    try:
        c = db()
        if not le2b_any(c):
            return resp
        d = resp.get_json(silent=True)
        if d is None:
            return resp
        m = le2b_mask(c, d)
        if m != d:
            resp.set_data(json.dumps(m, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        # 2.64.1 review 2 (L7): a failed lookup must not turn every v1 answer into a 500: the answer goes out with every
        # ciphertext emptied (a list that is 'on' holds no plain text on the server, so nothing readable is left); while a
        # list is being switched, or when even that fails, no answer rather than a text (fail closed)
        print("liste2eguard: mask failed:", type(e).__name__, flush=True)
        try:
            if db().execute("SELECT 1 FROM lists WHERE e2e IN ('encrypting', 'decrypting') LIMIT 1").fetchone():
                raise ValueError("switching")  # plain texts may still sit in a list that is being switched: no answer
            resp.set_data(json.dumps(_le2b_strip(resp.get_json(silent=True)), ensure_ascii=False))
        except Exception:  # noqa: BLE001
            resp.set_data(json.dumps({"error": {"code": "error", "message": tr("Error")}}))
            resp.status_code = 500
    return resp


def _le2b_strip(x, depth=0):
    """Every string that carries a ciphertext -> "" (the fallback of the v1 masking)."""
    if depth > 40:
        raise ValueError("deep")
    if isinstance(x, str):
        return "" if LE2E_PREFIX in x else x
    if isinstance(x, list):
        return [_le2b_strip(v, depth + 1) for v in x]
    if isinstance(x, dict):
        return {k: _le2b_strip(v, depth + 1) for k, v in x.items()}
    return x


# ---- history (tasks/validation.py log_act)
def le2b_act_data(c, tid, kind, data):
    """The data of a history entry of task tid: unchanged for open lists; in a locked list without any text (a title change
    is {"e2e": true}; the md_subtasks text before is kept only as an uncut ciphertext)."""
    if not tid or not le2b_task_locked(c, tid):
        # 2.64.1 review (L1): an open task's entry can still name a task of a locked list (dependencies across lists): a
        # ciphertext (often cut to 200 characters by the caller) never lands in the history
        if isinstance(data, dict) and any(isinstance(v, str) and v.startswith(LE2E_PREFIX) for v in data.values()):
            return {**{k: v for k, v in data.items() if not (isinstance(v, str) and v.startswith(LE2E_PREFIX))}, "e2e": True}
        return data
    return le2b_act_data_force(kind, data)


# ---- the copies of a list that is switched on (called by part A in /e2e/finish)
def le2b_scrub(c, lid):
    """Removes / neutralises the plain-text copies of list lid outside its text columns (finding H2). The caller commits.
    Returns {what: rows} (counts only, for the history / a test)."""
    n = {}
    tq = "SELECT id FROM tasks WHERE list_id=?"
    n.update(le2b_scrub_tasks(c, [r[0] for r in c.execute(tq, (lid,))]))
    n["time_entries"] = c.execute(f"UPDATE time_entries SET task_title='' WHERE task_title!='' AND (list_id=? OR task_id IN ({tq}))",
                                  (lid, lid)).rowcount
    n["shop_memory"] = c.execute("DELETE FROM shop_memory WHERE list_id=?", (lid,)).rowcount
    n["mail_tokens"] = c.execute("DELETE FROM mail_tokens WHERE list_id=?", (lid,)).rowcount
    n["notifications"] = 0
    for r in c.execute(f"SELECT id, data FROM notifications WHERE (list_id=? OR task_id IN ({tq})) AND data::text!='{{}}'",
                       (lid, lid)).fetchall():
        d = r["data"] if isinstance(r["data"], dict) else json.loads(r["data"] or "{}")
        nd = {k2: v for k2, v in d.items() if k2 in LE2B_ACT_SAFE or (not isinstance(v, str) and k2 not in LE2B_TEXT_KEYS)}
        if nd != d:
            c.execute("UPDATE notifications SET data=? WHERE id=?", (json.dumps(nd), r["id"]))
            n["notifications"] += 1
    # waiting deliveries / agent events that carry the list or one of its tasks: dropped (an agent is never a member of a
    # locked list; a webhook delivery after the switch carries no text)
    tids = {r[0] for r in c.execute(tq, (lid,))}
    n["webhook_queue"] = _drop_payloads(c, "webhook_queue", lid, tids)
    n["agent_events"] = _drop_payloads(c, "agent_events", lid, tids)
    n["tidy_pending"] = c.execute(f"DELETE FROM tidy_pending WHERE task_id IN ({tq})", (lid,)).rowcount
    # agent proposals about the list (cleanup, tidy, time ...): what they proposed / changed held titles; an open one is closed
    n["agent_jobs"] = c.execute(f"""UPDATE agent_jobs SET input='{{}}', proposal='{{}}', applied='{{}}',
                                    prop_state=CASE WHEN prop_state IN ('', 'applied', 'discarded') THEN prop_state ELSE 'discarded' END
                                    WHERE kind IS NOT NULL AND (list_id=? OR task_id IN ({tq}))""", (lid, lid)).rowcount
    # 2.64.1 review 2 (M5): an agent's chat answers about tasks of the list (an agent was a member before the switch) quote
    # their texts: they become the neutral word (earlier versions go too), the agent's steps of those answers and of the
    # list's jobs go empty. The person's own chat messages stay (their own words; docs/ARCHITECTURE.md names it).
    # imports (ids and counts only), webhook_log (never bodies) and journal (a person's day notes, no list) hold no copy.
    nw = le2e_neutral()
    n["agent_chat"] = c.execute(f"UPDATE agent_chat SET body=?, edits=NULL WHERE sender='agent' AND body!=? AND task_id IN ({tq})",
                                (nw, nw, lid)).rowcount
    n["agent_steps"] = c.execute(f"""UPDATE agent_steps SET text='' WHERE text!='' AND (
                                    message_id IN (SELECT id FROM agent_chat WHERE task_id IN ({tq}))
                                    OR job_id IN (SELECT id FROM agent_jobs WHERE list_id=? OR task_id IN ({tq})))""",
                                 (lid, lid, lid)).rowcount
    for fn in _SCRUB_MORE:
        n.update(fn(c, lid) or {})
    return n


_SCRUB_MORE = []  # further copies (other modules append a function (c, lid) -> {what: n})


def _drop_payloads(c, table, lid, tids):
    k = 0
    for r in c.execute(f"SELECT id, payload FROM {table}").fetchall():
        try:
            p = json.loads(r["payload"] or "{}")
        except ValueError:
            continue
        lids, ts = set(), set()
        _ids(p, lids, ts)
        if lid in lids or ts & tids:
            c.execute(f"DELETE FROM {table} WHERE id=?", (r["id"],))
            k += 1
    return k


def le2b_act_data_force(kind, data):
    """le2b_act_data for a row known to belong to a locked list."""
    if kind == "title":
        return {"e2e": True, **({"via": data["via"]} if isinstance(data, dict) and data.get("via") else {})}
    if not isinstance(data, dict) or not data:
        return data
    out = {}
    for k, v in data.items():
        if k == "prev" and kind == "md_subtasks":
            if le2e_is_cipher(v):
                out[k] = v
        elif k == "name" and kind == "list":
            out[k] = v
        elif k in LE2B_ACT_SAFE and not le2e_is_cipher(v):
            out[k] = v
        elif not isinstance(v, str) and k not in LE2B_TEXT_KEYS and k not in ("name", "names", "old", "new", "value"):
            out[k] = v
    if out != data:
        out["e2e"] = True
    return out


# ---- news (collab/news.py news_items: also the mail digest and pushes read it)
def le2b_news(c, items):
    """Items about tasks of a locked list: the title, the excerpt and text data go (also an agent group's task titles);
    enc: true + list_id stay, the app resolves the task by its id ("New comment in <list>")."""
    locked = le2b_locked_lists(c, [x.get("list_id") for x in items])
    for x in items:
        if isinstance(x.get("data"), dict):
            x["data"] = {k: (None if le2e_is_cipher(v) else v) for k, v in x["data"].items()}
        if (x.get("list_id") in locked and x.get("task_id")) or le2e_is_cipher(x.get("task_title")) \
                or le2e_is_cipher(x.get("excerpt")):
            x.update(task_title=None, excerpt="", enc=True)
            if isinstance(x.get("data"), dict):
                x["data"] = {k: v for k, v in x["data"].items() if not isinstance(v, str) or k in LE2B_ACT_SAFE}
            if x.get("tasks"):
                x["tasks"] = [{"id": t.get("id"), "title": None} for t in x["tasks"]]
    return items


# ---- agents (finding M4)
LE2B_AGENT_MSG = N_("This list is encrypted in the browser: agents cannot be added to it.")


def le2b_agent_problem(c, lid, uid):
    """The reason (translated) why uid cannot join list lid because of the lock, or None (only agents; the participant
    role is part A's rule). Used by ws_member_problem, so every share path (dialog, share-all, autoshare, folders, groups,
    proposals) skips a locked list."""
    if not lid or isinstance(uid, bool) or not isinstance(uid, int) or not le2b_list_locked(c, lid):
        return None
    if c.execute("SELECT 1 FROM users WHERE id=? AND kind='agent'", (uid,)).fetchone():
        return tr(LE2B_AGENT_MSG)
    return None


# ---- the net for every text that leaves the server (push, ntfy, mail; finding M5)
LE2B_CIPHER_RE = re.compile(r"e2e1:\{[^}]*\}?")


def le2b_net(s, lg=None):
    """Every ciphertext of a list with the lock (also a cut one) inside a text -> the neutral word ("Due: 🔒 Task"). The
    service worker and the mail reader never get a key, so a ciphertext there would only be noise and a length leak."""
    if not isinstance(s, str) or "e2e1:" not in s:
        return s
    return LE2B_CIPHER_RE.sub(lambda _m: le2e_neutral(lg), s)  # 2.64.2 D (#1817): in the recipient's language


def le2b_scrub_tasks(c, ids):
    """The copies of tasks that were just moved into a list with the lock (part A calls it after the move): their history
    texts, time entry snapshots and pending tidy events. The caller commits."""
    ids = [int(x) for x in ids or [] if isinstance(x, int)]
    n = {"activity": 0}
    for i in range(0, len(ids), 1000):
        part = ids[i:i + 1000]
        q = ",".join("?" * len(part))
        for r in c.execute(f"SELECT id, kind, data FROM activity WHERE task_id IN ({q})", part).fetchall():
            try:
                d = r["data"] if isinstance(r["data"], dict) else json.loads(r["data"] or "{}")
            except ValueError:
                d = {}
            nd = le2b_act_data_force(r["kind"], d)
            if nd != d:
                c.execute("UPDATE activity SET data=? WHERE id=?", (json.dumps(nd, ensure_ascii=False), r["id"]))
                n["activity"] += 1
        c.execute(f"UPDATE time_entries SET task_title='' WHERE task_id IN ({q})", part)
        c.execute(f"DELETE FROM tidy_pending WHERE task_id IN ({q})", part)
    return n
