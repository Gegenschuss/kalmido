"""2.70.0 C (#1359): contracts in view -- an agent reminds a person of a notice deadline, the person decides.

Once a day (the watchdog, notify/push.py) every open contract (tasks.fam kind contract, life/model.py: due = the last day to
cancel) whose last day to cancel is at most `lead` days away (the contract's own field, else CTR_LEAD days) goes as the
event contract_notice to every active agent that may see its list: shared with it (list_role: never a health list, the
agent's organisation, its token's list limit), inside agents.list_ids, agents.org_id not crossed. Once per contract, last
day to cancel and agent (table ctr_notices). The event carries what the contract costs, never a push or a title others see.

The agent answers with ONE sentence (POST /api/v1/agent/proposals {kind: notice, task_id, text}): a ready proposal of kind
notice for the person the contract belongs to (its creator, else the list's owner). Kalmido never phrases it itself. The
person gets News + push "Proposal ready" (switchable like every proposal) and a card: the contract, the sentence, the last
day to cancel, the cost. "Take it as a note" = a comment on the contract task as that person (history line "applied a
proposal by <agent>"), "Remind me" = the same plus a reminder 3 days before the last day to cancel (the task's reminders),
"Discard". One undo step. Nothing is ever cancelled, sent or deleted."""
import json
from datetime import date, timedelta

from flask import jsonify, request

from ..core.pg import insert_id
from ..core.i18n import lang, tr
from ..core.db import bump, db, iso, iso_ms, local_now, now_utc
from ..core.access import Denied, list_role, need_task, task_visible
from ..accounts.session import me
from ..core.errors import BadInput
from ..core.config import WATCHDOG_INTERVAL  # 2.149.0 G (#2517): pulled up from functions
from ..api.common import v1_err  # 2.149.0 G (#2517): pulled up from functions

CTR_KIND = "notice"
CTR_EVENT = "contract_notice"
CTR_LEAD = 30                 # days before the last day to cancel when the contract has no own lead
CTR_TEXT_MAX = 300            # the agent's sentence
CTR_DAY_MAX = 50              # notice proposals of one agent per 24 hours
CTR_REMIND_DAYS = 3           # "Remind me": this many days before the last day to cancel
CTR_KEEP_DAYS = 400           # sent markers are kept this long (a yearly contract comes back after a year)
CTR_EVERY_TICKS = 10          # the scan runs every 10th watchdog interval (5 min in production), not on every tick
_CTR_LAST = {"at": 0.0}
CTR_HINT = ("Write ONE friendly sentence for the person in their language (lang): when the notice period ends and what the "
            "contract costs a month or a year, so they can decide whether to cancel, renew or compare. No pressure, never say it "
            "was cancelled. Send it with POST /api/v1/agent/proposals {kind: notice, task_id, text} (MCP propose_contract_notice). "
            "You never cancel, send or change anything yourself.")


def _fam(t):
    try:
        f = json.loads(t["fam"] or "{}")
    except ValueError:
        return {}
    return f if isinstance(f, dict) else {}


def ctr_lead(f):
    """The days before the last day to cancel from which the agents hear of it (the contract's lead, else CTR_LEAD)."""
    lead = f.get("lead")
    return lead if isinstance(lead, int) and not isinstance(lead, bool) and lead > 0 else CTR_LEAD


def ctr_person(c, t):
    """Whose contract it is: the task's creator while they still see its list, else the list's owner (people only)."""
    for uid in (t["created_by"], c.execute("SELECT owner_id FROM lists WHERE id=?", (t["list_id"],)).fetchone()[0]):
        if not uid:
            continue
        u = c.execute("SELECT kind, disabled FROM users WHERE id=?", (uid,)).fetchone()
        if u and (u["kind"] or "user") == "user" and not u["disabled"] and list_role(c, t["list_id"], uid):
            return uid
    return None


def ctr_data(c, t, pid):
    """The event's / card's view of a contract (life/model.py contract_out) + the person and their language."""
    from ..life.model import contract_out
    from ..collab.comments import user_names
    d = contract_out({**dict(t), "fam": _fam(t)}, local_now().date())
    return {"task_id": d["task_id"], "list_id": d["list_id"], "name": d["name"], "provider": d["provider"], "cost": d["cost"],
            "per": d["per"], "monthly": d["monthly"], "yearly": d["yearly"], "notice": d["notice"], "notice_unit": d["notice_unit"],
            "due": d["due"], "ends": d["ends"], "renew_months": d["renew_months"], "days": d["days"],
            "user": {"id": pid, "name": user_names(c, [pid]).get(pid, "")}, "lang": lang(c, pid),
            "office": bool(_fam(t).get("office_agreement"))}  # 2.92.0 A (#1925): a business contract of the office (else Home & life)


def _agent_sees(c, a, t):
    """The agent may see the contract: its list is shared with it (list_role: never a health list, never outside the
    agent's organisation), inside its list limit, and the list belongs to its organisation (or to nobody's) when it has one."""
    from ..agents.safety import ids_parse
    lid, aid = t["list_id"], a["user_id"]
    if a["list_ids"] and lid not in ids_parse(a["list_ids"]):
        return False
    lo = c.execute("SELECT org_id, life FROM lists WHERE id=?", (lid,)).fetchone()
    if not lo or lo["life"] == "health" or (a["org_id"] and lo["org_id"] and lo["org_id"] != a["org_id"]):
        return False
    return bool(list_role(c, lid, aid)) and task_visible(c, t["id"], aid)


def _contracts(c):
    """Open contracts with a last day to cancel from today on (not archived lists, never health lists)."""
    today = local_now().date()
    rows = c.execute("""SELECT t.* FROM tasks t JOIN lists l ON l.id=t.list_id
                        WHERE t.status=0 AND t.deleted_at IS NULL AND t.due IS NOT NULL AND t.due>=? AND t.due<=?
                          AND t.fam ILIKE '%contract%' AND l.archived=0 AND l.life!='health'""",
                     (today.isoformat(), (today + timedelta(days=366)).isoformat())).fetchall()
    out = []
    for t in rows:
        f = _fam(t)
        if f.get("kind") == "contract" and date.fromisoformat(t["due"]) - timedelta(days=ctr_lead(f)) <= today:
            out.append(t)
    return out


def ctr_tick(c, now=None):
    """Watchdog: the event contract_notice for every contract in reach, once per contract, last day to cancel and agent.
    Runs at most every CTR_EVERY_TICKS watchdog intervals (the deadlines are whole days)."""
    import time
    from ..agents.core import agent_active, agent_emit, agent_ids, agent_row
    from ..life.model import feat_on
    from ..office.model import office_on
    if time.monotonic() - _CTR_LAST["at"] < CTR_EVERY_TICKS * WATCHDOG_INTERVAL:
        return
    _CTR_LAST["at"] = time.monotonic()
    due = _contracts(c)
    if not due:
        return
    agents = [a for a in (agent_row(c, x) for x in sorted(agent_ids(c))) if agent_active(a)]
    for t in due:
        pid = None
        for a in agents:
            if c.execute("SELECT 1 FROM ctr_notices WHERE task_id=? AND due=? AND agent_id=?", (t["id"], t["due"], a["user_id"])).fetchone():
                continue
            if not _agent_sees(c, a, t):
                continue
            pid = pid or ctr_person(c, t)
            # 2.92.0 A (#1925): a business contract's deadline task (fam office_agreement) needs the office, not "At home"
            if not pid or not (feat_on(c, pid, "contracts") or (_fam(t).get("office_agreement") and office_on(c, pid))):
                break  # nobody's contract (any more) / the module is off: no agent hears of it
            if agent_emit(c, a["user_id"], CTR_EVENT, {**ctr_data(c, t, pid), "hint": CTR_HINT}, actor=None) is None:
                continue  # not delivered (filtered): no marker, so no proposal for an event the agent never got
            c.execute("INSERT INTO ctr_notices(task_id,due,agent_id,user_id,list_id,sent_at) VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                      (t["id"], t["due"], a["user_id"], pid, t["list_id"], iso(now_utc())))
            c.commit()


def ctr_expire(c):
    """Open notice proposals whose last day to cancel passed are discarded (the agent is not told); old markers go."""
    ts, today = iso(now_utc()), local_now().date().isoformat()
    c.execute("""UPDATE agent_jobs SET prop_state='discarded', state='stopped', updated_at=? WHERE kind=? AND prop_state='ready'
                 AND (CASE WHEN kind=? THEN COALESCE(input::jsonb->>'due', '') END)<?""", (ts, CTR_KIND, CTR_KIND, today))
    # (the CASE: only notice rows are read as JSON, whatever order the planner picks)
    c.execute("DELETE FROM ctr_notices WHERE sent_at<?", (iso(now_utc() - timedelta(days=CTR_KEEP_DAYS)),))


# ---------------------------------------------------------------- the agent proposes (POST /api/v1/agent/proposals kind notice)
def _need_contract(c, aid, tid):
    """The open contract task tid the agent may see and has been told about for its current last day to cancel."""
    from ..agents.core import agent_row
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    a = agent_row(c, aid)
    if not t or not a or t["deleted_at"] or _fam(t).get("kind") != "contract" or not _agent_sees(c, a, t):
        raise Denied(404)
    if t["status"] != 0 or not t["due"]:
        raise Denied(409, tr("This contract has no open notice deadline"))
    if not c.execute("SELECT 1 FROM ctr_notices WHERE task_id=? AND due=? AND agent_id=?", (tid, t["due"], aid)).fetchone():
        raise Denied(409, tr("You can only propose a reminder for a contract_notice you received"))
    return t


def ctr_validate(b, inp):
    """prop_validate for kind notice: {task_id?, text, summary?} -> {task_id, text}; the task is the job's."""
    from ..agents.proposals import _p_keys, _p_int, _p_str
    _p_keys(b, "", ("kind", "summary", "task_id", "text"))
    tid = inp.get("task_id")
    if b.get("task_id") is not None and _p_int(b.get("task_id"), "task_id") != tid:
        raise BadInput(tr("Invalid value: {0}", "task_id"))
    return {"task_id": tid, "text": _p_str(b.get("text"), "text", CTR_TEXT_MAX, True)}


def ctr_agent_proposal(aid, b):
    """{kind: notice, task_id, text} -> a ready proposal (kind notice) for the person whose contract it is. An open one of this
    agent for the same contract is replaced. Nothing changes until the person takes it."""
    from ..agents.core import agent_row, job_dict, JOB_TITLE_MAX
    from ..agents.proposals import _p_keys, _p_int, prop_ready_notify, prop_validate, PROP_MAX_BYTES
    from ..agents.usage import usage_block
    _p_keys(b, "", ("kind", "task_id", "text", "summary"))
    if len(request.data or b"") > PROP_MAX_BYTES:
        return v1_err(413, tr("The proposal is too large (at most {0} KB)", PROP_MAX_BYTES // 1024))
    tid = _p_int(b.get("task_id"), "task_id")
    c = db()
    t = _need_contract(c, aid, tid)
    pid = ctr_person(c, t)
    if not pid:
        raise Denied(404)
    a = agent_row(c, aid)
    if usage_block(c, aid):
        return v1_err(409, tr("{0} reached its usage limit", a["display_name"] or a["username"]))
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND kind=? AND created_at>=?",
                 (aid, CTR_KIND, iso(now_utc() - timedelta(days=1)))).fetchone()[0] >= CTR_DAY_MAX:
        return v1_err(429, tr("At most {0} contract reminders per day", CTR_DAY_MAX))
    d = ctr_data(c, t, pid)
    inp = {k: d[k] for k in ("task_id", "list_id", "name", "provider", "cost", "per", "monthly", "yearly", "notice", "notice_unit",
                             "due", "ends", "renew_months")} | {"user_id": pid}
    p = prop_validate(CTR_KIND, {k: v for k, v in b.items() if k != "task_id"}, inp)
    ts = iso(now_utc())
    for r in c.execute("SELECT id FROM agent_jobs WHERE agent_id=? AND kind=? AND task_id=? AND prop_state='ready'",
                       (aid, CTR_KIND, tid)).fetchall():  # one open card per agent and contract: the new one replaces it
        c.execute("UPDATE agent_jobs SET prop_state='discarded', state='stopped', updated_at=? WHERE id=?", (ts, r[0]))
        c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND kind='proposal' AND read_at IS NULL AND data->>'job' = ?",
                  (ts, pid, str(r[0])))
    title = tr("Notice deadline: {0}", d["name"], lg=d["lang"])  # never the cost: the title shows in pushes and lists
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id,proposal)
                       VALUES(?,?,?,?,'waiting','',?,?,?,?,'ready',?,?)""",
                    (aid, tid, pid, title[:JOB_TITLE_MAX], ts, ts, CTR_KIND, json.dumps(inp, ensure_ascii=False), t["list_id"],
                     json.dumps(p, ensure_ascii=False)))
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    prop_ready_notify(c, j)
    bump(c)
    c.commit()
    print("contract notice proposal", jid, "agent", aid, "task", tid, flush=True)
    return jsonify({**job_dict(c, j), "proposal": p, "input": inp}), 201


# ---------------------------------------------------------------- the hooks of agents/proposals.py
def ctr_view_extra(c, j):
    """For the card: the contract as it is now (cost, last day to cancel, end of the term) and whether "Remind me" applies."""
    if j["user_id"] != me():
        return {}
    t = c.execute("SELECT * FROM tasks WHERE id=?", (j["task_id"],)).fetchone()
    if not t or t["deleted_at"] or not list_role(c, t["list_id"]):
        return {"contract": None}
    d = ctr_data(c, t, me())
    rem = [x for x in (t["reminders"] or "").split(",") if x.strip()]
    d["can_remind"] = bool(t["status"] == 0 and d["days"] is not None and d["days"] >= CTR_REMIND_DAYS
                           and str(CTR_REMIND_DAYS * 1440) not in rem)
    return {"contract": d}


def _rem_with(rem):
    xs = [x for x in (rem or "").split(",") if x.strip()]
    v = str(CTR_REMIND_DAYS * 1440)
    return ",".join(sorted(set(xs + [v]), key=lambda x: -int(x))) if v not in xs else rem


def ctr_run(c, j, sel, ed, extra, rec):
    """Take it (as the person): the sentence becomes a comment on the contract task; with remind also a reminder
    CTR_REMIND_DAYS days before the last day to cancel. rec = the undo record. Written straight into comments on purpose:
    a private note of the person, no comment push / news / comment event to the list's members and agents."""
    from ..tasks.lifecycle import apply_update
    from ..tasks.validation import log_act
    p, inp, uid = json.loads(j["proposal"]), json.loads(j["input"] or "{}"), me()
    tid = p["task_id"]
    need_task(c, tid, write=False, full=True)  # view-only members may comment, as everywhere
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if t["deleted_at"]:
        raise Denied(409, tr("The task is in the trash"))
    cid = insert_id(c, "INSERT INTO comments(task_id,user_id,body,mentions,created_at) VALUES(?,?,?,?,?)",
                    (tid, uid, p["text"], "", iso_ms(now_utc())))
    c.execute("INSERT INTO task_seen(user_id,task_id,seen_id) VALUES(?,?,?) "
              "ON CONFLICT(user_id,task_id) DO UPDATE SET seen_id=GREATEST(task_seen.seen_id, excluded.seen_id)", (uid, tid, cid))
    log_act(c, tid, "proposal", {"agent": j["agent_id"]}, uid=uid)
    rec.update(task_id=tid, comment_id=cid, remind=False)
    if extra.get("remind") is True and t["status"] == 0 and t["due"] == inp.get("due") \
            and (date.fromisoformat(t["due"]) - local_now().date()).days >= CTR_REMIND_DAYS:
        need_task(c, tid)  # a reminder is a change of the task: write access
        new = _rem_with(t["reminders"])
        if new != (t["reminders"] or ""):
            msg = apply_update(c, tid, {"reminders": new})
            if msg:
                raise BadInput(msg)
            rec.update(remind=True, rem_before=t["reminders"] or "", rem_after=new)
    return rec


def ctr_undo(c, j, rec, back=True):
    """Undo: the comment goes (unless someone edited it), the reminder goes back (unless the reminders changed since).
    Redo (back=False): both come again."""
    from ..tasks.lifecycle import apply_update
    p, n, skipped = json.loads(j["proposal"]), 0, []
    tid, cid = rec.get("task_id"), rec.get("comment_id")
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t:
        return 0, [p.get("text", "")[:40]]
    need_task(c, tid, write=False, full=True)
    r = c.execute("SELECT * FROM comments WHERE id=? AND task_id=? AND user_id=?", (cid, tid, me())).fetchone()
    if r and back and not r["deleted_at"] and not r["edited_at"]:
        n += c.execute("UPDATE comments SET body='', deleted_at=? WHERE id=?", (iso(now_utc()), cid)).rowcount
    elif r and not back and r["deleted_at"]:
        n += c.execute("UPDATE comments SET body=?, deleted_at=NULL WHERE id=?", (p["text"], cid)).rowcount
    elif r is None or (back and r["edited_at"]):
        skipped.append((t["title"] or "")[:40])
    if rec.get("remind"):
        want, to = (rec.get("rem_after"), rec.get("rem_before")) if back else (rec.get("rem_before"), rec.get("rem_after"))
        if (t["reminders"] or "") == (want or ""):
            need_task(c, tid)
            if not apply_update(c, tid, {"reminders": to or ""}):
                n = max(n, 1)
        else:
            skipped.append((t["title"] or "")[:40])
    bump(c)
    return n, sorted(set(skipped))


def ctr_result(rec):
    return {"task_id": rec.get("task_id"), "comment_id": rec.get("comment_id"), "reminder": bool(rec.get("remind"))}


# ---------------------------------------------------------------- OpenAPI (the body variant of POST /agent/proposals)
CTR_BODY = {"type": "object", "required": ["kind", "task_id", "text"], "additionalProperties": False, "properties": {
    "kind": {"type": "string", "enum": [CTR_KIND]}, "task_id": {"type": "integer", "description": "The contract of a contract_notice you got"},
    "text": {"type": "string", "maxLength": CTR_TEXT_MAX, "description": "ONE sentence: when the notice period ends, what it costs"},
    "summary": {"type": "string"}}}


def ctr_spec(paths):
    """2.70.0 C (#1359): POST /agent/proposals also takes {kind: notice, task_id, text} (agents/usage.py has the route's spec)."""
    o = (paths.get("/agent/proposals") or {}).get("post")
    if not o:
        return
    b = o.setdefault("requestBody", {}).setdefault("content", {}).setdefault("application/json", {}).setdefault("schema", {})
    if "oneOf" in b:
        b["oneOf"].append(CTR_BODY)
    o["description"] = ((o.get("description") or "") + (
        " 2.70.0 (#1359): or {kind: notice, task_id, text} -- after the event contract_notice ONE sentence for the person whose "
        f"contract it is (at most {CTR_TEXT_MAX} characters: when the notice period ends, what it costs); a ready proposal they take as a "
        "note on the contract (optionally with a reminder 3 days before) or discard. Only for a contract_notice you got for its current "
        f"deadline (else 409), contracts you cannot see 404; a new one replaces your open one; at most {CTR_DAY_MAX} a day. "
        "Never cancel anything.")).strip()
