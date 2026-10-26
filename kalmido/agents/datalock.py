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
from ..core.dlock import DL_ALWAYS, DL_DEFAULT, DL_LISTS_MAX, DL_SWITCH, DL_TAG_LEN, DL_TAGS_MAX, dl_forget, dl_parse, dl_tag
from ..core.errors import BadInput, UnknownFields
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
