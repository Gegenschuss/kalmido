"""2.392.0 D (#3369): what waits for a person, over every workspace: pure data, one place for the view "Waiting for me"
(GET /api/inbox), the API (GET /api/v1/me/waiting) and MCP get_waiting.

waiting_for(c, uid) gathers, only from what uid sees and only what uid can settle: waiting jobs (job_may_act, a proposal of
theirs that is ready), open approval cards from the chat and from comments, open merge / integrate / deploy requests, reviews
with uid as the reviewer, their own blocked tasks, and tasks marked irreversible without a yes where the list asks for one.
With agent_id only the lists shared with that agent count (as the briefing). Parked tasks (#3365) and watchdog findings
(#3366) do not exist yet; they join as kinds of their own here.

Each kind holds at most WAIT_MAX items (counts stop there as well), newest first; a kind reads at most WAIT_SCAN rows. Nothing
here writes or formulates. The texts of a list with the lock stay ciphertexts for the web app; le2b_v1_mask empties them in
the API. Titles taken from an agent's request are dropped there, the app shows the task's own title."""
import json

from flask import g, jsonify

from ..accounts.session import me
from ..api.common import v1_args, v1_view
from ..collab.cchoice import lv_jload, lv_may_decide, lv_state
from ..collab.comments import user_names
from ..collab.liste2eguard import le2b_locked_lists
from ..core.access import Denied, token_lists, tvis
from ..core.config import app
from ..core.db import db, inbox_default
from ..core.errors import BadInput
from ..core.i18n import tr
from ..integrations.delivery import GATE_ALL, WAIT_KINDS, WAIT_MAX
from ..tasks.briefing import brief_blocked, brief_lists
from .chat import chat_approvals_of
from .core import agent_shares, is_agent, is_approver, job_may_act

WAIT_SCAN = 500


def _lname(r):
    return tr("Basket") if r["is_inbox"] and inbox_default(r["list_name"]) else r["list_name"]


def _item(kind, oid, title, at, t=None, **more):
    """One entry. t: a row of the task (id, title, list_id, list_name, is_inbox) when uid sees it, else no task data at all."""
    d = {"kind": kind, "id": oid, "title": title or "", "at": at, "task_id": t["id"] if t else None,
         "task_title": t["title"] if t else None, "list_id": t["list_id"] if t else None, "list_name": _lname(t) if t else None}
    return {**d, **more}


class _Scope:
    """The lists and the task condition of one request."""

    def __init__(self, c, uid, agent_id):
        self.c, self.uid, self.agent_id = c, uid, agent_id
        tl = token_lists()
        self.lids = [x for x in brief_lists(c, uid, agent_id) if tl is None or x in tl]
        self.limited = tl is not None  # a token for some lists: nothing outside them, so nothing without a task either
        self.ql = ",".join(str(int(x)) for x in self.lids) or "0"
        self.vis = tvis(c, uid, "t.") + (f" AND {tvis(c, agent_id, 't.')}" if agent_id is not None else "")

    def hidden(self, tid, tasks):
        """A job or chat card of an agent is out when its task is outside what an agent or a limited token may read."""
        return self.limited and tid not in tasks or bool(self.agent_id and tid and tid not in tasks)

    def tasks(self, ids):
        """{task id: row} of those of ids the reader may see in these lists."""
        ids = sorted({x for x in ids if x})
        if not ids:
            return {}
        q = ",".join(str(int(x)) for x in ids)
        return {r["id"]: r for r in self.c.execute(
            f"""SELECT t.id, t.title, t.list_id, l.name AS list_name, l.is_inbox FROM tasks t JOIN lists l ON l.id=t.list_id
                WHERE t.id IN ({q}) AND t.list_id IN ({self.ql}) AND t.deleted_at IS NULL AND {self.vis}""")}


def _jobs(s):
    c, uid = s.c, s.uid
    conds, args = ["state='waiting'"], []
    if s.agent_id:
        conds.append("agent_id=?")
        args.append(s.agent_id)
    if not c.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()[0]:  # an admin acts on the jobs of every agent it reaches
        conds.append(f"(user_id=? OR task_id IN (SELECT id FROM tasks WHERE list_id IN ({s.ql})))")
        args.append(uid)
    rows = c.execute(f"SELECT * FROM agent_jobs WHERE {' AND '.join(conds)} ORDER BY updated_at DESC, id DESC LIMIT {WAIT_SCAN}", args).fetchall()
    tasks = s.tasks(j["task_id"] for j in rows)
    names, out = user_names(c, [j["agent_id"] for j in rows]), []
    for j in rows:
        if s.hidden(j["task_id"], tasks):
            continue
        ok = (j["user_id"] == uid and j["prop_state"] == "ready") if j["kind"] else job_may_act(c, j, uid, "approve")
        if ok:
            out.append(_item("job", j["id"], j["title"], j["updated_at"], tasks.get(j["task_id"]), agent_id=j["agent_id"],
                             agent_name=names.get(j["agent_id"], ""), proposal=bool(j["kind"])))
            if len(out) >= WAIT_MAX:
                break
    return out


def _chat_cards(s):
    rows = chat_approvals_of(s.c, s.uid, s.agent_id, WAIT_SCAN)
    tasks = s.tasks(m["task_id"] for m in rows)
    names = user_names(s.c, [m["agent_id"] for m in rows])
    out = []
    for m in rows:
        if s.hidden(m["task_id"], tasks):
            continue
        out.append(_item("approval", m["id"], (lv_jload(m["choices"]).get("approval") or {}).get("title") or m["body"][:200], m["created_at"],
                         tasks.get(m["task_id"]), source="chat", agent_id=m["agent_id"], agent_name=names.get(m["agent_id"], "")))
    return out[:WAIT_MAX]


def _comment_rows(s, cond, args=()):
    return s.c.execute(f"""SELECT k.id, k.user_id, k.choices, k.suggestion, k.created_at, t.id AS tid, t.title, t.list_id, l.name AS list_name, l.is_inbox
                           FROM comments k JOIN tasks t ON t.id=k.task_id JOIN lists l ON l.id=t.list_id
                           WHERE k.deleted_at IS NULL AND t.deleted_at IS NULL AND t.list_id IN ({s.ql}) AND {cond} AND {s.vis}
                           ORDER BY k.id DESC LIMIT {WAIT_SCAN}""", args).fetchall()


def _task_of(r):
    return {"id": r["tid"], "title": r["title"], "list_id": r["list_id"], "list_name": r["list_name"], "is_inbox": r["is_inbox"]}


def _comment_cards(s):
    c, uid, out = s.c, s.uid, []
    rows = _comment_rows(s, "k.choice IS NULL AND k.choices IS NOT NULL AND k.choices->>'approval' IS NOT NULL AND k.choices->>'withdrawn_at' IS NULL")
    names = user_names(c, [r["user_id"] for r in rows if r["user_id"]])
    for r in rows:
        ch = lv_jload(r["choices"])
        if lv_state(r, ch, None, 0) == "open" and lv_may_decide(c, r["tid"], uid, r["user_id"]):
            out.append(_item("approval", r["id"], (ch.get("approval") or {}).get("title"), r["created_at"], _task_of(r), source="comment",
                             agent_id=r["user_id"], agent_name=names.get(r["user_id"], "")))
            if len(out) >= WAIT_MAX:
                break
    return out


def _gates(s):
    c, uid, out, memo = s.c, s.uid, [], {}
    rows = _comment_rows(s, "k.suggestion LIKE ?", ('%"state": "open"%',))
    names = user_names(c, [r["user_id"] for r in rows if r["user_id"]])
    for r in rows:
        sug = json.loads(r["suggestion"])
        kind = sug.get("kind")
        if kind not in GATE_ALL or sug.get("state") != "open" or not r["user_id"]:
            continue
        key = (r["tid"], r["user_id"], kind == "merge_request")
        if key not in memo:
            t = c.execute("SELECT * FROM tasks WHERE id=?", (r["tid"],)).fetchone()
            au = c.execute("SELECT kind FROM users WHERE id=?", (r["user_id"],)).fetchone()
            memo[key] = bool(au) and au["kind"] == "agent" and is_approver(c, t, uid, agent=r["user_id"], assignee=kind == "merge_request")
        if memo[key]:
            refs = [sug[x] for x in ("source", "target") if sug.get(x)]
            out.append(_item("gate", r["id"], sug.get("summary") or " -> ".join(refs), r["created_at"], _task_of(r), gate=kind, agent_id=r["user_id"],
                             agent_name=names.get(r["user_id"], ""), branch=sug.get("source"), target=sug.get("target")))
            if len(out) >= WAIT_MAX:
                break
    return out


def _reviews(s):
    rows = s.c.execute(f"""SELECT t.id, t.title, t.list_id, t.review_at, l.name AS list_name, l.is_inbox FROM tasks t JOIN lists l ON l.id=t.list_id
                           WHERE t.reviewer_id=? AND t.review='pending' AND t.status=0 AND t.deleted_at IS NULL AND t.list_id IN ({s.ql}) AND {s.vis}
                           ORDER BY t.review_at DESC, t.id DESC LIMIT {WAIT_MAX}""", (s.uid,)).fetchall()
    return [_item("review", r["id"], r["title"], r["review_at"], r) for r in rows]


def _blocked(s):
    return [_item("blocked", r["id"], r["title"], r["waiting_at"], r, reason="waiting" if r["waiting_at"] else "blocked", open_blockers=r["open_blockers"])
            for r in brief_blocked(s.c, s.uid, s.ql, s.vis)[:WAIT_MAX]]


def _irreversible(s):
    c, uid = s.c, s.uid
    rows = c.execute(f"""SELECT t.*, l.name AS list_name, l.is_inbox FROM tasks t JOIN lists l ON l.id=t.list_id
                         WHERE l.irreversible_needs_yes=1 AND t.irreversible=1 AND t.irreversible_yes_at IS NULL AND t.deleted_at IS NULL
                         AND t.completed_at IS NULL AND t.list_id IN ({s.ql}) AND {s.vis} ORDER BY t.id DESC LIMIT {WAIT_SCAN}""").fetchall()
    out = [_item("irreversible", r["id"], r["title"], r["updated_at"], r, why=r["irreversible_reason"] or "") for r in rows
           if is_approver(c, r, uid, assignee=False)]  # as POST /api/tasks/<id>/irreversible-yes
    return out[:WAIT_MAX]


def _no_request_texts(c, items):
    """A list with the lock: what an agent wrote into its request stays out; the task's own title is the cipher the app opens."""
    locked = le2b_locked_lists(c, {x["list_id"] for x in items if x["list_id"]})
    for x in items:
        if x["list_id"] in locked and x["kind"] in ("approval", "gate", "job", "irreversible"):
            x["title"] = ""
            for k in ("branch", "target", "why"):
                x.pop(k, None)
    return items


def waiting_for(c, uid, *, agent_id=None):
    """-> {total, counts: {kind: n}, items: [...]} for person uid, the kinds in the order of WAIT_KINDS."""
    s = _Scope(c, uid, agent_id)
    by = {"job": _jobs(s), "approval": sorted(_chat_cards(s) + _comment_cards(s), key=lambda x: x["at"] or "", reverse=True)[:WAIT_MAX],
          "gate": _gates(s), "review": _reviews(s), "blocked": _blocked(s), "irreversible": _irreversible(s)}
    items = _no_request_texts(c, [x for k in WAIT_KINDS for x in by[k]])
    return {"total": len(items), "counts": {k: len(by[k]) for k in WAIT_KINDS}, "items": items}


@app.get("/api/inbox")
def inbox_get():
    """What waits for the signed-in person (the view "Waiting for me"); people only."""
    if is_agent(g.user):
        raise Denied(404)
    return jsonify(waiting_for(db(), me()))


@app.get("/api/v1/me/waiting")
@v1_view
def v1_me_waiting():
    """The same data. A personal token: its own (user_id left out or its own id), within the token's lists. An agent: user_id =
    a person it shares a list with; only the lists shared with it, in the chat only its own cards."""
    a = v1_args(("user_id",))
    c, uid = db(), me()
    raw = a.get("user_id")
    if is_agent(g.user):
        if not raw or not str(raw).isdigit():
            raise BadInput(tr("Invalid value: {0}", "user_id"))
        pid = int(raw)
        u = c.execute("SELECT * FROM users WHERE id=? AND disabled=0", (pid,)).fetchone()
        if not u or is_agent(u) or not agent_shares(c, uid, pid):
            raise Denied(404)
        return jsonify(waiting_for(c, pid, agent_id=uid))
    if raw and str(raw) != str(uid):
        raise Denied(404)
    return jsonify(waiting_for(c, uid))
