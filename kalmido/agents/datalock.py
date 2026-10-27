"""2.235.0 B (#2902): data an agent may never see - the section "Daten, die der Agent nie sieht" of its gear.

The owner of a personal agent (a person without an organisation is their own admin) or an instance admin (team agent) locks
areas (private e-mails, contracts, home, private trips; the journal with its mood, health, the budget and read later are
locked anyway), projects (list ids) and tags. Stored in agents.data_lock; the server enforces it in every read path of the
agent through ONE check (core/dlock.py, called by core/access.py). The agent learns WHAT is locked (GET /api/v1/agent
"data_lock", event data_lock_changed): the area keys, the list ids and the number of locked tags - never names it could not
see anyway."""
import json

from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, inbox_default
from ..core.access import list_role, vis_sql
from ..core.dlock import (
    DL_ALWAYS, DL_DEFAULT, DL_LISTS_MAX, DL_SWITCH, DL_TAG_LEN, DL_TAGS_MAX, dl_forget, dl_list_hidden, dl_of, dl_parse, dl_tag, dl_tasks_locked,
)
from ..core.errors import BadInput, Denied, UnknownFields
from ..accounts.session import me
from ..agents.core import agent_emit, agent_row
from ..agents.workstyle import ws_need_editor


def dl_get(a):
    """The effective lock of agent row a (defaults for an agent that never had one set)."""
    return dl_parse(a["data_lock"])


def dl_public(c, a):
    """What agent row a reads in GET /api/v1/agent "data_lock" (and the event data_lock_changed): the locked areas (keys),
    the fixed ones among them, the locked list ids and how many tags are locked (their names stay with the owner)."""
    d = dl_get(a)
    return {"areas": list(DL_ALWAYS) + [k for k in DL_SWITCH if d["areas"][k]], "always": list(DL_ALWAYS),
            "list_ids": d["lists"], "tags_count": len(d["tags"])}


def dl_clean(cur, b):
    """A partial change b ({areas: {key: bool}, lists: [ids], tags: [names]}) over the current lock cur -> the new lock."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid value: {0}", "data_lock"))
    unknown = set(b) - {"areas", "lists", "tags"}
    if unknown:
        raise UnknownFields(sorted(unknown))
    new = {"areas": dict(cur["areas"]), "lists": list(cur["lists"]), "tags": list(cur["tags"])}
    if "areas" in b:
        ar = b["areas"]
        if not isinstance(ar, dict):
            raise BadInput(tr("Invalid value: {0}", "areas"))
        for k, v in ar.items():
            if k in DL_ALWAYS and v is True:
                continue  # locked anyway
            if k in DL_ALWAYS:
                raise BadInput(tr("This area is never visible to agents"))
            if k not in DL_SWITCH or not isinstance(v, bool):
                raise BadInput(tr("Invalid value: {0}", "areas." + str(k)))
            new["areas"][k] = v
    if "lists" in b:
        ls = b["lists"]
        if not isinstance(ls, list) or len(ls) > DL_LISTS_MAX or \
                any(not isinstance(x, int) or isinstance(x, bool) or x <= 0 for x in ls):
            raise BadInput(tr("Invalid value: {0}", "lists"))
        new["lists"] = list(dict.fromkeys(ls))
    if "tags" in b:
        ts = b["tags"]
        if not isinstance(ts, list) or len(ts) > DL_TAGS_MAX or any(not isinstance(x, str) or not dl_tag(x) or len(dl_tag(x)) > DL_TAG_LEN for x in ts):
            raise BadInput(tr("Invalid value: {0}", "tags"))
        seen, out = set(), []
        for x in ts:
            if dl_tag(x).lower() not in seen:
                seen.add(dl_tag(x).lower())
                out.append(dl_tag(x))
        new["tags"] = out
    return new


def dl_set(c, a, b):
    """Validates and stores a partial change b for agent row a; event data_lock_changed when something changed. A project
    can only be added by someone who sees it (one already on the list stays)."""
    cur = dl_get(a)
    new = dl_clean(cur, b)
    for lid in set(new["lists"]) - set(cur["lists"]):
        if not list_role(c, lid, me()):
            raise BadInput(tr("Invalid value: {0}", "lists"))
    if new != cur or not a["data_lock"]:
        c.execute("UPDATE agents SET data_lock=? WHERE user_id=?", (json.dumps(new, ensure_ascii=False), a["user_id"]))
        dl_forget()
        agent_emit(c, a["user_id"], "data_lock_changed", {"data_lock": dl_public(c, agent_row(c, a["user_id"]))})
        print("agent", a["user_id"], "data lock", ",".join(k for k in ("areas", "lists", "tags") if new[k] != cur[k]) or "-",
              "by", g.user["username"], flush=True)
    return new


def _dl_view(c, a):
    """The answer of the gear's routes: the lock (projects with the names the editor sees), the fixed areas, the defaults and
    what can be added (the editor's projects and tags)."""
    d = dl_get(a)
    uid = me()
    rows = c.execute(f"SELECT id, name, is_inbox FROM lists l WHERE l.id IN {vis_sql()} ORDER BY lower(name), id LIMIT 1000",
                     (uid, uid)).fetchall()
    names = {r["id"]: tr("Basket") if r["is_inbox"] and inbox_default(r["name"]) else r["name"] for r in rows}
    tags = [r[0] for r in c.execute("SELECT DISTINCT tag FROM task_tags WHERE user_id=? ORDER BY tag LIMIT 500", (uid,))]
    tags += [r[0] for r in c.execute(f"SELECT DISTINCT name FROM list_tags WHERE list_id IN {vis_sql()} ORDER BY name LIMIT 500", (uid, uid))]
    return jsonify(data_lock={"areas": d["areas"], "lists": [{"id": x, "name": names.get(x)} for x in d["lists"]], "tags": d["tags"]},
                   always=list(DL_ALWAYS), defaults=DL_DEFAULT,
                   options={"lists": [{"id": k, "name": v} for k, v in names.items()],
                            "tags": sorted({t for t in tags if t}, key=str.lower)})


def dl_job_input(c, aid, kind, inp, tid=None, lid=None, strict=True):
    """2.235.0 B2 (#2902): a proposal job's input as agent aid may get it (job_request, GET /api/v1/agent/jobs/<id>): a person
    hands over their own view (basket, day plan, a task's subtasks), the agent's data lock still leaves its tasks and lists
    out. A locked task / list of the job itself -> 404. strict (a new request): nothing left -> BadInput like an empty input."""
    if not dl_of(c, aid) or not isinstance(inp, dict):
        return inp
    if (tid and dl_tasks_locked(c, aid, [tid])) or (lid and _dl_lists_locked(c, aid, [lid])):
        raise Denied(404)
    if kind == "triage":
        gone = dl_tasks_locked(c, aid, [x.get("task_id") for x in inp.get("items") or []])
        inp["items"] = [x for x in inp.get("items") or [] if x.get("task_id") not in gone]
        off = _dl_lists_locked(c, aid, [x.get("id") for x in inp.get("lists") or []])
        inp["lists"] = [x for x in inp.get("lists") or [] if x.get("id") not in off]
        if strict and not inp["items"]:
            raise BadInput(tr("The basket is empty"))
    elif kind == "dayplan":
        gone = dl_tasks_locked(c, aid, [x.get("task_id") for k in ("tasks", "fixed") for x in inp.get(k) or []])
        for k in ("tasks", "fixed"):
            inp[k] = [x for x in inp.get(k) or [] if x.get("task_id") not in gone]
        b = inp.get("builtin") or {}
        if b:
            b["plan"] = [x for x in b.get("plan") or [] if x.get("task_id") not in gone]
            b["nofit"] = [x for x in b.get("nofit") or [] if x not in gone]
        if strict and not inp["tasks"]:
            raise BadInput(tr("There are no open tasks to plan"))
    elif kind == "subtasks" and tid and isinstance(inp.get("task"), dict):
        rows = c.execute("SELECT id, title FROM tasks WHERE parent_id=? AND deleted_at IS NULL ORDER BY sort, id", (tid,)).fetchall()
        gone = dl_tasks_locked(c, aid, [r[0] for r in rows])
        inp["task"]["subtasks"] = [r[1] for r in rows if r[0] not in gone][:100]
    return inp


def _dl_lists_locked(c, aid, lids):
    ids = sorted({int(x) for x in lids if x})
    if not ids:
        return set()
    return {r[0] for r in c.execute(f"SELECT id, life, org_id FROM lists WHERE id IN ({','.join('?' * len(ids))})", ids)
            if dl_list_hidden(c, aid, r[0], r[1], r[2])}


@app.get("/api/agents/<int:aid>/data-lock")
def dl_route_get(aid):
    c = db()
    return _dl_view(c, ws_need_editor(c, aid))


@app.patch("/api/agents/<int:aid>/data-lock")
def dl_route_patch(aid):
    """{areas?: {key: bool}, lists?: [ids], tags?: [names]} -- changes only what is given (autosave)."""
    c = db()
    a = ws_need_editor(c, aid)
    dl_set(c, a, body())
    bump(c)
    c.commit()
    return _dl_view(c, agent_row(c, aid))
