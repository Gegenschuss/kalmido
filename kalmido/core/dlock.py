"""2.235.0 B (#2902): THE check "data an agent may never see" - the data lock of an agent (set in its gear, agents/datalock.py).

One place for every read path of an agent; core/access.py calls it at its central points:
 - _list_role: a locked list has no role for the agent (404 everywhere: lists, tasks, comments, files, calendar, writes),
   also when someone else's request asks for the agent (events: agent_emit -> acx_task_ok / list_role)
 - _req_filters_sql: the agent's own list scope (vis_sql / wr_sql / acx_lists_sql of its requests)
 - tvis / task_visible: single locked tasks (e-mails in a private space, tasks with a locked tag) and all their subtasks
The lock only ever narrows what an agent sees: the tenant boundary and the fixed rules (health, budget, read later, the
journal with its mood: never an agent's since 2.22.0 / 2.72.0 / 2.172.1) stay as they are and cannot be opened here.

Stored in agents.data_lock: JSON {areas: {key: bool}, lists: [list ids], tags: [names]}; '' = the defaults (DL_DEFAULT)."""
import json

from flask import g, has_request_context, request

DL_ALWAYS = ("journal", "mood", "health", "budget", "reading")  # fixed (scope "private" / list rules), shown as locked
DL_LIST_AREAS = ("contracts", "home", "travel")  # the private lists of Home & life (lists.life, no organisation)
DL_SWITCH = ("mail",) + DL_LIST_AREAS
DL_AREAS = DL_ALWAYS + DL_SWITCH
DL_DEFAULT = {"mail": True, "contracts": False, "home": False, "travel": False}  # private e-mails locked for every agent
DL_LISTS_MAX, DL_TAGS_MAX, DL_TAG_LEN = 200, 50, 50
DL_INLINE_MAX = 500  # 2.235.0 B2 (#2902): locked task ids written inline into a query, more = one array constant


def dl_tag(t):
    """A tag name as stored and compared (like tasks.set_tags: no '#', trimmed), '' when empty."""
    return str(t or "").strip().lstrip("#").strip()


def dl_parse(raw):
    """The effective lock of a stored value (invalid parts dropped): {areas: {key: bool}, lists: [ids], tags: [names]}."""
    try:
        d = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        d = {}
    d = d if isinstance(d, dict) else {}
    ar = d.get("areas") if isinstance(d.get("areas"), dict) else {}
    areas = {k: (ar[k] if isinstance(ar.get(k), bool) else v) for k, v in DL_DEFAULT.items()}
    lists = [int(x) for x in d.get("lists") or [] if isinstance(x, int) and not isinstance(x, bool) and x > 0][:DL_LISTS_MAX]
    tags = [dl_tag(x) for x in d.get("tags") or [] if isinstance(x, str) and dl_tag(x)][:DL_TAGS_MAX]
    return {"areas": areas, "lists": lists, "tags": tags}


def _dl_eff(raw):
    d = dl_parse(raw)
    d["_lids"] = frozenset(d["lists"])
    d["_lareas"] = tuple(k for k in DL_LIST_AREAS if d["areas"][k])
    d["_mail"] = d["areas"]["mail"]
    d["_tags"] = tuple(sorted({t.lower() for t in d["tags"]}))
    return d


def dl_forget():
    """Drops the request caches (after the lock of an agent changed)."""
    if has_request_context():
        g.pop("_dl", None)
        g.pop("_dl_t", None)


def dl_of(c, uid):
    """The effective lock of account uid when it is an agent (see _dl_eff), else None. An agent whose settings row cannot be
    read in this context gets the defaults (never less locked). Cached per request."""
    if not uid:
        return None
    cache = g.setdefault("_dl", {}) if has_request_context() else None
    if cache is not None and uid in cache:
        return cache[uid]
    r = c.execute("SELECT u.kind, a.data_lock FROM users u LEFT JOIN agents a ON a.user_id=u.id WHERE u.id=?", (int(uid),)).fetchone()
    out = _dl_eff(r[1]) if r and r[0] == "agent" else None
    if cache is not None:
        cache[uid] = out
    return out


def dl_list_hidden(c, uid, lid, life, org_id):
    """THE list check: is list lid (its lists.life / org_id) locked for account uid? False for people."""
    d = dl_of(c, uid)
    if not d or not lid:
        return False
    return int(lid) in d["_lids"] or (not org_id and (life or "") in d["_lareas"])


def dl_list_locked(c, uid, lid):
    """dl_list_hidden by the list id alone (reads the list row)."""
    if not dl_of(c, uid) or not lid:
        return False
    r = c.execute("SELECT life, org_id FROM lists WHERE id=?", (int(lid),)).fetchone()
    return bool(r) and dl_list_hidden(c, uid, lid, r[0], r[1])


def dl_lists_sql(c, uid, a="l"):
    """SQL conditions (no ? params, each starting with AND) on the lists alias a that leave out the lists locked for agent
    uid; "" for people and agents without a list lock."""
    d = dl_of(c, uid)
    if not d:
        return ""
    out = f" AND {a}.id NOT IN ({','.join(str(x) for x in sorted(d['_lids']))})" if d["_lids"] else ""
    if d["_lareas"]:
        out += f" AND NOT (COALESCE({a}.life, '') IN ({','.join(repr(x) for x in d['_lareas'])}) AND {a}.org_id IS NULL)"
    return out


def dl_task_ids(c, uid):
    """frozenset of the task ids locked for agent uid inside the lists it may see at all: e-mails in a private space
    (tasks.tt_id 'mail:...', area "mail") and tasks with a locked tag (its personal tags or a list tag), with all their
    subtasks. Empty for people. Cached while a GET runs (a write request asks again: a tag set in it counts at once)."""
    d = dl_of(c, uid)
    if not d or not (d["_mail"] or d["_tags"]):
        return frozenset()
    cache = g.setdefault("_dl_t", {}) if has_request_context() and request.method in ("GET", "HEAD") else None
    if cache is not None and uid in cache:
        return cache[uid]
    from .access import acx_lists_sql
    # 2.235.0 B2 (#2902): one base query per kind (the mail part can use the partial index tasks_mail_list), scoped once
    base, args = [], [int(uid), int(uid)]
    if d["_mail"]:
        base.append("SELECT t.id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.tt_id LIKE 'mail:%' AND l.org_id IS NULL"
                    " AND t.list_id IN (SELECT id FROM s)")
    if d["_tags"]:
        q = ",".join("?" * len(d["_tags"]))
        base.append(f"SELECT x.task_id FROM task_tags x JOIN tasks t ON t.id=x.task_id WHERE lower(x.tag) IN ({q}) AND t.list_id IN (SELECT id FROM s)")
        base.append(f"SELECT y.task_id FROM task_list_tags y JOIN list_tags z ON z.id=y.tag_id JOIN tasks t ON t.id=y.task_id"
                    f" WHERE lower(z.name) IN ({q}) AND t.list_id IN (SELECT id FROM s)")
        args += list(d["_tags"]) * 2
    rows = c.execute(f"""WITH RECURSIVE s(id) AS {acx_lists_sql(req=False)}, b(id) AS ({' UNION '.join(base)}),
                           r(id) AS (SELECT id FROM b UNION SELECT t.id FROM tasks t JOIN r ON t.parent_id=r.id)
                         SELECT id FROM r""", args).fetchall()
    out = frozenset(r[0] for r in rows)
    if cache is not None:
        cache[uid] = out
    return out


def dl_task_sql(c, uid, a=""):
    """SQL condition (no ? params, starting with AND) on the tasks alias a ("t." / "") that leaves out the tasks locked for
    agent uid; "" when none is."""
    ids = dl_task_ids(c, uid)
    if len(ids) > DL_INLINE_MAX:  # 2.235.0 B2 (#2902): many ids (a basket full of e-mails) = one array constant, not thousands
        return f" AND NOT ({a}id = ANY(CAST('{{{','.join(str(int(x)) for x in sorted(ids))}}}' AS BIGINT[])))"
    return f" AND {a}id NOT IN ({','.join(str(x) for x in sorted(ids))})" if ids else ""


def dl_task_hidden(c, tid, uid):
    """THE task check: is task tid locked for account uid (by itself or a parent)? 2.235.0 B2 (#2902): a GET asks the cached
    set (many checks in one read); a write or a run without a request (loops: cleanup, batch, the burst guard, events) asks
    for this one task and its parents only - always current, no query over all lists per task."""
    if not tid or not dl_of(c, uid):
        return False
    if has_request_context() and request.method in ("GET", "HEAD"):
        return int(tid) in dl_task_ids(c, uid)
    return int(tid) in dl_tasks_locked(c, uid, [tid])


def dl_tasks_locked(c, uid, tids):
    """2.235.0 B2 (#2902): the set of the task ids among tids that agent uid's data lock covers (locked list or area, e-mail in
    a private space, locked tag; by the task itself or a parent), whether or not the agent is in their lists: for the data a
    person hands an agent (proposal job inputs). One query for all ids; empty for people."""
    d = dl_of(c, uid)
    ids = sorted({int(x) for x in tids or () if x})
    if not d or not ids:
        return set()
    cond, args = [], []
    if d["_lids"]:
        cond.append(f"t.list_id IN ({','.join(str(x) for x in sorted(d['_lids']))})")
    if d["_lareas"]:
        cond.append(f"(COALESCE(l.life, '') IN ({','.join(repr(x) for x in d['_lareas'])}) AND l.org_id IS NULL)")
    if d["_mail"]:
        cond.append("(t.tt_id LIKE 'mail:%' AND l.org_id IS NULL)")
    if d["_tags"]:
        q = ",".join("?" * len(d["_tags"]))
        cond.append(f"EXISTS (SELECT 1 FROM task_tags x WHERE x.task_id=t.id AND lower(x.tag) IN ({q}))")
        cond.append(f"EXISTS (SELECT 1 FROM task_list_tags y JOIN list_tags z ON z.id=y.tag_id WHERE y.task_id=t.id AND lower(z.name) IN ({q}))")
        args += list(d["_tags"]) * 2
    if not cond:
        return set()
    rows = c.execute(f"""WITH RECURSIVE r(id, cur) AS (
                           SELECT id, id FROM tasks WHERE id IN ({','.join('?' * len(ids))})
                           UNION SELECT r.id, t.parent_id FROM r JOIN tasks t ON t.id=r.cur WHERE t.parent_id IS NOT NULL)
                         SELECT DISTINCT r.id FROM r JOIN tasks t ON t.id=r.cur JOIN lists l ON l.id=t.list_id
                         WHERE {' OR '.join(cond)}""", (*ids, *args)).fetchall()
    return {r[0] for r in rows}
