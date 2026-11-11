"""2.64.1 B (#1817): the lock per list -- the other ways out of the server (findings H2, M4, M5, M7, L6).

A list with the lock (lists.e2e not NULL, collab/liste2e.py) keeps its texts as browser ciphertexts. Only the web app of a
signed-in person gets them (and decrypts them); every other way that hands texts out gets empty texts or the neutral word
(le2e_neutral) and, in the API, the flag encrypted: true. Every way that writes texts without a browser is refused.

- API v1 / MCP / agents (one place for all of /api/v1/): a write that touches a locked list (path ids, list_id / task_id in
  the body) -> 403; a read answer is masked (texts of objects of locked lists empty + encrypted: true, any ciphertext anywhere
  empty). le2b_mask is also used for webhook payloads.
- History (activity.data): never texts of a locked list (le2b_act_data, called by tasks/validation.py log_act).
- Copies (le2b_scrub, called by part A when the lock is switched on): history texts, time entry snapshots, the shopping
  memory, news data, waiting webhook deliveries, agent events, the list's mail address, the trash copies of deleted
  sections and custom fields (#5549). Templates (private copies of people)
  are NOT deleted: deleting data is a one-way step (named in docs/SECURITY.md).

Prefix le2b_ (part B)."""
import hmac
import json
import re

from flask import g, has_request_context, request

from ..core.config import API_PREFIX, app
from ..core.db import db
from ..core.undogroups import ug_drop_ids, ug_gids
from ..core.i18n import N_, tr
from .liste2e import LE2E_PREFIX, le2e_is_cipher, le2e_modes, le2e_neutral
from ..api.common import v1_err  # 2.369.5 (#2517): pulled up from functions
from ..lists.fields import FIELD_KIND  # #5549
from ..personal.timewipe import TZW_KIND, h6b_sig  # #5549

LE2B_API_MSG = N_("This project is encrypted in the browser. Its texts cannot be read or changed through the API or by agents.")
LE2B_OFF_MSG = N_("Not available in projects encrypted in the browser.")
# text keys of objects of a locked list that are blanked for every reader but the web app (task, comment, note, section,
# news, search hit, webhook / event payload); names / values stay unless they are ciphertexts (list names, field names)
LE2B_TEXT_KEYS = frozenset(("title", "notes", "content", "url", "body", "text", "excerpt", "snippet", "task_title", "summary",
                            "description", "prev", "note_title", "note_body"))
# history data keys that never carry a text of the task (everything else of a locked list is dropped)
LE2B_ACT_SAFE = frozenset(("via", "due", "time", "start", "p", "from", "to_id", "n", "id", "rule", "inbox", "status", "kind",
                           "count", "e2e", "user_id", "assignee", "group_id", "blocker", "child", "files", "emoji", "role", "on",
                           "state"))  # 2.392.2 (#3365): the delivery state (an enum; ids stay anyway)


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
    if request.method == "POST" and request.path == f"{API_PREFIX}tasks/brief":
        return None  # 2.392.3 (#3368): reads only and leaves the tasks of a locked list out itself (skipped: locked); the mask below stays
    c = db()
    if le2b_any(c) and le2b_v1_target(c):
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
    n.update(le2b_scrub_free(c, lid))  # 2.538.0 (#4372)
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
    c.execute("DELETE FROM agent_burst_held WHERE list_id=?", (lid,))  # 2.465.0 (#3892)
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
    # #5408: the server's undo steps of the list's sections and of the order of its sections (tasks: le2b_scrub_tasks).
    # 2.858.0 CI red (#5476): + a section's create / delete steps (lists/secundo.py "section_life", labelled with its name;
    # also of a section in the list's trash) and the steps of the time entries whose note le2b_scrub_free empties
    # (personal/timeundo.py "time_entry", the note in obj_undo.snap)
    n["undo_sections"] = le2b_scrub_undo(c, "(kind IN ('section', 'section_life') AND ref_id IN (SELECT id FROM sections WHERE list_id=? "
                                            "UNION SELECT ref_id FROM list_part_trash WHERE list_id=? AND kind='section')) "
                                            "OR (kind='section_order' AND ref_id=?)", (lid, lid, lid))
    n["undo_time"] = n.get("undo_time", 0) + le2b_scrub_undo(  # 2.900.0 (review): + what le2b_scrub_tasks counted
        c, f"kind='time_entry' AND ref_id IN (SELECT id FROM time_entries WHERE list_id=? OR task_id IN ({tq}))", (lid, lid))
    n.update(le2b_scrub_undo_free(c, lid))  # 2.900.0 (#5550, #5551)
    n.update(le2b_scrub_trash(c, lid))  # #5549: after undo_sections (it reads the section copies)
    for fn in _SCRUB_MORE:
        n.update(fn(c, lid) or {})
    return n


def le2b_scrub_undo(c, where, args):
    """#5408 (finding H2): the server's undo steps (core/undogroups.py #5249, tasks/tundo.py #5251) keep a part's
    values before / after as plain text (obj_undo.snap) and their group's label names the task (undo_groups.label_args).
    Every group with a part matching where (on obj_undo) goes whole - a step is taken back as one, and its label may quote
    the text -, a part of an editor session matching where too. The caller commits. Returns the groups dropped."""
    gids = ug_gids(c, where, args)
    ug_drop_ids(c, gids)
    c.execute(f"DELETE FROM obj_undo WHERE {where}", tuple(args))
    return len(gids)


def le2b_scrub_undo_free(c, lid):
    """2.900.0 (#5550, #5551): the undo steps whose copy (obj_undo.snap / redo hold the whole row, core/writes.py _snap)
    keeps a free text the lock empties (le2b_scrub_free) or refuses: the time entries of the project and of its tasks also
    when the entry was deleted since ("time_life", its row only in the copy) or moved elsewhere, the project's own settings
    ("listset": description, status note) and its notepads ("notepad": title and text before they were emptied for the
    lock; also of a notepad deleted since). Part of le2b_scrub; core/db.py runs it once for the projects locked before.
    Idempotent, the caller commits. Returns {what: groups dropped}."""
    tids = [r[0] for r in c.execute("SELECT id FROM tasks WHERE list_id=?", (lid,))]
    # review (Fable): an undo / redo before the lock wrote the whole row's changes into the history (core/writes.py
    # obj_undo_hist, also columns never written back): the note / task title, description / status note, notepad texts
    hist = c.execute("""DELETE FROM obj_history WHERE (kind='time_entry' AND ref_id IN (SELECT id FROM time_entries WHERE list_id=?
                        OR task_id IN (SELECT id FROM tasks WHERE list_id=?))) OR (kind='listset' AND ref_id=?)
                        OR (kind='notepad' AND ref_id IN (SELECT id FROM list_notepads WHERE list_id=?))""", (lid, lid, lid, lid)).rowcount
    return {"history_copies": hist,
            "undo_time_copies": _scrub_undo_ids(c, le2b_undo_copies(c, ("time_entry", "time_life"), [lid], tids)),
            "undo_settings": le2b_scrub_undo(c, "kind='listset' AND ref_id=?", (lid,)),  # #5551
            "undo_notepads": le2b_scrub_undo(c, "kind='notepad' AND ref_id IN (SELECT id FROM list_notepads WHERE list_id=?)", (lid,))
            + _scrub_undo_ids(c, le2b_undo_copies(c, ("notepad",), [lid], ()))}  # #5551


def _undo_rows(js):
    """The rows a copy holds: a snap step {table: [row]}, a diff part of a deleted row {"row": row}."""
    try:
        d = json.loads(js) if isinstance(js, str) else js
    except ValueError:
        return []
    if not isinstance(d, dict):
        return []
    rows = [d["row"]] if isinstance(d.get("row"), dict) else []
    for v in d.values():
        if isinstance(v, list):
            rows += [r for r in v if isinstance(r, dict)]
    return rows


def _int(v):
    try:
        return int(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


def le2b_undo_copies(c, kinds, lids, tids):
    """2.900.0 (#5550): the ids of the undo parts of kinds whose copy (before or after) holds a row of a list in lids or of a
    task in tids -- also when that row is gone or elsewhere now, which a match on ref_id misses. The database picks the
    candidates (as le2b_scrub_trash_tasks), the rows of the copy decide."""
    lids, tids = {int(x) for x in lids or ()}, {int(x) for x in tids or ()}
    if not lids and not tids:
        return []
    ids = sorted(lids | tids)
    out, seen = [], set()
    kq = ",".join("?" * len(kinds))
    for ch in [ids[i:i + 500] for i in range(0, len(ids), 500)]:
        rx = rf'"(list|task)_id":\s*({"|".join(str(i) for i in ch)})\s*[,}}]'
        for r in c.execute(f"SELECT id, snap, redo FROM obj_undo WHERE kind IN ({kq}) AND (snap ~ ? OR COALESCE(redo, '') ~ ?)",
                           (*kinds, rx, rx)).fetchall():
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            if any(_int(row.get("list_id")) in lids or _int(row.get("task_id")) in tids
                   for row in _undo_rows(r["snap"]) + _undo_rows(r["redo"])):
                out.append(int(r["id"]))
    return out


def _scrub_undo_ids(c, ids):
    n = 0
    for i in range(0, len(ids), 1000):
        part = ids[i:i + 1000]
        n += le2b_scrub_undo(c, f"id IN ({','.join('?' * len(part))})", part)
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
LE2B_AGENT_MSG = N_("This project is encrypted in the browser: agents cannot be added to it.")


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


def le2b_scrub_free(c, lid):
    """2.538.0 (#4372): the three free texts the lock cannot encrypt go for good: the time entries' notes (of the project and
    its tasks), the project's status note (also in its status history) and its description (also the earlier ones kept for
    "bring back"). Part of le2b_scrub; core/db.py runs it once for the projects locked before 2.538 (review 2646, finding 1).
    Idempotent, the caller commits. Returns {what: rows}."""
    tq = "SELECT id FROM tasks WHERE list_id=?"
    return {
        "time_notes": c.execute(f"UPDATE time_entries SET note='' WHERE note<>'' AND (list_id=? OR task_id IN ({tq}))", (lid, lid)).rowcount,
        "list_texts": c.execute("UPDATE lists SET status_note='', description='' WHERE id=? AND (status_note<>'' OR COALESCE(description, '')<>'')",
                                (lid,)).rowcount,
        "list_status": c.execute("UPDATE list_status SET note='' WHERE list_id=? AND note<>''", (lid,)).rowcount,
        "desc_history": c.execute("DELETE FROM list_activity WHERE list_id=? AND kind='desc'", (lid,)).rowcount,
    }


def le2b_scrub_trash(c, lid, plain_only=False):
    """#5549 (finding H2): the copies of the list's trash (core/objparts.py part_copy, list_part_trash) made before the lock:
    a deleted section keeps its name (snap), a deleted custom field the values of the tasks (held) - both go for good, as the
    free texts of le2b_scrub_free (restoring them would also write plain text into the locked list). Planned sprints stay
    (their names are not encrypted). The Undo copies of "Delete all times" (personal/timewipe.py) keep their entries, without
    note and task title (emptied as le2b_scrub empties them in time_entries) and sealed again, so Undo still works.
    plain_only (core/db.py, once for the projects locked before #5549): only copies holding plain text - a section whose
    name is no ciphertext, a text field with a value that is none; a copy deleted under the lock stays.
    Idempotent, the caller commits. Returns {what: rows}."""
    n = {"trash_sections": 0, "trash_fields": 0, "trash_times": 0}
    for r in c.execute("SELECT id, kind, snap, held FROM list_part_trash WHERE list_id=? AND kind IN (?, ?, ?) ORDER BY id",
                       (lid, "section", FIELD_KIND, TZW_KIND)).fetchall():
        if r["kind"] == TZW_KIND:
            try:
                es = json.loads(r["held"] or "[]")
            except ValueError:
                continue
            es = es if isinstance(es, list) else []
            if not any(isinstance(e, dict) and (e.get("note") or e.get("task_title")) for e in es):
                continue
            for e in es:
                if isinstance(e, dict) and (e.get("note") or e.get("task_title")):
                    ok = isinstance(e.get("sig"), str) and hmac.compare_digest(e["sig"], h6b_sig(c, lid, e))
                    e["note"], e["task_title"] = "", ""
                    if e.get("sig"):  # review 4: sealed again only when the old seal held (a broken one stays broken)
                        e["sig"] = h6b_sig(c, lid, e) if ok else "-"
            c.execute("UPDATE list_part_trash SET held=? WHERE id=?", (json.dumps(es, ensure_ascii=False, default=str), r["id"]))
            n["trash_times"] += 1
            continue
        if plain_only and not _trash_plain(r):
            continue
        c.execute("DELETE FROM list_part_trash WHERE id=?", (r["id"],))
        n["trash_sections" if r["kind"] == "section" else "trash_fields"] += 1
    return n


def le2b_trash_cipher_purge(c, lid):
    """#5563 (finding of the review of #5549): when the lock of project lid is switched off (le2a_finish, decrypting) or a key
    change is done (e2e_reenc), the copies in its trash holding ciphertexts go for good, as le2b_scrub_trash drops the plain
    ones when it is switched on: a deleted custom field with a ciphertext value (held.vals) - nobody re-encrypts or decrypts
    the trash, a restore would bring back what nobody can read. The sections of the trash go in both cases through
    lists/parttrash.py lpt_section_purge_list (#5552). Like the files and comment texts of the trash (atr_purge_list,
    ctt_purge_list) it looks at no generation: a copy of the new key goes too (review 3, accepted). Idempotent, the caller commits. Returns the copies dropped."""
    k = 0
    for r in c.execute("SELECT id, held FROM list_part_trash WHERE list_id=? AND kind=? ORDER BY id", (lid, FIELD_KIND)).fetchall():
        try:
            held = json.loads(r["held"] or "{}")
        except ValueError:
            continue
        vals = held.get("vals") if isinstance(held, dict) else None
        if any(isinstance(v, list) and len(v) > 1 and le2e_is_cipher(v[1]) for v in vals or []):
            c.execute("DELETE FROM list_part_trash WHERE id=?", (r["id"],))
            k += 1
    return k


def _trash_plain(r):
    """Does copy r (a section or a custom field of list_part_trash) hold plain text of the encrypted fields?"""
    try:
        snap, held = json.loads(r["snap"] or "{}"), json.loads(r["held"] or "{}")
    except ValueError:
        return True
    snap, held = (snap if isinstance(snap, dict) else {}), (held if isinstance(held, dict) else {})
    if r["kind"] == "section":
        return bool(snap.get("name")) and not le2e_is_cipher(snap.get("name"))
    if snap.get("type") != "text":
        return False  # select / number / date values stay readable in a locked list too (collab/liste2e.py, decision E2)
    return any(isinstance(v, list) and len(v) > 1 and v[1] and not le2e_is_cipher(v[1]) for v in held.get("vals") or [])


def le2b_scrub_tasks(c, ids):
    """The copies of tasks that were just moved into a list with the lock (part A calls it after the move): their history
    texts, time entry snapshots and pending tidy events, #5562: their texts in the trash copies of other projects. The caller commits."""
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
        c.execute(f"UPDATE time_entries SET task_title='', note='' WHERE task_id IN ({q})", part)  # 2.538.0 (#4372): + the note
        # 2.392.0 C (#3370): the server cannot encrypt them: the reason goes, a decision keeps who and when, its text the neutral word
        c.execute(f"UPDATE tasks SET irreversible_reason='' WHERE irreversible_reason<>'' AND id IN ({q})", part)
        c.execute(f"UPDATE tasks SET delivery_note='' WHERE delivery_note<>'' AND id IN ({q})", part)  # 2.392.2 (#3365): as the reason
        c.execute(f"UPDATE task_decisions SET text=? WHERE task_id IN ({q})", (le2e_neutral(), *part))
        c.execute(f"DELETE FROM tidy_pending WHERE task_id IN ({q})", part)
        n["undo_tasks"] = n.get("undo_tasks", 0) + le2b_scrub_undo(c, f"kind='task' AND ref_id IN ({q})", part)  # #5408
        # 2.900.0 (#5550): + the steps of their time entries (the note and task title emptied above sit in the copy)
        n["undo_time"] = n.get("undo_time", 0) + le2b_scrub_undo(
            c, f"kind='time_entry' AND ref_id IN (SELECT id FROM time_entries WHERE task_id IN ({q}))", part)
        n["history_time"] = n.get("history_time", 0) + c.execute(  # review (Fable): their history rows too (le2b_scrub_undo_free)
            f"DELETE FROM obj_history WHERE kind='time_entry' AND ref_id IN (SELECT id FROM time_entries WHERE task_id IN ({q}))", part).rowcount
    # ... and of their entries deleted or moved elsewhere since (the row only in the copy)
    n["undo_time"] = n.get("undo_time", 0) + _scrub_undo_ids(c, le2b_undo_copies(c, ("time_entry", "time_life"), (), ids))
    n.update(le2b_scrub_trash_tasks(c, set(ids)))  # #5562
    return n


def le2b_scrub_trash_tasks(c, ids):
    """#5562 (finding of the review of #5549): the copies in the trash of OTHER projects (core/objparts.py part_copy) still quote
    tasks that are now in a locked project: the Undo copy of "Delete all times" (personal/timewipe.py) keeps their title and
    note -> emptied and sealed again (as le2b_scrub_trash does it), a deleted custom field (lists/fields.py fd_trash) keeps
    their values (held.vals) -> taken out (fd_back would not give them to a task outside its project anyway). The copy itself
    stays. Idempotent, the caller commits. Returns {what: rows}."""
    n = {"trash_task_times": 0, "trash_task_fields": 0}
    ids = {i for i in ids if isinstance(i, int)}
    rows, seen = [], set()
    for ch in [sorted(ids)[i:i + 500] for i in range(0, len(ids), 500)]:  # review 1: the database picks the copies naming them
        alt = "|".join(str(i) for i in ch)
        for r in c.execute("SELECT id, list_id, kind, held FROM list_part_trash WHERE kind IN (?, ?) AND held ~ ? ORDER BY id",
                           (FIELD_KIND, TZW_KIND, rf'"task_id":\s*({alt})\s*[,}}]|\[\s*({alt})\s*,')).fetchall():
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(r)
    for r in rows:
        try:
            held = json.loads(r["held"] or "null")
        except ValueError:
            continue
        if r["kind"] == TZW_KIND:
            es = held if isinstance(held, list) else []
            hit = [e for e in es if isinstance(e, dict) and isinstance(e.get("task_id"), int) and e["task_id"] in ids
                   and (e.get("note") or e.get("task_title"))]
            for e in hit:
                ok = isinstance(e.get("sig"), str) and hmac.compare_digest(e["sig"], h6b_sig(c, r["list_id"], e))
                e["note"], e["task_title"] = "", ""
                if e.get("sig"):  # as le2b_scrub_trash: sealed again only when the old seal held
                    e["sig"] = h6b_sig(c, r["list_id"], e) if ok else "-"
            if hit:
                c.execute("UPDATE list_part_trash SET held=? WHERE id=?", (json.dumps(es, ensure_ascii=False, default=str), r["id"]))
                n["trash_task_times"] += 1
            continue
        if not isinstance(held, dict) or not isinstance(held.get("vals"), list):
            continue
        vals = [v for v in held["vals"] if not (isinstance(v, list) and v and isinstance(v[0], int) and v[0] in ids)]
        if len(vals) != len(held["vals"]):
            held["vals"], held["n"] = vals, len({v[0] for v in vals if isinstance(v, list) and v and isinstance(v[0], int)})
            c.execute("UPDATE list_part_trash SET held=? WHERE id=?", (json.dumps(held, ensure_ascii=False), r["id"]))
            n["trash_task_fields"] += 1
    return n
