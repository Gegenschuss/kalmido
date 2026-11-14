"""2.235.0 B (#2902): THE check "data an agent may never see" - the data lock of an agent (set in its gear, agents/datalock.py).

One place for every read path of an agent; core/access.py calls it at its central points:
 - _list_role: a locked list has no role for the agent (404 everywhere: lists, tasks, comments, files, calendar, writes),
   also when someone else's request asks for the agent (events: agent_emit -> acx_task_ok / list_role)
 - _req_filters_sql: the agent's own list scope (vis_sql / wr_sql / acx_lists_sql of its requests)
 - tvis / task_visible: single locked tasks (e-mails in a private space, tasks with a locked tag) and all their subtasks
 - 2.560.0 B (#4699) the side ways to the same data: sheets/core.py sh_may (a table bound to a locked list, also when shared
   with the agent or filed in a folder shared with it), events/model.py ev_role_of / ev_range (an event whose task the lock
   covers), and the areas "calendar" / "contacts" (events/model.py _ev_role / my_cal_ids, contacts/model.py book_role /
   my_book_ids / contacts_on, need_feat for every write route of the two modules)
The lock only ever narrows what an agent sees: the tenant boundary and the fixed rules (health, budget, read later, the
journal with its mood: never an agent's since 2.22.0 / 2.72.0 / 2.172.1) stay as they are and cannot be opened here.

Stored in agents.data_lock: JSON {areas: {key: bool}, lists: [list ids], tags: [names], wiki_folders: [node ids]}; '' = the
defaults (DL_DEFAULT).

2.1045.0 (#5823): wiki_folders = knowledge folders (fs_nodes ids) kept out of what a share ABOVE them gives the agent -- above
all the share of a whole knowledge area (its root "Knowledge"). THE rule (dl_chain_cut): of a node's chain (node first) only
the shares on the deepest excluded folder and below it count; the folders above it (the area's root included) give nothing
there. So the exclusion covers the folder and everything below it, also what is added later, it stays with the folder's id
when it is renamed / moved, and an explicit share on the folder itself or on a folder / page inside it wins (who shares it on
its own means it). Applied in files/store.py _shares_role (every role check of the file store and the knowledge pages) and
fs_visible_sql_c (listings), wiki/wkfolder.py wkf_shared (the pages, the search), wiki/wkv1.py _shared_top (the paths)."""
import json
from contextlib import nullcontext

from flask import g, has_request_context, request

from .objtags import obj_tag_sql, obj_utag_sql  # 2.947.0 (#5275); 2.955.0 (#5276): obj_utag_sql
from .pg import system_ctx

DL_ALWAYS = ("journal", "mood", "health", "budget", "reading")  # fixed (scope "private" / list rules), shown as locked
DL_LIST_AREAS = ("contracts", "home", "travel")  # the private lists of Home & life (lists.life, no organisation)
# 2.560.0 B (#4699): whole modules an agent can be kept out of (its calendars with their events / its address books with
# their contacts), checked in their own role functions (events/model.py _ev_role, contacts/model.py book_role) and need_feat
DL_MOD_AREAS = ("calendar", "contacts")
DL_FEAT_AREA = {"events": "calendar", "contacts": "contacts"}  # need_feat module -> area
DL_SWITCH = ("mail",) + DL_LIST_AREAS + DL_MOD_AREAS
DL_AREAS = DL_ALWAYS + DL_SWITCH
DL_DEFAULT = {"mail": True, "contracts": False, "home": False, "travel": False,  # private e-mails locked for every agent
              "calendar": False, "contacts": False}
DL_LISTS_MAX, DL_TAGS_MAX, DL_TAG_LEN = 200, 50, 50
DL_WIKI_MAX = 200  # 2.1045.0 (#5823): excluded knowledge folders per agent
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
    wkf = [int(x) for x in d.get("wiki_folders") or [] if isinstance(x, int) and not isinstance(x, bool) and x > 0][:DL_WIKI_MAX]
    return {"areas": areas, "lists": lists, "tags": tags, "wiki_folders": wkf}  # 2.1045.0 (#5823): + wiki_folders


def _dl_eff(raw):
    d = dl_parse(raw)
    d["_lids"] = frozenset(d["lists"])
    d["_lareas"] = tuple(k for k in DL_LIST_AREAS if d["areas"][k])
    d["_mail"] = d["areas"]["mail"]
    d["_tags"] = tuple(sorted({t.lower() for t in d["tags"]}))
    d["_mods"] = frozenset(k for k in DL_MOD_AREAS if d["areas"][k])
    d["_wkf"] = frozenset(d["wiki_folders"])  # 2.1045.0 (#5823)
    return d


def dl_wiki_folders(c, uid):
    """2.1045.0 (#5823): the knowledge folders (node ids) excluded for account uid -- empty for people and agents without.
    2.1160.0 (#5862): a person's come from the shares of whole knowledge areas made for them (fs_shares.excl, _dl_person_wkf)."""
    d = dl_of(c, uid)
    # 2.1160.0 (#5862, Fable review 4): an agent keeps the exclusions of a share it got while it was a person (make_agent
    # leaves its user_id rows, _shares_role still counts them) -- they only ever narrow
    return d["_wkf"] | _dl_person_wkf(c, uid) if d else _dl_person_wkf(c, uid)


def _dl_person_wkf(c, uid):
    """2.1160.0 (#5862): the knowledge folders kept out of the shares of whole knowledge areas made for person uid (fs_shares.excl
    on the area's root, set in its Share dialog) -- the same rule as an agent's (dl_chain_cut). An expired share's exclusions
    still count: they only ever narrow, and the share itself gives nothing any more. Cached per request; read as system (ids only,
    the share rows of this one account, also when the asker is someone else: the Share dialog's inherited shares)."""
    if not uid:
        return frozenset()
    cache = g.setdefault("_dl_wkp", {}) if has_request_context() else None
    if cache is not None and uid in cache:
        return cache[uid]
    out = set()
    with system_ctx(c):  # ids only: the share rows of this one account, whoever asks (the Share dialog names other people)
        for r in c.execute("SELECT excl FROM fs_shares WHERE user_id=? AND excl IS NOT NULL", (int(uid),)):
            out.update(dl_excl_parse(r[0]))
    out = frozenset(out)
    if cache is not None:
        cache[uid] = out
    return out


def dl_excl_parse(raw):
    """2.1160.0 (#5862): the folder ids of a stored fs_shares.excl (invalid parts dropped, at most DL_WIKI_MAX)."""
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    return [int(x) for x in (d if isinstance(d, list) else []) if isinstance(x, int) and not isinstance(x, bool) and x > 0][:DL_WIKI_MAX]


def dl_chain_cut(c, uid, ids):
    """2.1045.0 (#5823): THE exclusion rule (module docstring). ids = a node's chain (node first, then its folders up to the
    root): the part whose shares still count for account uid -- up to and with the deepest excluded folder, else ids."""
    ex = dl_wiki_folders(c, uid)
    if not ex:
        return list(ids)
    for i, x in enumerate(ids):
        if int(x) in ex:
            return list(ids[:i + 1])
    return list(ids)


def dl_wiki_step_sql(c, uid, a="n"):
    """2.1045.0 (#5823): SQL condition (no ? params, starting with AND) for the step of a listing that walks down from shared
    nodes (files/store.py fs_visible_sql_c): an excluded folder is entered only as a shared node itself; '' when none."""
    ex = dl_wiki_folders(c, uid)
    return f" AND {a}.id NOT IN ({','.join(str(int(x)) for x in sorted(ex))})" if ex else ""


def dl_forget():
    """Drops the request caches (after the lock of an agent changed)."""
    if has_request_context():
        g.pop("_dl", None)
        g.pop("_dl_t", None)
        g.pop("_dl_wkp", None)  # 2.1160.0 (#5862)


def dl_of(c, uid):
    """The effective lock of account uid when it is an agent (see _dl_eff), else None. Cached per request. 2.1078.0 (#5866,
    N6): the row is read as system, so a context that cannot see the agent's organisation still gets its real lock."""
    if not uid:
        return None
    cache = g.setdefault("_dl", {}) if has_request_context() else None
    if cache is not None and uid in cache:
        return cache[uid]
    me = g.get("user") if has_request_context() else None
    if me is not None and me["id"] == int(uid) and me["kind"] != "agent":
        cache[uid] = None  # 2.1102.0 (#5137): the signed-in person itself has no lock - no system read (a set_config pair) per request
        return None
    with system_ctx(c):  # 2.1078.0 (#5866, N6): the agents row of another organisation's context too -- a defaults fallback
        # left wiki_folders empty (the open side); only the lock of this one account, never content handed to a person
        r = c.execute("SELECT u.kind, a.data_lock FROM users u LEFT JOIN agents a ON a.user_id=u.id WHERE u.id=?", (int(uid),)).fetchone()
    out = _dl_eff(r[1]) if r and r[0] == "agent" else None
    if cache is not None:
        cache[uid] = out
    return out


def dl_area_locked(c, uid, area):
    """2.560.0 B (#4699): is the whole module area ("calendar" | "contacts") locked for account uid? False for people."""
    d = dl_of(c, uid)
    return bool(d) and area in d["_mods"]


def dl_sheet_locked(c, uid, r):
    """2.560.0 B (#4699): is table row r (its rights row: a further sheet has its first sheet's) bound to a list locked for
    account uid? Asked by sheets/core.py sh_may before a share or a folder could open it. False for people."""
    return bool(r is not None and r["list_id"]) and dl_list_locked(c, uid, r["list_id"])


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
        base.append("SELECT t.id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.tt_id LIKE 'mail:%' AND l.org_id IS NULL"  # pg-ok: the prefix is always lower case; LIKE matches the partial index
                    " AND t.list_id IN (SELECT id FROM s)")
    if d["_tags"]:
        # 2.955.0 (#5276): anyone's personal tags of the core (were task_tags)
        base.append(f"SELECT t.id FROM tasks t WHERE {obj_utag_sql('t.id', 'names', 'any')} AND t.list_id IN (SELECT id FROM s)")
        # 2.947.0 (#5275): the project tags and labels of the core (obj_tag_sql: the tags of the task's project)
        base.append(f"SELECT t.id FROM tasks t WHERE {obj_tag_sql('t.id', 'names')} AND t.list_id IN (SELECT id FROM s)")
        args += [sorted(d["_tags"]), sorted(d["_tags"])]  # 2.955.0 (#5276): one array each (personal, project)
    # 2.947.0 (#5275): a label of an organisation is hidden from who is no member (row-level security) -- the lock still has to
    # see it on the task, so the query runs as "system"; it only decides what is HIDDEN from uid, in uid's own lists (s)
    with system_ctx(c) if d["_tags"] else nullcontext():
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
        cond.append("(t.tt_id LIKE 'mail:%' AND l.org_id IS NULL)")  # pg-ok: the prefix is always lower case (tasks_mail_list)
    if d["_tags"]:
        cond.append(obj_utag_sql("t.id", "names", "any"))  # 2.955.0 (#5276): anyone's personal tags of the core (were task_tags)
        cond.append(obj_tag_sql("t.id", "names"))  # 2.947.0 (#5275): the project tags and labels of the core
        args += [sorted(d["_tags"]), sorted(d["_tags"])]  # 2.955.0 (#5276): one array each (personal, project)
    if not cond:
        return set()
    with system_ctx(c) if d["_tags"] else nullcontext():  # 2.947.0 (#5275): as in dl_task_ids (only what is hidden)
        rows = c.execute(f"""WITH RECURSIVE r(id, cur) AS (
                               SELECT id, id FROM tasks WHERE id IN ({','.join('?' * len(ids))})
                               UNION SELECT r.id, t.parent_id FROM r JOIN tasks t ON t.id=r.cur WHERE t.parent_id IS NOT NULL)
                             SELECT DISTINCT r.id FROM r JOIN tasks t ON t.id=r.cur JOIN lists l ON l.id=t.list_id
                             WHERE {' OR '.join(cond)}""", (*ids, *args)).fetchall()
    return {r[0] for r in rows}
