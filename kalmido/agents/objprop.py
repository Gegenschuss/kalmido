"""2.623.0 (#4718): an agent's change of a core object as a PROPOSAL a person accepts (proposal kind 'obj_patch').

Stage 1 of the shared core lets an agent write directly with the version it read (core/writes.py obj_write, PATCH
/api/v1/agent/objects/<kind>/<id>). Instead it may propose the change:

  POST /api/v1/agent/objects/<kind>/<id>/proposals   {values: {<field>: <value>}, expect_updated_at, summary?, user_id?}

- the agent proposes only for an object it can see (core/objects.py obj_need 'view' as the agent: its workspace, the data
  lock, what the area hides from agents; another workspace's or an unshared object = 404) and with the kind's READ scope:
  a proposal changes nothing, the person writes. A view share is enough to propose; a token that may only read is refused
  like for every proposal that reaches a person (api/scopes.py AGENT_RO_REFUSED, 2.190.0 #2496).
- the values are checked like a write (the kind's cleaners: unknown field / bad value 400), expect_updated_at is required
  (400 version_required) and must still be the object's version (409 with the current state); nothing would change = 400.
- the card goes to user_id (a person, never an agent, with write rights on the object) or to the object's owner; nobody
  else sees, accepts or discards it (agents/proposals.py need_prop). 2.641.0 (#4974): user_id counts only for a person the
  agent sees anyway (its owner, the members of its organisation) who may change the object; any other id gets the answer
  of a proposal without user_id (the owner's card), so trying ids tells nothing about who may write. At most
  OBJP_PERSON_DAY_MAX a day for one person (429), besides OBJP_DAY_MAX for the agent.
- accepting = obj_write AS THAT PERSON with exactly the version the agent saw: their write right is checked then (403 / 404
  without), a change by anybody since = 409 with a plain message on the card (nothing written). Undo / redo of the proposal
  write the values back with the version the last step left (changed since = skipped).
- discarding as for every kind (agents/proposals.py proposal_discard); the agent gets the event job (approve / reject).
"""
import json
from datetime import timedelta

from flask import jsonify, request

from ..api.common import v1_args, v1_err, v1_json, v1_view
from ..core.access import Denied
from ..core.config import app
from ..core.conflict import Conflict, VersionRequired, ccf_check
from ..core.pg import ts_canon  # 2.760.0 (#5311): "stale" compares the version canonically, as ccf_check
from ..core.db import bump, db, insert_id, iso, now_utc
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..core.objects import obj_need, obj_public, obj_reg, obj_role, obj_title
from ..core.objweb import _agent_kind
from ..core.writes import NEED_VERSION, UNDO_CONFLICT, _clean, _same, obj_write
from ..accounts.session import me
from ..agents.core import JOB_TITLE_MAX, agent_ids, agent_row, job_dict

OBJP_DAY_MAX = 100  # obj_patch proposals one agent may make per day
OBJP_PERSON_DAY_MAX = 20  # 2.641.0 (#4974): ... of them for one person (the cards and pushes one person gets from one agent)
OBJP_STALE = N_("Changed by someone else since the proposal: open the object, check it and ask the agent again")
OBJP_WHO = N_("Only a person who may change it can accept the proposal (user_id)")
OBJP_NOTHING = N_("Nothing would change")


def _plain(v):
    """A JSON-safe copy (dates, decimals as text) for the stored proposal / undo record."""
    return json.loads(json.dumps(v, default=str))


def _objp_people(c, aid):
    """2.641.0 (#4974): the persons agent aid may name as user_id: its owner and the active persons of its organisation."""
    a = agent_row(c, aid)
    if not a:
        return set()
    ids = {a["owner_id"]} if a["owner_id"] else set()
    if a["org_id"]:
        ids |= {r[0] for r in c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id "
                                        "WHERE m.org_id=? AND u.kind<>'agent' AND NOT u.disabled", (a["org_id"],))}
    return ids


def _person(c, aid, kind, rid, row, uid_arg):
    """Whose card: user_id (a person the agent sees, with write rights on the object) or the object's owner (needs them too).
    2.641.0 (#4974): an id the agent may not name or without the right gets the owner's card, like no user_id."""
    pid = row["owner_id"]
    if uid_arg not in (None, ""):
        if isinstance(uid_arg, bool) or not isinstance(uid_arg, int):
            raise BadInput(tr("Invalid value: {0}", "user_id"))  # the form only: says nothing about any person
        if uid_arg in _objp_people(c, aid) and obj_role(c, uid_arg, kind, rid) in ("edit", "manage"):
            pid = uid_arg
    if not pid or pid in agent_ids(c) or obj_role(c, pid, kind, rid) not in ("edit", "manage"):
        raise BadInput(tr(OBJP_WHO))
    return pid


@app.post("/api/v1/agent/objects/<kind>/<int:rid>/proposals")
@v1_view
def v1_obj_propose(kind, rid):
    """{values, expect_updated_at, summary?, user_id?} -> a ready proposal (kind obj_patch) for the person (module docstring)."""
    from ..agents.proposals import PROP_MAX_BYTES, PROP_SUMMARY_MAX, _p_keys, _p_str, prop_ready_notify
    from ..agents.usage import usage_block
    v1_args(())
    aid = _agent_kind(kind)  # an agent's token with the kind's read scope (a read-only token: api/scopes.py AGENT_RO_REFUSED)
    if len(request.data or b"") > PROP_MAX_BYTES:
        return v1_err(413, tr("The proposal is too large (at most {0} KB)", PROP_MAX_BYTES // 1024))
    b = _p_keys(v1_json(), "", ("values", "expect_updated_at", "summary", "user_id"))
    c = db()
    reg = obj_reg(kind)
    row, _role = obj_need(c, aid, kind, rid, "view")  # only what the agent sees (404 otherwise)
    exp = b.get("expect_updated_at")
    if not exp or not isinstance(exp, str):
        raise VersionRequired(("expect_updated_at",), tr(NEED_VERSION))
    ccf_check({"expect_updated_at": exp}, row["updated_at"], "current", lambda: obj_public(c, aid, kind, row, _role))
    vals = b.get("values")
    if not isinstance(vals, dict) or not vals:
        raise BadInput(tr("Invalid value: {0}", "values"))
    if "expect_updated_at" in vals:
        raise BadInput(tr("Invalid value: {0}", "values"))
    clean = _clean(c, reg, vals, row)  # unknown field / bad value: 400
    changed = {k: v for k, v in clean.items() if not _same(row[k], v)}
    if not changed:
        raise BadInput(tr(OBJP_NOTHING))
    summary = _p_str(b.get("summary"), "summary", PROP_SUMMARY_MAX, line=False)
    pid = _person(c, aid, kind, rid, row, b.get("user_id"))
    if usage_block(c, aid):
        return v1_err(409, tr("You reached your usage limit"))
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND kind='obj_patch' AND created_at>=?",
                 (aid, iso(now_utc() - timedelta(days=1)))).fetchone()[0] >= OBJP_DAY_MAX:
        return v1_err(429, tr("At most {0} change proposals per day", OBJP_DAY_MAX))
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND user_id=? AND kind='obj_patch' AND created_at>=?",
                 (aid, pid, iso(now_utc() - timedelta(days=1)))).fetchone()[0] >= OBJP_PERSON_DAY_MAX:  # 2.641.0 (#4974)
        return v1_err(429, tr("At most {0} change proposals per day for one person", OBJP_PERSON_DAY_MAX))
    keys = sorted(changed)
    p = {"kind": "obj_patch", "summary": summary, "object_kind": kind, "object_id": int(rid), "version": str(row["updated_at"]),
         "values": _plain({k: vals[k] for k in keys}), "before": _plain({k: row[k] for k in keys}), "after": _plain({k: changed[k] for k in keys})}
    inp = {"object_kind": kind, "object_id": int(rid), "user_id": pid}
    title = tr("Change {0}: {1}", tr(reg["label"]), obj_title(c, kind, rid) or "#" + str(int(rid)))
    ts = iso(now_utc())
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id,proposal)
                       VALUES(?,NULL,?,?,'waiting','',?,?,'obj_patch',?,'ready',NULL,?)""",
                    (aid, pid, title[:JOB_TITLE_MAX], ts, ts, json.dumps(inp, ensure_ascii=False), json.dumps(p, ensure_ascii=False)))
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    prop_ready_notify(c, j)
    bump(c)
    c.commit()
    return jsonify({**job_dict(c, j), "proposal": p}), 201


def objp_view_extra(c, j):
    """For the card (the person who decides): the object as it is now, old -> new per field, whether it changed since."""
    p = json.loads(j["proposal"] or "null") or {}
    kind, rid = p.get("object_kind"), p.get("object_id")
    try:
        row, role = obj_need(c, me(), kind, rid, "view")
    except Denied:
        return {"object": None}
    reg = obj_reg(kind)
    cur = _plain({k: row[k] for k in p.get("after") or {} if k in row.keys()})
    rows = [{"field": k, "before": (p.get("before") or {}).get(k), "now": cur.get(k), "after": v} for k, v in (p.get("after") or {}).items()]
    return {"object": {"kind": kind, "id": rid, "label": tr(reg["label"]), "title": obj_title(c, kind, rid), "open": reg["open_url"](rid),
                       "can_write": role in ("edit", "manage"), "stale": ts_canon(row["updated_at"]) != ts_canon(p.get("version"))},
            "changes": rows}


def objp_run(c, j, rec):
    """Accepting: obj_write as the person with exactly the agent's version (their rights; 409 when changed since)."""
    p = json.loads(j["proposal"])
    kind, rid = p["object_kind"], int(p["object_id"])
    try:
        row, changed = obj_write(c, me(), kind, rid, dict(p["values"]), expect=p["version"])
    except Conflict:
        raise Denied(409, tr(OBJP_STALE)) from None
    rec.update(object_kind=kind, object_id=rid, changed=sorted(changed), version=str(row["updated_at"]),
               before=_plain({k: a for k, (a, _) in changed.items()}), after=_plain({k: z for k, (_, z) in changed.items()}),
               values=p["values"])
    return rec


def objp_result(rec):
    return {"changed": len(rec.get("changed") or []), "fields": rec.get("changed") or [], "object_id": rec.get("object_id")}


def objp_undo(c, j, rec, back=True):
    """Undo (back) / redo: the values before / the proposal's values, with the version the last step left -> (n, []).
    Review C (2.623): changed since by anybody = Denied 409 (nothing written, the caller rolls back), so the card keeps its
    state (applied / undone) instead of claiming a step that did not happen."""
    kind, rid = rec.get("object_kind"), rec.get("object_id")
    if not kind or not rid or not rec.get("changed"):
        return 0, []
    body = _raw(c, kind, rec["before"]) if back else dict(rec.get("values") or {})
    try:
        row, changed = obj_write(c, me(), kind, rid, body, expect=rec.get("version"))
    except Conflict:
        raise Denied(409, tr(UNDO_CONFLICT) if back else tr("Nothing to redo")) from None
    rec["version"] = str(row["updated_at"])
    return (1 if changed else 0), []


def _raw(c, kind, before):
    """The stored values before as the kind's cleaners take them again (a flag column 0 / 1 back to a boolean)."""
    reg = obj_reg(kind)
    out = {}
    for k, v in (before or {}).items():
        if k not in reg["fields"]:
            continue
        out[k] = v
        if v in (0, 1) and not isinstance(v, bool):
            try:
                reg["fields"][k](c, v, None)
            except BadInput:
                out[k] = bool(v)
    return out
